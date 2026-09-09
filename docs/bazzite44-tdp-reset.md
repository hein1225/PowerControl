# Bazzite 44 下 TDP / 游戏专属设置被"重置"的诊断与根治

> 适用场景：在 Bazzite 44（及之后版本）上升级后，PowerControl 设好的 TDP 与"依游戏设置档案"里的专属 TDP 在进入游戏/会话切换后被改回。
> 结论先行：**这不是 PowerControl 的 bug，也不是配置文件丢失**，而是 Bazzite 44 新增的 `powerstation`（SteamOS-Manager 后端）在运行时接管并覆盖 TDP。停下 `powerstation` 即可根治，且 PowerControl 自身完全不依赖它。

---

## 1. 现象

- 更新到 Bazzite 44 后，手动设置的 TDP 总是被重置。
- "游戏专属设置"（perApp / 依游戏设置档案）里的 TDP 也被重置。
- 两者同时发生，且每次进游戏 / 切换会话后复现。

## 2. 环境

- 设备：OneXPlayer 掌机（非 Steam Deck）。
- 系统：`bazzite-deck-gnome:stable` **44.20260908**（Bazzite 44 deck-gnome 变体）。
- 用户 home：`/home/bazzite`（注意不是 `/home/deck`，Decky 在 Bazzite 上以实际用户名运行）。
- PowerControl 配置位置：`/home/bazzite/homebrew/settings/PowerControl/config.json`。

## 3. 根因

Bazzite 44 是一次巨型更新（700+ commits，史上最大），其中：

- **移除了 Handheld Daemon（HHD）**；
- **TDP 控制权被移交给 SteamOS-Manager / PowerStation**，并暴露为 Steam 自带 QAM 性能菜单里的 TDP 滑块；
- 更新说明明确"Decky 插件在 44 后需要更新才能正常工作"。

`powerstation.service` 在 Bazzite 44 上默认 `enabled + active`，它会在进游戏 / 会话变更时按 Steam QAM 滑块的值**重新写一次 TDP**，把 PowerControl 写进 ryzenadj / AMD 接口的值冲掉。

**关键点：PowerControl 的 `config.json` 其实一直完好无损。** 配置文件里你设的 TDP（如 `perApp["0"].defaultSettig.tdp=20, tdpEnable=true`）从未被清空或换路径——只是"应用后的实际 TDP"被 Steam 侧覆盖，从而被感知为"重置"。

### 排除"配置文件丢失"（假设 B）

通过 `find` 确认 `config.json` 仍然存在且内容包含用户自设值（非默认），因此路径变更 / 文件丢失假设不成立：

```bash
find /home/bazzite -name config.json -path '*PowerControl*'
# -> /home/bazzite/homebrew/settings/PowerControl/config.json
cat /home/bazzite/homebrew/settings/PowerControl/config.json
# perApp["0"].defaultSettig: tdp=20, tdpEnable=true  (用户自设，非默认 50/false)
```

默认长相对照：`perApp["3264786444"].defaultSettig: tdp=50, tdpEnable=false`（即未改过的默认条目）。

## 4. 诊断命令清单（可复现）

```bash
# 1) 确认 home 与配置文件存在
echo "$HOME"
ls -la /home/bazzite/homebrew/settings/PowerControl/config.json

# 2) 确认 powerstation 是否在接管 TDP
systemctl status powerstation          # enabled + active 即坐实

# 3) 读取当前实际 TDP（关键）
#    注意：系统 PATH 里的 ryzenadj 可能不是 FlyGoat 原版，不认 --show-table
RYZ=$(find /home/bazzite/homebrew/plugins/PowerControl -name ryzenadj 2>/dev/null | head -1)
sudo "$RYZ" -i | grep -i stapm
#   看 STAPM LIMIT 是否等于你设的值，且进游戏后不被弹回默认
```

## 5. 根治（三种方式，均零代码改动）

PowerControl 的风扇控制（`fan.py` 直写 hwmon sysfs / EC，OneXPlayer 在 `fan_config/ec/onexplayer2|apex|mini.yml` 与 `hwmon/oxp_ec|oxpec.yml` 适配列表）与 TDP 控制（自带 `bin/ryzenadj`）**均不依赖 powerstation**。因此直接停用它是安全的、自包含的，且 PowerControl 仍能管全部（含风扇）。

### 方式 A：PowerControl UI 一键禁用（推荐）

设置面板 →「系统兼容 (Bazzite 44+)」→ 打开「禁用 PowerStation（防止 TDP 被重置）」。

- 后端在**每次插件启动**时检查该开关并重新屏蔽 powerstation，天然防更新复位。
- 该开关与脚本共享同一意图标记 `/etc/powercontrol/disable-powerstation.flag`，二者可互操作（在 UI 关掉后，脚本的开机服务也不会再屏蔽）。

### 方式 B：随插件附带的脚本

插件 `bin/disable-powerstation.sh`（幂等，root 运行）：

```bash
sudo /path/to/PowerControl/bin/disable-powerstation.sh              # 禁用并屏蔽
sudo /path/to/PowerControl/bin/disable-powerstation.sh --status     # 仅查看状态
sudo /path/to/PowerControl/bin/disable-powerstation.sh --install-service  # 禁用 + 安装开机 oneshot 服务（彻底防更新复位）
sudo /path/to/PowerControl/bin/disable-powerstation.sh --restore    # 恢复 powerstation
```

### 方式 C：手动命令

```bash
sudo systemctl disable --now powerstation
sudo systemctl mask powerstation
```

不论哪种方式，`mask` 后该单元指向 `/dev/null`，Bazzite 的 ostree 更新不动 `/etc`，因此更新也不会再把它启用。若仍担心更新反复，用方式 A 的 UI 开关或方式 B 的 `--install-service`（写入一个开机 oneshot 服务，每次启动重屏蔽）即可双保险。

## 6. 验证

停用后，设一个明显值（如给某游戏设 18W 并开"依游戏设置档案"），进游戏，再读 TDP：

```bash
RYZ=$(find /home/bazzite/homebrew/plugins/PowerControl -name ryzenadj 2>/dev/null | head -1)
sudo "$RYZ" -i | grep -i stapm
```

实测结果（OneXPlayer + Bazzite 44.20260908）：

- 桌面 / 全局态：`STAPM LIMIT = 20.000 W`，`STAPM VALUE = 3.978 W`
- 高负载 / 游戏态：`STAPM LIMIT = 20.000 W`，`STAPM VALUE = 11.453 W`

`STAPM LIMIT` 在进游戏、高负载下始终保持为用户设定值（20W），未被弹回默认 → **根因实锤、根治成功。**

## 7. 副作用（均无害）

1. **Steam QAM 性能菜单里的 TDP 滑块失效**（它走 SteamOS-Manager / powerstation）。改用 PowerControl 调即可——这正是预期行为。
2. **充电阈值等 SteamOS-Manager 附加功能**，PowerControl 可能不覆盖，属小功能，一般用户用不到。

## 8. 对上游客服 / 兼容性的说明

- 本问题**与 PowerControl 代码无关**，是发行版在 Bazzite 44 接管 TDP 所致。PowerControl 的持久化（`confManager` → `decky.DECKY_PLUGIN_SETTINGS_DIR`）与设置应用逻辑均正常。
- 若要在 Bazzite 44 上"开箱即用"地避免冲突，插件侧可选方案：
  - （已否决）让 PowerControl 在 powerstation 之后延时 / 周期重断言 TDP —— 没必要，因为根因是 powerstation 抢写，停掉即解决；
  - （推荐给用户）在 Bazzite 44+ 文档 / README 中提示：若 TDP 被重置，停用 `powerstation.service` 即可，PowerControl 自包含可管全部（含风扇）。
- 插件**无需为 powerstation 做代码改动**即可在 Bazzite 44 正常工作，前提是用户按上述方式停用 powerstation。
