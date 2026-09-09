import deckyPlugin from "@decky/rollup";
import replace from "@rollup/plugin-replace";

const cfg = deckyPlugin();

// 让 React 走开发版（报错含完整组件 stack，便于定位 185 无限循环）
cfg.plugins.unshift(
  replace({
    preventAssignment: true,
    values: { "process.env.NODE_ENV": JSON.stringify("development") },
  })
);

// 移除 terser / minify，保留原始函数名，避免 component stack 全是压缩名
if (Array.isArray(cfg.plugins)) {
  cfg.plugins = cfg.plugins.filter((p) => p && p.name !== "terser");
}
if (cfg.output && Array.isArray(cfg.output.plugins)) {
  cfg.output.plugins = cfg.output.plugins.filter((p) => p && p.name !== "terser");
}
cfg.output = { ...(cfg.output || {}), sourcemap: true };

export default cfg;
