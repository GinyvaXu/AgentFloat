/**
 * llm.js — 「AI 接入」页（v3.28）
 *
 * 结构对齐 docs/previews/LLM接入-ccswitch风格-20261102.html：
 *   顶部汇总（总余额 / 今日·本月 Token / 订阅数 / 低余额）
 *   左：供应商卡片（点击选中，卡片按钮一键切换）+ 添加 + Token 统计
 *   右：编辑表单（预设 / 名称 / Base URL / 模型 / Key / 类型 / 余额接口 / 监控）
 *
 * 安全：后端只返回 api_key_set / api_key_hint，本模块不回显 Key；
 *       保存时 Key 留空表示「不修改已保存的 Key」。
 */
import { esc, toast, loadingCard, errorCard } from "./util.js";

const state = {
  data: null,
  selected: "",     // 当前编辑的供应商 id；"" 表示新增
  draft: null,      // 编辑中的草稿（含 api_key 本地输入，不来自后端）
  dirty: false,     // 草稿是否被用户改过（改过就不要被服务端数据覆盖）
  busy: "",         // "" | save | test | activate | delete | refresh
  error: "",
  seq: 0,
  confirmDelete: "",
};

const FIELD_KEYS = [
  "id", "name", "preset", "base_url", "model", "api_key", "kind",
  "balance_url", "balance_field", "low_balance_warn", "currency", "enabled", "note",
];

const CURRENCY_SYMBOL = { CNY: "¥", USD: "$", EUR: "€", JPY: "JP¥" };

function fmtTokens(value) {
  const n = Number(value) || 0;
  if (n >= 1000000) return (n / 1000000).toFixed(2).replace(/\.?0+$/, "") + "M";
  if (n >= 1000) return (n / 1000).toFixed(1).replace(/\.0$/, "") + "K";
  return String(n);
}

function moneyText(amount, currency) {
  const sym = CURRENCY_SYMBOL[currency] || "";
  const n = Number(amount) || 0;
  const text = n.toFixed(2);
  return sym ? sym + text : text + " " + (currency || "");
}

function pctText(periods) {
  const labels = [["rolling", "5h"], ["weekly", "周"], ["monthly", "月"]];
  const bits = labels
    .filter(([key]) => periods && periods[key] != null)
    .map(([key, label]) => label + " " + Math.round(Number(periods[key])) + "%");
  return bits.join(" · ");
}

function hostOf(url) {
  return String(url || "").replace(/^https?:\/\//i, "").split("/")[0];
}

function presets() {
  return (state.data && state.data.presets) || [];
}

function providers() {
  return (state.data && state.data.providers) || [];
}

function providerById(id) {
  return providers().find((p) => p.id === id) || null;
}

function presetById(id) {
  return presets().find((p) => p.id === id) || null;
}

function blankDraft(presetId) {
  const preset = presetById(presetId || "custom") || presetById("custom") || {};
  return {
    id: "", name: preset.name || "", preset: preset.id || "custom",
    base_url: preset.base_url || "", model: preset.model || "",
    api_key: "", kind: preset.kind || "money",
    balance_url: preset.balance_url || "", balance_field: preset.balance_field || "",
    low_balance_warn: preset.low_balance_warn != null ? preset.low_balance_warn : 5,
    currency: preset.currency || "", enabled: true, note: "",
    api_key_set: false, api_key_hint: "",
  };
}

function draftFrom(provider) {
  const item = {};
  FIELD_KEYS.forEach((key) => { item[key] = provider[key]; });
  item.api_key = "";
  item.api_key_set = !!provider.api_key_set;
  item.api_key_hint = provider.api_key_hint || "";
  item.enabled = provider.enabled !== false;
  item.low_balance_warn = provider.low_balance_warn != null ? provider.low_balance_warn : 5;
  item.note = provider.note || "";
  return item;
}

/** 只提交后端认识的字段，避免把 balance / today_tokens 等只读字段回写。 */
function payloadOf(draft) {
  const body = {};
  FIELD_KEYS.forEach((key) => {
    if (key === "api_key" && !String(draft.api_key || "").trim()) return;
    body[key] = draft[key];
  });
  body.low_balance_warn = Number(body.low_balance_warn) || 0;
  body.enabled = draft.enabled !== false;
  return body;
}

// ── 渲染 ────────────────────────────────────────────────
export function renderLlmPage() {
  const box = document.getElementById("llmContent");
  if (!box) return;
  if (state.data) {
    paint();
    load(false);          // 后台静默刷新余额 / 用量
    return;
  }
  box.innerHTML = loadingCard(6);
  load(false);
}

async function load(force) {
  const seq = ++state.seq;
  state.error = "";
  try {
    const r = await API.api("/api/llm/providers" + (force ? "?refresh=1" : ""), { timeout: 30000 });
    if (seq !== state.seq) return;
    if (!r || r.ok === false) throw new Error((r && r.error) || "未知错误");
    state.data = r;
    const ids = providers().map((p) => p.id);
    const draftId = state.draft && state.draft.id;
    if (!state.draft) {
      if (!ids.includes(state.selected)) state.selected = r.active || ids[0] || "";
      if (state.selected) state.draft = draftFrom(providerById(state.selected) || {});
    } else if (state.dirty) {
      // 有未保存改动（尤其刚输入的 Key）：保留草稿，只更新列表数据
      if (draftId && !ids.includes(draftId)) {
        state.selected = "";
        state.draft = null;
        state.dirty = false;
      }
    } else if (draftId && providerById(draftId)) {
      // 未改动：跟随服务端最新数据重建（保留当前选中的供应商）
      state.selected = draftId;
      state.draft = draftFrom(providerById(draftId));
    }
    paint();
  } catch (e) {
    if (seq !== state.seq) return;
    state.error = e.message || String(e);
    paint();
  }
}

function paint() {
  const box = document.getElementById("llmContent");
  if (!box) return;
  if (window.App) window.App.llmReload = () => load(true);
  if (!state.data) {
    box.innerHTML = errorCard(state.error || "读取 AI 供应商失败", "llmReload");
    return;
  }
  box.innerHTML =
    "<div class=\"llm-wrap\">" +
      summaryBar() +
      (state.error ? '<div class="llm-alert">' + esc(state.error) + "</div>" : "") +
      '<div class="llm-layout">' +
        '<div class="llm-col">' + providerList() + usageCard() + "</div>" +
        editorCard() +
      "</div>" +
    "</div>";
  bind();
}

function summaryBar() {
  const totals = state.data.totals || {};
  const money = totals.money || [];
  const moneyTextValue = money.length
    ? money.map((m) => moneyText(m.amount, m.currency)).join(" / ")
    : "—";
  const usage = state.data.usage || {};
  const today = usage.today || {};
  const month = usage.month || {};
  const low = Number(totals.low_count) || 0;
  return '<div class="card llm-top">' +
    '<div class="llm-top-item"><span>总余额</span><b>' + esc(moneyTextValue) + "</b></div>" +
    '<div class="llm-top-item"><span>今日 Token</span><b>' + esc(fmtTokens(today.total_tokens)) + "</b></div>" +
    '<div class="llm-top-item"><span>本月 Token</span><b>' + esc(fmtTokens(month.total_tokens)) + "</b></div>" +
    '<div class="llm-top-item"><span>订阅供应商</span><b>' + esc(String(totals.subscriptions || 0)) + " 个</b></div>" +
    '<div class="llm-top-item"><span>低余额</span><b class="' + (low ? "llm-warn-text" : "") + '">' +
      esc(low ? String(low) + " 个" : "无") + "</b></div>" +
    '<button class="btn sm" id="llmRefresh"' + (state.busy === "refresh" ? " disabled" : "") + ">" +
      (state.busy === "refresh" ? "刷新中…" : "刷新余额") + "</button>" +
  "</div>";
}

function providerList() {
  const active = state.data.active || "";
  const cards = providers().map((p) => {
    const id = String(p.id || "");
    const isActive = id === active;
    const isSelected = id === state.selected;
    const balance = p.balance || {};
    let balanceLine = "";
    if (p.kind === "sub") {
      balanceLine = balance.ok
        ? "已用 " + (pctText(balance.periods) || "—")
        : "订阅用量未刷新";
    } else if (balance.ok) {
      balanceLine = "余额 " + moneyText(balance.balance, balance.currency || p.currency);
    } else if (balance.skipped) {
      balanceLine = "无余额接口";
    } else {
      balanceLine = "余额 —";
    }
    // 失败原因（401 / 字段缺失 / 网络）不能只显示「—」，否则用户无法排查
    const balanceError = (p.enabled !== false && !balance.ok && !balance.skipped &&
      balance.error && balance.error !== "尚未刷新") ? String(balance.error) : "";
    const meta = [];
    meta.push('<span class="llm-chip token">' + esc(fmtTokens(p.today_tokens)) + " tokens 今日</span>");
    meta.push('<span class="llm-chip"' + (balanceError ? ' title="' + esc(balanceError) + '"' : "") +
      ">" + esc(balanceLine) + "</span>");
    if (balanceError) {
      meta.push('<span class="llm-chip muted" title="' + esc(balanceError) + '">' +
        esc(balanceError.length > 32 ? balanceError.slice(0, 32) + "…" : balanceError) + "</span>");
    }
    if (balance.fetched_at) meta.push('<span class="llm-chip muted">' + esc(balance.fetched_at) + "</span>");
    if (!p.api_key_set) meta.push('<span class="llm-chip muted">未配置 Key</span>');
    if (p.enabled === false) meta.push('<span class="llm-chip muted">已停用</span>');
    const badges = [];
    if (isActive) badges.push('<span class="llm-badge on">当前使用</span>');
    if (p.kind === "sub") badges.push('<span class="llm-badge">订阅用量</span>');
    if (!isActive && balance.low) badges.push('<span class="llm-badge warn">余额偏低</span>');
    return '<div class="llm-provider' + (isActive ? " active" : "") + (isSelected ? " selected" : "") +
      '" data-llm-provider="' + esc(id) + '" role="button" tabindex="0">' +
      '<div class="llm-p-top"><span class="llm-p-name">' + esc(p.name || id) + "</span>" +
        badges.join("") + "</div>" +
      '<div class="llm-p-model">' + esc(p.model || "未配置模型") + " · " + esc(hostOf(p.base_url) || "未配置地址") + "</div>" +
      '<div class="llm-p-meta">' + meta.join("") + "</div>" +
      '<button class="btn sm' + (isActive ? " llm-on" : "") + '" data-llm-activate="' + esc(id) + '"' +
        (isActive ? " disabled" : "") + ">" + (isActive ? "使用中" : "切换") + "</button>" +
    "</div>";
  }).join('<div class="llm-gap"></div>');

  const empty = providers().length
    ? ""
    : '<div class="llm-empty">还没有供应商。先在右侧选一个预设（DeepSeek / OpenRouter / OpenCode Go…），填 Key 后保存。</div>';

  return '<div class="card llm-list">' + empty + cards +
    '<button class="llm-add" id="llmAdd">+ 添加供应商（预设 / 自定义）</button>' +
    '<div class="llm-note">切换只影响 AI 快报与 Skills 翻译，不改 Claude / Codex 配置。' +
      "订阅型（OpenCode Go）只显示已用百分比，不计入总余额。</div>" +
  "</div>";
}

function usageCard() {
  const usage = state.data.usage || {};
  const today = usage.today || {};
  const month = usage.month || {};
  const byPurpose = usage.by_purpose || {};
  const estimated = Number(today.estimated_calls) || 0;
  const recent = usage.recent || [];
  const recentHtml = recent.length
    ? recent.map((r) =>
      '<div class="llm-usage-line"><span>' + esc(String(r.ts || "").slice(5, 16).replace("T", " ")) + " · " +
        esc(r.model || r.provider_id || "—") + "</span><span>" +
        esc(fmtTokens(r.total_tokens)) + " tokens" + (r.estimated ? "（估算）" : "") + "</span></div>"
    ).join("")
    : '<div class="llm-usage-line"><span>最近调用</span><span>暂无</span></div>';
  return '<div class="card llm-stat-card">' +
    "<h3>今日 / 本月（分用途为累计）</h3>" +
    '<div class="llm-stats">' +
      stat("今日", fmtTokens(today.total_tokens), "tokens") +
      stat("本月", fmtTokens(month.total_tokens), "tokens") +
      stat("AI 快报·累计", fmtTokens((byPurpose.news || {}).total_tokens), "tokens") +
      stat("Skills 翻译·累计", fmtTokens((byPurpose.translate || {}).total_tokens), "tokens") +
    "</div>" +
    (estimated ? '<div class="llm-note">今日 ' + esc(String(estimated)) +
      " 次调用无 usage 字段，Token 按字符估算。</div>" : "") +
    '<div class="llm-usage">' + recentHtml + "</div>" +
  "</div>";
}

function stat(label, value, unit) {
  return '<div class="llm-stat"><div class="llm-k">' + esc(label) + '</div><div class="llm-v">' +
    esc(value) + (unit ? " <small>" + esc(unit) + "</small>" : "") + "</div></div>";
}

function editorCard() {
  const d = state.draft;
  if (!d) {
    return '<div class="card llm-editor"><h3>编辑供应商</h3>' +
      '<div class="llm-empty">点击左侧卡片编辑，或点「+ 添加供应商」新建。</div></div>';
  }
  const isNew = !d.id;
  const sub = d.kind === "sub";
  const presetOptions = presets().map((p) =>
    '<option value="' + esc(p.id) + '"' + (p.id === d.preset ? " selected" : "") + ">" +
      esc(p.name) + "</option>").join("");
  const keyPlaceholder = d.api_key_set
    ? "已保存 " + (d.api_key_hint || "••••") + "（留空不改）"
    : "sk-… 或 {{env:VAR_NAME}}";
  const busy = state.busy;
  const confirmDelete = state.confirmDelete === d.id;

  return '<div class="card llm-editor">' +
    '<h3>编辑供应商 <span class="llm-badge">' + esc(d.name || (isNew ? "新增" : d.id)) + "</span></h3>" +
    field("预设", '<select class="llm-inp" data-llm-field="preset" id="llmPreset">' + presetOptions + "</select>") +
    field("名称", '<input class="llm-inp" data-llm-field="name" value="' + esc(d.name || "") +
      '" placeholder="例如 DeepSeek 主力">') +
    field("Base URL", '<input class="llm-inp mono" data-llm-field="base_url" value="' +
      esc(d.base_url || "") + '" placeholder="https://api.deepseek.com/v1">') +
    field("模型", '<input class="llm-inp mono" data-llm-field="model" value="' +
      esc(d.model || "") + '" placeholder="deepseek-chat">') +
    field("API Key", '<div class="llm-inline"><input class="llm-inp mono" type="password" ' +
      'data-llm-field="api_key" value="' + esc(d.api_key || "") + '" placeholder="' +
      esc(keyPlaceholder) + '" autocomplete="new-password">' +
      '<button class="btn sm" id="llmTest"' + (busy ? " disabled" : "") + ">" +
      (busy === "test" ? "测试中…" : "测试") + "</button></div>") +
    field("类型", '<div class="llm-inline"><select class="llm-inp" data-llm-field="kind" style="width:130px">' +
      '<option value="money"' + (sub ? "" : " selected") + ">金额余额</option>" +
      '<option value="sub"' + (sub ? " selected" : "") + ">订阅用量</option></select>" +
      '<span class="llm-hint">' + (sub ? "只读 rolling / weekly / monthly 百分比" :
        "读取余额接口里的一个字段") + "</span></div>") +
    field("余额接口", '<input class="llm-inp mono" data-llm-field="balance_url" value="' +
      esc(d.balance_url || "") + '"' + (sub ? " disabled" : "") +
      ' placeholder="可选，例如 https://api.deepseek.com/user/balance">') +
    field("余额字段", '<input class="llm-inp mono" data-llm-field="balance_field" value="' +
      esc(d.balance_field || "") + '"' + (sub ? " disabled" : "") +
      ' placeholder="例如 balance_infos[0].total_balance">') +
    field("低余额提醒", '<div class="llm-inline"><input class="llm-inp" type="number" step="0.1" ' +
      'data-llm-field="low_balance_warn" value="' + esc(String(d.low_balance_warn == null ? 5 : d.low_balance_warn)) +
      '" style="width:100px"><span class="llm-hint">' +
      (sub ? "订阅型填已用百分比阈值" : "低于该金额时提示") + "</span></div>") +
    field("备注", '<input class="llm-inp" data-llm-field="note" value="' + esc(d.note || "") +
      '" placeholder="可选，例如：主力 / 备用">') +
    field("启用", '<label class="llm-check"><input type="checkbox" data-llm-field="enabled"' +
      (d.enabled !== false ? " checked" : "") + "> 参与余额监控与切换</label>") +
    '<div class="llm-actions">' +
      '<button class="btn primary" id="llmSave"' + (busy ? " disabled" : "") + ">" +
        (busy === "save" ? "保存中…" : "保存") + "</button>" +
      '<button class="btn" id="llmActivate"' + (busy || isNew || d.enabled === false ? " disabled" : "") + ">设为当前</button>" +
      '<button class="btn danger" id="llmDelete"' + (busy || isNew ? " disabled" : "") + ">" +
        (confirmDelete ? "再点一次确认删除" : "删除") + "</button>" +
    "</div>" +
    '<div class="llm-note">Key 只保存在本地 config.json，页面不回显、不写日志；' +
      "保存前留空表示沿用已保存的 Key。Base URL 需指向 OpenAI 兼容的 /v1 根路径。</div>" +
  "</div>";
}

function field(label, control) {
  return '<div class="llm-field"><label>' + esc(label) + "</label>" + control + "</div>";
}

// ── 交互 ────────────────────────────────────────────────
function bind() {
  const box = document.getElementById("llmContent");
  if (!box) return;
  box.querySelectorAll("[data-llm-provider]").forEach((el) => {
    el.addEventListener("click", (ev) => {
      if (ev.target.closest("[data-llm-activate]")) return;
      selectProvider(el.dataset.llmProvider);
    });
    el.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" || ev.key === " ") {
        ev.preventDefault();
        selectProvider(el.dataset.llmProvider);
      }
    });
  });
  box.querySelectorAll("[data-llm-activate]").forEach((btn) => {
    btn.addEventListener("click", (ev) => {
      ev.stopPropagation();
      activate(btn.dataset.llmActivate);
    });
  });
  const refresh = box.querySelector("#llmRefresh");
  if (refresh) refresh.addEventListener("click", refreshBalances);
  const add = box.querySelector("#llmAdd");
  if (add) add.addEventListener("click", () => newProvider());
  const saveBtn = box.querySelector("#llmSave");
  if (saveBtn) saveBtn.addEventListener("click", save);
  const activateBtn = box.querySelector("#llmActivate");
  if (activateBtn) activateBtn.addEventListener("click", () => {
    if (state.draft && state.draft.id) activate(state.draft.id);
  });
  const testBtn = box.querySelector("#llmTest");
  if (testBtn) testBtn.addEventListener("click", test);
  const delBtn = box.querySelector("#llmDelete");
  if (delBtn) delBtn.addEventListener("click", removeProvider);
  const presetSel = box.querySelector("#llmPreset");
  if (presetSel) presetSel.addEventListener("change", () => applyPreset(presetSel.value));

  box.querySelectorAll("[data-llm-field]").forEach((el) => {
    const key = el.dataset.llmField;
    const read = () => {
      if (!state.draft) return;
      state.draft[key] = el.type === "checkbox" ? el.checked : el.value;
      state.dirty = true;
      if (key === "kind") paint();
    };
    el.addEventListener(el.tagName === "SELECT" || el.type === "checkbox" ? "change" : "input", read);
  });
}

/** 有未保存草稿（可能含刚粘贴的 Key）时先确认，避免点错卡片静默丢失。 */
async function confirmDiscardDraft() {
  if (!state.dirty) return true;
  const body = "当前供应商有未保存的修改（含刚输入的 API Key），继续将丢弃这些内容。";
  if (window.App && window.App.confirmDialog) {
    return !!(await window.App.confirmDialog({
      title: "放弃未保存的修改？", body: body, okText: "放弃并继续", danger: true,
    }));
  }
  return window.confirm(body);
}

async function selectProvider(id) {
  if (!id || id === state.selected) return;
  const provider = providerById(id);
  if (!provider) return;
  if (!(await confirmDiscardDraft())) return;
  state.selected = id;
  state.draft = draftFrom(provider);
  state.dirty = false;
  state.confirmDelete = "";
  paint();
}

async function newProvider() {
  if (!(await confirmDiscardDraft())) return;
  state.selected = "";
  state.draft = blankDraft("custom");
  state.dirty = false;
  state.confirmDelete = "";
  paint();
  const box = document.getElementById("llmContent");
  const nameInput = box && box.querySelector('[data-llm-field="name"]');
  if (nameInput) nameInput.focus();
}

function applyPreset(presetId) {
  const preset = presetById(presetId);
  if (!preset || !state.draft) return;
  const d = state.draft;
  const previous = presetById(d.preset);
  d.preset = preset.id;
  ["base_url", "model", "balance_url", "balance_field", "kind", "currency"].forEach((key) => {
    if (preset[key] != null) d[key] = preset[key];
  });
  if (preset.low_balance_warn != null) d.low_balance_warn = preset.low_balance_warn;
  if (!d.name || (previous && d.name === previous.name)) d.name = preset.name || d.name;
  state.dirty = true;
  paint();
  toast("已套用预设：" + (preset.name || preset.id), "ok");
}

async function save() {
  const d = state.draft;
  if (!d) return;
  if (!String(d.name || "").trim()) return toast("请填写供应商名称", "err");
  if (!String(d.base_url || "").trim()) return toast("请填写 Base URL", "err");
  if (!String(d.model || "").trim()) return toast("请填写模型名", "err");
  state.busy = "save";
  paint();
  try {
    const r = await API.api("/api/llm/providers", {
      method: "POST", body: { provider: payloadOf(d) }, timeout: 20000,
    });
    if (!r || r.ok === false) throw new Error((r && r.error) || "保存失败");
    const savedId = (r.provider && r.provider.id) || d.id;
    state.selected = savedId;
    state.draft = null;
    state.dirty = false;
    state.busy = "";
    toast("已保存：" + ((r.provider && r.provider.name) || d.name), "ok");
    await load(true);
  } catch (e) {
    state.busy = "";
    paint();
    toast("保存失败：" + e.message, "err");
  }
}

async function activate(id) {
  if (!id || state.busy) return;
  // 切换的是别的供应商且当前草稿未保存时先确认；激活当前供应商则原样保留草稿
  if (state.draft && state.draft.id !== id && !(await confirmDiscardDraft())) return;
  state.busy = "activate";
  paint();
  try {
    const r = await API.api("/api/llm/providers/" + encodeURIComponent(id) + "/activate", {
      method: "POST", body: {}, timeout: 15000,
    });
    if (!r || r.ok === false) throw new Error((r && r.error) || "切换失败");
    state.busy = "";
    toast("已切换到：" + ((r.provider && r.provider.name) || id), "ok");
    if (!(state.draft && state.draft.id === id && state.dirty)) {
      // 未保存草稿只在「激活当前供应商」时保留；其余情况跟随服务端数据
      state.selected = id;
      state.draft = draftFrom(providerById(id) || {});
      state.dirty = false;
    }
    await load(false);
  } catch (e) {
    state.busy = "";
    paint();
    toast("切换失败：" + e.message, "err");
  }
}

async function test() {
  const d = state.draft;
  if (!d || state.busy) return;
  if (!String(d.base_url || "").trim() || !String(d.model || "").trim()) {
    return toast("测试前请先填 Base URL 和模型", "err");
  }
  state.busy = "test";
  paint();
  try {
    const r = await API.api("/api/llm/test", {
      method: "POST",
      body: { provider: payloadOf(d), id: d.id || "" },
      timeout: 45000,
    });
    state.busy = "";
    paint();
    if (!r || r.ok === false) throw new Error((r && r.error) || "测试失败");
    const used = r.usage && r.usage.total_tokens ? "（" + r.usage.total_tokens + " tokens" +
      (r.usage.estimated ? "，估算" : "") + "）" : "";
    toast("测试通过：" + (r.reply || "ok") + used, "ok");
    await load(false);      // 只刷新余额 / 统计；dirty 草稿会保留，Key 不会被清空
  } catch (e) {
    state.busy = "";
    paint();
    toast("测试失败：" + e.message, "err");
  }
}

async function removeProvider() {
  const d = state.draft;
  if (!d || !d.id || state.busy) return;
  if (state.confirmDelete !== d.id) {
    state.confirmDelete = d.id;
    paint();
    return;
  }
  const id = d.id;
  state.busy = "delete";
  state.confirmDelete = "";
  paint();
  try {
    const r = await API.api("/api/llm/providers/" + encodeURIComponent(id) + "/delete", {
      method: "POST", body: {}, timeout: 15000,
    });
    if (!r || r.ok === false) throw new Error((r && r.error) || "删除失败");
    state.busy = "";
    state.selected = "";
    state.draft = null;
    state.dirty = false;
    toast("已删除供应商", "ok");
    await load(false);
  } catch (e) {
    state.busy = "";
    paint();
    toast("删除失败：" + e.message, "err");
  }
}

async function refreshBalances() {
  if (state.busy) return;
  state.busy = "refresh";
  paint();
  try {
    const r = await API.api("/api/llm/refresh", { method: "POST", body: {}, timeout: 15000 });
    if (!r || r.ok === false) throw new Error((r && r.error) || "刷新请求失败");
    state.busy = "";
    await load(true);
    if (state.error) {
      toast("刷新失败：" + state.error, "err");
      return;
    }
    const failed = providers().filter(
      (p) => p.enabled !== false && p.balance && p.balance.ok === false &&
        !p.balance.skipped && p.balance.error !== "尚未刷新");
    if (failed.length) {
      const first = failed[0];
      const reason = (first.balance && first.balance.error) || "未知原因";
      toast(failed.length + " 个供应商查询失败：" +
        (first.name || first.id) + " — " + reason, "err");
    } else {
      toast("余额已刷新", "ok");
    }
  } catch (e) {
    state.busy = "";
    paint();
    toast("刷新失败：" + e.message, "err");
  }
}
