import {
  PanelSection,
  PanelSectionRow,
  ButtonItem,
  DialogButton,
  ModalRoot,
} from "@decky/ui";
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
  Backend,
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

const AITuneComponent: FC = () => {
  const [activeApp, setActiveApp] = useState<string>(RunningApps.active());
  const [enabled, setEnabled] = useState<boolean>(Settings.ensureEnable());
  const [step, setStep] = useState<Step>("config");
  const [online, setOnline] = useState<any>({
    configured: false,
    base_url: "",
    model: "",
    collect_sec: 600,
  });
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("");
  const [collectSec, setCollectSec] = useState(600);
  const [targetFps, setTargetFps] = useState(40);
  const [customFps, setCustomFps] = useState("");
  const [status, setStatus] = useState<any>(null);
  const [result, setResult] = useState<any>(null);
  const [errMsg, setErrMsg] = useState("");
  const [testMsg, setTestMsg] = useState("");
  const [applyMsg, setApplyMsg] = useState("");
  const appliedRef = useRef(false);

  // 轮询当前游戏与插件开关状态，保证游戏内才显示
  useEffect(() => {
    const id = setInterval(() => {
      setActiveApp(RunningApps.active());
      setEnabled(Settings.ensureEnable());
    }, 500);
    return () => clearInterval(id);
  }, []);

  // 监听插件开关变化
  useEffect(() => {
    PluginManager.listenUpdateComponent(
      ComponentName.SET_ENABLE,
      [ComponentName.SET_ENABLE],
      () => setEnabled(Settings.ensureEnable())
    );
  }, []);

  // 加载已保存的在线模型配置
  useEffect(() => {
    getAiOnline()
      .then((cfg: any) => {
        setOnline(cfg || {});
        setBaseUrl(cfg?.base_url || "");
        setModel(cfg?.model || "");
        setCollectSec(cfg?.collect_sec || 600);
        if (cfg?.configured) setStep("target");
      })
      .catch(() => {});
  }, []);

  // 调优中轮询状态
  useEffect(() => {
    if (step !== "tuning") return;
    const id = setInterval(() => {
      getAiTuneStatus()
        .then((st: any) => {
          setStatus(st);
          if (st.phase === "done") {
            setResult(st.result);
            if (!appliedRef.current) {
              appliedRef.current = true;
              if (st.result?.delta) {
                const ok = Settings.applyAITuneRecommendation(st.result.delta);
                setApplyMsg(
                  ok
                    ? "已保存至本游戏专属设置（已开启），下次进游戏自动套用 ✓"
                    : "写入专属设置失败"
                );
              }
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

  if (activeApp === DEFAULT_APP || !enabled) return null;

  const saveConfig = async () => {
    setTestMsg("保存中…");
    if (!baseUrl.trim() || !apiKey.trim() || !model.trim()) {
      setTestMsg("请填写端点、密钥与模型名");
      return;
    }
    const ok = await setAiOnline(baseUrl.trim(), apiKey, model.trim());
    if (!ok) {
      setTestMsg("保存失败");
      return;
    }
    const t = await testAiOnline();
    setTestMsg(
      t.ok
        ? "连接成功 ✓ " + (t.message || "")
        : "连接失败: " + (t.message || "")
    );
    if (t.ok) setStep("target");
  };

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
    const caps = {
      tdpMin: Backend.data.getTdpMin(),
      tdpMax: Backend.data.getTdpMax(),
      gpuMin: Backend.data.getGpuMin(),
      gpuMax: Backend.data.getGpuMax(),
      cpuMaxNum: Backend.data.getCpuMaxNum(),
      supportsRyzenadjUndervolt: Backend.data.getSupportsRyzenadjCoall(),
      deviceName: Backend.data.getCpuVendor() || "AMD",
    };
    const fps = customFps ? Number(customFps) : targetFps;
    if (!fps || fps <= 0) {
      setErrMsg("目标帧数无效");
      return;
    }
    appliedRef.current = false;
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

  const renderConfig = () => (
    <>
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
          <div style={{ marginBottom: "4px" }}>API 密钥（本地加密保存，不明文回显）</div>
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
        <ButtonItem layout="below" onClick={saveConfig}>
          保存并测试连接
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
    </>
  );

  const renderTarget = () => (
    <>
      <PanelSectionRow>
        <div style={{ fontSize: "12px", opacity: 0.85, lineHeight: "1.4" }}>
          选择「本机真实目标帧数」（忽略插帧/小黄鸭）。点开始后请正常游戏约{" "}
          {Math.round(collectSec / 60)} 分钟，插件后台采集后一次性给出最省电方案。
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
          <ButtonItem
            layout="below"
            onClick={() => {
              setStep("config");
              setTestMsg("");
            }}
          >
            重新配置模型
          </ButtonItem>
          <DialogButton
            onClick={() => startTune()}
            style={{ flex: 1 }}
          >
            开始 AI 调优
          </DialogButton>
        </div>
      </PanelSectionRow>
    </>
  );

  const renderTuning = () => {
    const elapsed = status?.elapsed || 0;
    const total = status?.total || collectSec;
    const pct = Math.min(100, Math.round((elapsed / total) * 100));
    return (
      <>
        <PanelSectionRow>
          <div style={{ fontSize: "12px", opacity: 0.9 }}>
            采集中：请正常游戏，勿退出本游戏…
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
  };

  const renderDone = () => (
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
          调优完成，已保存至本游戏专属设置（已开启）
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

  const renderError = () => (
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
          <ButtonItem
            layout="below"
            onClick={() => {
              setErrMsg("");
              setStep("config");
            }}
          >
            去配置模型
          </ButtonItem>
        </div>
      </PanelSectionRow>
    </>
  );

  return (
    <PanelSection title="AI 智能调优">
      {step === "config" && renderConfig()}
      {step === "target" && renderTarget()}
      {step === "tuning" && renderTuning()}
      {step === "done" && renderDone()}
      {step === "error" && renderError()}
    </PanelSection>
  );
};

export const AITuneSettingsModal: FC<{ closeModal?: () => void }> = ({
  closeModal,
}) => (
  <ModalRoot closeModal={closeModal}>
    <AITuneComponent />
  </ModalRoot>
);

export default AITuneComponent;
