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

/**
 * 加载骨架（v3.15.1 引入，v3.16.4 从 app.js 提到这里共用）
 * @param {number} lines 骨架行数
 */
export function loadingCard(lines) {
  const n = Math.max(1, lines || 3);
  let rows = "";
  for (let i = 0; i < n; i += 1) {
    rows += '<div class="skeleton-line" style="width:' + (92 - i * 14) + '%"></div>';
  }
  return '<div class="card skeleton">' + rows + "</div>";
}

/**
 * 错误卡片 + 重试（v3.16.4 共用；retryName 为 window.App 上的方法名）
 * 事件由 app.js 的全局 click 委托处理（data-retry-load / data-err-detail）。
 */
export function errorCard(msg, retryName) {
  return '<div class="card error"><h3>加载失败</h3>' +
    '<div class="desc">' + esc(msg || "未知错误") + "</div>" +
    '<div class="err-actions">' +
    '<button class="btn sm primary" data-retry-load="' + esc(retryName || "") + '">重试</button>' +
    '<button class="btn sm" data-err-detail>查看详情</button></div>' +
    '<pre class="err-detail hidden">' + esc(msg || "") + "</pre></div>";
}

