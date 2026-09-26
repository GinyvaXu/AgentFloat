/**
 * install.js — Agent 安装页（ES Module）
 * 独立管理安装状态与轮询；app.js 进入/离开页面时调用 render/leave。
 */
import { $, esc, toast } from "./util.js";

let active = false;
let timer = null;
let expanding = null;
let agents = [];
let refreshing = false;

export function renderInstallPage() {
  active = true;
  const el = $("#installContent");
  el.innerHTML = '<div class="desc" style="padding:6px 2px 10px">检测本机 Agent 安装情况，支持一键安装 / 升级 / 卸载（npm 全局安装，国内镜像优先自动回退）。</div><div id="installList">加载中…</div>';
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

function installCard(a) {
  const busy = a.busy || a.phase === "running";
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
    el.innerHTML = agents.map(installCard).join("");
  } catch (e) {
    if (!silent) el.innerHTML = '<div class="desc" style="color:#FF5F56">加载失败：' + esc(e.message) + "</div>";
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
  if (!confirm("确定卸载该 Agent 吗？")) return;
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
