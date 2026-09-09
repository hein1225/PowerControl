import asyncio
import os
import subprocess
import sys
from typing import Dict, List

import decky

try:
    import update
    from conf_manager import confManager
    from config import CPU_ID, CPU_VENDOR, PRODUCT_NAME, logger
    from cpu import cpuManager
    from fan import fanManager
    from fuse_manager import FuseManager
    from gpu import gpuManager
    from power_manager import PowerManager
    from sysInfo import sysInfoManager
    from ai_tuner import aiTuner
    from powerstation_manager import powerstationManager
    from qr_config_server import QRConfigServer

    sys.path.append(f"{decky.DECKY_PLUGIN_DIR}/py_modules/site-packages")
except Exception as e:
    decky.logger.error(e, exc_info=True)


class Plugin:
    def __init__(self):
        self.confManager = confManager
        self.powerManager = PowerManager()
        self.aiTuner = aiTuner
        self.powerstationManager = powerstationManager
        # 手机扫码填写 AI 模型配置：仅在用户点击「手机扫码填写」时临时启动本地 HTTP 服务
        self.qrConfigServer = QRConfigServer(
            save_cb=lambda bu, ak, m, cs: aiTuner.set_online(bu, ak, m, cs),
            get_cfg_cb=lambda: aiTuner.get_online(),
        )
        # 使用单例模式，不再存储 fuseManager 实例
        # 而是每次通过 FuseManager.get_instance() 获取

    async def _migration(self):
        decky.logger.info("start _migration")

        # 使用单例模式获取 FuseManager 实例
        # fuseManager = FuseManager.get_instance(power_manager=self.powerManager)
        # settings = self.confManager.getSettings()
        # enableNativeTDPSlider = (
        #     settings.get("enableNativeTDPSlider", False) if settings else False
        # )
        # if enableNativeTDPSlider:
        #     fuseManager.fuse_init()

    async def _bg_init(self):
        """后台初始化：仅重新应用已保存设置（与原版 PowerControl 行为一致，安全）。
        注意：绝不在此调用 systemctl / 自愈——那是加载期唯一比原版多、且会触发卡死的
        系统调用，改为用户在前端「修复」按钮按需触发（见 repair_powerstation_mask）。"""
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(None, self.powerManager.load)
        except Exception as e:
            logger.error(f"[main] powerManager.load 失败: {e}", exc_info=True)

    async def _main(self):
        decky.logger.info("start _main")
        # 关键：fire-and-forget，绝不 await 后台任务！decky 会 await _main()，
        # 若在此 await 重活，插件初始化会被卡住 → UI 不显示、系统卡死。
        # 同时 _main 本身不做任何 systemctl/IO，加载期零系统交互，保证插件一定能加载。
        try:
            asyncio.create_task(self._bg_init())
        except Exception as e:
            logger.error(f"[main] 调度后台初始化失败: {e}", exc_info=True)

    async def _unload(self):
        decky.logger.info("start _unload")
        gpuManager.unload()
        # 使用单例模式获取实例并卸载
        # FuseManager.get_instance().unload()
        self.powerManager.unload()
        try:
            if getattr(self, "qrConfigServer", None):
                self.qrConfigServer.stop()
        except Exception:
            pass
        logger.info("End PowerContorlAI")

    async def get_settings(self):
        return self.confManager.getSettings()

    async def set_settings(self, settings):
        self.confManager.setSettings(settings)
        return True

    async def get_hasRyzenadj(self):
        try:
            return cpuManager.get_hasRyzenadj()
        except Exception as e:
            logger.error(e, exc_info=True)
            return False

    async def get_cpuMaxNum(self):
        try:
            return cpuManager.get_cpuMaxNum()
        except Exception as e:
            logger.error(e, exc_info=True)
            return 0

    async def supports_smt(self):
        try:
            return cpuManager.get_isSupportSMT()
        except Exception as e:
            logger.error(e, exc_info=True)
            return False

    async def get_tdpMax(self):
        try:
            logger.info("Main get_tdpMax")
            tdpMax = self.powerManager.get_tdpMax()
            logger.info(f"Main get_tdpMax: {tdpMax}")
            return tdpMax
        except Exception as e:
            logger.error(e, exc_info=True)
            return 0

    async def get_tdpMin(self):
        try:
            logger.info("Main get_tdpMin")
            tdpMin = self.powerManager.get_tdpMin()
            logger.info(f"Main get_tdpMin: {tdpMin}")
            return tdpMin
        except Exception as e:
            logger.error(e, exc_info=True)
            return 3

    async def get_cpu_vendor(self):
        try:
            return CPU_VENDOR
        except Exception as e:
            logger.error(e, exc_info=True)
            return ""

    def _get_gpu_name(self) -> str:
        """尽量识别集显型号（失败回退为空）。"""
        try:
            out = subprocess.check_output(
                ["lspci"], text=True, stderr=subprocess.DEVNULL, timeout=5
            )
            for line in out.splitlines():
                if "VGA" in line or "Display" in line or "3D" in line:
                    return line.split(":", 1)[-1].strip()
        except Exception:
            pass
        return ""

    async def get_device_info(self):
        """返回供 AI 调优识别的设备信息：CPU 型号 / 产品名 / 厂商 / 显卡。
        GPU 型号识别走后台线程（lspci 同步调用，不放事件循环里）。"""
        try:
            gpu_name = await asyncio.get_event_loop().run_in_executor(
                None, self._get_gpu_name
            )
            return {
                "cpu_model": CPU_ID,
                "product_name": PRODUCT_NAME,
                "vendor": CPU_VENDOR,
                "gpu_name": gpu_name,
            }
        except Exception as e:
            logger.error(f"get_device_info 失败: {e}", exc_info=True)
            return {
                "cpu_model": "",
                "product_name": "",
                "vendor": CPU_VENDOR,
                "gpu_name": "",
            }

    async def get_gpuFreqRange(self):
        try:
            return gpuManager.get_gpuFreqRange()
        except Exception as e:
            logger.error(e, exc_info=True)
            return 0

    # 弃用
    async def get_cpu_AvailableFreq(self):
        try:
            return cpuManager.get_cpu_AvailableFreq()
        except Exception as e:
            logger.error(e, exc_info=True)
            return []

    async def get_language(self):
        try:
            return sysInfoManager.get_language()
        except Exception as e:
            logger.error(e, exc_info=True)
            return ""

    async def get_fanRPM(self, index):
        try:
            return fanManager.get_fanRPM(index)
        except Exception as e:
            logger.error(e, exc_info=True)
            return 0

    async def get_fanRPMPercent(self, index):
        try:
            return fanManager.get_fanRPMPercent(index)
        except Exception as e:
            logger.error(e, exc_info=True)
            return 0

    async def get_fanTemp(self, index):
        try:
            return fanManager.get_fanTemp(index)
        except Exception as e:
            logger.error(e, exc_info=True)
            return 0

    async def get_fanIsAuto(self, index):
        try:
            return fanManager.get_fanIsAuto(index)
        except Exception as e:
            logger.error(e, exc_info=True)
            return 0

    async def get_fanConfigList(self):
        try:
            return fanManager.get_fanConfigList()
        except Exception as e:
            logger.error(e, exc_info=True)
            return []

    async def set_fanAuto(self, index: int, value: bool):
        try:
            return fanManager.set_fanAuto(index, value)
        except Exception as e:
            logger.error(e, exc_info=True)
            return False

    async def set_fanPercent(self, index: int, value: int):
        try:
            return fanManager.set_fanPercent(index, value)
        except Exception as e:
            logger.error(e, exc_info=True)
            return False

    async def set_fanCurve(self, index: int, temp_list: List[int], pwm_list: List[int]):
        try:
            return fanManager.set_fanCurve(index, temp_list, pwm_list)
        except Exception as e:
            logger.error(e, exc_info=True)
            return False

    async def set_gpuAuto(self, value: bool):
        try:
            return gpuManager.set_gpuAuto(value)
        except Exception as e:
            logger.error(e, exc_info=True)
            return False

    async def set_gpuAutoFreqRange(self, min: int, max: int):
        try:
            return gpuManager.set_gpuAutoFreqRange(min, max)
        except Exception as e:
            logger.error(e, exc_info=True)
            return False

    async def set_gpuFreq(self, value: int):
        try:
            return gpuManager.set_gpuFreqFix(value)
        except Exception as e:
            logger.error(e, exc_info=True)
            return False

    async def set_gpuFreqRange(self, value: int, value2: int):
        try:
            return gpuManager.set_gpuFreqRange(value, value2)
        except Exception as e:
            logger.error(e, exc_info=True)
            return False

    async def set_cpuTDP(self, value: int):
        try:
            # return cpuManager.set_cpuTDP(value)
            return self.powerManager.set_tdp(value)
        except Exception as e:
            logger.error(e, exc_info=True)
            return False

    async def set_cpuTDP_unlimited(self):
        logger.info("Main set_cpuTDP_unlimited")
        try:
            return self.powerManager.set_tdp_unlimited()
        except Exception as e:
            logger.error(e, exc_info=True)
            return False

    async def is_intel(self):
        try:
            return cpuManager.is_intel()
        except Exception as e:
            logger.error(e, exc_info=True)
            return False

    async def set_cpuOnline(self, value: int):
        try:
            return cpuManager.set_cpuOnline(value)
        except Exception as e:
            logger.error(e, exc_info=True)
            return False

    async def set_smt(self, value: bool):
        try:
            return cpuManager.set_smt(value)
        except Exception as e:
            logger.error(e, exc_info=True)
            return False

    async def set_cpuBoost(self, value: bool):
        try:
            return cpuManager.set_cpuBoost(value)
        except Exception as e:
            logger.error(e, exc_info=True)
            return False

    async def set_cpuFreq(self, value: int):
        try:
            return cpuManager.set_cpuFreq(value)
        except Exception as e:
            logger.error(e, exc_info=True)
            return False

    async def set_cpu_freq_by_core_type(self, freq_config: Dict[str, int]):
        try:
            logger.info(f"设置按核心类型CPU频率: {freq_config}")
            return cpuManager.set_cpu_freq_by_core_type(freq_config)
        except Exception as e:
            logger.error(f"按核心类型设置CPU频率失败: {e}", exc_info=True)
            return False

    async def get_cpu_core_info(self):
        """获取CPU核心类型详细信息"""
        try:
            return cpuManager.get_cpu_core_info()
        except Exception as e:
            logger.error(f"获取CPU核心信息失败: {e}", exc_info=True)
            return {
                "is_heterogeneous": False,
                "vendor": "Error",
                "architecture_summary": "Failed to detect CPU information",
                "core_types": {},
            }

    async def get_cpu_topology_for_ui(self):
        """获取CPU拓扑信息（供前端核心选择UI使用）"""
        try:
            return cpuManager.get_cpu_topology_for_ui()
        except Exception as e:
            logger.error(f"获取CPU拓扑信息失败: {e}", exc_info=True)
            return {
                "cores": [],
                "core_types": [],
                "is_heterogeneous": False,
            }

    async def set_cpu_online_list(self, online_list: list):
        """按逻辑核心列表设置CPU在线状态"""
        try:
            logger.info(f"设置CPU在线列表: {online_list}")
            return cpuManager.set_cpu_online_list(online_list)
        except Exception as e:
            logger.error(f"设置CPU在线列表失败: {e}", exc_info=True)
            return False

    async def receive_suspendEvent(self):
        try:
            return True
        except Exception as e:
            logger.error(e, exc_info=True)
            return False

    async def fix_gpuFreqSlider(self):
        try:
            return gpuManager.fix_gpuFreqSlider()
        except Exception as e:
            logger.error(e, exc_info=True)
            return False

    async def start_gpu_notify(self):
        try:
            return gpuManager.start_gpu_notify()
        except Exception as e:
            logger.error(e, exc_info=True)
            return False

    async def stop_gpu_notify(self):
        try:
            return gpuManager.stop_gpu_notify()
        except Exception as e:
            logger.error(e, exc_info=True)
            return False

    async def update_latest(self):
        logger.info("Updating latest")
        # return update.update_latest()
        try:
            return update.update_latest()
        except Exception as e:
            logger.error(e, exc_info=True)
            return False

    async def get_version(self):
        return update.get_version()

    async def get_latest_version(self):
        try:
            return update.get_latest_version()
        except Exception as e:
            logger.error(e, exc_info=True)
            return ""

    async def get_ryzenadj_info(self):
        return cpuManager.get_ryzenadj_info()

    async def check_ryzenadj_coall(self) -> bool:
        """检测并缓存 RyzenAdj 降压支持情况"""
        try:
            result = cpuManager.check_ryzenadj_coall_support()
            # 保存检测结果到配置
            settings = self.confManager.getSettings()
            settings['supportsRyzenadjCoall'] = result
            self.confManager.setSettings(settings)
            logger.info(f"RyzenAdj 降压支持检测完成: {result}")
            return result
        except Exception as e:
            logger.error(f"检测降压支持失败: {e}", exc_info=True)
            return False

    async def set_ryzenadj_undervolt(self, enable: bool, value: int) -> bool:
        """设置 RyzenAdj 降压值"""
        try:
            logger.info(f"Main 设置降压: enable={enable}, value={value}")
            return self.powerManager.set_ryzenadj_undervolt(enable, value)
        except Exception as e:
            logger.error(f"设置降压失败: {e}", exc_info=True)
            return False

    async def get_rapl_info(self):
        logger.info("Main get_rapl_info")
        return cpuManager.get_rapl_info()

    async def get_power_info(self):
        return self.powerManager.get_power_info()

    async def get_tdp_backends(self):
        try:
            return self.powerManager.get_tdp_backends()
        except Exception as e:
            logger.error(e, exc_info=True)
            return {
                "available": [{"id": "auto", "available": True}],
                "current": "auto",
                "effective": "auto",
                "active": "cpu",
                "vendorHint": "unknown",
            }

    async def set_tdp_backend(self, backend_id: str):
        try:
            return self.powerManager.set_tdp_backend(backend_id)
        except Exception as e:
            logger.error(e, exc_info=True)
            return False

    async def get_max_perf_pct(self):
        try:
            return cpuManager.get_max_perf_pct()
        except Exception as e:
            logger.error(e, exc_info=True)
            return 0

    async def set_max_perf_pct(self, value: int):
        try:
            return cpuManager.set_max_perf_pct(value)
        except Exception as e:
            logger.error(e, exc_info=True)
            return False

    async def set_auto_cpumax_pct(self, value: bool):
        try:
            return cpuManager.set_auto_cpumax_pct(value)
        except Exception as e:
            logger.error(e, exc_info=True)
            return False

    async def get_cpu_governor(self):
        """获取当前 CPU 调度器"""
        try:
            return cpuManager.get_cpu_governor()
        except Exception as e:
            logger.error(e, exc_info=True)
            return ""

    async def get_available_governors(self):
        """获取所有可用的 CPU 调度器"""
        try:
            return cpuManager.get_available_governors()
        except Exception as e:
            logger.error(e, exc_info=True)
            return []

    async def set_cpu_governor(self, governor: str):
        """设置 CPU 调度器

        Args:
            governor (str): 调度器名称
        """
        logger.debug(f"Main 设置 CPU 调度器为 {governor}")
        try:
            return cpuManager.set_cpu_governor(governor)
        except Exception as e:
            logger.error(e, exc_info=True)
            return False

    async def supported_epp(self):
        """检查系统是否支持 EPP 功能。"""
        try:
            return cpuManager.is_epp_supported()
        except Exception as e:
            logger.error(e, exc_info=True)
            return False

    async def get_epp_modes(self):
        """获取可用的 EPP 模式列表。"""
        try:
            return cpuManager.get_epp_modes()
        except Exception as e:
            logger.error(e, exc_info=True)
            return []

    async def get_current_epp(self):
        """获取当前的 EPP 模式。"""
        try:
            return cpuManager.get_current_epp()
        except Exception as e:
            logger.error(e, exc_info=True)
            return None

    async def set_epp(self, mode: str):
        """设置 EPP 模式。"""
        try:
            return cpuManager.set_epp(mode)
        except Exception as e:
            logger.error(e, exc_info=True)
            return False

    async def supports_sched_ext(self):
        """检查系统是否支持 sched_ext 功能。"""
        try:
            return self.powerManager.supports_sched_ext()
        except Exception as e:
            logger.error(e, exc_info=True)
            return False

    async def get_sched_ext_list(self):
        """获取可用的 sched_ext 调度器列表。"""
        try:
            # 先检查是否支持 sched_ext
            if not self.powerManager.supports_sched_ext():
                return []
            return self.powerManager.get_sched_ext_list()
        except Exception as e:
            logger.error(e, exc_info=True)
            return []

    async def get_current_sched_ext_scheduler(self):
        """获取当前的 sched_ext 调度器。"""
        try:
            # 先检查是否支持 sched_ext
            if not self.powerManager.supports_sched_ext():
                return ""
            result = self.powerManager.get_current_sched_ext_scheduler()
            logger.info(f"获取当前 SCX 调度器: {result}")
            return result
        except Exception as e:
            logger.error(e, exc_info=True)
            return ""

    async def set_sched_ext_scheduler(self, scheduler: str, param: str = ""):
        """设置 sched_ext 调度器。

        Args:
            scheduler (str): 调度器名称
            param (str, optional): 调度器参数，默认为空字符串
        """
        logger.debug(f"Main 设置 sched_ext 调度器为 {scheduler}, 参数: {param}")
        try:
            return self.powerManager.set_sched_ext(scheduler, param)
        except Exception as e:
            logger.error(e, exc_info=True)
            return False

    async def get_bypass_charge(self) -> bool | None:
        """获取 Bypass Charge 值。"""
        try:
            return self.powerManager.get_bypass_charge()
        except Exception as e:
            logger.error(e, exc_info=True)
            return None

    async def set_bypass_charge(self, value: int):
        """设置旁路供电值。"""
        logger.info(f"Main 设置旁路供电值为 {value}")
        try:
            return self.powerManager.set_bypass_charge(value)
        except Exception as e:
            logger.error(e, exc_info=True)
            return False

    async def set_charge_limit(self, value: int):
        """设置充电限制电量"""
        logger.debug(f"设置充电限制电量为 {value}")
        try:
            return self.powerManager.set_charge_limit(value)
        except Exception as e:
            logger.error(e, exc_info=True)
            return False

    async def supports_bypass_charge(self) -> bool:
        """判断设备是否支持旁路供电"""
        try:
            result = self.powerManager.supports_bypass_charge()
            logger.info(f"当前设备支持旁路供电: {result}")
            return result
        except Exception as e:
            logger.error(e, exc_info=True)
            return False

    async def supports_charge_limit(self) -> bool:
        """判断设备是否支持充电限制"""
        try:
            result = self.powerManager.supports_charge_limit()
            logger.info(f"当前设备支持充电限制: {result}")
            return result
        except Exception as e:
            logger.error(e, exc_info=True)
            return False

    async def software_charge_limit(self) -> bool:
        """判断设备是否支持软件充电限制"""
        try:
            result = self.powerManager.software_charge_limit()
            logger.info(f"当前设备支持软件充电限制: {result}")
            return result
        except Exception as e:
            logger.error(e, exc_info=True)
            return False

    # supports_reset_charge_limit
    async def supports_reset_charge_limit(self) -> bool:
        """判断设备是否支持重置充电限制"""
        try:
            result = self.powerManager.supports_reset_charge_limit()
            logger.info(f"当前设备支持重置充电限制: {result}")
            return result
        except Exception as e:
            logger.error(e, exc_info=True)
            return False

    # reset_charge_limit
    async def reset_charge_limit(self):
        """重置充电限制"""
        try:
            return self.powerManager.reset_charge_limit()
        except Exception as e:
            logger.error(e, exc_info=True)
            return False

    async def log_info(self, message: str):
        try:
            return logger.info(f"Frontend: {message}")
        except Exception as e:
            logger.error(e, exc_info=True)
            return False

    async def log_error(self, message: str):
        try:
            return logger.error(f"Frontend: {message}")
        except Exception as e:
            logger.error(e, exc_info=True)
            return False

    async def log_warn(self, message: str):
        try:
            return logger.warn(f"Frontend: {message}")
        except Exception as e:
            logger.error(e, exc_info=True)
            return False

    async def log_debug(self, message: str):
        try:
            return logger.debug(f"Frontend: {message}")
        except Exception as e:
            logger.error(e, exc_info=True)
            return False

    # 创建一个新的方法来控制 FUSE 挂载
    async def toggle_native_tdp_slider(self, enabled: bool):
        """
        启用或禁用原生 TDP 滑块

        Args:
            enabled: 是否启用

        Returns:
            操作是否成功
        """
        try:
            settings = self.confManager.getSettings()
            settings["enableNativeTDPSlider"] = enabled
            self.confManager.setSettings(settings)

            fuseManager = FuseManager.get_instance(power_manager=self.powerManager)
            if enabled:
                # 启用 FUSE
                if not fuseManager.fuse_init():
                    logger.error("Failed to initialize FUSE")
                    return False
            else:
                # 禁用 FUSE
                fuseManager.unload()

            return True
        except Exception as e:
            logger.error(f"Error toggling native TDP slider: {e}", exc_info=True)
            return False

    async def check_file_exist(self, file_path: str) -> bool:
        try:
            return os.path.exists(file_path)
        except Exception as e:
            logger.error(f"Error checking file exist: {e}", exc_info=True)
            return False

    async def supports_native_gpu_slider(self) -> bool:
        try:
            from utils import check_native_gpu_slider_support

            return check_native_gpu_slider_support()
        except Exception as e:
            logger.error(
                f"Error checking native GPU slider support: {e}", exc_info=True
            )
            return False

    async def supports_native_tdp_limit(self) -> bool:
        try:
            from utils import check_native_tdp_limit_support

            return check_native_tdp_limit_support()
        except Exception as e:
            logger.error(f"Error checking native TDP limit support: {e}", exc_info=True)
            return False

    # ---------------- AI 智能调优（在线 API 版） ----------------
    async def get_ai_online(self):
        try:
            return self.aiTuner.get_online()
        except Exception as e:
            logger.error(f"get_ai_online 失败: {e}", exc_info=True)
            return {"configured": False, "base_url": "", "model": "", "collect_sec": 600}

    async def set_ai_online(self, base_url: str, api_key: str, model: str, collect_sec: int = 600) -> bool:
        try:
            return self.aiTuner.set_online(base_url, api_key, model, collect_sec)
        except Exception as e:
            logger.error(f"set_ai_online 失败: {e}", exc_info=True)
            return False

    async def test_ai_online(self):
        try:
            return self.aiTuner.test_online()
        except Exception as e:
            logger.error(f"test_ai_online 失败: {e}", exc_info=True)
            return {"ok": False, "message": f"自检异常: {e}"}

    async def start_ai_tune(
        self,
        app_id: str,
        target_fps: int,
        collect_sec: int,
        current: dict,
        caps: dict,
    ):
        try:
            return self.aiTuner.start(app_id, target_fps, collect_sec, current, caps)
        except Exception as e:
            logger.error(f"start_ai_tune 失败: {e}", exc_info=True)
            return {"started": False, "message": f"启动失败: {e}"}

    async def get_ai_tune_status(self):
        try:
            return self.aiTuner.status()
        except Exception as e:
            logger.error(f"get_ai_tune_status 失败: {e}", exc_info=True)
            return {"phase": "error", "error": str(e)}

    async def stop_ai_tune(self) -> bool:
        try:
            return self.aiTuner.stop()
        except Exception as e:
            logger.error(f"stop_ai_tune 失败: {e}", exc_info=True)
            return False

    async def get_ai_tune_enabled(self) -> bool:
        try:
            return self.aiTuner.get_enabled()
        except Exception as e:
            logger.error(f"get_ai_tune_enabled 失败: {e}", exc_info=True)
            return False

    async def set_ai_tune_enabled(self, enabled: bool) -> bool:
        try:
            return self.aiTuner.set_enabled(bool(enabled))
        except Exception as e:
            logger.error(f"set_ai_tune_enabled 失败: {e}", exc_info=True)
            return False

    # ---------------- 手机扫码填写 AI 模型配置 ----------------
    async def start_qr_config(self) -> str:
        """启动本地临时 HTTP 服务，返回手机可访问的 URL（含局域网 IP）。"""
        try:
            return self.qrConfigServer.start()
        except Exception as e:
            logger.error(f"start_qr_config 失败: {e}", exc_info=True)
            return ""

    async def get_qr_config_url(self) -> str:
        """返回当前正在运行的扫码服务 URL（未运行则返回空串）。"""
        try:
            return self.qrConfigServer.url() if self.qrConfigServer.running else ""
        except Exception as e:
            logger.error(f"get_qr_config_url 失败: {e}", exc_info=True)
            return ""

    async def stop_qr_config(self) -> bool:
        """停止并释放本地 HTTP 服务。"""
        try:
            self.qrConfigServer.stop()
            return True
        except Exception as e:
            logger.error(f"stop_qr_config 失败: {e}", exc_info=True)
            return False

    # ---------------- PowerStation 管理（Bazzite 44+ TDP 防重置） ----------------
    async def get_powerstation_status(self):
        try:
            # 后台线程执行 systemctl 调用，避免阻塞 decky 事件循环（挂载设置页时调用）
            return await asyncio.get_event_loop().run_in_executor(
                None, self.powerstationManager.get_status
            )
        except Exception as e:
            logger.error(f"get_powerstation_status 失败: {e}", exc_info=True)
            return {
                "exists": False,
                "enabled": False,
                "masked": False,
                "active": False,
                "disabled_by_plugin": False,
            }

    async def set_powerstation_disabled(self, disabled: bool) -> bool:
        try:
            # 放到后台线程执行，避免阻塞后端事件循环
            await asyncio.get_event_loop().run_in_executor(
                None, lambda: self.powerstationManager.set_disabled(bool(disabled))
            )
            return True
        except Exception as e:
            logger.error(f"set_powerstation_disabled 失败: {e}", exc_info=True)
            return False

    async def repair_powerstation_mask(self) -> dict:
        """按需修复：移除历史版本误留的 powerstation mask 软链（导致系统卡死的持久副作用）。
        仅由前端「修复」按钮触发，绝不在插件加载期自动调用，避免加载期卡死。"""
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, self.powerstationManager.repair_if_masked
            )
            decky.logger.info(f"[main] powerstation 手动修复结果: {result}")
            return result or {"was_masked": False, "unmasked": False}
        except Exception as e:
            logger.error(f"repair_powerstation_mask 失败: {e}", exc_info=True)
            return {"error": str(e)}
