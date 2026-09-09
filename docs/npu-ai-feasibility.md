# 可行性方案：在线 AI 智能调优（按真实帧数最节能，复用游戏专属设置）

> 目标：在 PowerControl 中增加一个**可选**功能——用户进游戏后**先选择目标真实帧数**，点击"AI 调优"，然后**正常游戏 10 分钟**由插件在后台采集设备遥测，结束后调用**用户自备的在线大模型 API** 推理出**最节能**的 APU 功率/频率/降压分配方案，写入该游戏的**专属设置**并**自动打开"依游戏设置档案"开关、立即应用**；之后进该游戏原生自动套用。
>
> 相对上一版的关键变更：（1）推理**仅在线 API**（去掉本地 NPU/GPU 模型）；（2）采集从"点一下即时采样"改为"**正常玩 10 分钟**"；（3）目标为"**按设定的真实帧数（忽略插帧）最节能调优**"；（4）**不再另建 `aiProfiles`**，而是**复用 PowerControl 既有的「游戏专属设置」(`perApp[appId]`)**——调优完直接写入该游戏专属配置、打开开关、应用；"下次自动套用"由专属设置机制原生提供。
>
> 文档状态：可行性分析（未开始编码）。是否进入实现由作者（hein1225）决定。

---

## 1. 目标与范围（本版定义）

### 1.1 功能定义
- **前置（用户明确要求：先配置模型）**：使用本功能前**必须先配置在线模型**（端点 / 密钥 / 模型名），模型配置是启用调优的**第一道门槛**；未配置时「AI 调优」按钮置灰并提示"请先配置在线模型"。配置本身不触发任何调优，仅解锁后续流程。
- **触发**：进游戏 → 在面板选择「目标真实帧数」→ 点「AI 调优」→ **正常游戏 10 分钟**（插件后台采集）→ 结束后一次性推理 + 写入该游戏专属设置。
- **推理后端**：**仅在线 API**（用户自备 OpenAI 兼容端点 + Key）。本地**不跑任何模型**，零本地算力。
- **真实帧数**：由用户**设定**（本机率），采集与判定**只读本机渲染帧率、忽略插帧**（小黄鸭/Lossless Scaling、FSR FrameGen 等，见 §3.2）。
- **调优目标**：在**满足目标真实帧数（含 1% 低帧裕度）**前提下，尽量**降低 APU 功耗 / 延长续航**。
- **落点（本版核心）**：调优结果**写入该游戏的专属设置** `perApp[appId]`，并**自动打开"依游戏设置档案"开关（`overwrite=true`）**、**立即应用**；之后进入该游戏由专属设置机制**原生自动套用**。

### 1.2 适用场景
- 所有 AMD Ryzen 掌机/APU（含 Steam Deck、Legion Go、ROG Ally、Ryzen AI 系列）：本方案**不依赖 NPU**，覆盖全部 AMD 掌机。
- 用户不想手动调参，希望"设个目标帧数、玩 10 分钟、系统帮我配到最省电并记住"，且同一游戏下次免调。

### 1.3 明确非目标
- **不做常驻实时闭环**：仅"采集 10 分钟 → 一次性调优 → 写入专属设置复用"，无持续 AI 占用、无逐帧振荡风险。
- **不做字面独立 CPU/GPU 电压直写**：受 ryzenadj/SMU 限制，以"功率/频率预算分配 + 每核 CO 降压"实现（见 §4.3）。
- **不新增独立存储**：直接复用 `perApp[appId]`，不引入 `aiProfiles` 平行结构（避免双份真相源、与现有专属设置 UI 冲突）。
- **默认关闭、不污染无 AI 设备的既有行为**：在线 API 必须用户配置 Key 后才可用。

---

## 2. 现状分析（基于本仓库 `hein1225/PowerControl`）

### 2.1 架构速览
- decky-loader 插件，root 权限；Python 后端 `main.py` 暴露 WebSocket RPC；设置经 `confManager` 持久化（`confManager.setSettings(settings)` 存整份 `SettingsData`）。
- 现有控制面（AI 动作落点，全部可复用）：`powerManager.set_tdp()`、`cpuManager`（boost/SMT/在线核/CO 降压）、`gpuManager`（频率 fix/range）、`sysInfo.py`、`tdp_backend.py`（TDP 多后端统一 dispatch）。

### 2.2 游戏专属设置（**本功能直接复用，关键**）
- 存储：`SettingsData.perApp: { [appId: string]: AppSettingData }`（`src/util/settings.ts`）。
  - `AppSettingData` 含：`overwrite`（依游戏设置档案开关）、`defaultSettig` / `acStting` / `batSetting` 三套 `AppSetting`。
  - `AppSetting` 字段（即 AI 要写的旋钮，见 §4.4 映射）：`tdpEnable`/`tdp`、`gpuMode`/`gpuFreq`/`gpuRangeMinFreq`/`gpuRangeMaxFreq`、`cpuboost`、`cpuNum`（在线核数）、`smt`、`enableRyzenadjUndervolt`/`ryzenadjUndervoltValue`（CO 降压）、`epp`/`cpuGovernor`/`cpuMaxPerfPct`、`coreSelectionEnabled`/`cpuCoreSelection` 等。
- **原生行为（重要）**：`Settings.ensureAppID()` 在 `perApp[appId].overwrite == true` 时返回该 appId，插件据此走 `perApp[appId]` 配置；进入该游戏即**自动套用专属设置**——因此"下次进入自动应用"是免费获得的，无需另做 `aiAutoApply`。
- **UI**：`settings.tsx` 的「依游戏设置档案」`ToggleField` 绑定 `Settings.setOverWrite(override)`；首次为该游戏开专属设置时从 `DEFAULT_APP` 复制（`settings.ts` `initAppSettingIfNeeded`/deepCopy 逻辑）。
- **当前游戏识别**：`RunningApps.active()` 返回前台 appid（Steam 游戏）；非游戏（桌面）时为 `DEFAULT_APP`，此时不可调优（与现有专属设置一致）。

---

## 3. 技术可行性

### 3.1 仅在线 API：风险最低、覆盖最广
| 项 | 说明 |
|---|---|
| 本地算力 | 零；依赖联网 + 用户自备 Key |
| 设备要求 | 任意 AMD APU；**含 Steam Deck**；无需 NPU、无需 amdxdna/ONNX 打包 |
| 成熟度 | 高（OpenAI 兼容 chat + JSON/function 输出） |
| 代价 | 遥测出网（需用户明确同意 + Key 本地加密）；依赖网络 |

### 3.2 真实帧数采集（忽略插帧）——核心
- **目标帧数由用户设定**（本机率）；插件不替用户猜。
- **采集"本机真实渲染帧率"**，排除插值：
  - 主源：`gamescope --stats-path` 的 **`app_fps`**（游戏本机渲染率，已排除 gamescope FSR FrameGen）。
  - 更准：`MangoHUD` 挂钩游戏进程的 present 率（只计游戏自身 present，不计下游注入帧）。
  - **绝不采用** composited/displayed FPS 或插帧后显示帧率。
- **外部帧生成（小黄鸭/Lossless Scaling）**：在游戏与 compositor 之间注入帧，gamescope 看到的是已插帧流。对策：用户把目标设为**想要的本机率**；插件优先用 **MangoHUD 本机 present 率**作真值。两源皆无则提示并拒绝用插帧率。

### 3.3 10 分钟后台采集——可行且轻量
- ~1 Hz 采样，10 分钟约 600 条；后台进行、对用户无感；支持挂起恢复、中途退出取消、提前结束（≥60s 即用已采数据）；结束才聚合、发一次 HTTPS。

### 3.4 在线 API 协议
- OpenAI 兼容 Chat Completions（base_url / api_key / model 可配，兼容 OpenAI、DeepSeek、通义、Ollama 等）。
- `system` 固化"掌机功耗优化专家"；`user` 携带聚合统计 + 目标真实帧数 + 设备能力 + 当前控制量。
- 响应：受约束 JSON（见 §4.5）；用 JSON mode / response_format 降低解析失败率。
- **失败兜底**：API 超时/不可用 → 回退内置启发式最节能规则（§6），提示"在线推理失败，已用本地启发式"，不卡死。

### 3.5 当前游戏识别——可行（`RunningApps.active()`，见 §2.2）

---

## 4. 系统架构设计

### 4.1 组件与数据流（复用专属设置）
```
用户进游戏 → 选「目标真实帧数」→ 点「AI 调优」
   │
   ▼
[采集 10:00 倒计时] ~1Hz: 本机真实FPS(gamescope app_fps/MangoHUD) + 遥测(sysInfo/hwmon)
   │ （后台进行，用户正常游戏；可提前结束/取消）
   ▼
聚合统计 → 在线 API (HTTPS, JSON) → 解析出「推荐 AppSetting 增量」
   │
   ▼
AI 后端返回增量 + 理由；前端写入专属设置：
   perApp[appId].defaultSettig  ←  应用增量（仅改 AI 优化的旋钮，其余保留）
   perApp[appId].overwrite = true   ← 自动打开「依游戏设置档案」开关
   │
   ▼
保存 Settings（现有 setSettings RPC）+ 现有 apply 路径立即应用
   │
   ▼
弹提示「调优完成，已保存至本游戏专属设置（已开启）」+ 前后对比/理由
   │
   ▼
（之后进入该游戏 → 专属设置机制原生自动套用）
```

### 4.2 新增模块（建议）
- 后端 `py_modules/ai_tuner.py`：
  - `collect(duration_s=600)`：10 分钟后台采样（暂停/取消/提前结束）。
  - `aggregate(samples)`：本机 FPS 的 mean / p1 低帧 / 方差 / max + CPU%/GPU%/温度/功耗均值 + 续航放电率。
  - `infer(targetFps, stats, deviceCaps, current)`：发 HTTPS → 解析 **AppSetting 增量**；失败回退 `heuristic_tune()`。
  - `heuristic_tune(...)`：内置最节能规则（§6）作兜底。
  - `apply` 不在后端做——后端只返回增量；**写入 `perApp` 与 apply 走前端现有专属设置逻辑**（保持 `perApp` 单一所有权在前端 `Settings`）。
- 前端 `src/`：
  - 新增「AI 智能调优」卡片（目标帧数选择、在线 API 配置、采集倒计时/进度、完成横幅）。
  - `start_ai_tune(targetFps)`（后端采集+推理，返回增量）→ 写入 `perApp[appId].defaultSettig`（调用现有初始化/复制逻辑，仅覆盖 AI 旋钮）→ `Settings.setOverWrite(true)` → 现有保存 + apply。
- `main.py` 新增 RPC（风格一致）：`get_ai_status()` / `set_ai_online(base_url,api_key,model)` / `start_ai_tune(targetFps)` / `stop_ai_tune()`。
  - **不再需要** `aiProfiles` / `apply_ai_profile` / `aiAutoApply` 等独立 RPC——全部由现有专属设置 `perApp` + `overwrite` 承担。

### 4.3 "电压分配"→"预算分配"的等价映射（不变）
- GPU 侧：调 `gpuMode`/`gpuFreq`(fix) 或 `gpuRangeMinFreq/MaxFreq`（下限↑=GPU 分得更多预算）。
- CPU 侧：调 `cpuboost`/`smt`/`cpuNum`(在线核) + `enableRyzenadjUndervolt`/`ryzenadjUndervoltValue`(CO 降压)（限核/降压=腾出预算）。
- 总预算：`tdpEnable`+`tdp` 设天花板；在总 TDP 内把比例让给瓶颈侧。
- 安全护栏：动作带最小步进与最大偏移；不突破现有 TDP/温度上限；用户手动改某项则 AI 让出该项（用户优先）。

### 4.4 AI 动作 → AppSetting 字段映射（写入 `perApp[appId].defaultSettig`）
| AI 推荐 | 写入字段 |
|---|---|
| APU TDP 上限 | `tdpEnable=true`, `tdp` |
| GPU 频率（定频） | `gpuMode=fix`, `gpuFreq` |
| GPU 频率（区间） | `gpuMode=range`, `gpuRangeMinFreq`, `gpuRangeMaxFreq` |
| CPU boost | `cpuboost` |
| 在线核数 | `cpuNum` |
| SMT | `smt` |
| 每核 CO 降压 | `enableRyzenadjUndervolt=true`, `ryzenadjUndervoltValue` |
| CPU 能效偏好 | `epp` / `cpuGovernor` / `cpuMaxPerfPct`（可选） |
- **保留用户其余设置**：AI 仅在 `defaultSettig` 中覆盖自己优化的字段；若该游戏已有专属设置，其余字段保持用户原值；若首次创建，则从 `DEFAULT_APP` 继承（沿用现有 `initAppSettingIfNeeded` 行为）。

### 4.5 在线 API 请求/响应 schema（建议）
```json
// 请求 user 消息
{
  "device": "SteamDeck OLED / Ryzen AI 9 HX370 ...",
  "targetNativeFps": 40,
  "objective": "minimize APU power while native 1% low FPS >= target (small margin)",
  "current": { "tdp": 15, "gpuMode": "fix", "gpuFreq": 1600, "cpuboost": true,
               "cpuNum": 8, "ryzenadjUndervoltValue": 0 },
  "stats": { "nativeFpsMean": 58.2, "nativeFpsP1": 44.0, "nativeFpsVar": 3.1,
             "cpuUtil": 55, "gpuUtil": 92, "tempC": 73,
             "apuPowerW": 14.5, "battDischargeW": 13.0 }
}
// 响应（受约束 JSON，即 AppSetting 增量）
{
  "tdp": 11, "gpuMode": "fix", "gpuFreq": 1300, "cpuboost": false,
  "cpuNum": 6, "enableRyzenadjUndervolt": true, "ryzenadjUndervoltValue": -12,
  "reason": "GPU 瓶颈且本机率远超目标，降 TDP+降频+限核+降压以最省电，p1 仍>40"
}
```

### 4.6 调优目标：最节能约束优化（给模型的硬约束）
- **约束**：应用后本机 **1% 低帧 ≥ 目标 ×(1 − 裕度)**（裕度 5–10%）。
- **目标**：约束内**最小化 APU 功耗**（最大化续航）；当前余量大则继续下调 TDP/频率/核数/加降压。
- **低于目标**：必须上调预算达标，提示"已到该硬件最省电达标点"。
- 插件侧叠加：动作死区/步进、温度/TDP 硬上限、不超过出厂上限。

### 4.7 落点：写入专属设置并开开关（本版核心，替代原 aiProfiles）
- **不新增存储**，直接复用 `perApp[appId]`：
  - 调优完成前端把增量写入 `perApp[appId].defaultSettig`（首次则按现有逻辑从 `DEFAULT_APP` 建档）。
  - 置 `perApp[appId].overwrite = true` → **自动打开「依游戏设置档案」开关**。
  - 经现有 `setSettings` 保存 + 现有 apply 路径**立即应用**。
- **下次进入该游戏**：专属设置机制原生自动套用（无需 AI 模块额外逻辑）。
- **查看/编辑/重置**：完全复用现有「游戏专属设置」UI，AI 不另做管理页；用户可在专属设置里手动微调，AI 下次调优会在此基础上更新优化字段。

### 4.8 前端（向导式，薄一层）
- 新增「AI 智能调优」卡片，按**强制顺序**分步：
  - **Step 0 · 配置模型（必做）**：在线 API 配置（端点 / 密钥 / 模型名），密钥本地加密保存、输入框不明文回显；保存后立即做连通性自检（一次轻量请求）。**未通过配置前，「AI 调优」按钮整体置灰不可用**，并提示"请先配置在线模型"。
  - **Step 1 · 目标真实帧数**：选择器（30/40/45/60/90/120 + 自定义），标注"本机率，忽略插帧"。
  - **Step 2 · 调优**：「AI 调优」按钮（仅 Step 0 完成后可点）+ **10:00 采集倒计时进度条** + "请正常游戏" + 推理中转圈。
  - **完成态**：横幅「调优完成，已保存至本游戏专属设置（已开启）」+ 前后对比 + 推荐理由；提示"下次进该游戏会自动套用本配置"。
- 真正的"专属设置"查看/开关/编辑 = 现有 `settings.tsx` 那套，不动。

### 4.9 配置持久化
- `confManager` 新增项**仅**：`aiOnline`(base_url/api_key/model，密钥加密)、`aiCollectSec`(默认 600，可配)。
- 调优结果本身存于既有 `perApp[appId]`，**不**在 `SettingsData` 另开段。
- 默认全部关闭/空，不影响现有默认行为。

---

## 5. 控制策略要点（一次性）
- **特征**：本机真实 FPS 分布、CPU%/GPU%/温度/功耗、当前控制量（见 §4.4 来源）。
- **动作**：写入 `perApp[appId].defaultSettig` 的对应字段（TDP/频率/boost/核数/CO 降压/SMT…）。
- **目标**：真实帧数约束下最省电；稳帧裕度由 1% 低帧保证。
- **安全**：聚合平滑、动作死区/步进、温度/TDP 硬上限、应用前可预览取消、看门狗（API 超时回退启发式）、可"再调一次"迭代、"撤销/恢复专属设置"。

---

## 6. 内置启发式最节能规则（API 兜底，零依赖）
当在线 API 不可用时本地兜底，即"最节能约束优化"的规则化近似：
1. `nativeFpsP1 ≥ target × 1.1`：有余量 → 逐步降 `tdp`、降 `gpuFreq`、关 `cpuboost`、减 `cpuNum`、加 CO 降压，直到余量收窄到 5–10%。
2. `target ≤ nativeFpsP1 < target × 1.1`：维持现状（已最省且达标）。
3. `nativeFpsP1 < target`：上调预算（提 TDP/频率/开 boost）直至达标，提示"已到该硬件最省电达标点"。
4. 全程受温度/TDP 上限钳制；每次只动一项并验证，避免过冲。
> 该规则本身有独立价值：Phase 1 不接在线 API 也能交付"按真实帧数最节能 + 写入专属设置"。

---

## 7. 实施路线（分阶段，配置模型先行）
- **Phase 0 — 配置模型（用户要求的第一道门槛）**：实现 `set_ai_online(base_url, api_key, model)`（密钥本地加密存储、不明文回显）+ 连通性自检 RPC + 前端 Step 0 配置 UI；完成后才解锁「AI 调优」按钮。此阶段即满足"先配置模型"。
- **Phase 1 — 真实帧率源验证**：确认 `gamescope app_fps` / MangoHUD 本机 present 率可读且能排除插帧；产出探测代码。
- **Phase 2 — 采集 + 启发式最节能 + 写入专属设置 + 开开关 + 完成提示（零模型推理依赖）**：打通"选目标帧数 → 采 10 分钟 → 启发式出增量 → 写 `perApp[appId]` + `overwrite=true` + 应用 → 弹提示"；验证 `RunningApps.active()` 识别与专属设置写入/自动套用。运行时若已配置模型且 API 可达，可直接走 API（见 Phase 3）；未配置则仍可用启发式兜底（但按钮按用户要求需先配置才出现）。
- **Phase 3 — 接入在线 API 推理**：补全 `infer()`（HTTPS + JSON 解析 + 超时回退启发式），替换/增强 Phase 2 的规则输出。
- **Phase 4 — UI 向导打磨**：倒计时/进度/前后对比/理由展示；回归（无后端设备完全不受影响）。

---

## 8. 风险与缓解
| 风险 | 等级 | 缓解 |
|---|---|---|
| 在线 API 出网/隐私/超时 | 中 | 默认关闭、密钥本地加密、仅发聚合统计、超时回退本地启发式、UI 明确提示 |
| 真实帧率被插帧污染 | 中 | 只用 `app_fps`/MangoHUD 本机率；两源皆无则拒绝用插帧率 |
| 当前游戏 appid 取不到（桌面态） | 中 | 非游戏态（`DEFAULT_APP`）禁止调优，与现有专属设置一致 |
| 误调/覆盖用户手动设置 | 中 | AI 仅覆盖优化字段、保留其余；应用前可取消、可撤销专属设置 |
| 10 分钟采集被打断 | 低 | 支持提前结束(≥60s)/取消丢弃/挂起恢复 |
| 热/电池安全 | 中 | 动作受现有 TDP/温度上限约束 |
| 插件体积/依赖膨胀 | 低 | 仅新增在线 HTTP 调用（无模型/无 NPU 驱动） |

---

## 9. 结论与建议
- **可行性结论**：高度可行、风险低。去掉本地模型后最大技术不确定项消失，设备覆盖全部 AMD 掌机；10 分钟采集轻量无感；在线 API 用 OpenAI 兼容接口即可；"按真实帧数最节能"是良定义约束优化。
- **复用专属设置是关键简化**：不另建 `aiProfiles`，直接写 `perApp[appId]` 并开 `overwrite`，既消除双份存储/双管理 UI 的风险，又**白嫖"进游戏自动套用"的原生能力**——这是比上版更干净、更易被上游 mengmeet 接受的形态。
- **推荐顺序**：先 **Phase 1（采集 + 启发式最节能 + 写专属设置 + 开开关 + 提示）** 跑通整条链路，再 **Phase 2 接在线 API**、**Phase 3 UI**。
- **上游 PR 策略**：可选模块、默认关闭、不污染现有设备；差异化亮点"设目标真实帧数 → 玩 10 分钟 → 最省电 → 自动写入并开启该游戏专属设置"，且完全复用现有专属设置 UI/自动套用。

---

## 10. 待确认问题（实现前需 hein1225 拍板）
1. 在线 API 协议/厂商？（默认 OpenAI 兼容端点，是否要预置某家或支持自定义 base_url）
2. API 失败时是否**回退内置启发式**兜底，还是直接报错让用户重试？
3. 调优写入 `defaultSettig`（不论插电/电池）即可，还是需要对 **AC / 电池分别调优**（写 `acStting`/`batSetting`）？
4. 10 分钟采集时长是否**固定 600s**，还是允许 UI 配置（5/10/15 分钟）与提前结束？
5. 是否把**续航放电率**纳入采集（仅电池模式有意义，插电可省略）？
6. 文案是否接受"智能功率分配/最节能调优"而非字面"电压分配"？

> 文档完。确认后建议从 **Phase 0（真实帧率源验证）** 或 **Phase 1（采集+启发式+写专属设置+开开关+提示）** 切入（push 类操作仍须你明确许可）。

---

## 11. 实现进度（2026-09-09 起，hein1225 已授权开始执行）

已按本方案（纯在线 API 版、复用游戏专属设置）落地核心代码：

- **后端** `py_modules/ai_tuner.py`：在线模型配置持久化（独立配置 `ai_tune_config`，密钥 XOR+base64 混淆，不进主 settings blob 以免被前端 saveSettings 覆盖）、10 分钟后台采集（gamescope `app_fps` + hwmon 遥测）、聚合（含 1% 低帧）、在线 API 推理（urllib，OpenAI 兼容，失败回退启发式）、最节能启发式规则、状态机与取消。
- **`main.py`** 注册 6 个 RPC：`get_ai_online / set_ai_online / test_ai_online / start_ai_tune / get_ai_tune_status / stop_ai_tune`。
- **前端** `backend.ts` 增加对应 callable；`settings.ts` 增加 `applyAITuneRecommendation(delta)`（写入 active 游戏 `defaultSettig` + 开 `overwrite` 开关 + 应用）。
- **新增向导** `src/components/aiTune.tsx`（三步：配置模型→选目标真实帧数→采集倒计时/完成提示），已注册进 `settings.tsx` 的「AI 智能调优」分区，仅游戏内且插件开启时显示；调优完成自动写专属设置并提示。

**未决 / 待设备验证**：
- gamescope 统计文件实际路径需在真机确认（`--stats-path`）；取不到本机率时调优报错提示，符合 §3.2。
- 前端需 `npm install && npm run build`（decky 打包）才能真机运行；本机仅做了 Python 语法校验。
- §10 待确认问题按默认决策实现：默认写 `defaultSettig`（AC/电池分别调优未做）、采集时长可配（前端传 `collectSec`，默认 600s）、在线推理失败时回退启发式。
- **git 状态**：改动未提交、未推送（按 hein1225 规则，push 须其明确许可）。
