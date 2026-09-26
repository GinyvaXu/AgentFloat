/**
 * util.js — 通用工具（ES Module）
 * DOM 选择 / HTML 转义 / 配置路径读写 / Toast 提示
 * 由 app.js、install.js 等模块导入使用。
 */
export const $ = (s, r) => (r || document).querySelector(s);
export const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
export const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
export const getPath = (o, p) => p.split(".").reduce((a, k) => (a == null ? undefined : a[k]), o);
export const setPath = (o, p, v) => { const ks = p.split("."); let t = o; for (let i = 0; i < ks.length - 1; i++) { if (t[ks[i]] == null || typeof t[ks[i]] !== "object") t[ks[i]] = {}; t = t[ks[i]]; } t[ks[ks.length - 1]] = v; };
export const num = (v, d) => { const n = parseFloat(v); return isNaN(n) ? (d || 0) : n; };
export const deep = (o) => JSON.parse(JSON.stringify(o));

export function toast(msg, kind) {
  const wrap = $("#toastWrap");
  const t = document.createElement("div");
  t.className = "toast " + (kind || "ok");
  t.textContent = msg;
  wrap.appendChild(t);
  setTimeout(() => { t.classList.add("out"); setTimeout(() => t.remove(), 320); }, 2600);
}
