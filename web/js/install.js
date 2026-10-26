/**
 * install.js — Agent 安装页（ES Module）
 * 独立管理安装状态与轮询；app.js 进入/离开页面时调用 render/leave。
 */
import { $, esc, toast, loadingCard, errorCard } from "./util.js";

let active = false;
let timer = null;
let expanding = null;
let agents = [];
let refreshing = false;

export function renderInstallPage() {
  active = true;
  const el = $("#installContent");
  // v3.16.4：首屏用骨架，不再是一行「加载中…」
  el.innerHTML = '<div class="desc" style="padding:6px 2px 10px">检测本机 Agent 安装情况，支持一键安装 / 升级 / 卸载（npm 全局安装，国内镜像优先自动回退）。</div>' +
    '<div id="catalogBox">' + loadingCard(3) + "</div>" +
    '<div id="installList">' + loadingCard(3) + "</div>";
  loadCatalog();
  refreshInstall();
  if (timer) clearInterval(timer);
  timer = setInterval(() => {
    if (!active) { clearInterval(timer); timer = null; return; }
    refreshInstall(true);
  }, 1500);
}

export function leaveInstallPage() {
  active = false;
  if (timer) { clearInterval(timer); timer = null; }
}

// v3.17.0：Agent 目录（新版）——只读展示内置 6 条 + 本机安装状态
async function loadCatalog() {
  const box = $("#catalogBox");
  if (!box) return;
  try {
    const r = await API.api("/api/catalog");
    const items = r.items || [];
    box.innerHTML = '<div class="card"><h3>Agent 目录（新版）</h3>' +
      '<div class="desc">内置 ' + items.length + ' 条已核实条目；当前只读展示，安装/卸载下一步接入。</div>' +
      items.map(function (a) {
        const tag = a.installed
          ? '<span class="tag green">已安装</span>'
          : '<span class="tag gray">未安装</span>';
        const src = a.installed ? (a.installSource === "path" ? " · PATH" : " · 受管目录") : "";
        return '<div class="row"><div class="lbl">' + esc(a.name) + " " + tag +
          "<small>" + esc(a.command) + " · " + esc(a.package) + " · " + esc(a.installType) + esc(src) + "</small></div>" +
          '<div class="ctl"><span class="desc">' + esc(a.verifiedAt || "") + "</span></div></div>";
      }).join("") + "</div>";
  } catch (e) {
    box.innerHTML = '<div class="card error"><h3>目录加载失败</h3><div class="desc">' +
      esc(e.message || "未知错误") + "</div></div>";
  }
}

function installCard(a) {  const busy = a.busy || a.phase === "running";
  const ver = a.version ? "v" + esc(a.version) : "未安装";
  const statusTag = a.found
    ? '<span class="tag blue">已安装</span>'
    : '<span class="tag gray">未安装</span>';
  let actionBtns = "";
  if (busy) {
    actionBtns = '<button class="btn sm" disabled>处理中…</button>';
  } else if (a.found) {
    actionBtns =
      '<button class="btn sm" onclick="App.installAgent(\'' + a.id + '\',\'upgrade\')">升级</button>' +
      '<button class="btn sm danger" onclick="App.uninstallAgent(\'' + a.id + '\')">卸载</button>';
  } else {
    actionBtns = '<button class="btn sm primary" onclick="App.installAgent(\'' + a.id + '\',\'install\')">安装</button>';
  }
  const phaseMsg = (a.phase === "running") ? '<div class="desc" style="color:#4D6BFE">' + esc(a.message || "处理中…") + "</div>" :
    (a.phase === "error" ? '<div class="desc" style="color:#FF5F56">' + esc(a.message || "操作失败") + "</div>" :
    (a.phase === "done" ? '<div class="desc" style="color:#30D158">' + esc(a.message || "完成") + "</div>" : ""));
  const logsOpen = expanding === a.id;
  const logBox = logsOpen
    ? '<pre class="install-log">' + esc((a.logs || []).join("\n")) + "</pre>" +
      '<button class="btn sm" onclick="App.toggleInstallLog(\'' + a.id + '\')">收起日志</button>'
    : (a.logs && a.logs.length ? '<button class="btn sm" onclick="App.toggleInstallLog(\'' + a.id + '\')">查看日志（' + a.logs.length + " 行）</button>" : "");
  return '<div class="agent-card">' +
    '<div class="agent-ico" style="background:' + esc(a.icon_color || "#5B8DEF") + '">' + esc(a.icon_char || "A") + "</div>" +
    '<div class="agent-info">' +
    '<div class="agent-name">' + esc(a.name) + " " + statusTag + "</div>" +
    '<div class="agent-cmd">' + esc(a.package) + " · " + ver + "</div>" +
    '<div class="agent-cmd">' + esc(a.description || "") + "</div>" + phaseMsg +
    "</div>" +
    '<div class="agent-actions">' + actionBtns + "</div>" +
    "</div>" + (logBox ? '<div style="margin:0 0 8px 0">' + logBox + "</div>" : "");
}

export async function refreshInstall(silent) {
  const el = $("#installList");
  if (!el) return;
  if (refreshing) return;          // 防重叠：上一次请求未返回时跳过本轮轮询
  refreshing = true;
  try {
    const resp = await API.api("/api/agent_install/status");
    agents = resp.agents || [];
    // v3.16.4：空态行（后端返回空列表时不再是一片空白）
    el.innerHTML = agents.length
      ? agents.map(installCard).join("")
      : '<div class="card"><div class="desc">暂未收录可安装的 Agent。可在设置页手动添加启动命令。</div></div>';
  } catch (e) {
    // v3.16.4：错误卡片 + 重试（轮询失败时只在非静默态提示，避免刷屏）
    if (!silent) el.innerHTML = errorCard(e.message, "refreshInstall");
  } finally {
    refreshing = false;
  }
}

export async function installAgent(id, action) {
  try {
    const r = await API.api("/api/agent_install/install", { method: "POST", body: { id: id, action: action } });
    toast(r.message || "已开始", "ok");
  } catch (e) { toast("操作失败：" + e.message, "err"); }
  refreshInstall(true);
}

export async function uninstallAgent(id) {
  // v3.16.4：改用统一确认弹层（原生 confirm 带系统边框，与本页观感不一致）
  const a = agents.find((x) => x.id === id) || {};
  const body = "确定卸载「" + (a.name || id) + "」吗？卸载后可重新安装。";
  let ok;
  if (window.App && typeof window.App.confirmDialog === "function") {
    ok = await window.App.confirmDialog({ title: "卸载 Agent", body: body, okText: "卸载", danger: true });
  } else {
    ok = confirm(body);
  }
  if (!ok) return;
  try {
    const r = await API.api("/api/agent_install/uninstall", { method: "POST", body: { id: id } });
    toast(r.message || "已开始卸载", "ok");
  } catch (e) { toast("卸载失败：" + e.message, "err"); }
  refreshInstall(true);
}

export function toggleInstallLog(id) {
  expanding = expanding === id ? null : id;
  refreshInstall(true);
}
