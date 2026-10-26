/**
 * install.js — Agent 安装页（ES Module）
 * 目录来自 /api/catalog；安装走后台任务（/api/catalog/install + /api/catalog/job 轮询），
 * 卸载同步完成（/api/catalog/uninstall），已安装条目可一键启动（/api/catalog/launch）。
 * 不再维护旧版 #installList 的第二套状态。
 * app.js 进入/离开页面时调用 render/leave。
 */
import { $, esc, toast, loadingCard, errorCard } from "./util.js";

const POLL_MS = 1000;

let active = false;
let jobTimer = null;
let items = [];
let job = null;
let busy = false;          // 同步卸载请求进行中

export function renderInstallPage() {
  active = true;
  stopJobPolling();
  job = null;
  const el = $("#installContent");
  el.innerHTML = '<div class="desc" style="padding:6px 2px 10px">检测本机 Agent 安装情况。安装 / 卸载只作用于 AgentFloat 受管目录，不会改动系统全局安装。</div>' +
    '<div id="catalogBox">' + loadingCard(3) + "</div>";
  loadCatalog();
  resumeJob();
}

export function leaveInstallPage() {
  active = false;
  stopJobPolling();
}

// ── 目录 ───────────────────────────────────────────
export async function loadCatalog() {
  const box = $("#catalogBox");
  if (!box) return;
  try {
    const r = await API.api("/api/catalog");
    if (!active) return;
    items = r.items || [];
    renderCatalog();
  } catch (e) {
    if (!active) return;
    box.innerHTML = errorCard(e.message, "loadCatalog");
  }
}

function renderCatalog() {
  const box = $("#catalogBox");
  if (!box) return;
  const running = busy || !!(job && job.running);
  const rows = items.length
    ? items.map(function (a) { return catalogRow(a, running); }).join("")
    : '<div class="desc">暂无收录的 Agent。</div>';
  box.innerHTML = renderJobCard() +
    '<div class="card"><h3>Agent 目录</h3>' +
    '<div class="desc">共 ' + items.length + ' 条已核实条目。安装到受管目录后可在浮球菜单直接启动；系统 PATH 里的同名 Agent 只展示、不接管。</div>' +
    rows + "</div>";
}

function catalogRow(a, running) {
  const source = a.installSource === "path" ? " · 系统 PATH"
    : (a.installSource === "managed" ? " · 受管目录" : "");
  const meta = [a.command, a.package, a.installType,
    a.verifiedAt ? "核验 " + a.verifiedAt : ""].filter(Boolean).join(" · ");
  return '<div class="row"><div class="lbl">' + esc(a.name) + " " + statusTag(a) +
    "<small>" + esc(meta) + esc(source) + "</small></div>" +
    '<div class="ctl">' + actionCtl(a, running) + "</div></div>";
}

function statusTag(a) {
  if (!a.installed) return '<span class="tag gray">未安装</span>';
  // 系统 PATH 安装：明确标注，且不提供卸载（避免误删用户全局）
  if (a.installSource === "path") return '<span class="tag blue">已安装 · 系统</span>';
  return '<span class="tag green">已安装</span>';
}

function actionCtl(a, running) {
  if (!a.installed) {
    const attr = running ? " disabled" : ' onclick="App.catalogInstall(\'' + esc(a.id) + '\')"';
    return '<button class="btn sm primary"' + attr + ">安装</button>";
  }
  // 已安装（受管目录 / 系统 PATH）都可启动；启动不占安装任务，运行中也不禁用
  const launchBtn = '<button class="btn sm primary" onclick="App.catalogLaunch(\'' +
    esc(a.id) + '\')">启动</button>';
  // 系统 PATH 安装不提供卸载（避免误删用户全局）
  if (a.installSource === "path") return launchBtn;
  const attr = running ? " disabled" : ' onclick="App.catalogUninstall(\'' + esc(a.id) + '\')"';
  return launchBtn + '<button class="btn sm danger"' + attr + ">卸载</button>";
}

// ── 任务进度 ───────────────────────────────────────
function renderJobCard() {
  if (!job) return "";
  if (job.phase === "error") {
    const logs = (job.log || []).slice(-8);
    return '<div class="card error"><h3>操作失败</h3>' +
      '<div class="desc">' + esc(job.message || "未知错误") + "</div>" +
      (logs.length ? '<pre class="install-log" style="margin-top:8px">' + esc(logs.join("\n")) + "</pre>" : "") +
      "</div>";
  }
  if (!job.id) return "";
  const verb = job.action === "uninstall" ? "卸载" : "安装";
  const tag = job.running
    ? '<span class="tag blue">进行中</span>'
    : '<span class="tag green">完成</span>';
  const detail = job.message || (job.running ? "处理中…" : "完成");
  const last = (job.log || []).slice(-1)[0] || "";
  return '<div class="card"><h3>' + verb + "进度 " + tag + "</h3>" +
    '<div class="desc">' + esc(detail) + "</div>" +
    (last && last !== detail ? '<pre class="install-log">' + esc(last) + "</pre>" : "") +
    "</div>";
}

function showError(message) {
  job = {
    id: "local",
    action: "",
    running: false,
    phase: "error",
    message: message || "操作失败",
    log: [message || "操作失败"],
    startedAt: null,
    finishedAt: null,
  };
  renderCatalog();
  toast(job.message, "err");
}

function startJobPolling() {
  stopJobPolling();
  jobTimer = setInterval(pollJob, POLL_MS);
}

function stopJobPolling() {
  if (jobTimer) {
    clearInterval(jobTimer);
    jobTimer = null;
  }
}

async function resumeJob() {
  // 离开页面期间任务可能仍在跑：重新进入时接上进度
  try {
    const j = await API.api("/api/catalog/job");
    if (!active || !j || !j.id || !j.running) return;
    job = j;
    renderCatalog();
    startJobPolling();
  } catch (e) { /* 恢复失败不影响目录展示 */ }
}

async function pollJob() {
  if (!active) {
    stopJobPolling();
    return;
  }
  try {
    const j = await API.api("/api/catalog/job");
    if (!active) {
      stopJobPolling();
      return;
    }
    if (!j || !j.id) {
      stopJobPolling();
      job = null;
      renderCatalog();
      return;
    }
    job = j;
    renderCatalog();
    if (!j.running) {
      stopJobPolling();
      if (j.phase === "done") toast(j.message || "操作完成", "ok");
      else if (j.phase === "error") toast(j.message || "操作失败", "err");
      await loadCatalog();
    }
  } catch (e) {
    stopJobPolling();
    showError("任务状态获取失败：" + (e.message || e));
  }
}

// ── 用户操作 ───────────────────────────────────────
export async function catalogInstall(id) {
  if (busy || (job && job.running)) {
    toast("已有任务在执行，请稍候", "err");
    return;
  }
  try {
    const r = await API.api("/api/catalog/install", { method: "POST", body: { id: id } });
    if (!r || r.ok === false) {
      if (r && r.busy) {
        job = r.job || null;
        renderCatalog();
        startJobPolling();
        toast(r.error || "已有任务在执行", "err");
        return;
      }
      showError((r && r.error) || "启动安装失败");
      return;
    }
    job = r.job || null;
    renderCatalog();
    startJobPolling();
    toast("已开始安装，请稍候…", "ok");
  } catch (e) {
    showError("启动安装失败：" + (e.message || e));
  }
}

export async function catalogUninstall(id) {
  if (busy || (job && job.running)) {
    toast("已有任务在执行，请稍候", "err");
    return;
  }
  const a = items.find(function (x) { return x.id === id; }) || {};
  const body = "确定卸载「" + (a.name || id) + "」吗？只删除 AgentFloat 受管目录，不影响系统全局安装。";
  let ok;
  if (window.App && typeof window.App.confirmDialog === "function") {
    ok = await window.App.confirmDialog({ title: "卸载 Agent", body: body, okText: "卸载", danger: true });
  } else {
    ok = window.confirm(body);
  }
  if (!ok) return;

  busy = true;
  renderCatalog();
  try {
    const r = await API.api("/api/catalog/uninstall", { method: "POST", body: { id: id } });
    busy = false;
    if (!r || r.ok === false) {
      showError((r && r.error) || "卸载失败");
      return;
    }
    toast(r.removed ? "已卸载" : "受管目录不存在，无需卸载", "ok");
    job = null;
    await loadCatalog();
  } catch (e) {
    busy = false;
    showError("卸载失败：" + (e.message || e));
  }
}

export async function catalogLaunch(id) {
  // 启动是即发即忘：不占用安装任务状态，也不启动 job 轮询
  const a = items.find(function (x) { return x.id === id; }) || {};
  try {
    const r = await API.api("/api/catalog/launch", { method: "POST", body: { id: id } });
    if (!r || r.ok === false) {
      toast("启动失败：" + ((r && r.reason) || "未知错误"), "err");
      return;
    }
    toast("已启动 " + (a.name || id), "ok");
  } catch (e) {
    toast("启动失败：" + (e.message || e), "err");
  }
}
