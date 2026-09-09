import {
  PanelSection,
  PanelSectionRow,
  ButtonItem,
  DialogButton,
  ModalRoot,
  ToggleField,
  showModal,
} from "@decky/ui";
import QRCode from "qrcode";
import { useEffect, useRef, useState, FC } from "react";
import {
  Settings,
  RunningApps,
  DEFAULT_APP,
  PluginManager,
  ComponentName,
  UpdateType,
} from "../util";
import {
  getAiOnline,
  setAiOnline,
  testAiOnline,
  startAiTune,
  getAiTuneStatus,
  stopAiTune,
  startQrConfig,
  stopQrConfig,
  Backend,
  getDeviceInfo,
} from "../util/backend";

type Step = "config" | "target" | "tuning" | "done" | "error";

const FPS_OPTIONS = [30, 40, 45, 60, 90, 120];

const inputStyle: React.CSSProperties = {
  width: "100%",
  height: "32px",
  background: "rgba(0,0,0,0.25)",
  border: "1px solid rgba(255,255,255,0.15)",
  borderRadius: "4px",
  color: "#fff",
  padding: "0 8px",
  fontSize: "13px",
};

const rowGap: React.CSSProperties = { marginBottom: "8px" };

// ---------------- 1) 远程 AI 模型配置（始终可访问） ----------------
export const AITuneConfigComponent: FC = () => {
  (globalThis as any).__traceRender?.("AITuneConfigComponent");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("");
  const [collectMin, setCollectMin] = useState(5);
  const [testMsg, setTestMsg] = useState("");

  useEffect(() => {
    getAiOnline()
      .then((cfg: any) => {
        setBaseUrl(cfg?.base_url || "");
        setModel(cfg?.model || "");
        setCollectMin(Math.max(1, Math.round((cfg?.collect_sec || 600) / 60)));
      })
      .catch(() => {});
  }, []);

  const saveConfig = async () => {
    setTestMsg("保存中…");
    if (!baseUrl.trim() || !apiKey.trim() || !model.trim()) {
      setTestMsg("请填写端点、密钥与模型名");
      return;
    }
    const ok = await setAiOnline(
      baseUrl.trim(),
      apiKey,
      model.trim(),
      collectMin * 60
    );
    if (!ok) {
      setTestMsg("保存失败");
      return;
    }
    const t = await testAiOnline();
    setTestMsg(
      t.ok ? "连接成功 ✓ " + (t.message || "") : "连接失败: " + (t.message || "")
    );
  };

  const [qrLoading, setQrLoading] = useState(false);

  useEffect(() => {
    console.error("AITuneConfigComponent MOUNTED (route=" + (Settings as any).currentTabRoute + ")");
    return () => console.error("AITuneConfigComponent UNMOUNTED");
  }, []);

  const openQrFill = async () => {
    setQrLoading(true);
    try {
      const url = await startQrConfig();
      if (!url) {
        setTestMsg("启动扫码服务失败（请确认掌机已联网）");
        return;
      }
      let modal: any;
      modal = showModal(
        <QrFillModal url={url} closeModal={() => modal?.Close()} />
      );
    } catch (e: any) {
      setTestMsg("启动扫码服务异常：" + String(e));
    } finally {
      setQrLoading(false);
    }
  };

  return (
    <PanelSection title="远程 AI 模型">
      <PanelSectionRow>
        <div style={rowGap}>
          <div style={{ marginBottom: "4px" }}>在线模型端点 (OpenAI 兼容)</div>
          <input
            style={inputStyle}
            placeholder="https://api.openai.com/v1"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
          />
        </div>
      </PanelSectionRow>
      <PanelSectionRow>
        <div style={rowGap}>
          <div style={{ marginBottom: "4px" }}>
            API 密钥（本地加密保存，不明文回显）
          </div>
          <input
            style={inputStyle}
            type="password"
            placeholder="sk-..."
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
          />
        </div>
      </PanelSectionRow>
      <PanelSectionRow>
        <div style={rowGap}>
          <div style={{ marginBottom: "4px" }}>模型名</div>
          <input
            style={inputStyle}
            placeholder="gpt-4o-mini / deepseek-chat / qwen …"
            value={model}
            onChange={(e) => setModel(e.target.value)}
          />
        </div>
      </PanelSectionRow>
      <PanelSectionRow>
        <div style={rowGap}>
          <div style={{ marginBottom: "4px" }}>每轮采集时长（分钟）</div>
          <input
            style={{ ...inputStyle, width: "120px" }}
            type="number"
            min={1}
            max={60}
            value={collectMin}
            onChange={(e) => setCollectMin(Number(e.target.value) || 5)}
          />
        </div>
      </PanelSectionRow>
      <PanelSectionRow>
        <div style={{ fontSize: "11px", opacity: 0.6, lineHeight: "1.4" }}>
          调优共 3 轮，每轮按上述时长采集帧率与功耗；每轮结果应用到硬件后，下一轮再观测帧率变化，3 轮后正式结束。
        </div>
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={saveConfig}>
          保存并测试连接
        </ButtonItem>
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" disabled={qrLoading} onClick={openQrFill}>
          {qrLoading ? "正在启动扫码服务…" : "手机扫码填写（免掌机输入）"}
        </ButtonItem>
      </PanelSectionRow>
      {testMsg && (
        <PanelSectionRow>
          <div style={{ fontSize: "12px", opacity: 0.85 }}>{testMsg}</div>
        </PanelSectionRow>
      )}
      <PanelSectionRow>
        <div style={{ fontSize: "11px", opacity: 0.6, lineHeight: "1.4" }}>
          调优推理仅把本机帧率与功耗统计发给该端点；密钥仅在配置时落盘（混淆存储）。
          需用户自备可用端点与额度。
        </div>
      </PanelSectionRow>
    </PanelSection>
  );
};

// ---------------- 1.5) 手机扫码填写弹窗 ----------------
const QrFillModal: FC<{ url: string; closeModal: () => void }> = ({
  url,
  closeModal,
}) => {
  const [qrData, setQrData] = useState<string>("");
  const [err, setErr] = useState<string>("");
  useEffect(() => {
    QRCode.toDataURL(url, { width: 256, margin: 2, color: { dark: "#000000", light: "#ffffff" } })
      .then((d) => setQrData(d))
      .catch((e) => setErr(String(e)));
    return () => {
      // 关闭弹窗即停止本地临时 HTTP 服务
      stopQrConfig().catch(() => {});
    };
  }, [url]);

  const close = () => {
    stopQrConfig().catch(() => {});
    closeModal();
  };

  return (
    <ModalRoot closeModal={close} onCancel={close} onEscKeypress={close}>
      <div style={{ textAlign: "center", padding: "4px 8px" }}>
        <h2 style={{ fontSize: 18, margin: "0 0 6px" }}>手机扫码填写</h2>
        <div style={{ fontSize: 12, opacity: 0.7, marginBottom: 14, lineHeight: 1.5 }}>
          用手机相机/扫码 App 扫描下方二维码，在手机浏览器中填写并保存配置，自动写入掌机。
        </div>
        {qrData ? (
          <img
            src={qrData}
            alt="qr"
            style={{
              width: 256,
              height: 256,
              background: "#fff",
              borderRadius: 8,
              display: "block",
              margin: "0 auto 12px",
            }}
          />
        ) : (
          <div style={{ fontSize: 12, opacity: 0.7, margin: "40px 0" }}>
            {err ? "二维码生成失败：" + err : "生成二维码中…"}
          </div>
        )}
        <div
          style={{
            fontSize: 11,
            opacity: 0.65,
            marginBottom: 14,
            wordBreak: "break-all",
            lineHeight: 1.4,
          }}
        >
          若扫码无反应，手机浏览器手动打开：{url}
        </div>
        <DialogButton onClick={close}>关闭</DialogButton>
      </div>
    </ModalRoot>
  );
};

// ---------------- 2) 接管开关（AI 调优接管手动调优） ----------------
export const SettingsAITuneGateComponent: FC = () => {
  const [enabled, setEnabled] = useState<boolean>(Settings.aiTuneEnabled());
  useEffect(() => {
    setEnabled(Settings.aiTuneEnabled());
    return Settings.subscribeAiTuneEnabled(() => setEnabled(Settings.aiTuneEnabled()));
  }, []);
  return (
    <PanelSection title="AI 调优接管">
      <PanelSectionRow>
        <ToggleField
          label="AI 调优接管手动调优"
          description={
            enabled
              ? "已开启：手动调优控件已禁用，设置由 AI 调优结果接管。关闭本开关即可恢复手动调优。"
              : "未开启：可手动调优。完成一次 AI 调优后会自动开启并接管。"
          }
          checked={enabled}
          onChange={(v: boolean) => Settings.setAiTuneEnabled(v)}
        />
      </PanelSectionRow>
      {enabled && (
        <PanelSectionRow>
          <div
            style={{
              fontSize: "12px",
              opacity: 0.85,
              lineHeight: "1.4",
              color: "rgba(120,200,255,0.9)",
            }}
          >
            AI 调优已接管：手动调优控件已禁用。如需手动调优，请先关闭上方开关。
          </div>
        </PanelSectionRow>
      )}
    </PanelSection>
  );
};

// ---------------- 3) 游戏内调优流程 ----------------
export const AITuneFlowComponent: FC = () => {
  const [activeApp, setActiveApp] = useState<string>(RunningApps.active());
  const [enabled, setEnabled] = useState<boolean>(Settings.ensureEnable());
  const [step, setStep] = useState<Step>("target");
  const [configured, setConfigured] = useState<boolean>(false);
  const [collectSec, setCollectSec] = useState<number>(600);
  const [targetFps, setTargetFps] = useState(40);
  const [customFps, setCustomFps] = useState("");
  const [status, setStatus] = useState<any>(null);
  const [result, setResult] = useState<any>(null);
  const [errMsg, setErrMsg] = useState("");
  const [applyMsg, setApplyMsg] = useState("");
  const appliedRoundRef = useRef(0);
  const doneRef = useRef(false);

  useEffect(() => {
    const id = setInterval(() => {
      setActiveApp(RunningApps.active());
      setEnabled(Settings.ensureEnable());
    }, 500);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    PluginManager.listenUpdateComponent(
      ComponentName.SET_ENABLE,
      [ComponentName.SET_ENABLE],
      () => setEnabled(Settings.ensureEnable())
    );
  }, []);

  useEffect(() => {
    getAiOnline()
      .then((cfg: any) => {
        setConfigured(!!cfg?.configured);
        setCollectSec(cfg?.collect_sec || 600);
      })
      .catch(() => setConfigured(false));
  }, []);

  useEffect(() => {
    if (step !== "tuning") return;
    appliedRoundRef.current = 0;
    doneRef.current = false;
    const id = setInterval(() => {
      getAiTuneStatus()
        .then((st: any) => {
          setStatus(st);
          // 每完成一轮，把该轮 delta 应用到硬件（让下一轮能观测帧率变化）
          if (st?.lastDelta && st.round && st.round !== appliedRoundRef.current) {
            try {
              Settings.applyAITuneRecommendation(st.lastDelta);
              appliedRoundRef.current = st.round;
            } catch {
              /* ignore */
            }
          }
          if (st.phase === "done") {
            setResult(st.result);
            if (!doneRef.current) {
              doneRef.current = true;
              // 调优完成后接管手动调优：前端置灰手动控件
              Settings.setAiTuneEnabled(true);
              setApplyMsg(
                "已保存至本游戏专属设置（已开启 AI 接管），下次进游戏自动套用 ✓"
              );
            }
            setStep("done");
            clearInterval(id);
          } else if (st.phase === "error" || st.phase === "cancelled") {
            setErrMsg(st.error || "调优失败");
            setStep("error");
            clearInterval(id);
          }
        })
        .catch((e) => {
          setErrMsg(String(e));
          setStep("error");
          clearInterval(id);
        });
    }, 1000);
    return () => clearInterval(id);
  }, [step]);

  // 非游戏内：仅提示
  if (activeApp === DEFAULT_APP || !enabled) {
    return (
      <PanelSectionRow>
        <div style={{ fontSize: "12px", opacity: 0.8, lineHeight: "1.4" }}>
          启动游戏后，可在此对本游戏进行 AI 智能调优（自动采集帧率/功耗并给出最省电方案）。
        </div>
      </PanelSectionRow>
    );
  }

  if (!configured) {
    return (
      <PanelSectionRow>
        <div style={{ fontSize: "12px", opacity: 0.85, lineHeight: "1.4" }}>
          尚未配置远程 AI 模型，请先在上方「远程 AI 模型」中填写端点、密钥与模型名并测试连接。
        </div>
      </PanelSectionRow>
    );
  }

  const startTune = async () => {
    const appId = RunningApps.active();
    const cur = Settings.ensureApp();
    const current = {
      tdp: cur.tdp,
      tdpEnable: cur.tdpEnable,
      gpuMode: cur.gpuMode,
      gpuFreq: cur.gpuFreq,
      gpuRangeMinFreq: cur.gpuRangeMinFreq,
      gpuRangeMaxFreq: cur.gpuRangeMaxFreq,
      cpuboost: cur.cpuboost,
      cpuNum: cur.cpuNum,
      smt: cur.smt,
      enableRyzenadjUndervolt: cur.enableRyzenadjUndervolt,
      ryzenadjUndervoltValue: cur.ryzenadjUndervoltValue,
    };
    let dev: any = {};
    try {
      dev = await getDeviceInfo();
    } catch {
      dev = {};
    }
    const caps = {
      tdpMin: Backend.data.getTdpMin(),
      tdpMax: Backend.data.getTdpMax(),
      gpuMin: Backend.data.getGpuMin(),
      gpuMax: Backend.data.getGpuMax(),
      cpuMaxNum: Backend.data.getCpuMaxNum(),
      supportsRyzenadjUndervolt: Backend.data.getSupportsRyzenadjCoall(),
      cpuModel: dev?.cpu_model || Backend.data.getCpuVendor() || "",
      gpuName: dev?.gpu_name || "",
      productName: dev?.product_name || "",
      vendor: dev?.vendor || "",
    };
    const fps = customFps ? Number(customFps) : targetFps;
    if (!fps || fps <= 0) {
      setErrMsg("目标帧数无效");
      return;
    }
    appliedRoundRef.current = 0;
    doneRef.current = false;
    setErrMsg("");
    setApplyMsg("");
    setResult(null);
    setStatus(null);
    const r = await startAiTune(appId, fps, collectSec, current, caps);
    if (r && r.started) setStep("tuning");
    else setErrMsg(r?.message || "启动失败");
  };

  const cancelTune = async () => {
    await stopAiTune();
    setStep("target");
  };

  if (step === "tuning") {
    const elapsed = status?.elapsed || 0;
    const total = status?.total || 300;
    const pct = Math.min(100, Math.round((elapsed / total) * 100));
    const round = status?.round || 1;
    const rounds = status?.rounds || 3;
    return (
      <>
        <PanelSectionRow>
          <div style={{ fontSize: "12px", opacity: 0.9 }}>
            第 {round} / {rounds} 轮采集中：请正常游戏，勿退出本游戏…
          </div>
        </PanelSectionRow>
        <PanelSectionRow>
          <div
            style={{
              width: "100%",
              height: "10px",
              background: "rgba(0,0,0,0.35)",
              borderRadius: "5px",
              overflow: "hidden",
            }}
          >
            <div
              style={{
                width: `${pct}%`,
                height: "100%",
                background: "linear-gradient(90deg,#3aa0ff,#2e6fff)",
                transition: "width 0.4s",
              }}
            />
          </div>
        </PanelSectionRow>
        <PanelSectionRow>
          <div style={{ fontSize: "12px", opacity: 0.85 }}>
            {elapsed}s / {total}s （{pct}%）
          </div>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => cancelTune()}>
            取消采集
          </ButtonItem>
        </PanelSectionRow>
      </>
    );
  }

  if (step === "done") {
    return (
      <>
        <PanelSectionRow>
          <div
            style={{
              background: "rgba(60,180,90,0.18)",
              border: "1px solid rgba(60,180,90,0.5)",
              borderRadius: "6px",
              padding: "10px",
              fontSize: "13px",
            }}
          >
            调优完成，已保存至本游戏专属设置（已开启 AI 接管）
          </div>
        </PanelSectionRow>
        {result?.reason && (
          <PanelSectionRow>
            <div style={{ fontSize: "12px", opacity: 0.9, lineHeight: "1.4" }}>
              理由：{result.reason}
            </div>
          </PanelSectionRow>
        )}
        {result?.used_fallback && (
          <PanelSectionRow>
            <div style={{ fontSize: "11px", opacity: 0.7 }}>
              （在线推理不可用，已用本地启发式兜底）
            </div>
          </PanelSectionRow>
        )}
        {applyMsg && (
          <PanelSectionRow>
            <div style={{ fontSize: "12px", opacity: 0.9 }}>{applyMsg}</div>
          </PanelSectionRow>
        )}
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={() => {
              setResult(null);
              setApplyMsg("");
              setStep("target");
            }}
          >
            再调一次
          </ButtonItem>
        </PanelSectionRow>
      </>
    );
  }

  if (step === "error") {
    return (
      <>
        <PanelSectionRow>
          <div
            style={{
              background: "rgba(200,60,60,0.18)",
              border: "1px solid rgba(200,60,60,0.5)",
              borderRadius: "6px",
              padding: "10px",
              fontSize: "13px",
            }}
          >
            {errMsg || "调优失败"}
          </div>
        </PanelSectionRow>
        <PanelSectionRow>
          <div style={{ display: "flex", gap: "8px" }}>
            <ButtonItem
              layout="below"
              onClick={() => {
                setErrMsg("");
                setStep("target");
              }}
            >
              重试
            </ButtonItem>
          </div>
        </PanelSectionRow>
      </>
    );
  }

  // step === "target"
  return (
    <>
      <PanelSectionRow>
        <div style={{ fontSize: "12px", opacity: 0.85, lineHeight: "1.4" }}>
          选择「本机真实目标帧数」（忽略插帧/小黄鸭）。点开始后插件将进行 3 轮调优，
          每轮约 {Math.round((collectSec || 300) / 60)} 分钟：自动采集帧率/功耗 → AI 调优 →
          应用到硬件 → 下一轮再观测帧率变化，3 轮后正式结束。期间请正常游戏勿退出。
        </div>
      </PanelSectionRow>
      <PanelSectionRow>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "6px" }}>
          {FPS_OPTIONS.map((f) => (
            <ButtonItem
              key={f}
              style={{
                minWidth: "48px",
                background:
                  targetFps === f && !customFps
                    ? "rgba(80,160,255,0.35)"
                    : "rgba(0,0,0,0.25)",
              }}
              onClick={() => {
                setTargetFps(f);
                setCustomFps("");
              }}
            >
              {f}
            </ButtonItem>
          ))}
          <input
            style={{ ...inputStyle, width: "70px" }}
            type="number"
            placeholder="自定义"
            value={customFps}
            onChange={(e) => setCustomFps(e.target.value)}
          />
        </div>
      </PanelSectionRow>
      <PanelSectionRow>
        <div style={{ display: "flex", gap: "8px" }}>
          <DialogButton onClick={() => startTune()} style={{ flex: 1 }}>
            开始 AI 调优
          </DialogButton>
        </div>
      </PanelSectionRow>
    </>
  );
};

// ---------------- 4) AI 调优分类（独立 Tab） ----------------
export const TabAiTune: FC = () => {
  (globalThis as any).__traceRender?.("TabAiTune");
  return (
    <>
      <AITuneConfigComponent />
      <SettingsAITuneGateComponent />
      <PanelSection title="AI 智能调优">
        <AITuneFlowComponent />
      </PanelSection>
    </>
  );
};

export const AITuneSettingsModal: FC<{ closeModal?: () => void }> = ({
  closeModal,
}) => (
  <ModalRoot closeModal={closeModal}>
    <TabAiTune />
  </ModalRoot>
);

export default TabAiTune;
