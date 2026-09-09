/**
 * 渲染期插桩：用于定位 React #185 "Maximum update depth" 无限重渲染的真凶组件。
 * 在 decky 提供的压缩版 production React 下无法拿到组件栈，只能用渲染计数法：
 * 哪个组件在极短时间内被渲染成百上千次，它就是循环源头。
 *
 * 用法：在 function component 函数体顶部调用 `traceRender("ComponentName");`
 * 仅在 dev/诊断构建中引入，production 构建里不调用。
 */
const counts: Record<string, number> = {};
const flagged: Record<string, boolean> = {};

export function traceRender(name: string) {
  const c = (counts[name] || 0) + 1;
  counts[name] = c;
  if (c === 1 || c % 20 === 0) {
    console.log(`[RENDER_TRACE] ${name} render #${c}`);
  }
  // 前 3 次渲染打印完整调用栈，借以看清"谁在反复触发本组件重渲染"（父链）
  if (c <= 3) {
    console.error(`[RT-STACK] ${name} render #${c}\n${new Error().stack}`);
  }
  // 超过阈值即判定为无限循环，打印渲染期调用栈（我的代码未压缩，能显示组件名）
  if (c >= 40 && !flagged[name]) {
    flagged[name] = true;
    console.error(
      `[RENDER_LOOP_DETECTED] ${name} 已渲染 ${c} 次 —— 这是 #185 无限循环源头。渲染期调用栈：`,
      new Error().stack
    );
  }
}

// 挂载到 globalThis，便于其它组件在不 import 的情况下调用（index.tsx 引入本模块一次即可生效）
if (typeof globalThis !== "undefined") {
  (globalThis as any).__traceRender = traceRender;
}
