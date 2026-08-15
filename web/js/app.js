/**
 * app.js — AgentFloat Web 控制台（设置 / API 用量 / AI 快报）
 * 数据流：配置以 JSON 形式在浏览器内编辑 → PUT /api/config 持久化并应用到浮窗。
 */
(function () {
  "use strict";

  // ── 状态 ────────────────────────────────────────
  let cfg = null;
  let baseStr = "";
  let page = "settings";
  let sub = "general";
  let version = "";
  let apiState = { results: [], testing: {}, error: "" };
  let newsState = { report: null, dates: [], generating: false, phase: "" };

  // ── 工具 ────────────────────────────────────────
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const getPath = (o, p) => p.split(".").reduce((a, k) => (a == null ? undefined : a[k]), o);
  const setPath = (o, p, v) => { const ks = p.split("."); let t = o; for (let i = 0; i < ks.length - 1; i++) { if (t[ks[i]] == null || typeof t[ks[i]] !== "object") t[ks[i]] = {}; t = t[ks[i]]; } t[ks[ks.length - 1]] = v; };
  const num = (v, d) => { const n = parseFloat(v); return isNaN(n) ? (d || 0) : n; };
  const deep = (o) => JSON.parse(JSON.stringify(o));

  function toast(msg, kind) {
    const wrap = $("#toastWrap");
    const t = document.createElement("div");
    t.className = "toast " + (kind || "ok");
    t.textContent = msg;
    wrap.appendChild(t);
    setTimeout(() => { t.classList.add("out"); setTimeout(() => t.remove(), 320); }, 2600);
  }

  // ── 配置绑定 ────────────────────────────────────
  function bindRead(el) {
    const path = el.dataset.bind;
    if (!path) return;
    let v;
    if (el.type === "checkbox") v = el.checked;
    else if (el.type === "radio") { if (!el.checked) return; v = el.value; }
    else if (el.type === "range") v = num(el.value);
    else if (el.type === "number") v = num(el.value);
    else if (el.tagName === "SELECT" && el.dataset.num) v = num(el.value);
    else v = el.value;
    if (el.dataset.array === "line") v = String(v).split("\n").map((s) => s.trim()).filter(Boolean);
    if (el.dataset.int !== undefined) v = Math.round(num(v));
    setPath(cfg, path, v);
    if (path === "theme") applyTheme();
    if (path === "theme" || path === "widget_size" || path === "opacity") schedulePreview();
    refreshDirty();
  }
  function bindWrite(el) {
    const path = el.dataset.bind;
    if (!path) return;
    let v = getPath(cfg, path);
    if (el.dataset.array === "line") v = (v || []).join("\n");
    if (el.type === "checkbox") el.checked = !!v;
    else if (el.tagName === "SELECT") el.value = v == null ? "" : String(v);
    else el.value = v == null ? "" : String(v);
  }
  function bindAll(root) { $$("[data-bind]", root).forEach(bindWrite); }

  // ── 主题 / 脏检测 / 预览 ────────────────────────
  function applyTheme() {
    document.documentElement.dataset.theme = (cfg && cfg.theme === "dark") ? "dark" : "light";
  }
  let previewTimer = null;
  function schedulePreview() {
    clearTimeout(previewTimer);
    previewTimer = setTimeout(async () => {
      try { await API.api("/api/preview", { method: "POST", body: { config: cfg } }); } catch (e) { /* 预览失败可忽略 */ }
    }, 400);
  }
  function refreshDirty() {
    const dirty = cfg && JSON.stringify(cfg) !== baseStr;
    $("#btnSave").disabled = !dirty;
    $("#dirtyHint").classList.toggle("show", !!dirty);
    return !!dirty;
  }
  function diffKeys(a, b) {
    const out = [];
    for (const k of Object.keys(a)) {
      if (JSON.stringify(a[k]) !== JSON.stringify(b[k])) out.push(k);
    }
    return out;
  }
  const KEY_LABEL = {
    launch_mode: "启动模式", working_directory: "工作目录", theme: "外观主题",
    widget_size: "浮窗尺寸", opacity: "不透明度", snap_enabled: "边缘吸附",
    snap_hidden: "吸附隐藏", hide_delay_ms: "隐藏延迟", cleanup_on_quit: "退出清理",
    auto_start: "开机自启", check_updates: "检查更新", agents: "Agent 管理",
    radial_menu: "环绕菜单", skills: "Skills 设置", api_monitor: "API 用量",
    news: "AI 快报", water: "喝水助手", services: "本地 AI 服务",
  };
  const labelOf = (k) => KEY_LABEL[k] || k;

  // ── 保存 ────────────────────────────────────────
  async function save() {
    try {
      $$("[data-bind]").forEach(bindRead);
      const changed = diffKeys(cfg, JSON.parse(baseStr));
      await API.api("/api/config", { method: "PUT", body: { config: cfg, changed_keys: changed } });
      const resp = await API.api("/api/config");
      cfg = resp.config;
      baseStr = JSON.stringify(cfg);
      applyTheme();
      refreshDirty();
      toast("已保存：" + (changed.length ? changed.map(labelOf).join("、") : "无变化"), "ok");
      renderPage();
    } catch (e) {
      toast("保存失败：" + e.message, "err");
    }
  }

  // ── 页面导航 ────────────────────────────────────
  function goPage(p) {
    page = p;
    $$("#nav .nav-item").forEach((a) => a.classList.toggle("active", a.dataset.page === p));
    ["settings", "api", "news"].forEach((id) => $("#page-" + id).classList.toggle("hidden", id !== p));
    $("#pageTitle").textContent = { settings: "设置", api: "API 用量", news: "AI 快报" }[p];
    if (p === "settings") renderSettings();
    else if (p === "api") loadApiPage();
    else loadNewsPage();
    try { history.replaceState(null, "", "#/" + p); } catch (e) { /* ignore */ }
  }
  function goSub(s) {
    sub = s;
    $$("#settingsSubnav .sub").forEach((b) => b.classList.toggle("active", b.dataset.sub === s));
    renderSettings();
  }

  // ── 卡片与表单助手 ──────────────────────────────
  function card(title, desc, inner, extra) {
    return '<div class="card"><h3>' + esc(title) + (extra || "") + "</h3>" +
      (desc ? '<div class="desc">' + desc + "</div>" : "") + inner + "</div>";
  }
  function row(lbl, tip, ctl) {
    return '<div class="row"><div class="lbl">' + esc(lbl) + (tip ? "<small>" + esc(tip) + "</small>" : "") + "</div>" +
      '<div class="ctl">' + ctl + "</div></div>";
  }
  function switchCtl(path, checked) {
    return '<label class="switch"><input type="checkbox" data-bind="' + path + '" ' + (checked ? "checked" : "") + "><span class='track'></span></label>";
  }
  function numCtl(path, val, opts) {
    opts = opts || {};
    return '<input type="number" data-bind="' + path + '" value="' + esc(val) + '"' +
      (opts.min != null ? ' min="' + opts.min + '"' : "") + (opts.max != null ? ' max="' + opts.max + '"' : "") +
      (opts.step != null ? ' step="' + opts.step + '"' : "") + ">";
  }
  function rangeCtl(path, val, min, max, step, show) {
    return '<input type="range" data-bind="' + path + '" value="' + esc(val) + '" min="' + min + '" max="' + max + '" step="' + (step || 1) + '"' +
      (show ? ' oninput="App.rangeLabel(this, \'' + show + '\')"' : "") + ">";
  }
  function selectCtl(path, val, options, numMode) {
    let opts = "";
    options.forEach((o) => {
      const v = Array.isArray(o) ? o[0] : o;
      const t = Array.isArray(o) ? o[1] : o;
      opts += '<option value="' + esc(v) + '"' + (String(val) === String(v) ? " selected" : "") + ">" + esc(t) + "</option>";
    });
    return '<select data-bind="' + path + '"' + (numMode ? " data-num" : "") + ">" + opts + "</select>";
  }
  function textCtl(path, val, width) {
    return '<input type="text" data-bind="' + path + '" value="' + esc(val) + '"' + (width ? ' style="width:' + width + 'px"' : "") + ">";
  }
  // ══════════════════ 设置页 ══════════════════
  function renderSettings() {
    const el = $("#settingsContent");
    const agents = cfg.agents || [];
    const primary = agents.find((a) => a.primary) || agents[0] || {};
    if (sub === "general") {
      const canSkip = !!primary.skip_permissions_arg && (primary.launcher || "terminal") !== "web";
      const agentOpts = agents.map((a) => [a.id, a.name + (a.primary ? "（默认）" : "")]);
      let inner = "";
      inner += card("主 Agent 启动", "点击浮窗快捷启动的默认 Agent；DeepSeek Harness 以 Web UI 方式启动并自动打开浏览器。",
        row("默认启动的 Agent", "可在「Agent 管理」中增删与编辑", selectCtl("__primary", primary.id || "", agentOpts)) +
        row("启动模式", canSkip ? "「跳过权限」会追加该 Agent 配置的跳过权限参数" : "该 Agent（Web 启动器）无跳过权限参数",
          '<label class="tag-row"><input type="radio" name="launch_mode" value="normal"' + (cfg.launch_mode !== "skip_permissions" ? " checked" : "") + "> 普通模式</label>" +
          '<label class="tag-row"><input type="radio" name="launch_mode" value="skip_permissions"' + (cfg.launch_mode === "skip_permissions" ? " checked" : "") + (canSkip ? "" : " disabled") + "> 跳过权限</label>") +
        row("默认工作目录", "留空则使用用户主目录", textCtl("working_directory", cfg.working_directory || "", 260) + '<button class="btn sm" onclick="App.resetDir()">重置</button>'));
      inner += card("外观主题", "实时预览，保存后生效并同步到浮窗。",
        row("主题", "浅色适合日间，深色适合夜间",
          '<label class="tag-row"><input type="radio" name="theme" data-bind="theme" value="light"' + (cfg.theme !== "dark" ? " checked" : "") + "> ☀ 浅色</label>" +
          '<label class="tag-row"><input type="radio" name="theme" data-bind="theme" value="dark"' + (cfg.theme === "dark" ? " checked" : "") + "> ☾ 深色</label>") +
        row("浮窗尺寸", "", rangeCtl("widget_size", cfg.widget_size || 52, 30, 200, 1, "sizeLabel") + '<span id="sizeLabel" class="val-tag">' + (cfg.widget_size || 52) + "px</span>") +
        row("不透明度", "", rangeCtl("opacity", cfg.opacity || 0.88, 0.1, 1, 0.01, "opLabel") + '<span id="opLabel" class="val-tag">' + Math.round((cfg.opacity || 0.88) * 100) + "%</span>"));
      inner += card("行为",
        row("屏幕边缘吸附", "靠近边缘自动吸附并隐藏", switchCtl("snap_enabled", cfg.snap_enabled)) +
        row("吸附后自动隐藏", "吸附后鼠标移开即隐藏，悬停弹出", switchCtl("snap_hidden", cfg.snap_hidden)) +
        row("隐藏延迟 (ms)", "", numCtl("hide_delay_ms", cfg.hide_delay_ms, { min: 200, max: 3000 })) +
        row("退出时清理 Agent 进程", "退出 AgentFloat 时结束主 Agent 进程", switchCtl("cleanup_on_quit", cfg.cleanup_on_quit)) +
        row("开机自启", "登录 Windows 后自动运行", switchCtl("auto_start", cfg.auto_start)) +
        row("启动时检查更新", "", switchCtl("check_updates", cfg.check_updates)));
      el.innerHTML = inner;
      bindAll(el);
      $("#settingsContent [name='launch_mode']").forEach((r) => r.addEventListener("change", () => {
        cfg.launch_mode = $("input[name='launch_mode']:checked").value;
        refreshDirty();
      }));
      $("#settingsContent [data-bind='theme']").forEach((r) => r.addEventListener("change", () => { bindRead(r); refreshDirty(); }));
      const sel = $("#settingsContent [data-bind='__primary']");
      if (sel) sel.addEventListener("change", () => {
        agents.forEach((a) => { a.primary = (a.id === sel.value); });
        refreshDirty();
      });
    } else if (sub === "agents") renderAgents(el);
    else if (sub === "radial") renderRadial(el);
    else if (sub === "skills") renderSkills(el);
    else if (sub === "water") renderWater(el);
    else if (sub === "about") renderAbout(el);
  }

  // ── Agent 管理 ──
  function renderAgents(el) {
    const agents = cfg.agents || [];
    const cards = agents.map((a, i) => {
      const badges = [];
      if (a.primary) badges.push('<span class="tag blue">主 Agent</span>');
      if (a.builtin) badges.push('<span class="tag gray">内置</span>');
      if ((a.launcher || "terminal") === "web") badges.push('<span class="tag purple">Web UI</span>');
      return '<div class="agent-card">' +
        '<div class="agent-ico" style="background:' + esc(a.icon_color || "#5B8DEF") + '">' + esc(a.icon_char || "A") + "</div>" +
        '<div class="agent-info"><div class="agent-name">' + esc(a.name) + " " + badges.join("") + "</div>" +
        '<div class="agent-cmd">' + esc(a.command) + (a.args && a.args.length ? " " + esc(a.args.join(" ")) : "") + "</div>" +
        '<div class="agent-cmd">' + esc(a.description || "") + "</div></div>" +
        '<div class="agent-actions">' +
        (!a.primary ? '<button class="btn sm" onclick="App.setPrimary(' + i + ')">设为默认</button>' : "") +
        '<button class="btn sm" onclick="App.editAgent(' + i + ')">编辑</button>' +
        (!a.builtin ? '<button class="btn sm danger" onclick="App.delAgent(' + i + ')">删除</button>' : "") +
        "</div></div>";
    }).join("");
    el.innerHTML =
      card("Agent 列表", "内置预设会自动补齐（升级后新增的 Agent 不会覆盖你的自定义）。DeepSeek Harness 使用 Web UI 启动模式。", cards) +
      '<div style="display:flex;gap:8px"><button class="btn primary" onclick="App.addAgent()">＋ 添加 Agent</button>' +
      '<button class="btn" onclick="App.openDsh()">打开 DeepSeek Harness</button></div>';
  }

  function agentModal(idx) {
    const a = idx == null ? { id: "", name: "", command: "", args: [], skip_permissions_arg: "", working_directory: "", launch_mode: "normal", icon_color: "#5B8DEF", icon_char: "A", launcher: "terminal", description: "" } : deep(cfg.agents[idx]);
    const html = "<h3>" + (idx == null ? "添加 Agent" : "编辑 Agent") + "</h3>" +
      '<div class="f"><label>名称</label><input type="text" id="m-name" value="' + esc(a.name) + '"></div>' +
      '<div class="f"><label>命令</label><input type="text" id="m-command" value="' + esc(a.command) + '" placeholder="如 claude / codex / pi / dsh / C:\\path\\app.exe"></div>' +
      '<div class="f"><label>附加参数（逗号分隔）</label><input type="text" id="m-args" value="' + esc((a.args || []).join(", ")) + '"></div>' +
      '<div class="f-row">' +
      '<div class="f"><label>启动器</label><select id="m-launcher"><option value="terminal"' + (a.launcher !== "web" ? " selected" : "") + ">终端（wt）</option><option value=\"web\"" + (a.launcher === "web" ? " selected" : "") + ">Web UI（自动开浏览器）</option></select></div>" +
      '<div class="f"><label>启动模式</label><select id="m-mode"><option value="normal"' + (a.launch_mode !== "skip_permissions" ? " selected" : "") + ">普通</option><option value=\"skip_permissions\"" + (a.launch_mode === "skip_permissions" ? " selected" : "") + ">跳过权限</option></select></div>" +
      "</div>" +
      '<div class="f"><label>跳过权限参数（可留空）</label><input type="text" id="m-skip" value="' + esc(a.skip_permissions_arg) + '"></div>' +
      '<div class="f"><label>默认工作目录（可留空）</label><input type="text" id="m-wd" value="' + esc(a.working_directory || "") + '"></div>' +
      '<div class="f-row">' +
      '<div class="f"><label>图标文字</label><input type="text" id="m-char" maxlength="1" value="' + esc(a.icon_char || "A") + '"></div>' +
      '<div class="f"><label>图标颜色</label><input type="color" id="m-color" value="' + esc(a.icon_color || "#5B8DEF") + '"></div>' +
      "</div>" +
      '<div class="f"><label>描述</label><textarea id="m-desc" rows="2">' + esc(a.description || "") + "</textarea></div>" +
      '<div class="modal-actions"><button class="btn" data-close>取消</button><button class="btn primary" data-save>保存</button></div>';
    openModal(html);
    $("#modalBox [data-save]").addEventListener("click", () => {
      const name = $("#m-name").value.trim();
      const command = $("#m-command").value.trim();
      if (!name || !command) { toast("名称与命令不能为空", "err"); return; }
      const item = {
        id: a.id || "agent_" + Date.now().toString(36),
        name: name,
        command: command,
        args: $("#m-args").value.split(",").map((s) => s.trim()).filter(Boolean),
        skip_permissions_arg: $("#m-skip").value.trim(),
        working_directory: $("#m-wd").value.trim(),
        launch_mode: $("#m-mode").value,
        launcher: $("#m-launcher").value,
        icon_color: $("#m-color").value,
        icon_char: ($("#m-char").value || name[0] || "A").toUpperCase(),
        description: $("#m-desc").value.trim(),
        check: a.check || command,
        primary: a.primary ? true : false,
        builtin: a.builtin ? true : false,
      };
      if (idx == null) cfg.agents.push(item);
      else cfg.agents[idx] = item;
      closeModal();
      refreshDirty();
      renderAgents($("#settingsContent"));
    });
    $("#modalBox [data-close]").addEventListener("click", closeModal);
  }

  // ── 环绕菜单 ──
  function renderRadial(el) {
    const rm = cfg.radial_menu || {};
    const agents = cfg.agents || [];
    const slotOpts = [["", "自动（默认布局）"]];
    agents.forEach((a) => slotOpts.push(["agent:" + a.id, "启动 " + a.name]));
    [["skills", "Skills 辅助窗"], ["api", "API 用量"], ["settings", "设置"], ["news", "AI 快报"], ["clip", "剪贴板历史"], ["cmd", "命令面板"], ["water", "喝水助手"], ["quit", "退出"]].forEach((o) => slotOpts.push(o));
    const slots = Array.isArray(rm.slots) ? rm.slots : [];
    const slotRows = Array.from({ length: rm.slot_count || 6 }, (_, i) =>
      row("扇区 " + (i + 1), "", selectCtl("__slot_" + i, slots[i] || "", slotOpts))).join("");
    el.innerHTML =
      card("环绕菜单", "鼠标悬停 / 长按浮窗唤出环绕菜单；扇区功能可自由映射，未来扩展功能在此预留。",
        row("启用环绕菜单", "", switchCtl("radial_menu.enabled", rm.enabled)) +
        row("触发方式", "", selectCtl("radial_menu.trigger_mode", rm.trigger_mode || "both", [["both", "悬停 + 长按"], ["hover", "仅悬停"], ["long_press", "仅长按"]])) +
        row("悬停延迟 (ms)", "", numCtl("radial_menu.hover_delay_ms", rm.hover_delay_ms || 400, { min: 100, max: 2000 })) +
        row("长按延迟 (ms)", "", numCtl("radial_menu.long_press_delay_ms", rm.long_press_delay_ms || 500, { min: 100, max: 2000 })) +
        row("半径 (px)", "", numCtl("radial_menu.radius", rm.radius || 120, { min: 80, max: 260 })) +
        row("扇区数量", "", selectCtl("__slot_count", rm.slot_count || 6, [[4, "4 扇区"], [6, "6 扇区"], [8, "8 扇区"]], true))) +
      card("扇区功能映射", "每个扇区可映射为启动某 Agent 或打开某面板；「自动」表示按默认布局（所有 Agent + 固定 4 项）自动填充。", slotRows);
    bindAll(el);
    $$("#settingsContent [data-bind^='__slot_']").forEach((s) => s.addEventListener("change", () => {
      const i = parseInt(s.dataset.bind.split("_")[1], 10);
      rm.slots = rm.slots || [];
      rm.slots[i] = s.value;
      refreshDirty();
    }));
    const sc = $("#settingsContent [data-bind='__slot_count']");
    if (sc) sc.addEventListener("change", () => {
      const n = parseInt(sc.value, 10) || 6;
      rm.slot_count = n;
      if (!Array.isArray(rm.slots)) rm.slots = [];
      while (rm.slots.length < n) rm.slots.push("");
      rm.slots.length = n;
      renderRadial(el);
    });
  }

  // ── Skills ──
  function renderSkills(el) {
    const sk = cfg.skills || {};
    el.innerHTML =
      card("Skills 设置", "辅助窗扫描本机已安装的 agent skills；本地 AI 服务可为 API 配置与 skills 翻译提供帮助。",
        row("扫描根目录", "每行一个目录，留空使用默认根（.codex / .agents / 插件缓存）",
          '<textarea data-bind="skills.roots" data-array="line" rows="3" style="width:100%">' + esc((sk.roots || []).join("\n")) + "</textarea>") +
        row("AI 调用方式", "", textCtl("skills.ai_tool", sk.ai_tool || "codex exec", 200)) +
        row("描述截断长度", "", numCtl("skills.max_description_len", sk.max_description_len || 160, { min: 40, max: 400 })) +
        row("新 skill 自动翻译", "检测到新装 skill 自动触发本地 AI 补译", switchCtl("skills.auto_translate_new_skills", sk.auto_translate_new_skills)) +
        '<div class="row"><div class="lbl">本地 AI 自检服务</div><div class="ctl"><button class="btn" onclick="App.runAiServices()">立即运行（API 配置 / Skills 翻译）</button></div></div>');
    bindAll(el);
  }

  // ── 喝水助手 ──
  function renderWater(el) {
    const w = cfg.water || {};
    const timers = w.timers || [];
    const timerRows = timers.map((t, i) =>
      '<div class="mini-row"><span class="dot" style="background:' + esc(t.color || "#00A6A6") + '"></span>' +
      '<span class="grow">' + esc(t.name) + " · 每 " + esc(t.interval_min) + " 分钟</span>" +
      '<label class="switch"><input type="checkbox" data-bind="__wtimer_en_' + i + '" ' + (t.enabled ? "checked" : "") + "><span class='track'></span></label>" +
      '<button class="btn sm" onclick="App.editTimer(' + i + ')">编辑</button>' +
      '<button class="btn sm danger" onclick="App.delTimer(' + i + ')">删除</button></div>').join("");
    el.innerHTML =
      card("喝水助手", "喝水 / 久坐 / 护眼多循环计时提醒；游戏、全屏场景可自动降级或豁免。",
        row("启用提醒", "", switchCtl("water.enabled", w.enabled)) +
        row("提醒形态", "", selectCtl("water.reminder_mode", w.reminder_mode || "fullscreen", [["fullscreen", "全屏遮罩"], ["popup", "居中弹窗"], ["tray", "仅托盘气泡"]])) +
        row("屏幕选择", "-1 = 跟随浮窗所在屏幕", numCtl("water.screen_index", w.screen_index == null ? -1 : w.screen_index, { min: -1, max: 8 })) +
        row("提示音", "", switchCtl("water.sound", w.sound)) +
        row("每日目标杯数", "", numCtl("water.target_cups", w.target_cups || 8, { min: 1, max: 30 })) +
        row("稍后提醒 (分钟)", "", numCtl("water.snooze_minutes", w.snooze_minutes || 5, { min: 1, max: 120 })) +
        row("豁免时降级", "", selectCtl("water.exempt_behavior", w.exempt_behavior || "tray", [["tray", "托盘气泡"], ["silent", "完全静默"]])) +
        row("豁免进程", "每行一个进程名（如 notepad.exe），前台为该进程时不打扰",
          '<textarea data-bind="water.exempt_processes" data-array="line" rows="2" style="width:100%">' + esc((w.exempt_processes || []).join("\n")) + "</textarea>")) +
      card("计时器", "每个计时器可独立启停、设置间隔与提醒文案。",
        timerRows + '<div style="margin-top:10px"><button class="btn primary" onclick="App.addTimer()">＋ 添加计时器</button></div>');
    bindAll(el);
    $$("#settingsContent [data-bind^='__wtimer_en_']").forEach((s) => s.addEventListener("change", () => {
      const i = parseInt(s.dataset.bind.split("_").pop(), 10);
      if (timers[i]) timers[i].enabled = s.checked;
      refreshDirty();
    }));
  }

  function timerModal(idx) {
    const w = cfg.water || {};
    const t = idx == null ? { name: "", char: "水", color: "#00A6A6", enabled: true, interval_min: 60, messages: ["该喝水啦 💧"] } : deep(w.timers[idx]);
    const html = "<h3>" + (idx == null ? "添加计时器" : "编辑计时器") + "</h3>" +
      '<div class="f"><label>名称</label><input type="text" id="m-name" value="' + esc(t.name) + '"></div>' +
      '<div class="f-row">' +
      '<div class="f"><label>图标文字</label><input type="text" id="m-char" maxlength="1" value="' + esc(t.char || "水") + '"></div>' +
      '<div class="f"><label>颜色</label><input type="color" id="m-color" value="' + esc(t.color || "#00A6A6") + '"></div>' +
      "</div>" +
      '<div class="f"><label>间隔（分钟）</label><input type="number" id="m-interval" min="1" max="600" value="' + esc(t.interval_min || 60) + '"></div>' +
      '<div class="f"><label>提醒文案（每行一条，随机选取）</label><textarea id="m-msg" rows="4">' + esc((t.messages || []).join("\n")) + "</textarea></div>" +
      '<div class="f"><label>启用</label><label class="switch"><input type="checkbox" id="m-enabled"' + (t.enabled ? " checked" : "") + "><span class='track'></span></label></div>" +
      '<div class="modal-actions"><button class="btn" data-close>取消</button><button class="btn primary" data-save>保存</button></div>';
    openModal(html);
    $("#modalBox [data-save]").addEventListener("click", () => {
      const name = $("#m-name").value.trim();
      if (!name) { toast("名称不能为空", "err"); return; }
      const item = {
        id: t.id || "timer_" + Date.now().toString(36),
        name: name,
        char: $("#m-char").value || name[0],
        color: $("#m-color").value,
        enabled: $("#m-enabled").checked,
        interval_min: parseInt($("#m-interval").value, 10) || 60,
        messages: $("#m-msg").value.split("\n").map((s) => s.trim()).filter(Boolean),
      };
      if (idx == null) (w.timers = w.timers || []).push(item);
      else w.timers[idx] = item;
      closeModal();
      refreshDirty();
      renderWater($("#settingsContent"));
    });
    $("#modalBox [data-close]").addEventListener("click", closeModal);
  }

  // ── 关于 ──
  function renderAbout(el) {
    el.innerHTML =
      card("AgentFloat v" + version, "通用 AI Agent 桌面悬浮助手：毛玻璃浮窗一键启动任意 Agent，环绕菜单自定义、Skills 辅助窗、API 余额监控、AI 快报、喝水助手。",
        '<div class="row"><div class="lbl">当前版本</div><div class="ctl"><span class="tag blue">v' + esc(version) + "</span></div></div>" +
        '<div class="row"><div class="lbl">检查更新</div><div class="ctl"><button class="btn" onclick="App.checkUpdate()">检查更新</button></div></div>') +
      card("下载与支持",
        '<div class="row"><div class="lbl">GitHub 仓库</div><div class="ctl"><a class="btn" href="https://github.com/GinyvaXu/AgentFloat" target="_blank">打开</a></div></div>' +
        '<div class="row"><div class="lbl">Releases 下载</div><div class="ctl"><a class="btn" href="https://github.com/GinyvaXu/AgentFloat/releases" target="_blank">打开</a></div></div>' +
        '<div class="row"><div class="lbl">使用教程</div><div class="ctl"><a class="btn" href="https://github.com/GinyvaXu/AgentFloat#readme" target="_blank">打开</a></div></div>' +
        '<div class="row"><div class="lbl">个人网站</div><div class="ctl"><a class="btn" href="https://ginyva.cn" target="_blank">打开</a></div></div>') +
      card("提示", "设置保存在本地 config.json；DeepSeek Harness（dsh）通过 Web UI 模式启动（后台服务 + 自动打开浏览器）。");
  }
  // ══════════════════ API 用量页 ══════════════════
  async function loadApiPage() {
    const el = $("#apiContent");
    el.innerHTML = '<div class="card">加载中…</div>';
    try {
      const st = await API.api("/api/api_state");
      apiState.results = st.results || [];
      renderApi(el, st);
    } catch (e) {
      el.innerHTML = '<div class="card">加载失败：' + esc(e.message) + "</div>";
    }
  }
  async function loadApiState() {
    if (page !== "api") return;
    try {
      const st = await API.api("/api/api_state");
      apiState.results = st.results || [];
      renderApi($("#apiContent"), st);
    } catch (e) { /* ignore */ }
  }
  function renderApi(el, st) {
    const cfgApi = cfg.api_monitor || {};
    const eps = cfgApi.endpoints || [];
    const warnTh = num(cfgApi.low_balance_warn, 5);
    let inner = card("监控设置", "通用 JSONPath 框架，可监控任意 API 用量/余额端点；余额角标实时显示在浮窗旁。",
      row("启用监控", "", switchCtl("api_monitor.enabled", cfgApi.enabled)) +
      row("轮询间隔（秒）", "", numCtl("api_monitor.poll_interval_seconds", cfgApi.poll_interval_seconds || 60, { min: 10, max: 3600 })) +
      row("低余额警告阈值", "低于该值端点标红并触发浮窗角标变色", '<input type="number" data-bind="api_monitor.low_balance_warn" step="0.1" min="0" value="' + esc(warnTh) + '">') +
      '<div class="row"><div class="lbl">测试与保存</div><div class="ctl"><button class="btn primary" onclick="App.save()">保存设置</button></div></div>');
    let epCards = "";
    eps.forEach((ep, i) => {
      const res = apiState.results[i];
      const ok = res && !res.error;
      const fields = (res && res.fields && res.fields.length) ? res.fields : (ep.fields || []).map((f) => ({ label: f.label, value: "--", unit: f.unit || "" }));
      const fieldHtml = fields.map((f) => {
        let warn = false;
        const v = f.value;
        if (typeof v === "number" && (String(f.label).indexOf("余额") >= 0 || String(f.label).indexOf("额度") >= 0) && v < warnTh) warn = true;
        return '<div class="ep-field' + (warn ? " warn" : "") + '"><div class="k">' + esc(f.label) + "</div><div class=\"v\">" + esc(v) + esc(f.unit || "") + "</div></div>";
      }).join("");
      epCards += '<div class="ep-card">' +
        '<div class="ep-head"><span class="ep-status"><span class="dot ' + (ok ? "ok" : "err") + '"></span>' + (ok ? "正常" : "错误") + "</span>" +
        '<span class="ep-name">' + esc(ep.name || "未命名端点") + '</span><span class="tag gray">' + esc((ep.method || "GET").toUpperCase()) + "</span>" +
        '<div style="flex:1"></div>' +
        (ep.platform_url ? '<button class="btn sm" onclick="App.openPlatform(' + i + ')">打开平台</button>' : "") +
        '<button class="btn sm" onclick="App.testEndpoint(' + i + ')">' + (apiState.testing[i] ? "测试中…" : "测试") + "</button>" +
        '<button class="btn sm" onclick="App.editEndpoint(' + i + ')">编辑</button>' +
        '<button class="btn sm danger" onclick="App.delEndpoint(' + i + ')">删除</button></div>' +
        '<div class="ep-url">' + esc(ep.url || "") + "</div>" +
        '<div class="ep-fields">' + (fieldHtml || '<div class="ep-field"><div class="v">无字段</div></div>') + "</div>" +
        (res && res.error ? '<div class="ep-url" style="color:var(--warn)">' + esc(res.error) + "</div>" : "") +
        "</div>";
    });
    inner += card("监控端点", "点击「测试」即时验证；「保存设置」后浮窗后台监控会按新配置重启。",
      epCards + '<div style="margin-top:10px"><button class="btn primary" onclick="App.addEndpoint()">＋ 添加端点</button></div>');
    inner += card("模板变量说明", "URL / Headers / Body 支持模板：<code>{{env:KEY}}</code> 读取环境变量（如 <code>{{env:DEEPSEEK_API_KEY}}</code>）、<code>{{today}}</code> 今日日期、<code>{{yesterday}}</code> 昨日日期。JSONPath 示例：<code>$.balance_infos[0].total_balance</code>。");
    el.innerHTML = inner;
    bindAll(el);
  }

  function endpointModal(idx) {
    const cfgApi = cfg.api_monitor || {};
    const editing = idx != null && idx >= 0;
    const src = editing ? cfgApi.endpoints[idx] : null;
    const ep = src ? deep(src) : { name: "", url: "", method: "GET", platform_url: "", headers: { "Content-Type": "application/json" }, body: null, fields: [{ label: "剩余额度", jsonpath: "", unit: "¥", display: "number" }], progress_field: null };
    const headersTxt = Object.entries(ep.headers || {}).map((kv) => kv[0] + ": " + kv[1]).join("\n");
    const bodyTxt = ep.body ? (typeof ep.body === "string" ? ep.body : JSON.stringify(ep.body)) : "";
    const fieldRows = (ep.fields || []).map((f, fi) =>
      '<div class="mini-row"><span class="grow">' + esc(f.label || "?") + " · " + esc(f.jsonpath || "?") + "</span>" +
      '<button class="btn sm" onclick="App.editField(' + fi + ')">编辑</button>' +
      '<button class="btn sm danger" onclick="App.delField(' + fi + ')">删除</button></div>').join("");
    const html = "<h3>" + (editing ? "编辑端点" : "添加端点") + "</h3>" +
      '<div class="f"><label>名称</label><input type="text" id="m-name" value="' + esc(ep.name || "") + '"></div>' +
      '<div class="f"><label>请求 URL（支持模板）</label><input type="text" id="m-url" value="' + esc(ep.url || "") + '" placeholder="https://api.deepseek.com/user/balance"></div>' +
      '<div class="f-row">' +
      '<div class="f"><label>方法</label><select id="m-method">' + ["GET", "POST", "PUT", "PATCH"].map((m) => '<option value="' + m + '"' + ((ep.method || "GET") === m ? " selected" : "") + ">" + m + "</option>").join("") + "</select></div>" +
      '<div class="f"><label>平台网页（余额页）</label><input type="text" id="m-platform" value="' + esc(ep.platform_url || "") + '" placeholder="https://platform.deepseek.com/usage"></div>' +
      "</div>" +
      '<div class="f"><label>Headers（每行 Key: Value）</label><textarea id="m-headers" rows="3">' + esc(headersTxt) + "</textarea></div>" +
      '<div class="f"><label>Body（JSON，可选）</label><textarea id="m-body" rows="2" placeholder="{\"model\":\"deepseek-chat\"}">' + esc(bodyTxt) + "</textarea></div>" +
      '<div class="f"><label>解析字段（JSONPath）</label>' + (fieldRows || "") +
      '<div style="margin-top:6px"><button class="btn sm" onclick="App.addField()">＋ 添加字段</button></div></div>' +
      '<div class="f-row">' +
      '<div class="f"><label>进度 used（JSONPath，可选）</label><input type="text" id="m-pused" value="' + esc((ep.progress_field || {}).used || "") + '"></div>' +
      '<div class="f"><label>进度 total（JSONPath，可选）</label><input type="text" id="m-ptotal" value="' + esc((ep.progress_field || {}).total || "") + '"></div>' +
      "</div>" +
      '<div class="modal-actions"><button class="btn" data-close>取消</button><button class="btn primary" data-save>保存</button></div>';
    openModal(html);
    window._epDraft = { fields: (ep.fields || []).map((f) => deep(f)), idx: editing ? idx : null };
    $("#modalBox [data-save]").addEventListener("click", () => {
      const headers = {};
      $("#m-headers").value.split("\n").forEach((ln) => {
        const i = ln.indexOf(":");
        if (i > 0) headers[ln.slice(0, i).trim()] = ln.slice(i + 1).trim();
      });
      let bodyVal = null;
      const bodyStr = $("#m-body").value.trim();
      if (bodyStr) { try { bodyVal = JSON.parse(bodyStr); } catch (e) { bodyVal = bodyStr; } }
      const progress = {};
      if ($("#m-pused").value.trim()) progress.used = $("#m-pused").value.trim();
      if ($("#m-ptotal").value.trim()) progress.total = $("#m-ptotal").value.trim();
      const item = {
        name: $("#m-name").value.trim() || "未命名端点",
        url: $("#m-url").value.trim(),
        method: $("#m-method").value,
        platform_url: $("#m-platform").value.trim(),
        headers: headers,
        body: bodyVal,
        fields: window._epDraft.fields,
        progress_field: Object.keys(progress).length ? progress : null,
      };
      if (!item.url) { toast("URL 不能为空", "err"); return; }
      cfgApi.endpoints = cfgApi.endpoints || [];
      if (window._epDraft.idx == null) cfgApi.endpoints.push(item);
      else cfgApi.endpoints[window._epDraft.idx] = item;
      closeModal();
      refreshDirty();
      renderApi($("#apiContent"), { results: apiState.results });
    });
    $("#modalBox [data-close]").addEventListener("click", closeModal);
  }

  function fieldModal(fi) {
    const f = window._epDraft.fields[fi] || { label: "", jsonpath: "", unit: "", display: "number" };
    const html = "<h3>编辑字段</h3>" +
      '<div class="f"><label>显示名称</label><input type="text" id="f-label" value="' + esc(f.label || "") + '"></div>' +
      '<div class="f"><label>JSONPath</label><input type="text" id="f-path" value="' + esc(f.jsonpath || "") + '" placeholder="$.balance_infos[0].total_balance"></div>' +
      '<div class="f-row">' +
      '<div class="f"><label>单位</label><input type="text" id="f-unit" value="' + esc(f.unit || "") + '"></div>' +
      '<div class="f"><label>显示</label><select id="f-display">' + ["number", "text"].map((d) => '<option value="' + d + '"' + (f.display === d ? " selected" : "") + ">" + d + "</option>").join("") + "</select></div>" +
      "</div>" +
      '<div class="modal-actions"><button class="btn" data-close>取消</button><button class="btn primary" data-save>保存</button></div>';
    openModal(html);
    $("#modalBox [data-save]").addEventListener("click", () => {
      window._epDraft.fields[fi] = { label: $("#f-label").value.trim() || "字段", jsonpath: $("#f-path").value.trim(), unit: $("#f-unit").value.trim(), display: $("#f-display").value };
      closeModal();
      endpointModal(window._epDraft.idx);
    });
    $("#modalBox [data-close]").addEventListener("click", closeModal);
  }

  // ══════════════════ AI 快报页 ══════════════════
  async function loadNewsPage() {
    API.api("/api/news/read", { method: "POST" }).catch(() => {});
    const el = $("#newsContent");
    el.innerHTML = '<div class="card">加载中…</div>';
    await loadNewsState();
  }
  async function loadNewsState(date) {
    if (page !== "news") return;
    try {
      const url = "/api/news/state" + (date ? "?date=" + encodeURIComponent(date) : "");
      const st = await API.api(url);
      newsState = st;
      renderNews($("#newsContent"), st);
    } catch (e) {
      toast("快报状态加载失败：" + e.message, "err");
    }
  }
  function renderNews(el, st) {
    const n = cfg.news || {};
    const report = st.report;
    const catColor = { "模型": "#4D6BFE", "工具": "#16A085", "论文": "#8E44AD", "产品": "#E67E22", "行业": "#2E86C1", "综合": "#7F8C8D" };
    const width = st.generating ? (st.phase === "AI 摘要" ? "72%" : "38%") : "";
    let reader = '<div class="card"><h3>今日快报</h3>';
    if (st.generating) {
      reader += '<div class="desc">正在生成：' + esc(st.phase || "抓取数据源…") + "</div>" + '<div class="progress"><div style="width:' + width + '"></div></div>';
    } else if (report) {
      reader += '<div class="news-headline">' + esc(report.headline || "今日 AI 速览") + "</div>" +
        '<div class="desc">生成于 ' + esc(report.generated_at || "") + (report.used_ai ? ' · <span class="tag purple">AI 摘要</span>' : ' · <span class="tag gray">标题列表</span>') + "</div>";
      (report.items || []).forEach((it) => {
        const c = catColor[it.category] || "#7F8C8D";
        reader += '<div class="news-item"><div class="t"><a href="' + esc(it.url) + '" target="_blank">' + esc(it.title) + "</a></div>" +
          (it.summary ? '<div class="s">' + esc(it.summary) + "</div>" : "") +
          '<div class="meta"><span class="chip" style="color:#fff;background:' + c + '">' + esc(it.category || "综合") + "</span>" +
          (it.source ? '<span class="src">' + esc(it.source) + "</span>" : "") + "</div></div>";
      });
    } else {
      reader += '<div class="desc">今日尚未生成快报。</div>';
    }
    reader += "</div>";
    const hist = (st.dates && st.dates.length) ? card("历史记录", "点击日期查看历史快报。",
      '<div class="hist-chips">' + st.dates.map((d) => '<button class="hist-chip" onclick="App.viewNews(\'' + esc(d) + '\')">' + esc(d) + "</button>").join("") + "</div>") : "";
    const srcOpts = [["hackernews", "Hacker News"], ["github_trending", "GitHub 趋势"], ["sspai", "少数派"], ["qbitai", "量子位"], ["arxiv_ai", "arXiv AI"]];
    const srcChecks = srcOpts.map((o) =>
      '<label class="chip-check"><input type="checkbox" data-src="' + o[0] + '"' + ((n.sources || []).indexOf(o[0]) >= 0 ? " checked" : "") + "> " + o[1] + "</label>").join("");
    const interests = (n.interests || []);
    const intRows = interests.map((it, i) =>
      '<div class="mini-row"><span class="dot" style="background:' + esc(it.color || "#5B8DEF") + '"></span>' +
      '<span class="grow">' + esc(it.label || "") + " · 权重 " + esc(it.weight || 1) + "</span>" +
      '<button class="btn sm" onclick="App.editInterest(' + i + ')">编辑</button>' +
      '<button class="btn sm danger" onclick="App.delInterest(' + i + ')">删除</button></div>').join("");
    const agentOpts = [["", "默认主 Agent"]].concat((cfg.agents || []).map((a) => [a.id, a.name]));
    const settings = card("快报设置",
      row("启用快报", "定时 / 启动时自动生成", switchCtl("news.enabled", n.enabled)) +
      row("生成语言", "", selectCtl("news.language", n.language || "zh", [["zh", "简体中文"], ["en", "English"], ["both", "中英双语"]])) +
      row("定时策略", "", selectCtl("news.schedule_mode", n.schedule_mode || "daily_startup", [["off", "关闭"], ["daily", "每日定时"], ["startup", "启动时"], ["daily_startup", "每日 + 启动补生成"]])) +
      row("定时时间", "", '<input type="time" data-bind="news.schedule_time" value="' + esc(n.schedule_time || "09:00") + '">') +
      row("条数上限", "", numCtl("news.max_items", n.max_items || 6, { min: 3, max: 15 })) +
      row("正文字号", "应用于本页快报阅读区", numCtl("news.font_size", n.font_size || 13, { min: 11, max: 20 })) +
      row("使用本地 AI 摘要", "关闭则仅显示标题列表（零成本离线）", switchCtl("news.use_ai", n.use_ai)) +
      row("摘要 Agent", "生成 AI 摘要使用的 Agent", selectCtl("news.agent_id", n.agent_id || "", agentOpts)) +
      row("完成后托盘通知", "", switchCtl("news.notify", n.notify)) +
      row("生成后自动打开快报", "", switchCtl("news.auto_show_panel", n.auto_show_panel)));
    const srcCard = card("数据源", "勾选要聚合的数据源。", '<div class="src-grid">' + srcChecks + "</div>");
    const intCard = card("关注主题", "定向偏好：命中主题的条目按权重优先收录，不同类型可用颜色标注。",
      intRows +
      '<div style="margin-top:10px;display:flex;gap:8px">' +
      '<button class="btn primary" onclick="App.addInterest()">＋ 添加主题</button>' +
      '<button class="btn" onclick="App.addInterestPreset()">预设主题 ▾</button></div>');
    el.innerHTML =
      '<div class="card"><h3>生成</h3><div class="row"><div class="lbl">' +
      (n.last_generated ? "上次生成：" + esc(n.last_generated) : "尚未生成") + "</div>" +
      '<div class="ctl"><button class="btn primary" id="btnGen"' + (st.generating ? " disabled" : "") + ">立即生成</button></div></div>" +
      (st.generating ? '<div class="progress"><div style="width:' + width + '"></div></div>' : "") + "</div>" +
      reader + hist + settings + srcCard + intCard;
    bindAll(el);
    const btnGen = $("#btnGen");
    if (btnGen) btnGen.addEventListener("click", async () => {
      btnGen.disabled = true;
      newsState.generating = true;
      renderNews(el, newsState);
      try { await API.api("/api/news/generate", { method: "POST" }); toast("已开始生成快报…", "ok"); }
      catch (e) { newsState.generating = false; toast("启动生成失败：" + e.message, "err"); renderNews(el, newsState); }
    });
    $$("#newsContent [data-src]").forEach((cb) => cb.addEventListener("change", () => {
      cfg.news.sources = $$("#newsContent [data-src]:checked").map((c) => c.dataset.src);
      refreshDirty();
    }));
  }

  function interestModal(idx) {
    const n = cfg.news || {};
    const it = idx == null ? { label: "", weight: 3, color: "#5B8DEF" } : deep(n.interests[idx]);
    const html = "<h3>" + (idx == null ? "添加关注主题" : "编辑关注主题") + "</h3>" +
      '<div class="f"><label>主题 / 关键词（逗号分隔）</label><input type="text" id="m-label" value="' + esc(it.label || "") + '" placeholder="新模型发布, GPT, DeepSeek"></div>' +
      '<div class="f-row">' +
      '<div class="f"><label>权重（1-5）</label><input type="number" id="m-weight" min="1" max="5" value="' + esc(it.weight || 3) + '"></div>' +
      '<div class="f"><label>标注颜色</label><input type="color" id="m-color" value="' + esc(it.color || "#5B8DEF") + '"></div>' +
      "</div>" +
      '<div class="modal-actions"><button class="btn" data-close>取消</button><button class="btn primary" data-save>保存</button></div>';
    openModal(html);
    $("#modalBox [data-save]").addEventListener("click", () => {
      const label = $("#m-label").value.trim();
      if (!label) { toast("主题不能为空", "err"); return; }
      const item = { label: label, weight: parseInt($("#m-weight").value, 10) || 3, color: $("#m-color").value };
      if (idx == null) (n.interests = n.interests || []).push(item);
      else n.interests[idx] = item;
      closeModal();
      refreshDirty();
      loadNewsState();
    });
    $("#modalBox [data-close]").addEventListener("click", closeModal);
  }

  // ── 模态框 / SSE / 启动 ─────────────────────────
  function openModal(html) {
    $("#modalBox").innerHTML = html;
    $("#modalMask").classList.remove("hidden");
  }
  function closeModal() {
    $("#modalMask").classList.add("hidden");
  }
  function wireEvents() {
    API.streamEvents((ev) => {
      if (ev.event === "news_started") { newsState.generating = true; newsState.phase = "抓取数据源…"; if (page === "news") loadNewsState(); }
      else if (ev.event === "news_done") {
        newsState.generating = false;
        toast("AI 快报已生成（" + (ev.payload.count || 0) + " 条）", "ok");
        if (cfg.news && cfg.news.auto_show_panel && page !== "news") goPage("news");
        if (page === "news") loadNewsState();
      }
      else if (ev.event === "news_failed") { newsState.generating = false; toast("快报生成失败：" + (ev.payload.error || ""), "err"); if (page === "news") loadNewsState(); }
      else if (ev.event === "api_updated") { if (page === "api") loadApiState(); }
      else if (ev.event === "theme_changed") { if (cfg) { cfg.theme = ev.payload.theme || cfg.theme; applyTheme(); refreshDirty(); } }
      else if (ev.event === "ai_service_done") toast("AI 自检完成：" + (ev.payload.summary || ""), "ok");
      else if (ev.event === "ai_service_failed") toast("AI 自检失败：" + (ev.payload.error || ""), "err");
      else if (ev.event === "auto_translate_done") toast("自动翻译：" + (ev.payload.message || ""), "ok");
      else if (ev.event === "auto_translate_failed") toast("自动翻译失败：" + (ev.payload.error || ""), "err");
    });
  }

  async function init() {
    $$("#nav .nav-item").forEach((a) => a.addEventListener("click", () => goPage(a.dataset.page)));
    $$("#settingsSubnav .sub").forEach((b) => b.addEventListener("click", () => goSub(b.dataset.sub)));
    $("#btnSave").addEventListener("click", save);
    $("#btnTheme").addEventListener("click", () => {
      cfg.theme = cfg.theme === "dark" ? "light" : "dark";
      applyTheme();
      schedulePreview();
      refreshDirty();
      renderPage();
    });
    $("#modalMask").addEventListener("click", (e) => { if (e.target.id === "modalMask") closeModal(); });
    window.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModal(); });

    wireEvents();
    const [cfgResp, stateResp] = await Promise.all([API.api("/api/config"), API.api("/api/state")]);
    cfg = cfgResp.config;
    baseStr = JSON.stringify(cfg);
    version = stateResp.version || "";
    $("#verText").textContent = "v" + version;
    applyTheme();
    refreshDirty();
    const h = (location.hash || "").replace(/^#\/?/, "");
    if (["api", "news", "settings"].indexOf(h) >= 0) goPage(h);
    else goPage("settings");
  }

  window.App = {
    save: save, goPage: goPage, goSub: goSub,
    rangeLabel: (el, id) => { const t = $("#" + id); if (t) t.textContent = el.value + (id === "opLabel" ? "%" : "px"); },
    resetDir: () => { cfg.working_directory = ""; refreshDirty(); renderPage(); },
    setPrimary: (i) => { (cfg.agents || []).forEach((a, j) => { a.primary = (i === j); }); refreshDirty(); renderAgents($("#settingsContent")); },
    addAgent: () => agentModal(null),
    editAgent: (i) => agentModal(i),
    delAgent: (i) => { if (confirm("确定删除 Agent「" + cfg.agents[i].name + "」？")) { cfg.agents.splice(i, 1); refreshDirty(); renderAgents($("#settingsContent")); } },
    openDsh: () => API.api("/api/open_url", { method: "POST", body: { url: "http://127.0.0.1:3080" } }).catch(() => toast("请先启动 DeepSeek Harness", "err")),
    runAiServices: () => API.api("/api/run_ai_services", { method: "POST", body: { auto: false } }).then(() => toast("已发起本地 AI 自检服务", "ok")).catch((e) => toast("启动失败：" + e.message, "err")),
    checkUpdate: () => API.api("/api/check_update", { method: "POST" }).then(() => toast("已发起检查更新", "ok")).catch((e) => toast("检查失败：" + e.message, "err")),
    addTimer: () => timerModal(null),
    editTimer: (i) => timerModal(i),
    delTimer: (i) => { if (confirm("确定删除计时器？")) { cfg.water.timers.splice(i, 1); refreshDirty(); renderWater($("#settingsContent")); } },
    addEndpoint: () => endpointModal(null),
    editEndpoint: (i) => endpointModal(i),
    delEndpoint: (i) => { if (confirm("确定删除端点？")) { cfg.api_monitor.endpoints.splice(i, 1); refreshDirty(); renderApi($("#apiContent"), { results: apiState.results }); } },
    testEndpoint: async (i) => {
      const ep = cfg.api_monitor.endpoints[i];
      apiState.testing[i] = true;
      renderApi($("#apiContent"), { results: apiState.results });
      try {
        const r = await API.api("/api/api_monitor/test", { method: "POST", body: { endpoint: ep } });
        if (r.ok) toast("测试成功：" + (r.result.fields || []).map((f) => f.label + "=" + f.value).join("，"), "ok");
        else toast("测试失败：" + (r.result && r.result.error ? r.result.error : "未知错误"), "err");
      } catch (e) { toast("测试请求失败：" + e.message, "err"); }
      apiState.testing[i] = false;
      renderApi($("#apiContent"), { results: apiState.results });
    },
    openPlatform: (i) => {
      const ep = cfg.api_monitor.endpoints[i];
      const url = ep.platform_url || ep.url;
      if (url) API.api("/api/open_url", { method: "POST", body: { url: url } }).catch((e) => toast(e.message, "err"));
    },
    addField: () => { window._epDraft.fields.push({ label: "", jsonpath: "", unit: "", display: "number" }); fieldModal(window._epDraft.fields.length - 1); },
    editField: (i) => fieldModal(i),
    delField: (i) => { window._epDraft.fields.splice(i, 1); endpointModal(window._epDraft.idx); },
    addInterest: () => interestModal(null),
    editInterest: (i) => interestModal(i),
    delInterest: (i) => { if (confirm("删除该关注主题？")) { cfg.news.interests.splice(i, 1); refreshDirty(); loadNewsState(); } },
    addInterestPreset: () => {
      const presets = [
        { label: "价格调整, 降价, 涨价, pricing", weight: 3, color: "#E67E22" },
        { label: "新模型发布, GPT, Claude, Gemini, DeepSeek", weight: 4, color: "#4D6BFE" },
        { label: "优秀 skills 推荐, skills, 工具", weight: 3, color: "#8E44AD" },
        { label: "产品发布, 开源, release", weight: 2, color: "#16A085" },
        { label: "论文, arxiv, 研究, benchmark", weight: 2, color: "#7F8C8D" },
      ];
      (cfg.news.interests = cfg.news.interests || []).push.apply(cfg.news.interests, presets);
      refreshDirty();
      loadNewsState();
      toast("已添加 5 个预设主题", "ok");
    },
    viewNews: (d) => loadNewsState(d),
    renderPage: () => { if (page === "settings") renderSettings(); else if (page === "api") loadApiPage(); else loadNewsPage(); },
  };

  document.addEventListener("DOMContentLoaded", init);
})();