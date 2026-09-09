import { Component, ErrorInfo, ReactNode } from "react";

/**
 * 顶层错误边界：捕获插件前端渲染期崩溃（含 React #185 无限渲染循环），
 * 把 error.stack + componentStack 打到 cef_log.txt，避免把 Steam 渲染进程拖垮到自动重启。
 * 这是诊断手段，也是健壮性兜底：崩溃后展示可读信息而非无限冻结。
 */
export class PluginErrorBoundary extends Component<
  { children: ReactNode },
  { error: Error | null }
> {
  constructor(props: { children: ReactNode }) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    try {
      console.error("==== [PowerContorlAI] PluginErrorBoundary caught render error ====");
      console.error("message:", error && error.message);
      console.error("stack:", error && error.stack);
      console.error("componentStack:", info && (info as any).componentStack);
    } catch (e) {
      console.error("PluginErrorBoundary logging failed:", e);
    }
  }

  render() {
    if (this.state.error) {
      return (
        <div
          style={{
            padding: "12px 14px",
            color: "#ff8a8a",
            fontSize: "12px",
            lineHeight: "1.5",
            whiteSpace: "pre-wrap",
          }}
        >
          <div style={{ fontWeight: 700, marginBottom: 6 }}>
            PowerContorlAI 渲染崩溃（已被错误边界捕获，Steam 不会卡死）
          </div>
          <div style={{ opacity: 0.85 }}>
            {(this.state.error && this.state.error.message) || String(this.state.error)}
          </div>
          <div style={{ marginTop: 8, opacity: 0.6, fontSize: 11 }}>
            请关闭本面板后重新打开；开发者可从 cef_log.txt 读取完整组件栈定位。
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
