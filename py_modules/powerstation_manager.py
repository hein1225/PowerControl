"""
PowerStation 管理：解决 Bazzite 44+ 下 powerstation（SteamOS-Manager 后端）
在运行时覆盖 PowerControl 设置的 TDP / 游戏专属设置的问题。

设计要点（安全版，绝不 mask）：
- 单一真相：FLAG 文件 /etc/powercontrol/disable-powerstation.flag 表示「用户意图禁用」。
  与 bin/disable-powerstation.sh 共享同一 FLAG，二者完全兼容、可互操作。
- 禁用（disabled=true）= touch FLAG + systemctl disable --now。
- 恢复（disabled=false）= rm FLAG + systemctl enable。
- 注意：绝不使用 `systemctl mask/unmask`。mask 会在 /etc/systemd 写入指向 /dev/null 的
  软链，该改动在卸掉插件与重启后都不会自动撤销，可能使依赖 powerstation 的会话卡死。
  因此只做可逆的 disable/enable。
- 不再于 Plugin._main 自动调用：避免任何启动期 systemctl 操作卡住事件循环或改动系统状态。
- 仅操作固定的 powerstation.service 单元，命令参数白名单化，不拼接用户字符串。
"""

import os
import subprocess

from config import logger

UNIT = "powerstation.service"
FLAG = "/etc/powercontrol/disable-powerstation.flag"


def _systemctl(args):
    """调用 systemctl。优先用绝对路径，回退 PATH 中的 systemctl。"""
    for binp in ("/usr/bin/systemctl", "/bin/systemctl", "systemctl"):
        if binp == "systemctl" or os.path.exists(binp):
            try:
                return subprocess.run(
                    [binp, *args], capture_output=True, text=True, timeout=30
                )
            except Exception as e:
                logger.error(f"[powerstation] 调用 {binp} 失败: {e}")
                return None
    return None


def get_status() -> dict:
    """返回 powerstation 当前状态。"""
    try:
        exists = False
        r = _systemctl(["list-unit-files", UNIT])
        if r and UNIT in (r.stdout or ""):
            exists = True
        enabled_out = (_systemctl(["is-enabled", UNIT]).stdout or "").strip()
        active_out = (_systemctl(["is-active", UNIT]).stdout or "").strip()
        return {
            "exists": exists,
            "enabled": enabled_out == "enabled",
            "masked": enabled_out == "masked",
            "active": active_out == "active",
            "disabled_by_plugin": os.path.exists(FLAG),
        }
    except Exception as e:
        logger.error(f"[powerstation] 读取状态失败: {e}", exc_info=True)
        return {
            "exists": False,
            "enabled": False,
            "masked": False,
            "active": False,
            "disabled_by_plugin": os.path.exists(FLAG),
        }


def set_disabled(disabled: bool) -> bool:
    """设置是否禁用 powerstation（仅 disable --now / enable，可逆，绝不 mask）。"""
    try:
        if disabled:
            os.makedirs(os.path.dirname(FLAG), exist_ok=True)
            open(FLAG, "w").close()
            _systemctl(["disable", "--now", UNIT])
            logger.info("[powerstation] 已禁用（disable --now，未 mask）")
        else:
            if os.path.exists(FLAG):
                os.remove(FLAG)
            _systemctl(["enable", UNIT])
            logger.info("[powerstation] 已恢复 powerstation（enable）")
        return True
    except Exception as e:
        logger.error(f"[powerstation] 设置禁用失败: {e}", exc_info=True)
        return False


def ensure_disabled() -> None:
    """若用户意图禁用，则重新 disable --now（幂等，防更新复位）。绝不 mask。"""
    try:
        if os.path.exists(FLAG):
            _systemctl(["disable", "--now", UNIT])
            logger.info("[powerstation] ensure_disabled: 已重新 disable --now（未 mask）")
    except Exception as e:
        logger.error(f"[powerstation] ensure_disabled 失败: {e}", exc_info=True)


def repair_if_masked() -> dict:
    """自愈：历史上某些版本误用 `systemctl mask` 在 /etc/systemd/system/ 留下了指向
    /dev/null 的持久软链；该软链在卸插件与重启后都不会自动撤销，且会让依赖 powerstation
    的会话在加载期卡死（表现为「打开 decky loader 系统直接卡死」，且换回原版也卡）。

    本函数在插件加载时自动检测并修复：
    - 若 powerstation 处于 masked：unmask 移除坏软链（恢复系统可用）；
    - 修复后若用户曾意图禁用（FLAG 存在），则重新以『可逆的 disable --now』保持原意图，
      但绝不再 mask。
    返回修复动作摘要，便于日志排查。

    注意：unmask/enable/disable 均为系统常规可逆操作；本函数不重启任何服务、不删除用户数据。
    """
    result = {"was_masked": False, "unmasked": False, "disabled_after": False}
    try:
        st = get_status()
        if st.get("masked"):
            result["was_masked"] = True
            _systemctl(["unmask", UNIT])
            result["unmasked"] = True
            logger.info("[powerstation] repair_if_masked: 检测到 masked，已执行 unmask 移除坏软链")
            # 若用户此前意图禁用，重新以可逆方式 disable（不 mask），保持原行为
            if os.path.exists(FLAG):
                _systemctl(["disable", "--now", UNIT])
                result["disabled_after"] = True
                logger.info("[powerstation] repair_if_masked: 已重新 disable --now（保留用户意图，未 mask）")
            else:
                logger.info("[powerstation] repair_if_masked: unmask 完成，未改动启用状态（按系统默认）")
        else:
            logger.info("[powerstation] repair_if_masked: 未发现 masked，无需修复")
        return result
    except Exception as e:
        logger.error(f"[powerstation] repair_if_masked 失败: {e}", exc_info=True)
        return result


class _PowerStationManager:
    def get_status(self):
        return get_status()

    def set_disabled(self, disabled: bool):
        return set_disabled(disabled)

    def ensure_disabled(self):
        return ensure_disabled()

    def repair_if_masked(self):
        return repair_if_masked()


# 暴露单例，供 main.py 以 powerstationManager.get_status() 等方式调用
powerstationManager = _PowerStationManager()
