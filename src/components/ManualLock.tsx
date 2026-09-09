import { createContext, useContext, useEffect, useState, FC, ReactNode } from "react";
import { PanelSectionRow } from "@decky/ui";
import { Settings } from "../util";

/**
 * AI 调优"接管手动调优"时，手动调优控件（CPU/GPU/Power 分类）应被禁用。
 * 通过 Context 把禁用状态下发到各手动控件，并在分类顶部显示提示。
 */
export const ManualLockContext = createContext<{ disabled: boolean }>({
  disabled: false,
});

export const ManualLockProvider: FC<{ children: ReactNode }> = ({ children }) => {
  (globalThis as any).__traceRender?.("ManualLockProvider");
  const [disabled, setDisabled] = useState<boolean>(Settings.aiTuneEnabled());

  useEffect(() => {
    setDisabled(Settings.aiTuneEnabled());
    return Settings.subscribeAiTuneEnabled(() => setDisabled(Settings.aiTuneEnabled()));
  }, []);

  return (
    <ManualLockContext.Provider value={{ disabled }}>
      {children}
    </ManualLockContext.Provider>
  );
};

export const useManualLock = () => useContext(ManualLockContext);

/**
 * 手动调优分类的禁用包装：AI 调优接管后，屏蔽内部所有控件并提示。
 */
export const ManualLockGate = ({ children }: { children: ReactNode }) => {
  const { disabled } = useManualLock();
  return (
    <>
      {disabled && (
        <PanelSectionRow>
          <div
            style={{
              width: "100%",
              background: "rgba(120,200,255,0.14)",
              border: "1px solid rgba(120,200,255,0.5)",
              borderRadius: "6px",
              padding: "9px 10px",
              fontSize: "12px",
              lineHeight: "1.4",
              color: "rgba(150,215,255,0.95)",
            }}
          >
            手动调优需关闭 AI 调优
          </div>
        </PanelSectionRow>
      )}
      <div
        style={
          disabled
            ? {
                pointerEvents: "none",
                opacity: 0.45,
                filter: "grayscale(0.6)",
                transition: "opacity 0.2s",
              }
            : undefined
        }
      >
        {children}
      </div>
    </>
  );
};
