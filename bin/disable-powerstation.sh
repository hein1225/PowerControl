#!/usr/bin/env bash
#
# disable-powerstation.sh
# -----------------------------------------------------------------------------
# 解决 Bazzite 44+ 下 powerstation（SteamOS-Manager 后端）在运行时覆盖
# PowerControl 设置的 TDP / 游戏专属设置的问题。
#
# 原理：Bazzite 44 把 TDP 控制权从 Handheld Daemon 移交给了 SteamOS-Manager /
# PowerStation。powerstation.service 默认 enabled + active，会在进游戏 / 会话
# 切换时按 Steam QAM 滑块值重写 TDP，把 PowerControl 设的值冲掉（config.json
# 本身不会丢）。停用并屏蔽 powerstation 即可根治——PowerControl 用自带
# bin/ryzenadj（TDP）+ fan.py 直写 hwmon/EC（风扇）即可管全部，不依赖它。
#
# 本脚本幂等，可重复运行。需以 root 执行（Bazzite 上一般 sudo）。
#
# 单一真相：FLAG 文件表示"用户意图禁用"，与本插件后端的开关完全共享。
#   /etc/powercontrol/disable-powerstation.flag  存在 = 禁用意图
#
# 用法：
#   sudo ./disable-powerstation.sh                禁用并屏蔽（默认动作）
#   sudo ./disable-powerstation.sh --status        仅查看状态
#   sudo ./disable-powerstation.sh --install-service  禁用 + 安装开机 oneshot 服务（彻底防更新复位）
#   sudo ./disable-powerstation.sh --restore       恢复 powerstation（取消禁用）
#
# 验证是否被覆盖已解除：
#   RYZ=$(find /home/*/homebrew/plugins/PowerControl -name ryzenadj 2>/dev/null | head -1)
#   sudo "$RYZ" -i | grep -i stapm
#   （STAPM LIMIT 应等于你在 PowerControl 设的值，进游戏后不被弹回默认）
# -----------------------------------------------------------------------------
set -u

UNIT="powerstation.service"
SERVICE_NAME="disable-powerstation.service"
FLAG="/etc/powercontrol/disable-powerstation.flag"
SELF="$(readlink -f "${BASH_SOURCE[0]}")"

# 定位 systemctl 二进制
systemctl_bin="systemctl"
for p in /usr/bin/systemctl /bin/systemctl; do
  [ -x "$p" ] && systemctl_bin="$p" && break
done

is_masked() { [ "$( "$systemctl_bin" is-enabled "$UNIT" 2>/dev/null )" = "masked" ]; }
is_enabled() { [ "$( "$systemctl_bin" is-enabled "$UNIT" 2>/dev/null )" = "enabled" ]; }
is_active() { [ "$( "$systemctl_bin" is-active  "$UNIT" 2>/dev/null )" = "active" ]; }
unit_exists() { "$systemctl_bin" list-unit-files "$UNIT" 2>/dev/null | grep -q "$UNIT"; }

print_status() {
  echo "== PowerStation 状态 =="
  if ! unit_exists; then echo "  unit: 不存在（无需处理）"; return; fi
  echo "  存在:       是"
  echo "  启用(enable): $(is_enabled && echo 是 || echo 否)"
  echo "  运行(active): $(is_active && echo 是 || echo 否)"
  echo "  已屏蔽(mask): $(is_masked && echo 是 || echo 否)"
  echo "  本插件禁用意图: $([ -f "$FLAG" ] && echo 是 || echo 否)"
}

do_disable() {
  if ! unit_exists; then echo "powerstation.service 不存在，无需禁用。"; return 0; fi
  echo "正在停用并屏蔽 powerstation（防 Bazzite 更新复位）..."
  "$systemctl_bin" disable --now "$UNIT" 2>/dev/null
  "$systemctl_bin" mask "$UNIT" 2>/dev/null
  mkdir -p "$(dirname "$FLAG")"
  : > "$FLAG"
  if is_masked; then
    echo "✓ 已屏蔽 powerstation（指向 /dev/null，系统更新也不会复拉）"
  else
    echo "✗ 屏蔽失败，请确认是否以 root 执行"
    return 1
  fi
}

do_restore() {
  if ! unit_exists; then echo "powerstation.service 不存在。"; return 0; fi
  echo "正在恢复 powerstation..."
  rm -f "$FLAG"
  "$systemctl_bin" unmask "$UNIT" 2>/dev/null
  "$systemctl_bin" enable "$UNIT" 2>/dev/null
  "$systemctl_bin" start "$UNIT" 2>/dev/null
  echo "✓ 已恢复 powerstation（启用并启动，TDP 交由 SteamOS-Manager 管理）"
}

install_service() {
  local svc="/etc/systemd/system/$SERVICE_NAME"
  echo "安装开机服务 $SERVICE_NAME（每次启动重屏蔽 powerstation，彻底防更新复位）..."
  cat > "$svc" <<EOF
[Unit]
Description=Ensure powerstation stays disabled (PowerControl fix)
After=multi-user.target
Wants=multi-user.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/bash "$SELF" --ensure

[Install]
WantedBy=multi-user.target
EOF
  "$systemctl_bin" daemon-reload
  "$systemctl_bin" enable "$SERVICE_NAME"
  echo "✓ 已安装并启用开机服务（$svc）"
}

case "${1:-}" in
  --status)
    print_status
    ;;
  --restore)
    do_restore
    ;;
  --install-service)
    do_disable
    install_service
    ;;
  --ensure)
    # 供开机服务调用：仅当存在禁用意图标记时才重屏蔽（与 UI 开关一致）
    if [ -f "$FLAG" ] && unit_exists; then
      "$systemctl_bin" disable --now "$UNIT" 2>/dev/null
      "$systemctl_bin" mask "$UNIT" 2>/dev/null
    fi
    ;;
  --disable|"")
    do_disable
    print_status
    ;;
  *)
    echo "用法: $0 [--disable|--status|--install-service|--restore]"
    exit 1
    ;;
esac
