"""
AI 智能调优模块（在线 API 版）

功能：进游戏后由用户选定「目标真实帧数」，插件后台分 3 轮调优，每轮约 5 分钟采集本机
真实帧率与遥测，调用用户自备的 OpenAI 兼容在线模型推理出「在达标前提下最省电」的 APU 设置，
把该轮结果应用到硬件后再观测下一轮帧率变化，3 轮后正式结束；在线不可用则走本地启发式兜底。
前端把最终推荐写入该游戏的专属设置并开启开关（自动接管手动调优）。

设计要点：
- 本模块不写 perApp / 不碰底层 hw 写路径，只负责「采集 + 推理 + 产出 AppSetting 增量」。
  把增量写回 perApp、开 overwrite 开关、应用，由前端 Settings 完成（保持 perApp 单一所有权）。
- 仅在线 API：本地零算力、不依赖 NPU/ONNX。
- 真实帧率优先读 gamescope stats 的 app_fps（游戏本机渲染率，排除 FSR FrameGen）；
  外部插帧（小黄鸭/Lossless Scaling）无法被 gamescope 区分时，以用户自设目标为本机率，
  且当且仅当能取到本机率时才参与判定，取不到则拒绝用插帧率。
- 密钥在落盘时做 XOR+base64 混淆（仅防明文泄露，非加密；decky 插件以 root 运行）。
"""

import asyncio
import base64
import glob
import json
import os
import time
import urllib.error
import urllib.request

import decky
from settings import SettingsManager
from config import logger

# 在线模型配置单独存一个配置文件（ai_tune_config），避免被前端 saveSettings 序列化 SettingsData 时覆盖
_AI_CFG_MANAGER = SettingsManager(
    name="ai_tune_config", settings_directory=decky.DECKY_PLUGIN_SETTINGS_DIR
)
AI_ONLINE_KEY = "aiOnline"
# AI 调优是否"接管"手动调优（开启后手动控件置灰，需先关闭才能手动）
AI_TUNE_ENABLED_KEY = "aiTuneEnabled"
# 采集时最少需要的有效样本秒数（提前结束时仍可用）
MIN_SAMPLES = 30
# 混淆用的固定盐（仅混淆，非密钥保护）
_OBF_SALT = b"PowerControl-AI-Tune-2026"

GAMESCOPE_STATS_CANDIDATES = [
    "/tmp/gamescope_stats.log",
    "/tmp/gamescope_stats.json",
    "/tmp/gamescope_stats_0.json",
    "/run/gamescope_stats.log",
    "/run/gamescope_stats.json",
]


def _obfuscate(plain: str) -> str:
    """XOR + base64 混淆，避免密钥明文落盘。"""
    if not plain:
        return ""
    data = plain.encode("utf-8")
    out = bytes([data[i] ^ _OBF_SALT[i % len(_OBF_SALT)] for i in range(len(data))])
    return base64.b64encode(out).decode("ascii")


def _deobfuscate(b64: str) -> str:
    if not b64:
        return ""
    try:
        data = base64.b64decode(b64.encode("ascii"))
        return bytes(
            [data[i] ^ _OBF_SALT[i % len(_OBF_SALT)] for i in range(len(data))]
        ).decode("utf-8")
    except Exception:
        return ""


class AITuner:
    def __init__(self):
        self._state = {
            "phase": "idle",  # idle | collecting | inferring | done | error | cancelled
            "app_id": None,
            "target_fps": 0,
            "elapsed": 0,
            "total": 600,
            "collected": 0,
            "result": None,  # {delta, reason, stats, used_fallback}
            "error": None,
        }
        self._task = None
        self._cancel = False

    # ---------- 配置持久化 ----------
    def _load_online(self) -> dict:
        try:
            return _AI_CFG_MANAGER.getSetting(AI_ONLINE_KEY) or {}
        except Exception as e:
            logger.error(f"[ai_tuner] 读取在线配置失败: {e}", exc_info=True)
            return {}

    def _save_online(self, cfg: dict):
        _AI_CFG_MANAGER.setSetting(AI_ONLINE_KEY, cfg)

    def set_online(self, base_url: str, api_key: str, model: str, collect_sec: int = 600) -> bool:
        """保存在线模型配置（密钥混淆落盘）。"""
        try:
            cfg = {
                "base_url": (base_url or "").rstrip("/"),
                "api_key": _obfuscate(api_key or ""),
                "model": model or "",
                "collect_sec": int(collect_sec or 600),
            }
            self._save_online(cfg)
            logger.info("[ai_tuner] 在线模型配置已保存")
            return True
        except Exception as e:
            logger.error(f"[ai_tuner] 保存在线配置失败: {e}", exc_info=True)
            return False

    def get_online(self) -> dict:
        """返回配置概览（不回显密钥）。"""
        cfg = self._load_online()
        configured = bool(cfg.get("base_url") and cfg.get("api_key") and cfg.get("model"))
        return {
            "configured": configured,
            "base_url": cfg.get("base_url", ""),
            "model": cfg.get("model", ""),
            "collect_sec": cfg.get("collect_sec", 600),
        }

    def get_enabled(self) -> bool:
        """AI 调优是否接管手动调优。"""
        try:
            return bool(_AI_CFG_MANAGER.getSetting(AI_TUNE_ENABLED_KEY) or False)
        except Exception as e:
            logger.error(f"[ai_tuner] 读取 aiTuneEnabled 失败: {e}", exc_info=True)
            return False

    def set_enabled(self, v: bool) -> bool:
        """设置 AI 调优接管状态（持久化）。"""
        try:
            _AI_CFG_MANAGER.setSetting(AI_TUNE_ENABLED_KEY, bool(v))
            logger.info(f"[ai_tuner] aiTuneEnabled = {bool(v)}")
            return True
        except Exception as e:
            logger.error(f"[ai_tuner] 设置 aiTuneEnabled 失败: {e}", exc_info=True)
            return False

    def test_online(self) -> dict:
        """连通性自检：发一次极轻量请求。"""
        cfg = self._load_online()
        base_url = cfg.get("base_url", "")
        api_key = _deobfuscate(cfg.get("api_key", ""))
        model = cfg.get("model", "")
        if not (base_url and api_key and model):
            return {"ok": False, "message": "配置不完整，请先填写端点/密钥/模型"}
        try:
            resp = self._chat(
                base_url,
                api_key,
                model,
                "你是掌机功耗优化助手，只回答 ok。",
                "ping",
                timeout=20,
            )
            content = (resp.get("choices", [{}])[0].get("message", {}).get("content", "") or "").strip()
            if content:
                return {"ok": True, "message": "连接成功"}
            return {"ok": False, "message": "模型返回为空"}
        except Exception as e:
            logger.error(f"[ai_tuner] 连通性自检失败: {e}", exc_info=True)
            return {"ok": False, "message": f"连接失败: {e}"}

    # ---------- 采集 ----------
    @staticmethod
    def read_native_fps() -> float | None:
        """读取 gamescope 统计中的 app_fps（游戏本机渲染率）。取不到返回 None。"""
        for path in GAMESCOPE_STATS_CANDIDATES:
            if not os.path.exists(path):
                continue
            try:
                with open(path, "r") as f:
                    lines = f.read().splitlines()
                # 取最后一行有效 JSON
                for line in reversed(lines):
                    line = line.strip()
                    if not line:
                        continue
                    obj = json.loads(line)
                    fps = obj.get("app_fps")
                    if fps is None and "fps" in obj:
                        fps = obj.get("fps")
                    if isinstance(fps, (int, float)) and fps > 0:
                        return float(fps)
            except Exception as e:
                logger.warning(f"[ai_tuner] 读取 {path} 失败: {e}")
                continue
        return None

    @staticmethod
    def read_telemetry() -> dict:
        """尽力读取 APU 功耗(W) 与温度(℃)。取不到相应字段为 None。"""
        power_w = None
        temp_c = None
        try:
            for d in glob.glob("/sys/class/hwmon/hwmon*"):
                for f in glob.glob(f"{d}/power*_input"):
                    try:
                        v = int(open(f).read().strip())  # 微瓦
                        power_w = (power_w or 0) + v / 1_000_000.0
                    except Exception:
                        pass
                for f in glob.glob(f"{d}/temp*_input"):
                    try:
                        v = int(open(f).read().strip()) / 1000.0
                        if temp_c is None or v > temp_c:
                            temp_c = v
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"[ai_tuner] 读取 hwmon 遥测失败: {e}")
        return {"powerW": power_w, "tempC": temp_c}

    def start(self, app_id: str, target_fps: int, collect_sec: int, current: dict, caps: dict) -> dict:
        """启动一次调优采集。返回 {started, message}。"""
        if self._state["phase"] in ("collecting", "inferring"):
            return {"started": False, "message": "已有调优任务进行中"}
        cfg = self._load_online()
        if not (cfg.get("base_url") and cfg.get("api_key") and cfg.get("model")):
            return {"started": False, "message": "请先配置在线模型"}
        if not app_id or app_id == "0":
            return {"started": False, "message": "未检测到当前游戏，无法调优"}
        if not target_fps or target_fps <= 0:
            return {"started": False, "message": "目标帧数无效"}
        round_sec = max(60, int(collect_sec or 300))

        self._state = {
            "phase": "collecting",
            "app_id": app_id,
            "target_fps": target_fps,
            "elapsed": 0,
            "total": round_sec,
            "round": 0,
            "rounds": 3,
            "collected": 0,
            "samples": [],
            "current": current or {},
            "caps": caps or {},
            "result": None,
            "error": None,
        }
        self._cancel = False
        try:
            loop = asyncio.get_event_loop()
            self._task = loop.create_task(self._collect_and_tune())
        except Exception as e:
            logger.error(f"[ai_tuner] 启动采集任务失败: {e}", exc_info=True)
            self._state["phase"] = "error"
            self._state["error"] = str(e)
            return {"started": False, "message": f"启动失败: {e}"}
        return {"started": True, "message": "已开始采集，请正常游戏"}

    def status(self) -> dict:
        s = dict(self._state)
        s.pop("samples", None)
        s.pop("current", None)
        s.pop("caps", None)
        # 暴露多轮进度给前端（逐轮应用）
        for k in ("round", "rounds", "lastDelta", "lastReason", "lastStats"):
            if k not in s:
                s[k] = None
        return s

    def stop(self) -> bool:
        if self._state["phase"] in ("collecting", "inferring"):
            self._cancel = True
            return True
        return False

    # ---------- 内部：多轮采集循环 ----------
    async def _collect_and_tune(self):
        st = self._state
        cfg = self._load_online()
        base_url = cfg.get("base_url", "")
        api_key = _deobfuscate(cfg.get("api_key", ""))
        model = cfg.get("model", "")
        ROUNDS = int(st.get("rounds") or 3)
        round_sec = max(60, int(st.get("total") or 300))
        try:
            current = dict(st.get("current") or {})
            caps = dict(st.get("caps") or {})
            app_id = st["app_id"]
            target = st["target_fps"]
            used_fallback_overall = False
            last_delta = None
            last_reason = ""
            last_stats = None

            for rnd in range(1, ROUNDS + 1):
                if self._cancel:
                    break
                st["round"] = rnd
                st["phase"] = "collecting"
                st["samples"] = []
                st["collected"] = 0
                st["elapsed"] = 0
                st["total"] = round_sec

                while st["elapsed"] < round_sec and not self._cancel:
                    sample = {
                        "ts": int(time.time()),
                        "fps": self.read_native_fps(),
                        "powerW": None,
                        "tempC": None,
                    }
                    # 每 5 秒采一次遥测，降低开销
                    if st["collected"] % 5 == 0:
                        tel = self.read_telemetry()
                        sample["powerW"] = tel["powerW"]
                        sample["tempC"] = tel["tempC"]
                    st["samples"].append(sample)
                    st["collected"] += 1
                    st["elapsed"] = st["collected"]
                    await asyncio.sleep(1.0)

                if self._cancel and st["collected"] < MIN_SAMPLES:
                    st["phase"] = "cancelled"
                    st["error"] = "已取消，采集样本不足"
                    return
                if self._cancel:
                    st["phase"] = "cancelled"
                    st["error"] = "已取消"
                    return

                st["phase"] = "inferring"
                samples = st["samples"]
                stats = self._aggregate(samples)
                if stats.get("nativeFpsP1") is None:
                    st["phase"] = "error"
                    st["error"] = (
                        "未能读取到本机真实帧率（gamescope 统计不可用）。"
                        "若使用了插帧工具，请关闭后重试；或在 gamescope 启用 --stats-path。"
                    )
                    return

                reason = ""
                used_fallback = False
                delta = None
                try:
                    delta, reason, used_fallback = self._infer(
                        base_url, api_key, model,
                        target, stats, current, caps, app_id,
                    )
                except Exception as e:
                    logger.error(f"[ai_tuner] 在线推理失败，回退启发式: {e}", exc_info=True)
                    delta, reason = self._heuristic(target, stats, current, caps)
                    used_fallback = True

                if not delta:
                    delta, reason = self._heuristic(target, stats, current, caps)
                    used_fallback = True

                # 统一安全护栏：锁范围 + 降压上限 + TDP 变化幅度，防差异过大/崩溃
                try:
                    delta = self._safeguard(delta, current, caps)
                except Exception as e:
                    logger.error(f"[ai_tuner] 护栏失败，回退启发式: {e}", exc_info=True)
                    delta, reason = self._heuristic(target, stats, current, caps)
                    used_fallback = True

                last_delta = delta
                last_reason = reason
                last_stats = stats
                if used_fallback:
                    used_fallback_overall = True

                # 把本轮结果并入 current，作为下一轮推理上下文；
                # 前端会把本轮 lastDelta 应用到硬件，下一轮即可观测帧率变化
                current.update(delta)
                st["lastDelta"] = delta
                st["lastReason"] = reason
                st["lastStats"] = stats
                logger.info(f"[ai_tuner] 第 {rnd}/{ROUNDS} 轮完成 app={app_id} fallback={used_fallback}")

                # 非最后一轮，留几秒让前端把本轮结果应用到硬件，下一轮再测帧率变化
                if rnd < ROUNDS:
                    await asyncio.sleep(3)

            st["result"] = {
                "delta": last_delta,
                "reason": last_reason,
                "rounds": ROUNDS,
                "stats": last_stats,
                "used_fallback": used_fallback_overall,
            }
            st["phase"] = "done"
            # 调优完成后自动接管手动调优（前端据此置灰手动控件）
            try:
                self.set_enabled(True)
            except Exception as e:
                logger.error(f"[ai_tuner] 标记接管失败: {e}", exc_info=True)
            logger.info(f"[ai_tuner] 多轮调优完成 app={app_id} 共 {ROUNDS} 轮 fallback={used_fallback_overall}")
        except Exception as e:
            logger.error(f"[ai_tuner] 采集/推理异常: {e}", exc_info=True)
            st["phase"] = "error"
            st["error"] = str(e)
        finally:
            self._task = None

    @staticmethod
    def _aggregate(samples: list) -> dict:
        fps_list = [s["fps"] for s in samples if isinstance(s.get("fps"), (int, float)) and s["fps"] > 0]
        if not fps_list:
            return {"nativeFpsMean": None, "nativeFpsP1": None, "nativeFpsP5": None, "nativeFpsVar": None}
        fps_sorted = sorted(fps_list)
        n = len(fps_sorted)
        mean = sum(fps_sorted) / n
        # 1% 低帧（p1）：取最差 1% 区间的均值，避免单点抖动
        p1_idx = max(0, int(n * 0.01) - 1)
        p1 = sum(fps_sorted[: max(1, p1_idx + 1)]) / max(1, p1_idx + 1)
        p5_idx = max(0, int(n * 0.05) - 1)
        p5 = sum(fps_sorted[: max(1, p5_idx + 1)]) / max(1, p5_idx + 1)
        var = sum((x - mean) ** 2 for x in fps_sorted) / n
        powers = [s["powerW"] for s in samples if isinstance(s.get("powerW"), (int, float))]
        temps = [s["tempC"] for s in samples if isinstance(s.get("tempC"), (int, float))]
        return {
            "nativeFpsMean": round(mean, 1),
            "nativeFpsP1": round(p1, 1),
            "nativeFpsP5": round(p5, 1),
            "nativeFpsVar": round(var, 2),
            "powerWMean": round(sum(powers) / len(powers), 1) if powers else None,
            "tempCMean": round(sum(temps) / len(temps), 1) if temps else None,
            "samples": n,
        }

    # ---------- 在线推理 ----------
    @staticmethod
    def _chat(base_url, api_key, model, system, user, timeout=30):
        url = base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
            "max_tokens": 700,
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    @staticmethod
    def _extract_json(content: str) -> dict:
        """从模型回复里抠出第一个 JSON 对象。"""
        if not content:
            return {}
        start = content.find("{")
        end = content.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return {}
        try:
            return json.loads(content[start : end + 1])
        except Exception:
            return {}

    def _infer(self, base_url, api_key, model, target, stats, current, caps, app_id):
        system = (
            "你是掌机 APU 功耗优化专家。目标：在满足『本机 1% 低帧 ≥ 目标真实帧数 × 0.95』"
            "的前提下，给出最省电（APU 功耗最低/续航最长）的设置。\n"
        "只允许调整以下旋钮，且必须在设备能力范围内："
        "tdp(APU 总功耗上限 W)、cpuboost(是否 CPU 加速)、cpuNum(在线 CPU 核心数)、"
        "smt、enableRyzenadjUndervolt+ryzenadjUndervoltValue(全核 CO 降压，负值 mV)、"
        "ryzenadjUndervoltCpuValue(大核 CO 降压 mV，负值)、ryzenadjUndervoltLittleValue(小核 CO 降压 mV，负值)、"
        "gpuVoltageValue(GPU VDD 偏移 mV，负值降压)、"
        "gpuMode(fix/range/native)、gpuFreq(fix 时 GPU 定频 MHz)、"
        "gpuRangeMinFreq/gpuRangeMaxFreq(range 时 GPU 频率区间 MHz)。\n"
            "当前帧率远超目标时，优先降低 tdp、关闭 boost、减少核心、加降压、降低 GPU 频率；"
            "当前帧率低于目标时，提高 tdp/开启 boost 直至达标（此即该硬件最省电达标点）。\n"
            "【稳定性硬规则，务必遵守】：降压必须保守，CPU CO 降压绝对值不超过 25mV，"
            "GPU VDD 偏移绝对值不超过 40mV；TDP 相对当前值的变化不得超过 ±40%；"
            "禁止任何可能导致系统不稳定的极端值；若不确定则贴近当前值微调。\n"
        "只输出一个 JSON 对象，不要任何解释文字，格式："
        '{"tdp":int,"cpuboost":bool,"cpuNum":int,"smt":bool,'
        '"enableRyzenadjUndervolt":bool,"ryzenadjUndervoltValue":int,'
        '"ryzenadjUndervoltCpuValue":int,"ryzenadjUndervoltLittleValue":int,'
        '"gpuVoltageValue":int,'
        '"gpuMode":"fix|range|native","gpuFreq":int,"gpuRangeMinFreq":int,'
        '"gpuRangeMaxFreq":int,"reason":"中文一句话说明"}'
        )
        user = (
            f"设备: {caps.get('cpuModel') or caps.get('deviceName') or '未知'} "
            f"(产品: {caps.get('productName','')}, 显卡: {caps.get('gpuName') or caps.get('vendor','')})\n"
            f"目标真实帧数: {target}\n"
            f"实测统计: {json.dumps(stats, ensure_ascii=False)}\n"
            f"当前设置: {json.dumps(current, ensure_ascii=False)}\n"
            f"设备能力: tdpMin={caps.get('tdpMin')} tdpMax={caps.get('tdpMax')} "
            f"gpuMin={caps.get('gpuMin')} gpuMax={caps.get('gpuMax')} "
            f"cpuMaxNum={caps.get('cpuMaxNum')} "
            f"supportRyzenadjUndervolt={caps.get('supportsRyzenadjUndervolt')}\n"
            "请输出最省电且满足帧数约束的 JSON 设置。"
        )
        resp = self._chat(base_url, api_key, model, system, user, timeout=40)
        content = resp.get("choices", [{}])[0].get("message", {}).get("content", "") or ""
        parsed = self._extract_json(content)
        if not parsed:
            raise ValueError("模型未返回可解析的 JSON")
        delta, reason = self._normalize_delta(parsed, current, caps)
        return delta, (reason or "在线模型推荐"), False

    # ---------- 启发式兜底 ----------
    @staticmethod
    def _clamp(v, lo, hi, default):
        try:
            v = int(round(float(v)))
        except Exception:
            return default
        return max(lo, min(hi, v))

    def _normalize_delta(self, parsed: dict, current: dict, caps: dict) -> tuple:
        tdp_min = caps.get("tdpMin", 3)
        tdp_max = caps.get("tdpMax", 25)
        gpu_min = caps.get("gpuMin", 200)
        gpu_max = caps.get("gpuMax", 1600)
        cpu_max = caps.get("cpuMaxNum", 8)
        rec = {}
        if "tdp" in parsed or "tdpEnable" in parsed:
            rec["tdpEnable"] = True
            rec["tdp"] = self._clamp(parsed.get("tdp", current.get("tdp", tdp_max // 2)), tdp_min, tdp_max, tdp_max // 2)
        if "cpuboost" in parsed:
            rec["cpuboost"] = bool(parsed["cpuboost"])
        if "cpuNum" in parsed:
            rec["cpuNum"] = self._clamp(parsed["cpuNum"], 2, cpu_max, cpu_max)
        if "smt" in parsed:
            rec["smt"] = bool(parsed["smt"])
        if "enableRyzenadjUndervolt" in parsed:
            rec["enableRyzenadjUndervolt"] = bool(parsed["enableRyzenadjUndervolt"])
            rec["ryzenadjUndervoltValue"] = self._clamp(
                parsed.get("ryzenadjUndervoltValue", 0), -30, 0, 0
            ) if rec["enableRyzenadjUndervolt"] else 0
        # 更细的 CPU/GPU 电压（分大小核 CO + GPU VDD 偏移）；仅在各自合法范围才采纳
        if "ryzenadjUndervoltCpuValue" in parsed:
            rec["ryzenadjUndervoltCpuValue"] = self._clamp(
                parsed.get("ryzenadjUndervoltCpuValue", 0), -30, 0, 0
            )
        if "ryzenadjUndervoltLittleValue" in parsed:
            rec["ryzenadjUndervoltLittleValue"] = self._clamp(
                parsed.get("ryzenadjUndervoltLittleValue", 0), -30, 0, 0
            )
        if "gpuVoltageValue" in parsed:
            rec["gpuVoltageValue"] = self._clamp(
                parsed.get("gpuVoltageValue", 0), -50, 0, 0
            )
        gpu_mode = parsed.get("gpuMode", current.get("gpuMode"))
        if gpu_mode in ("fix", "range"):
            rec["gpuMode"] = gpu_mode
            if gpu_mode == "fix" and "gpuFreq" in parsed:
                rec["gpuFreq"] = self._clamp(parsed["gpuFreq"], gpu_min, gpu_max, gpu_max)
            if gpu_mode == "range":
                rec["gpuRangeMinFreq"] = self._clamp(parsed.get("gpuRangeMinFreq", gpu_min), gpu_min, gpu_max, gpu_min)
                rec["gpuRangeMaxFreq"] = self._clamp(parsed.get("gpuRangeMaxFreq", gpu_max), gpu_min, gpu_max, gpu_max)
        reason = parsed.get("reason", "")
        return rec, reason

    def _safeguard(self, delta: dict, current: dict, caps: dict) -> dict:
        """统一安全护栏：锁死设备范围 + 降压保守上限 + TDP 单次变化幅度限制。

        目的：避免不同次 AI 调优结果差异过大，或降压/降频过猛导致 CPU/GPU 崩溃。
        任何越界值都被夹回安全区间；非法字段被丢弃。
        """
        if not isinstance(delta, dict):
            return {}
        tdp_min = caps.get("tdpMin", 3)
        tdp_max = caps.get("tdpMax", 25)
        gpu_min = caps.get("gpuMin", 200)
        gpu_max = caps.get("gpuMax", 1600)
        cpu_max = caps.get("cpuMaxNum", 8)
        # 保守降压上限（避免 CPU/GPU 崩溃）
        SAFE_CO_MAX = 25
        SAFE_GPU_MAX = 40

        def _i(v, d=0):
            try:
                return int(round(float(v)))
            except Exception:
                return d

        # TDP：范围内 + 与当前值偏差不超过 ±40%（防大幅跳变）
        if "tdp" in delta:
            tdp = max(tdp_min, min(tdp_max, _i(delta["tdp"], tdp_max // 2)))
            cur = current.get("tdp") or (tdp_max // 2)
            lo = max(tdp_min, int(round(cur * 0.6)))
            hi = min(tdp_max, int(round(cur * 1.4)))
            tdp = max(lo, min(hi, tdp))
            delta["tdp"] = tdp

        # 降压：锁死保守上限，禁止过猛
        for k in (
            "ryzenadjUndervoltValue",
            "ryzenadjUndervoltCpuValue",
            "ryzenadjUndervoltLittleValue",
        ):
            if k in delta:
                delta[k] = max(-SAFE_CO_MAX, min(0, _i(delta[k], 0)))
        if "gpuVoltageValue" in delta:
            delta["gpuVoltageValue"] = max(-SAFE_GPU_MAX, min(0, _i(delta["gpuVoltageValue"], 0)))

        if "cpuNum" in delta:
            delta["cpuNum"] = max(2, min(cpu_max, _i(delta["cpuNum"], cpu_max)))
        if "gpuFreq" in delta:
            delta["gpuFreq"] = max(gpu_min, min(gpu_max, _i(delta["gpuFreq"], gpu_max)))
        if "gpuRangeMinFreq" in delta:
            delta["gpuRangeMinFreq"] = max(
                gpu_min, min(gpu_max, _i(delta["gpuRangeMinFreq"], gpu_min))
            )
        if "gpuRangeMaxFreq" in delta:
            delta["gpuRangeMaxFreq"] = max(
                gpu_min, min(gpu_max, _i(delta["gpuRangeMaxFreq"], gpu_max))
            )
        # 布尔字段只保留合法布尔
        for k in ("cpuboost", "smt", "enableRyzenadjUndervolt"):
            if k in delta:
                delta[k] = bool(delta[k])
        return delta

    def _heuristic(self, target, stats, current, caps) -> tuple:
        """内置最节能规则（在线不可用 / 解析失败兜底）。"""
        p1 = stats.get("nativeFpsP1")
        if not isinstance(p1, (int, float)) or p1 <= 0:
            return None, "无有效帧率，未调整"

        tdp_min = caps.get("tdpMin", 3)
        tdp_max = caps.get("tdpMax", 25)
        gpu_min = caps.get("gpuMin", 200)
        gpu_max = caps.get("gpuMax", 1600)
        cpu_max = caps.get("cpuMaxNum", 8)
        support_uv = bool(caps.get("supportsRyzenadjUndervolt"))

        tdp = int(current.get("tdp") or max(tdp_min, tdp_max // 2))
        cpuboost = bool(current.get("cpuboost", True))
        cpu_num = int(current.get("cpuNum") or cpu_max)
        smt = bool(current.get("smt", True))
        uv = bool(current.get("enableRyzenadjUndervolt", False))
        uvv = int(current.get("ryzenadjUndervoltValue", 0) or 0)
        gpu_mode = current.get("gpuMode") or "native"
        gpu_freq = current.get("gpuFreq")
        gm_min = current.get("gpuRangeMinFreq")
        gm_max = current.get("gpuRangeMaxFreq")

        rec = {"tdpEnable": True}
        if p1 >= target:
            excess = (p1 - target) / target  # 余量比例，>=0
            reduce_frac = min(excess, 0.35)
            new_tdp = int(round(tdp * (1 - reduce_frac)))
            rec["tdp"] = max(tdp_min, min(tdp_max, new_tdp))
            if excess > 0.25 and cpuboost:
                cpuboost = False
            if excess > 0.35 and support_uv and uvv > -25:
                uv = True
                uvv = max(-25, uvv - 5)
            if excess > 0.40 and cpu_num > 3:
                cpu_num = max(3, cpu_num - 2)
            if excess > 0.30 and gpu_mode == "fix" and gpu_freq and gpu_freq > gpu_min + 100:
                rec["gpuMode"] = "fix"
                rec["gpuFreq"] = max(gpu_min + 100, int(gpu_freq * 0.9))
            if excess > 0.30 and gpu_mode == "range" and gm_max and gm_max > gpu_min + 200:
                rec["gpuMode"] = "range"
                rec["gpuRangeMinFreq"] = gm_min
                rec["gpuRangeMaxFreq"] = max(gpu_min + 200, int(gm_max * 0.9))
            reason = f"实测 1% 低帧 {p1:.0f} ≥ 目标 {target}，已下调至最省电（TDP≈{rec['tdp']}W）"
        else:
            deficit = (target - p1) / target
            add_frac = min(deficit, 0.5)
            new_tdp = int(round(tdp * (1 + add_frac)))
            rec["tdp"] = min(tdp_max, max(tdp_min, new_tdp))
            if not cpuboost:
                cpuboost = True
            reason = f"实测 1% 低帧 {p1:.0f} < 目标 {target}，已上调预算至达标（TDP≈{rec['tdp']}W，接近该硬件最省电达标点）"

        rec["cpuboost"] = cpuboost
        rec["cpuNum"] = cpu_num
        rec["smt"] = smt
        rec["enableRyzenadjUndervolt"] = uv
        rec["ryzenadjUndervoltValue"] = uvv
        return rec, reason


aiTuner = AITuner()
