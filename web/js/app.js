/**
 * app.js — AgentFloat Web 控制台（设置 / API 用量 / AI 快报）
 * 数据流：配置以 JSON 形式在浏览器内编辑 → PUT /api/config 持久化并应用到浮窗。
 * P3：拆分 ES Module —— 工具函数在 util.js，Agent 安装页在 install.js。
 */
import { $, $$, esc, getPath, setPath, num, deep, toast } from "./util.js";
import {
  renderInstallPage, leaveInstallPage, refreshInstall,
  installAgent, uninstallAgent, toggleInstallLog,
} from "./install.js";

(function () {
  "use strict";

  // ── 状态 ────────────────────────────────────────
  let cfg = null;
  let baseStr = "";
  let page = "settings";
  let sub = "general";
  let version = "";
  let apiState = { results: [], testing: {}, error: "", presets: null, rowPresets: null, badgePreview: [], fetchedAt: null };
  let newsState = { report: null, dates: [], generating: false, phase: "" };

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
  function bindAll(root) {
    $$("[data-bind]", root).forEach((el) => {
      // PATCH 3.2.1：__ 前缀是虚拟控件（主 Agent / 扇区 / 扇区数量 / 计时器开关），
      // 不是配置路径；此前会被 getPath(undefined) 刷成空值 →「扇区数量等无法设置」
      if (!el.dataset.bind.startsWith("__")) bindWrite(el);
    });
  }

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
    intro: "启动动画", process_panel: "进程面板",
  };
  const labelOf = (k) => KEY_LABEL[k] || k;

  // ── 保存 ────────────────────────────────────────
  async function save() {
    try {
      // PATCH 3.1.1：虚拟绑定（__slot_* / __primary / __wtimer_en_*）不写入配置，避免垃圾键；
      // 普通开关/输入统一由委托监听置脏
      $$("[data-bind]").forEach((el) => {
        if (!el.dataset.bind.startsWith("__")) bindRead(el);
      });
      const changed = diffKeys(cfg, JSON.parse(baseStr));
      const put = await API.api("/api/config", { method: "PUT", body: { config: cfg, changed_keys: changed } });
      // PATCH 3.1.1：PUT 返回「同步应用后」的完整配置（后端等待 Qt 线程 apply 完成），
      // 避免异步 apply 间隙回读把刚改的开关打回
      if (put && put.config) cfg = put.config;
      else { const resp = await API.api("/api/config"); cfg = resp.config; }
      baseStr = JSON.stringify(cfg);
      applyTheme();
      refreshDirty();
      toast("已保存：" + (changed.length ? changed.map(labelOf).join("、") : "无变化"), "ok");
      renderPage();
    } catch (e) {
      toast("保存失败：" + e.message, "err");
    }
  }

  // PATCH 3.1.1：补回本地 renderPage（此前只挂在 window.App 上，save 收尾调用时报
  //「renderPage is not defined」→ 明明保存成功却提示失败）
  function renderPage() {
    if (page === "settings") renderSettings();
    else if (page === "install") renderInstallPage();
    else if (page === "api") loadApiPage();
    else loadNewsPage();
  }

  // ── 页面导航 ────────────────────────────────────
  function goPage(p) {
    page = p;
    if (p !== "install") leaveInstallPage();
    $$("#nav .nav-item").forEach((a) => a.classList.toggle("active", a.dataset.page === p));
    ["guide", "settings", "install", "api", "news"].forEach((id) => $("#page-" + id).classList.toggle("hidden", id !== p));
    $("#pageTitle").textContent = { guide: "使用指南", settings: "设置", install: "Agent 安装", api: "API 用量", news: "AI 快报" }[p];
    if (p === "guide") renderGuide();
    else if (p === "settings") renderSettings();
    else if (p === "install") renderInstallPage();
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
    if (!el) return;
    if (!cfg) return;      // v3.6.0：配置尚未加载完成时（过早点击子页）直接跳过，避免空引用
    const agents = cfg.agents || [];
    const primary = agents.find((a) => a.primary) || agents[0] || {};

    // v3.9.0：新用户提示卡（未看过引导时显示；点「我已熟悉」写入 onboarding_done）
    let _guideBanner = "";
    if (!cfg.onboarding_done) {
      _guideBanner = '<div class="card guide-hero"><h3>新用户？先看这里</h3>' +
        '<div class="desc">花 3 分钟看完「使用指南」：浮球操作、Agent 启动、密钥保险箱、余额监控与自动更新一次讲清。</div>' +
        '<div style="margin-top:12px;display:flex;gap:8px;flex-wrap:wrap">' +
        '<button class="btn primary" id="btnGoGuide">打开使用指南</button>' +
        '<button class="btn" id="btnSkipOnboard">我已熟悉，不再提示</button></div></div>';
    }    if (sub === "general") {
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
      inner += card("启动动画", "每次启动在屏幕中心播放：光晕 + 扩散圆环 + 放大浮球 → 缩小飞向落点（不可跳过）。",
        row("播放启动动画", "", switchCtl("intro.enabled", (cfg.intro || {}).enabled !== false)) +
        row("启动音效", "代码合成的「叮—咚」双音提示音", switchCtl("intro.sound", (cfg.intro || {}).sound !== false)) +
        row("音效音量", "", rangeCtl("intro.volume", (cfg.intro || {}).volume != null ? cfg.intro.volume : 0.6, 0, 1, 0.05, "ivLabel") +
          '<span id="ivLabel" class="val-tag">' + Math.round(((cfg.intro || {}).volume != null ? cfg.intro.volume : 0.6) * 100) + "%</span>") +
        row("问候语", "留空则每次启动随机一句", '<input type="text" data-bind="intro.greeting" value="' + esc((cfg.intro || {}).greeting || "") + '" placeholder="（随机问候）" style="width:170px">'));
      inner += card("行为",
        row("屏幕边缘吸附", "靠近边缘自动吸附并隐藏", switchCtl("snap_enabled", cfg.snap_enabled)) +
        row("吸附后自动隐藏", "吸附后鼠标移开即隐藏，悬停弹出", switchCtl("snap_hidden", cfg.snap_hidden)) +
        row("隐藏延迟 (ms)", "", numCtl("hide_delay_ms", cfg.hide_delay_ms, { min: 200, max: 3000 })) +
        row("退出时清理 Agent 进程", "退出 AgentFloat 时结束主 Agent 进程", switchCtl("cleanup_on_quit", cfg.cleanup_on_quit)) +
        row("开机自启", "登录 Windows 后自动运行", switchCtl("auto_start", cfg.auto_start)) +
        row("启动时检查更新", "", switchCtl("check_updates", cfg.check_updates)) +
        row("Agent 进程面板", "悬停浮球显示在线 Agent 进程与操作（中断 / 继续任务）",
          switchCtl("process_panel.enabled", (cfg.process_panel || {}).enabled !== false)) +
        row("面板悬停延迟 (ms)", "", numCtl("process_panel.hover_delay_ms",
          (cfg.process_panel || {}).hover_delay_ms || 250, { min: 100, max: 1000 })) +
        row("面板大小", "也可在面板上滚动滚轮调整（Ctrl+滚轮调不透明度）",
          rangeCtl("process_panel.scale", (cfg.process_panel || {}).scale != null ? cfg.process_panel.scale : 1, 0.8, 1.8, 0.05, "psLabel") +
          '<span id="psLabel" class="val-tag">' + num((cfg.process_panel || {}).scale != null ? cfg.process_panel.scale : 1, 1).toFixed(2) + "×</span>") +
        row("面板不透明度", "只影响面板背景，文字保持清晰",
          rangeCtl("process_panel.opacity", (cfg.process_panel || {}).opacity != null ? cfg.process_panel.opacity : 1, 0.35, 1, 0.05, "ppLabel") +
          '<span id="ppLabel" class="val-tag">' + Math.round(((cfg.process_panel || {}).opacity != null ? cfg.process_panel.opacity : 1) * 100) + "%</span>"));
      el.innerHTML = _guideBanner + inner;
      bindAll(el);
      $$("#settingsContent [name='launch_mode']").forEach((r) => r.addEventListener("change", () => {
        cfg.launch_mode = $("input[name='launch_mode']:checked").value;
        refreshDirty();
      }));
      $$("#settingsContent [data-bind='theme']").forEach((r) => r.addEventListener("change", () => { bindRead(r); refreshDirty(); }));
      const sel = $("#settingsContent [data-bind='__primary']");
      if (sel) sel.addEventListener("change", () => {
        agents.forEach((a) => { a.primary = (a.id === sel.value); });
        refreshDirty();
      });
    } else if (sub === "agents") renderAgents(el);
    else if (sub === "radial") renderRadial(el);
    else if (sub === "skills") renderSkills(el);
    else if (sub === "water") renderWater(el);
    else if (sub === "vault") { renderVault(el); loadVault(); }
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
      if ((a.launcher || "terminal") === "app") badges.push('<span class="tag purple">桌面应用</span>');
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
      '<div class="f"><label>启动器</label><select id="m-launcher">' +
        '<option value="terminal"' + ((a.launcher || "terminal") === "terminal" ? " selected" : "") + ">终端（wt）</option>" +
        '<option value="web"' + (a.launcher === "web" ? " selected" : "") + ">Web UI（自动开浏览器）</option>" +
        '<option value="app"' + (a.launcher === "app" ? " selected" : "") + ">桌面应用（无终端窗口）</option>" +
        "</select></div>" +
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
    [["skills", "Skills 辅助窗"], ["api", "API 用量"], ["settings", "设置"], ["news", "AI 快报"], ["clip", "剪贴板历史"], ["cmd", "命令面板"], ["water", "喝水助手"], ["move", "移动浮窗"], ["quit", "退出"]].forEach((o) => slotOpts.push(o));
    const slots = Array.isArray(rm.slots) ? rm.slots : [];
    const slotRows = Array.from({ length: rm.slot_count || 6 }, (_, i) =>
      row("扇区 " + (i + 1), "", selectCtl("__slot_" + i, slots[i] || "", slotOpts))).join("");
    el.innerHTML =
      card("环绕菜单", "鼠标悬停 / 长按浮窗唤出环绕菜单；扇区功能可自由映射，未来扩展功能在此预留。",
        row("启用环绕菜单", "", switchCtl("radial_menu.enabled", rm.enabled)) +
        row("唤出方式", "悬停唤出已取消；按住立即外滑 = 轮盘（松手执行）；按住不动 = 启动进度", '<span class="hint">按住外滑 · 按住启动</span>') +
        row("按住选环", "轮盘弹出后滑到目标扇区松开即执行（PATCH 3.2.0）", switchCtl("radial_menu.hold_select", rm.hold_select !== false)) +
        row("按住外滑唤出轮盘", "按住后立即向外滑 = 游戏式轮盘；轮盘里可选「移动浮窗」（PATCH 3.3.0/3.3.1）", switchCtl("radial_menu.wheel_enabled", rm.wheel_enabled !== false)) +
        row("按住启动 (ms)", "按住不动完成该时长 → 启动主 Agent（环形进度条，PATCH 3.3.0）", numCtl("radial_menu.hold_launch_ms", rm.hold_launch_ms || 2000, { min: 500, max: 5000 })) +
        row("半径 (px)", "", numCtl("radial_menu.radius", rm.radius || 120, { min: 80, max: 260 })) +
        row("扇区数量", "", selectCtl("__slot_count", rm.slot_count || 6, [[4, "4 扇区"], [6, "6 扇区"], [8, "8 扇区"]], true))) +
      card("扇区功能映射", "每个扇区可映射为启动某 Agent 或打开某面板；「自动」表示按默认布局（所有 Agent + 固定 4 项）自动填充。", slotRows);
    bindAll(el);
    $$("#settingsContent [data-bind^='__slot_']").forEach((s) => s.addEventListener("change", () => {
      if (s.dataset.bind === "__slot_count") return;   // 由专用处理器负责
      const i = parseInt(s.dataset.bind.split("_").pop(), 10);   // PATCH 3.2.1：修复 NaN 下标（槽位映射此前从未保存）
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
      '<label class="switch"><input type="checkbox" data-bind="water.timers.' + i + '.enabled" ' + (t.enabled ? "checked" : "") + "><span class='track'></span></label>" +
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
  // ══════════════════ 账户与密钥（v3.6.0）══════════════
  let vaultState = { accounts: [], unlocked: false, active: "", has_quick: false, crypto: true,
                     keys: [], importB64: null, importPreview: null };

  function vaultNameValue() {
    const sel = $("select[data-bind='__vault_name']");
    if (sel) return sel.value;
    const inp = $("#vaultName");
    return inp ? inp.value.trim() : "";
  }

  function readFileB64(file) {
    return new Promise((resolve, reject) => {
      const fr = new FileReader();
      fr.onload = () => {
        const s = String(fr.result || "");
        const i = s.indexOf(",");
        resolve(i >= 0 ? s.slice(i + 1) : s);
      };
      fr.onerror = () => reject(new Error("文件读取失败"));
      fr.readAsDataURL(file);
    });
  }

  async function loadVault() {
    try {
      const st = await API.api("/api/vault_state");
      vaultState = Object.assign(vaultState, st);
      vaultState.keys = st.unlocked ? ((await API.api("/api/vault/keys")).keys || []) : [];
    } catch (e) { toast("账户状态读取失败：" + e.message, "err"); }
    if (page === "settings" && sub === "vault") renderVault($("#settingsContent"));
  }

  const VAULT_QUICK_KEYS = ["OPENCODE_GO_API_KEY", "DEEPSEEK_API_KEY", "MOONSHOT_API_KEY",
    "SILICONFLOW_API_KEY", "OPENROUTER_API_KEY"];

  function vaultAccountCard(v) {
    const accounts = v.accounts || [];
    if (v.unlocked) {
      return card("密钥保险箱", "已解锁：启动 Agent 时自动把这些密钥注入为环境变量；密钥在本机以 AES-256-GCM 加密保存。",
        row("当前账户", "", "<b>" + esc(v.active || "") + '</b><button class="btn sm" style="margin-left:10px" onclick="App.vaultLogout()">登出</button>') +
        row("密钥数量", "", esc((v.keys || []).length) + " 个 · 修改后自动重新加密保存") +
        (accounts.length > 1 ? row("切换账户", "各账户密钥独立加密；切换后需用该账户口令登录",
          accounts.filter((a) => !a.active).map((a) =>
            '<button class="btn sm" style="margin-right:6px" onclick="App.vaultSwitch(\'' + esc(a.id) + '\')">' + esc(a.name) + "</button>").join("")) : "") +
        row("修改口令", "将重新加密保险箱并清除本机快速登录", '<button class="btn sm" onclick="App.vaultChangePw()">修改口令</button>'));
    }
    const options = accounts.map((a) => [a.name, a.name + (a.has_keys ? "（含密钥）" : "")]);
    return card("密钥保险箱", "本地多账户：口令加密保存 API Key；登录后启动 Agent 会自动注入为环境变量。",
      row("账户", "", accounts.length ? selectCtl("__vault_name", v.active || (accounts[0] || {}).name, options)
        : '<input id="vaultName" type="text" placeholder="账户名（如 zhenl）" style="width:180px">') +
      row("口令", "至少 6 位；输入后按回车即可提交", '<input id="vaultPw" type="password" placeholder="口令" style="width:180px">') +
      row("快速登录", "本机免口令解锁（DPAPI 绑定当前 Windows 用户，可随时禁用）",
        '<label class="tag-row"><input type="checkbox" id="vaultQuick" checked> 在此设备记住</label>') +
      row("", "", (accounts.length ? '<button class="btn" onclick="App.vaultLogin()">登录</button>' : "") +
        '<button class="btn primary" style="margin-left:8px" onclick="App.vaultCreate()">新建账户</button>' +
        (v.has_quick ? '<button class="btn" style="margin-left:8px" onclick="App.vaultQuickLogin()">快速登录</button>' : "")));
  }

  function vaultKeysCard(v) {
    if (!v.unlocked) return "";
    const rowsHtml = (v.keys || []).map((k) => '<div class="mini-row">' +
      '<span class="grow"><b>' + esc(k.name) + "</b>" +
      (k.note ? ' <span style="color:var(--hint)">' + esc(k.note) + "</span>" : "") +
      '<br><span style="font-family:monospace;font-size:11px;color:var(--text2)">' + esc(k.value) + "</span></span>" +
      '<button class="btn sm" onclick="App.keyCopy(\'' + esc(k.name) + '\')">复制</button>' +
      '<button class="btn sm" onclick="App.keyReveal(\'' + esc(k.name) + '\')">显示</button>' +
      '<button class="btn sm" onclick="App.keyEdit(\'' + esc(k.name) + '\')">编辑</button>' +
      '<button class="btn sm danger" onclick="App.keyDelete(\'' + esc(k.name) + '\')">删除</button></div>').join("");
    return card("API Key 管理", "密钥名即环境变量名（如 OPENCODE_GO_API_KEY）；界面默认掩码，可「复制」或「显示」。",
      (rowsHtml || '<div class="ep-empty">暂无保存的密钥：点下方按钮添加，或直接从常用名称开始</div>') +
      '<div class="ep-add"><button class="btn primary" onclick="App.keyEdit(null)">＋ 添加密钥</button>' +
      VAULT_QUICK_KEYS.map((n) => '<button class="btn sm" onclick="App.keyEdit(\'' + n + '\')">＋ ' + n + "</button>").join("") + "</div>");
  }

  function vaultTransferCard(v) {
    return card("配置导出 / 导入", "导出为单个 .afpack 文件（口令保护，AES-256-GCM）；在新设备输入同一口令即可导入。",
      row("导出密码", "至少 6 位；新设备导入时需输入", '<input id="expPw" type="password" style="width:130px" placeholder="密码">' +
        '<input id="expPw2" type="password" style="width:130px;margin-left:6px" placeholder="确认密码">') +
      row("包含 API Key", v.unlocked ? "密钥将一起加密写入文件" : "未登录：仅导出配置（登录后可含密钥）",
        '<label class="tag-row"><input type="checkbox" id="expKeys"' + (v.unlocked ? " checked" : " disabled") + "> 包含密钥</label>") +
      row("导出", "默认保存到桌面（文件名带日期时间）", '<button class="btn primary" onclick="App.exportBundle()">导出 .afpack</button>') +
      row("导入文件", "选择 .afpack 后输入密码 → 预览 → 确认导入",
        '<input type="file" id="impFile" accept=".afpack,.bin" style="max-width:210px">') +
      row("导入密码", "", '<input id="impPw" type="password" style="width:130px" placeholder="密码">' +
        '<button class="btn" style="margin-left:6px" onclick="App.importPreview()">预览</button>') +
      (v.importPreview ? row("导入预览", "确认后将合并配置（保留本机窗口位置）并写入密钥（同名覆盖）",
        '<span style="font-size:12px">账户 ' + esc(v.importPreview.account || "-") +
          " · v" + esc(v.importPreview.app_version || "?") +
          " · Agent " + esc(v.importPreview.agents) +
          " · 端点 " + esc(v.importPreview.endpoints) +
          " · 密钥 " + ((v.importPreview.keys || []).length) + " 个</span>" +
        '<button class="btn primary" style="margin-left:10px" onclick="App.importApply()">确认导入</button>') : ""));
  }

  function renderVault(el) {
    const v = vaultState;
    if (!v.crypto) {
      el.innerHTML = card("密钥保险箱", "当前构建缺少 cryptography 组件，账户与密钥功能不可用。");
      bindAll(el);
      return;
    }
    el.innerHTML = vaultAccountCard(v) + vaultKeysCard(v) + vaultTransferCard(v);
    bindAll(el);
    // 交互：账户名/口令输入后按回车直接提交
    const submit = (e) => {
      if (e.key !== "Enter") return;
      e.preventDefault();
      if ((v.accounts || []).length) App.vaultLogin();
      else App.vaultCreate();
    };
    ["vaultName", "vaultPw"].forEach((id) => {
      const node = $("#" + id);
      if (node) node.addEventListener("keydown", submit);
    });
  }

  // ══════════════════ API 用量页 ══════════════════
  async function loadApiPage() {
    const el = $("#apiContent");
    el.innerHTML = '<div class="card">加载中…</div>';
    try {
      await loadApiPresets();
      const st = await API.api("/api/api_state");
      apiState.results = st.results || [];
      apiState.badgePreview = st.badge_preview || [];
      apiState.fetchedAt = new Date();
      renderApi(el, st);
    } catch (e) {
      el.innerHTML = '<div class="card">加载失败：' + esc(e.message) + "</div>";
    }
  }
  async function loadApiPresets(force) {
    if (apiState.presets && !force) return;
    try {
      const r = await API.api("/api/api_monitor/presets");
      apiState.presets = r.presets || [];
      apiState.rowPresets = r.row_presets || [];
    } catch (e) { /* ignore */ }
  }
  async function loadApiState() {
    if (page !== "api") return;
    try {
      await loadApiPresets();
      const st = await API.api("/api/api_state");
      apiState.results = st.results || [];
      apiState.badgePreview = st.badge_preview || [];
      apiState.fetchedAt = new Date();
      renderApi($("#apiContent"), st);
    } catch (e) { /* ignore */ }
  }
  // 局部重绘（本地编辑后不重新请求，使用缓存预览）
  function renderApiCached() {
    if (page !== "api") return;
    renderApi($("#apiContent"), { results: apiState.results, badge_preview: apiState.badgePreview });
  }
  // ══════════════════ API 用量页 ══════════════════
  const EP_BADGE_LABEL = { balance: "角标 · 余额", remaining: "角标 · 剩余%", used: "角标 · 已用%" };

  function epErrorHint(err) {
    const s = String(err || "");
    if (s.indexOf("401") >= 0 || s.indexOf("403") >= 0) return "鉴权失败：检查环境变量或 Headers 中的 Key 是否正确";
    if (s.indexOf("404") >= 0) return "地址不存在：检查请求 URL";
    if (s.indexOf("closed") >= 0 || s.indexOf("超时") >= 0 || s.indexOf("timed out") >= 0) return "网络异常：检查网络 / 代理";
    if (s.indexOf("JSON") >= 0) return "响应不是 JSON：检查 URL 是否指向接口";
    return "";
  }

  function renderApi(el, st) {
    const cfgApi = cfg.api_monitor || {};
    const eps = cfgApi.endpoints || [];
    const warnTh = num(cfgApi.low_balance_warn, 5);
    const results = (st && st.results) || apiState.results || [];
    const byName = {};
    results.forEach((r) => {
      const n = r && (r.name || r.endpoint_name);
      if (n && byName[n] === undefined) byName[n] = r;
    });
    // 结果按「端点名称」对齐（修复增删端点后按下标错位显示的问题）
    const resOf = (ep, i) => {
      const n = String(ep.name || "");
      if (n && byName[n] !== undefined) return byName[n];
      return results[i];
    };
    const pendingCount = eps.filter((ep, i) => !resOf(ep, i)).length;
    const errCount = eps.filter((ep, i) => { const r = resOf(ep, i); return r && r.error; }).length;
    const okCount = eps.length - pendingCount - errCount;
    const updated = apiState.fetchedAt ? "更新于 " + apiState.fetchedAt.toLocaleTimeString() : "尚未拉取";

    let inner =
      '<div class="api-hero">' +
        '<span class="dot ' + (cfgApi.enabled ? "ok" : "wait") + '"></span>' +
        '<div><div class="ah-title">' + (cfgApi.enabled ? "监控已开启" : "监控已关闭") + "</div>" +
        '<div class="ah-sub">共 ' + eps.length + " 个端点" +
          (okCount ? " · 正常 " + okCount : "") +
          (errCount ? " · 异常 " + errCount : "") +
          (pendingCount ? " · 等待 " + pendingCount : "") +
          " · 轮询 " + num(cfgApi.poll_interval_seconds, 60) + "s · " + esc(updated) + "</div></div>" +
        '<div class="ah-right">' + switchCtl("api_monitor.enabled", cfgApi.enabled) +
          '<button class="btn" onclick="App.refreshApi()">立即拉取</button>' +
          '<button class="btn primary" onclick="App.save()">保存设置</button></div>' +
      "</div>" +
      '<div class="ah-note">流程：添加端点 → 保存 → 立即拉取；余额显示框与端点卡片会即刻更新。显示框内容在下方「余额显示框」中自定义。</div>';

    // ── 端点卡片 ──
    const urls = {};
    let dupeCount = 0;
    let placeholderCount = 0;
    eps.forEach((e) => {
      const u = String(e.url || "").trim();
      if (u.indexOf("api.example.com") >= 0) placeholderCount++;
      if (u) { if (urls[u]) dupeCount++; urls[u] = true; }
    });
    let warnBar = "";
    if (dupeCount || placeholderCount) {
      const parts = [];
      if (placeholderCount) parts.push(placeholderCount + " 个示例占位端点（api.example.com）");
      if (dupeCount) parts.push(dupeCount + " 个重复端点（相同 URL）");
      warnBar = '<div class="ep-warn"><span>⚠ 检测到 ' + parts.join("、") +
        "，建议先整理（整理后记得保存）。</span>" +
        '<button class="btn sm" onclick="App.cleanupEndpoints()">一键整理</button></div>';
    }
    const cards = eps.map((ep, i) => {
      const res = resOf(ep, i);
      const pending = !res;
      const ok = !!(res && !res.error);
      const hasErr = !!(res && res.error);
      const fields = (!hasErr && res && res.fields && res.fields.length)
        ? res.fields
        : (ep.fields || []).map((f) => ({ label: f.label, value: "--", unit: f.unit || "" }));
      const fieldHtml = fields.map((f) => {
        let warn = false;
        const v = f.value;
        if (typeof v === "number" && /余额|额度/.test(String(f.label)) && v < warnTh) warn = true;
        return '<div class="ep-field' + (warn ? " warn" : "") + '"><div class="k">' + esc(f.label) +
          '</div><div class="v">' + esc(v) + esc(f.unit || "") + "</div></div>";
      }).join("");
      const tags = (ep.preset ? '<span class="tag gray">预设</span>' : "") +
        (ep.badge_mode ? '<span class="tag blue">' + esc(EP_BADGE_LABEL[ep.badge_mode] || ("角标 · " + ep.badge_mode)) + "</span>" : "");
      const errBlock = res && res.error
        ? '<div class="ep-error">✗ ' + esc(res.error) +
          (epErrorHint(res.error) ? '<div class="ep-error-hint">' + esc(epErrorHint(res.error)) + "</div>" : "") + "</div>"
        : "";
      return '<div class="ep-card">' +
        '<div class="ep-head">' +
          '<span class="ep-status"><span class="dot ' + (pending ? "wait" : (ok ? "ok" : "err")) + '"></span>' +
            (pending ? "等待首次拉取" : (ok ? "正常" : "异常")) + "</span>" +
          '<span class="ep-name">' + esc(ep.name || "未命名端点") + "</span>" + tags +
          '<span class="tag gray">' + esc(String(ep.method || "GET").toUpperCase()) + "</span>" +
          '<div style="flex:1"></div>' +
          (ep.platform_url ? '<button class="btn sm" onclick="App.openPlatform(' + i + ')">平台</button>' : "") +
          '<button class="btn sm" onclick="App.testEndpoint(' + i + ')">' + (apiState.testing[i] ? "测试中…" : "测试") + "</button>" +
          '<button class="btn sm" onclick="App.editEndpoint(' + i + ')">编辑</button>' +
          '<button class="btn sm" onclick="App.duplicateEndpoint(' + i + ')">复制</button>' +
          '<button class="btn sm danger" onclick="App.delEndpoint(' + i + ')">删除</button>' +
        "</div>" +
        '<div class="ep-url">#' + (i + 1) + " " + esc(ep.url || "") + "</div>" +
        '<div class="ep-fields">' + (fieldHtml || '<div class="ep-field"><div class="v">无字段</div></div>') + "</div>" +
        errBlock + "</div>";
    }).join("");
    const presets = apiState.presets || [];
    const presetBtn = (p) => '<button class="btn sm" title="' + esc(p.description || "") +
      '" onclick="App.addApiPreset(\'' + p.id + '\')">＋ ' + esc(p.name) + "</button>";
    inner += card("监控端点", "端点决定「拉什么数据」；「测试」只即时验证、不改配置，绿色/红色为最近一次后台拉取的结果。",
      warnBar +
      (cards || '<div class="ep-empty">暂无监控端点：用下面的预设一键添加，或点「自定义端点」手动配置。</div>') +
      '<div class="ep-add"><button class="btn" onclick="App.addEndpoint()">＋ 自定义端点</button>' +
      (presets.length ? '<span class="ep-add-label">预设快速添加：</span>' + presets.map(presetBtn).join("") : "") +
      "</div>");

    // ── 余额显示框 ──
    const preview = (st && st.badge_preview) || apiState.badgePreview || [];
    const previewHtml = '<div class="badge-preview">' +
      (preview.length
        ? preview.map((r) => '<div class="bp-line">' +
            (r.title ? '<span class="bp-t">' + esc(r.title) + "</span>" : "") +
            '<span class="bp-v">' + esc(r.value) + "</span></div>").join("")
        : '<div class="bp-line"><span class="bp-v">--</span></div>') +
      "</div>";
    const rowCount = (cfgApi.badge_rows || []).length;
    inner += card("余额显示框", "半透明小框显示在浮球旁，可拖动位置；下方预览 = 小框此刻显示的内容（按已保存配置渲染，保存后即刷新）。",
      row("实时预览", rowCount ? ("按 " + rowCount + " 行自定义显示") : "未配置显示行：按「单行模式」显示",
        previewHtml +
        '<button class="btn sm" style="margin-left:10px" onclick="App.clearBadgeRows()">清空显示行</button>') +
      row("显示位置", "小框可直接用鼠标拖动到任意位置（松开即自动保存）",
        selectCtl("api_monitor.badge_position", cfgApi.badge_position || "top",
          [["top", "浮球上方"], ["bottom", "浮球下方"]]) +
        '<button class="btn sm" style="margin-left:8px" onclick="App.resetBadgePos()">重置拖动偏移</button>') +
      row("大小", "也可在浮球旁的小框上滚动滚轮 / 拖右下角缩放",
        rangeCtl("api_monitor.badge_scale", cfgApi.badge_scale || 1.0, 0.7, 2, 0.05, "bsLabel") +
        '<span id="bsLabel" class="val-tag">' + num(cfgApi.badge_scale, 1.0).toFixed(2) + "×</span>") +
      row("不透明度", "只影响背景，文字保持清晰；小框上 Ctrl+滚轮 可调",
        rangeCtl("api_monitor.badge_opacity", cfgApi.badge_opacity != null ? cfgApi.badge_opacity : 0.88, 0.25, 1, 0.05, "boLabel") +
        '<span id="boLabel" class="val-tag">' + Math.round(num(cfgApi.badge_opacity != null ? cfgApi.badge_opacity : 0.88, 0.88) * 100) + "%</span>") +
      row("单行模式", "未配置「显示行」时生效；端点可单独覆盖（如 OpenCode Go 预设为剩余%）",
        selectCtl("api_monitor.badge_mode", cfgApi.badge_mode || "balance",
          [["balance", "余额金额"], ["remaining", "剩余百分比"], ["used", "已用百分比"]])) +
      row("行预设（一键添加）", "推荐先点对应平台（重复点会在末尾继续追加，可在下方逐行删改）",
        (apiState.rowPresets || []).map((p) =>
          '<button class="btn sm" style="margin:0 6px 4px 0" onclick="App.addBadgeRowPreset(\'' + p.id + '\')">＋ ' + esc(p.name) + "</button>").join("") || "加载中…") +
      row("显示行", "每行 = 标题 + 数据源 + 小数位 + 后缀；示例：「5h / 剩余百分比 / 0 位小数 / %」→ 5h 92%",
        badgeRowsEditor()));
    // ── 轮询与告警 ──
    inner += card("轮询与告警", "后台按间隔自动拉取；阈值只影响显示与告警颜色。",
      row("轮询间隔（秒）", "「立即拉取」不受此限制", numCtl("api_monitor.poll_interval_seconds", cfgApi.poll_interval_seconds || 60, { min: 10, max: 3600 })) +
      row("低余额警告阈值", "余额 / 剩余额度低于该值标红", '<input type="number" data-bind="api_monitor.low_balance_warn" step="0.1" min="0" value="' + esc(warnTh) + '">'));
    // ── 帮助（默认折叠，减少页面噪音）──
    inner += card("模板与 JSONPath 说明",
      '<details class="help"><summary>展开：模板变量、JSONPath 与字段显示方式</summary><div class="help-body">' +
      "<p><b>模板变量</b>：<code>{{env:KEY}}</code> 读取环境变量（如 <code>{{env:DEEPSEEK_API_KEY}}</code>，也兼容注册表中的用户变量）、" +
      "<code>{{today}}</code> 今日日期、<code>{{yesterday}}</code> 昨日日期、<code>{{now_iso}}</code>、<code>{{timestamp}}</code>。</p>" +
      "<p><b>JSONPath</b>：<code>$.a.b</code> 取嵌套键、<code>$.a[0].b</code> 取数组元素、<code>$.a[*].b</code> 取列表。示例：<code>$.balance_infos[0].total_balance</code>（DeepSeek）。</p>" +
      "<p><b>字段 display</b>：<code>number</code> 数值、<code>percent</code> 百分比（自动补 %）、<code>text</code> 文本；显示行可用「自定义字段」引用字段标签（如填「每周已用」）。</p>" +
      "</div></details>");
    el.innerHTML = _guideBanner + inner;
    bindAll(el);
    // PATCH 3.5.1：余额显示框「自定义显示行」编辑（输入即写入配置，保存后生效）
    $$("#badgeRows [data-brow]").forEach((rowEl) => {
      const i = Number(rowEl.getAttribute("data-brow"));
      const collect = () => {
        const rows = cfg.api_monitor.badge_rows = cfg.api_monitor.badge_rows || [];
        const sel = rowEl.querySelector(".brow-src");
        let src = sel.value;
        if (src === "field:" || src === "field_remain:") {
          src = src + (rowEl.querySelector(".brow-field").value.trim() || "剩余额度");
        }
        const decRaw = rowEl.querySelector(".brow-dec").value.trim();
        const item = { title: rowEl.querySelector(".brow-title").value.trim(), source: src };
        if (decRaw !== "") item.decimals = Number(decRaw);
        const suf = rowEl.querySelector(".brow-suffix").value;
        if (suf !== "") item.suffix = suf;
        rows[i] = item;
        refreshDirty();
      };
      rowEl.querySelectorAll("input, select").forEach((c) => c.addEventListener("input", collect));
      const sel = rowEl.querySelector(".brow-src");
      sel.addEventListener("change", () => {
        rowEl.querySelector(".brow-field").disabled = (sel.value !== "field:" && sel.value !== "field_remain:");
        collect();
      });
    });
  }

  function badgeRowsEditor() {
    const rows = (cfg.api_monitor || {}).badge_rows || [];
    const opts = [["balance", "余额字段"], ["progress:remain_pct", "剩余百分比"], ["progress:used_pct", "已用百分比"], ["progress:used", "已用量"], ["progress:total", "总量"], ["progress:remain_value", "剩余额度(数值)"], ["field:", "自定义字段"], ["field_remain:", "字段剩余%"]];
    let html = "";
    rows.forEach((r, i) => {
      const src = String(r.source || "balance");
      const custom = src.indexOf("field_remain:") === 0 || src.indexOf("field:") === 0;
      const fnPrefix = src.indexOf("field_remain:") === 0 ? "field_remain:" : "field:";
      html += '<div class="mini-row" data-brow="' + i + '">' +
        '<span class="brow-idx">' + (i + 1) + "</span>" +
        '<input class="brow-title" style="width:56px" placeholder="标题" value="' + esc(r.title || "") + '">' +
        '<select class="brow-src">' + opts.map(([v, l]) =>
          '<option value="' + v + '"' + (v === (custom ? fnPrefix : src) ? " selected" : "") + ">" + l + "</option>").join("") + "</select>" +
        '<input class="brow-field" style="width:78px" placeholder="字段标签" value="' + esc(custom ? src.slice(fnPrefix.length) : "") + '"' + (custom ? "" : " disabled") + ">" +
        '<input class="brow-dec" type="number" style="width:46px" placeholder="小数" value="' + esc(r.decimals != null ? r.decimals : "") + '">' +
        '<input class="brow-suffix" style="width:40px" placeholder="后缀" value="' + esc(r.suffix != null ? r.suffix : "") + '">' +
        '<button class="btn sm danger" onclick="App.delBadgeRow(' + i + ')">删</button></div>';
    });
    return '<div id="badgeRows">' +
      (html
        ? '<div class="mini-row brow-head"><span class="brow-idx">#</span>' +
          '<span style="width:56px">标题</span><span class="brow-src-label">数据源</span><span style="width:78px">字段标签</span>' +
          '<span style="width:46px">小数</span><span style="width:40px">后缀</span><span style="width:34px"></span></div>' + html
        : '<div class="mini-row"><span class="grow">未配置显示行 → 使用「单行模式」</span></div>') +
      "</div>" +
      '<div style="margin-top:6px"><button class="btn sm" onclick="App.addBadgeRow()">＋ 添加行</button>' +
      '<span style="margin-left:8px;font-size:11px;color:var(--hint)">示例：标题「5h」+ 数据源「剩余百分比」+ 小数 0 + 后缀 % → 显示「5h 92%」</span></div>';
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
      renderApiCached();
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

  // ══════════════════ AI 快报页（v3.9.0 交互层重写）══════════════════
  // 阅读器状态（跨重渲染保留：搜索词 / 过滤 / 折叠 / 密度 / 键盘焦点）
  const newsUI = { search: "", filter: "all", collapsed: {}, focus: -1, showSettings: false };

  async function loadNewsPage() {
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

  const NEWS_CAT_COLOR = { "模型": "#4D6BFE", "工具": "#16A085", "论文": "#8E44AD",
                           "产品": "#E67E22", "行业": "#2E86C1", "综合": "#7F8C8D" };

  function newsFilteredItems(report) {
    const n = cfg.news || {};
    const kw = (newsUI.search || "").trim().toLowerCase();
    return (report.items || []).filter((it) => {
      if (newsUI.filter === "unread" && it.read) return false;
      if (newsUI.filter === "starred" && !it.starred) return false;
      if (!kw) return true;
      return ((it.title || "") + " " + (it.summary || "") + " " + (it.source || "") +
              " " + (it.category || "")).toLowerCase().indexOf(kw) >= 0;
    });
  }

  function newsItemHtml(it, idx) {
    const c = NEWS_CAT_COLOR[it.category] || "#7F8C8D";
    return '<div class="news-item' + (it.read ? "" : " unread") + (newsUI.focus === idx ? " focus" : "") +
      '" data-idx="' + idx + '" data-id="' + esc(it.id || "") + '">' +
      '<div class="news-line">' +
      '<span class="news-dot" title="' + (it.read ? "已读" : "未读") + '"></span>' +
      '<div class="t"><a href="' + esc(it.url) + '" target="_blank" rel="noopener">' + esc(it.title || "") + "</a></div>" +
      '<button class="news-star' + (it.starred ? " on" : "") + '" title="收藏/取消收藏" data-star="' +
      esc(it.id || "") + '">' + (it.starred ? "★" : "☆") + "</button></div>" +
      (it.summary ? '<div class="s">' + esc(it.summary) + "</div>" : "") +
      '<div class="meta"><span class="chip" style="color:#fff;background:' + c + '">' +
      esc(it.category || "综合") + "</span>" +
      (it.source ? '<span class="src">' + esc(it.source) + "</span>" : "") +
      '<button class="linklike" data-toggle-read="' + esc(it.id || "") + '" data-read="' +
      (it.read ? "1" : "0") + '">' + (it.read ? "标为未读" : "标为已读") + "</button></div></div>";
  }

  function renderNews(el, st) {
    const n = cfg.news || {};
    const report = st.report || null;
    const scrollTop = el.scrollTop || 0;
    const prog = st.progress || {};
    const phaseLabel = st.generating
      ? (prog.label || st.phase || "抓取数据源…")
      : "";
    const pct = st.generating
      ? (prog.total ? Math.round((prog.done / prog.total) * 100) : (prog.phase === "ai" ? 80 : 12))
      : 0;

    // ── 生成卡片：阶段进度 + 取消 + 每源状态 ──
    let gen = '<div class="card"><h3>生成</h3>' +
      '<div class="row"><div class="lbl">' +
      (n.last_generated ? "上次生成：" + esc(n.last_generated) : "尚未生成") +
      (st.next_run ? '<span class="hint"> · 下次自动生成 ' + esc(st.next_run) + "</span>" : "") +
      "</div><div class=\"ctl\">" +
      (st.generating
        ? '<button class="btn danger" id="btnCancel">取消生成</button>'
        : '<button class="btn primary" id="btnGen">立即生成</button>') +
      "</div></div>";
    if (st.generating) {
      gen += '<div class="desc">' + esc(phaseLabel) +
        (prog.total ? "（" + prog.done + "/" + prog.total + "）" : "") + "</div>" +
        '<div class="progress"><div style="width:' + pct + '%"></div></div>';
    }
    if (report && (report.sources || []).length) {
      gen += '<div class="news-sources">' + report.sources.map((s) =>
        '<span class="news-src-chip' + (s.ok ? " ok" : " bad") + '" title="' + esc(s.error || "") + '">' +
        esc(s.name) + (s.ok ? " · " + (s.count || 0) : " · 失败") +
        (s.ok ? "" : ' <button class="linklike" data-retry="' + esc(s.id) + '">重试</button>') + "</span>").join("") +
        "</div>";
    }
    if (report && report.stats) {
      const s = report.stats;
      gen += '<div class="desc">抓取 ' + (s.raw || 0) + " 条" +
        (s.blocked ? " · 屏蔽 " + s.blocked : "") +
        " · 去重后 " + (s.deduped || 0) + " · 展示 " + (s.shown || report.count || 0) + "</div>";
    }
    gen += "</div>";

    // ── 阅读器：工具条 + 分类分组 ──
    let reader = '<div class="card"><div class="news-head">' +
      "<h3>今日快报</h3>" +
      '<div class="news-tools">' +
      '<input id="newsSearch" class="news-search" placeholder="搜索标题 / 摘要 / 来源（/）" value="' + esc(newsUI.search) + '">' +
      '<div class="news-filter">' + [["all", "全部"], ["unread", "未读"], ["starred", "收藏"]]
        .map((f) => '<button class="news-filter-btn' + (newsUI.filter === f[0] ? " on" : "") +
                    '" data-filter="' + f[0] + '">' + f[1] + "</button>").join("") + "</div>" +
      '<button class="btn sm" id="btnDensity">' + (n.density === "compact" ? "紧凑" : "舒适") + "</button>" +
      '<button class="btn sm" id="btnExport" title="导出为 Markdown">导出</button>' +
      "</div></div>";
    if (report) {
      const items = newsFilteredItems(report);
      const unread = report.unread != null ? report.unread : (report.items || []).filter((i) => !i.read).length;
      reader += '<div class="news-headline">' + esc(report.headline || "今日 AI 速览") + "</div>" +
        '<div class="desc">生成于 ' + esc(report.generated_at || "") +
        (report.used_ai ? ' · <span class="tag purple">AI 摘要</span>' : ' · <span class="tag gray">标题列表</span>') +
        " · 共 " + (report.items || []).length + " 条 · 未读 " + unread +
        (st.starred_count ? " · 收藏 " + st.starred_count : "") + "</div>";
      if (!items.length) {
        reader += '<div class="desc">没有符合条件的条目（换个筛选或清空搜索）。</div>';
      }
      const groups = {};
      items.forEach((it) => { (groups[it.category || "综合"] = groups[it.category || "综合"] || []).push(it); });
      let flat = 0;
      Object.keys(groups).sort().forEach((cat) => {
        const collapsed = !!newsUI.collapsed[cat];
        const c = NEWS_CAT_COLOR[cat] || "#7F8C8D";
        reader += '<div class="news-group"><button class="news-group-head" data-cat="' + esc(cat) + '">' +
          '<span class="chip" style="color:#fff;background:' + c + '">' + esc(cat) + "</span>" +
          '<span class="grow">' + groups[cat].length + " 条</span>" +
          '<span class="caret">' + (collapsed ? "▸" : "▾") + "</span></button>";
        if (!collapsed) {
          groups[cat].forEach((it) => { reader += newsItemHtml(it, flat); flat += 1; });
        }
        reader += "</div>";
      });
    } else {
      reader += '<div class="desc">今日尚未生成快报。点上方「立即生成」开始。</div>';
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
    const blocked = (n.blocked_keywords || []).join(", ");
    const settings = card("快报设置",
      row("启用快报", "定时 / 启动时自动生成", switchCtl("news.enabled", n.enabled)) +
      row("生成语言", "", selectCtl("news.language", n.language || "zh", [["zh", "简体中文"], ["en", "English"], ["both", "中英双语"]])) +
      row("定时策略", "", selectCtl("news.schedule_mode", n.schedule_mode || "daily_startup", [["off", "关闭"], ["daily", "每日定时"], ["startup", "启动时"], ["daily_startup", "每日 + 启动补生成"]])) +
      row("定时时间", "", '<input type="time" data-bind="news.schedule_time" value="' + esc(n.schedule_time || "09:00") + '">') +
      row("展示条数", "AI 摘要条数 / 标题列表条数", numCtl("news.max_items", n.max_items || 6, { min: 3, max: 20 })) +
      row("每源抓取条数", "单个数据源最多取多少条", numCtl("news.per_source", n.per_source || 12, { min: 3, max: 30 })) +
      row("AI 摘要条数", "送给本地 Agent 精选的条目数", numCtl("news.ai_max_items", n.ai_max_items || 6, { min: 1, max: 20 })) +
      row("屏蔽关键词", "逗号分隔；标题/摘要命中即丢弃", '<input type="text" data-bind="news.blocked_keywords" value="' + esc(blocked) + '" placeholder="招聘, 广告, 优惠" style="width:220px">') +
      row("历史保留天数", "超过天数的历史快报自动清理", numCtl("news.retention_days", n.retention_days || 14, { min: 3, max: 180 })) +
      row("正文字号", "应用于本页快报阅读区", numCtl("news.font_size", n.font_size || 13, { min: 11, max: 20 })) +
      row("阅读密度", "", selectCtl("news.density", n.density || "comfortable", [["comfortable", "舒适"], ["compact", "紧凑"]])) +
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
    const shortcut = card("快捷键", "阅读区支持键盘操作。",
      '<div class="desc">j / k 上下移动 · Enter 打开原文 · s 收藏 · r 标已读 · / 搜索 · Esc 清空搜索</div>');
    const density = n.density === "compact" ? " compact" : "";
    el.innerHTML = '<div class="news-reader' + density + '" style="--news-fs:' + (n.font_size || 13) + 'px">' +
      gen + reader + hist + shortcut + settings + srcCard + intCard + "</div>";
    bindAll(el);
    const btnGen = $("#btnGen");
    if (btnGen) btnGen.addEventListener("click", async () => {
      btnGen.disabled = true;
      newsState.generating = true;
      renderNews(el, newsState);
      try { await API.api("/api/news/generate", { method: "POST" }); toast("已开始生成快报…", "ok"); }
      catch (e) { newsState.generating = false; toast("启动生成失败：" + e.message, "err"); renderNews(el, newsState); }
    });
    const btnCancel = $("#btnCancel");
    if (btnCancel) btnCancel.addEventListener("click", async () => {
      btnCancel.disabled = true;
      try { await API.api("/api/news/cancel", { method: "POST" }); toast("已请求取消…", "ok"); }
      catch (e) { toast("取消失败：" + e.message, "err"); }
    });
    const btnExport = $("#btnExport");
    if (btnExport) btnExport.addEventListener("click", async () => {
      try {
        const r = await API.api("/api/news/export", { method: "POST", body: { date: st.date || null } });
        toast(r.ok ? ("已导出：" + r.path) : ("导出失败：" + (r.error || "")), r.ok ? "ok" : "err");
      } catch (e) { toast("导出失败：" + e.message, "err"); }
    });
    const btnDensity = $("#btnDensity");
    if (btnDensity) btnDensity.addEventListener("click", () => {
      cfg.news = cfg.news || {};
      cfg.news.density = (cfg.news.density === "compact") ? "comfortable" : "compact";
      refreshDirty();
      loadNewsState();
    });
    const search = $("#newsSearch");
    if (search) {
      search.addEventListener("input", () => {
        newsUI.search = search.value;
        const pos = search.selectionStart;
        renderNews(el, newsState);
        const s2 = $("#newsSearch");
        if (s2) { s2.focus(); try { s2.setSelectionRange(pos, pos); } catch (e) {} }
      });
    }
    $$("#newsContent [data-filter]").forEach((b) => b.addEventListener("click", () => {
      newsUI.filter = b.dataset.filter;
      renderNews(el, newsState);
    }));
    $$("#newsContent [data-cat]").forEach((b) => b.addEventListener("click", () => {
      const c = b.dataset.cat;
      newsUI.collapsed[c] = !newsUI.collapsed[c];
      renderNews(el, newsState);
    }));
    $$("#newsContent [data-star]").forEach((b) => b.addEventListener("click", async (ev) => {
      ev.preventDefault();
      const id = b.dataset.star;
      try {
        const r = await API.api("/api/news/star", { method: "POST", body: { item_id: id } });
        (newsState.report.items || []).forEach((it) => { if (it.id === id) it.starred = !!r.starred; });
        newsState.starred_count = (newsState.report.items || []).filter((i) => i.starred).length;
        renderNews(el, newsState);
      } catch (e) { toast("收藏失败：" + e.message, "err"); }
    }));
    $$("#newsContent [data-toggle-read]").forEach((b) => b.addEventListener("click", async () => {
      const id = b.dataset.toggleRead;
      const read = b.dataset.read !== "1";
      try {
        await API.api("/api/news/read", { method: "POST", body: { item_id: id, read: read } });
        (newsState.report.items || []).forEach((it) => { if (it.id === id) it.read = read; });
        newsState.unread = (newsState.report.items || []).filter((i) => !i.read).length;
        newsState.report.unread = newsState.unread;
        renderNews(el, newsState);
      } catch (e) { toast("标记失败：" + e.message, "err"); }
    }));
    $$("#newsContent [data-retry]").forEach((b) => b.addEventListener("click", async () => {
      b.disabled = true;
      try {
        const r = await API.api("/api/news/retry_source", { method: "POST", body: { source_id: b.dataset.retry } });
        toast(r.ok ? ("已补抓 " + (r.added || 0) + " 条") : ("重试失败：" + (r.error || "")), r.ok ? "ok" : "err");
        if (r.ok && r.added) loadNewsState();
      } catch (e) { toast("重试失败：" + e.message, "err"); b.disabled = false; }
    }));
    $$("#newsContent [data-src]").forEach((cb) => cb.addEventListener("change", () => {
      cfg.news.sources = $$("#newsContent [data-src]:checked").map((c) => c.dataset.src);
      refreshDirty();
    }));
    el.scrollTop = scrollTop;
  }

  // 键盘导航（仅快报页生效）
  document.addEventListener("keydown", (e) => {
    if (page !== "news") return;
    const tag = (e.target && e.target.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea" || tag === "select") {
      if (e.key === "Escape" && e.target.id === "newsSearch") { e.target.value = ""; newsUI.search = ""; loadNewsState(); }
      return;
    }
    const items = newsFilteredItems(newsState.report || {});
    if (!items.length) return;
    if (e.key === "j" || e.key === "ArrowDown") { e.preventDefault(); newsUI.focus = Math.min(items.length - 1, newsUI.focus + 1); renderNews($("#newsContent"), newsState); }
    else if (e.key === "k" || e.key === "ArrowUp") { e.preventDefault(); newsUI.focus = Math.max(0, newsUI.focus - 1); renderNews($("#newsContent"), newsState); }
    else if (e.key === "/") { e.preventDefault(); const s = $("#newsSearch"); if (s) s.focus(); }
    else if (e.key === "Enter") {
      const it = items[Math.max(0, newsUI.focus)];
      if (it && it.url) window.open(it.url, "_blank", "noopener");
    } else if (e.key === "s") {
      const it = items[Math.max(0, newsUI.focus)];
      if (it) { const b = $('[data-star="' + it.id + '"]'); if (b) b.click(); }
    } else if (e.key === "r") {
      const it = items[Math.max(0, newsUI.focus)];
      if (it) { const b = $('[data-toggle-read="' + it.id + '"]'); if (b) b.click(); }
    }
  });

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

  // ══════════════════ 使用指南页（v3.9.0）══════════════════
  function guideSection(id, title, desc, body, media, mediaDesc) {
    const img = media
      ? '<figure class="guide-media"><img src="' + media + '" alt="' + esc(title) + '" loading="lazy">' +
        (mediaDesc ? "<figcaption>" + esc(mediaDesc) + "</figcaption>" : "") + "</figure>"
      : "";
    return '<div class="card guide-section" id="' + id + '"><h3>' + esc(title) + "</h3>" +
      (desc ? '<div class="desc">' + desc + "</div>" : "") +
      (img ? img : "") + (body || "") + "</div>";
  }

  function renderGuide() {
    const el = $("#guideContent");
    if (!el) return;
    const steps = (rows) => '<ol class="guide-steps">' +
      rows.map((r) => "<li><b>" + r[0] + "</b>" + (r[1] ? " — " + r[1] : "") + "</li>").join("") + "</ol>";
    const keys = (rows) => '<div class="guide-keys">' +
      rows.map((r) => '<div class="guide-key"><kbd>' + esc(r[0]) + "</kbd><span>" + esc(r[1]) + "</span></div>").join("") + "</div>";
    const toc = [
      ["quick", "① 快速上手（3 分钟）"],
      ["orb", "② 浮球怎么用"],
      ["menu", "③ 环绕菜单"],
      ["agent", "④ 启动你的 Agent"],
      ["api", "⑤ API 余额监控"],
      ["news", "⑥ AI 快报"],
      ["vault", "⑦ 账户与密钥保险箱"],
      ["update", "⑧ 自动更新"],
      ["faq", "⑨ 常见问题与快捷键"],
    ];

    el.innerHTML =
      '<div class="card guide-hero">' +
      "<h3>欢迎使用 AgentFloat 🌀</h3>" +
      '<div class="desc">一颗常驻桌面的小球，把繁琐的 Agent 启动、密钥管理、余额与资讯都收进来。<br>' +
      "这份指南按「第一次使用」的顺序编排，全程约 3 分钟；也可以随时从浮球右键菜单 →「使用教程」重看浮球引导。</div>" +
      '<div class="guide-toc">' + toc.map((t) =>
        '<a class="guide-toc-item" href="#/guide" data-goto="' + t[0] + '">' + esc(t[1]) + "</a>").join("") + "</div>" +
      "</div>" +

      guideSection("quick", "① 快速上手（3 分钟）",
        "三步就能开始用：",
        steps([["安装", "下载 AgentFloat-Setup 安装包，双击（免管理员，装到用户目录）"],
               ["启动", "启动后屏幕中央会出现浮球；第一次会有 6 步聚光灯引导"],
               ["开始用", "单击浮球启动默认 Agent；长按唤出环绕菜单；右键是更多入口"]]) +
        '<div class="guide-tip">💡 首次运行自动播放浮窗引导；跳过也没关系，右键浮球 →「使用教程」可随时重看。</div>',
        "assets/guide/guide-orb.gif", "浮球：呼吸 → 点击涟漪 → 长按唤出环绕菜单") +

      guideSection("orb", "② 浮球怎么用",
        "所有交互都围绕这颗小球：",
        steps([["单击", "启动「默认 Agent」（在 设置 → 通用 → 主 Agent 启动 里更换）"],
               ["长按不动 2 秒", "环形进度条走满即启动（可在设置里调整时长）"],
               ["按住向外滑", "唤出环绕菜单，滑到哪个扇区松手就执行哪个动作"],
               ["右键", "启动具体 Agent / 设置 / 使用教程 / 复制控制台令牌 / 开机自启 / 退出"],
               ["拖拽", "自由移动；拖到屏幕边缘会吸附，开启「贴边隐藏」后鼠标靠近边缘自动滑出"]]) +
        '<div class="guide-tip">💡 换显示器或改分辨率后浮球会自动回到可见区域（v3.9.0 起监听显示器变化）。</div>',
        "assets/guide/menu.png", "环绕菜单：滑到扇区松手即执行") +

      guideSection("menu", "③ 环绕菜单",
        "菜单里的每一项都能自定义：<b>设置 → 环绕菜单</b> 可调整扇区数量、每一项的图标/文字/颜色，以及「灵敏档」时延。",
        steps([["Skills 辅助窗", "浏览与触发本地 Skills"],
               ["API 用量", "打开余额监控页"],
               ["AI 快报", "打开今日快报"],
               ["剪贴板历史", "查看最近复制的内容"],
               ["移动浮窗", "进入移动模式：左键放置、右键/Esc 取消"],
               ["退出", "退出 AgentFloat（不会结束你已启动的 Agent 进程）"]])) +

      guideSection("agent", "④ 启动你的 Agent",
        "AgentFloat 支持一键安装与启动常见 Agent。",
        steps([["一键安装", "设置 → Agent 安装：Claude Code / Codex CLI / Pi / DeepSeek Harness 一键装（npm 全局安装，国内镜像优先）"],
               ["自定义 Agent", "设置 → Agent 管理：填名称、启动命令、参数、工作目录"],
               ["Web 类型 Agent", "如 DeepSeek Harness：以 Web 方式启动并自动打开浏览器页面"]]) +
        '<div class="guide-tip">💡 保险箱里保存的密钥会在启动 Agent 时自动注入环境变量，Agent 无需再手工配置 Key。</div>',
        "assets/guide/install.png", "Agent 安装：一键安装 / 升级 / 卸载") +

      guideSection("api", "⑤ API 余额监控",
        "把各家 API 的余额与用量显示在浮球旁：<b>设置 → API 用量</b>。",
        steps([["添加端点", "用预设一键添加（OpenCode Go / DeepSeek / Kimi / SiliconFlow / OpenRouter），或自定义端点"],
               ["显示位置", "余额显示框可贴在浮球上/下方，可拖动、可调整大小与不透明度"],
               ["显示行", "自定义显示哪些字段、小数位、后缀；支持进度条与告警阈值"],
               ["手动拉取", "「立即拉取」不等轮询即刻刷新"]]) +
        '<div class="guide-tip">⚠️ 密钥通过 <b>{{env:xxx}}</b> 模板注入；把 Key 存进保险箱并设为环境变量（见第 ⑦ 节）后即可自动读取。</div>',
        "assets/guide/api-dark.png", "API 用量页（深色主题）") +

      guideSection("news", "⑥ AI 快报",
        "把 AI 行业资讯聚合成一份可读的日报：<b>设置 → AI 快报</b>（或环绕菜单 → AI 快报）。",
        steps([["数据源", "Hacker News / GitHub 趋势 / 少数派 / 量子位 / arXiv AI 任选"],
               ["生成", "「立即生成」会经历：抓取（逐源进度）→ 去重筛选 → AI 摘要 → 写入；随时可取消，失败的源可单独重试"],
               ["阅读", "按分类分组、未读圆点、收藏星标、搜索过滤、舒适/紧凑密度；j/k 上下、Enter 打开、s 收藏、r 标已读、/ 搜索"],
               ["导出", "一键导出 Markdown，方便存档或分享"],
               ["提醒", "生成完成会弹托盘通知（点击直达），托盘提示显示未读数与下次生成时间"]]) +
        '<div class="guide-tip">💡 「关注主题」支持权重：命中主题的条目优先收录；「屏蔽关键词」可过滤掉不关心的内容。</div>',
        "assets/guide/guide-news.gif", "快报：阶段进度 → 分类阅读 → 收藏 → 搜索过滤") +

      guideSection("vault", "⑦ 账户与密钥保险箱",
        "本地多账户 + AES-256-GCM 加密的密钥保险箱：<b>设置 → 账户与密钥</b>。",
        steps([["创建账户", "设置一个主口令（PBKDF2-HMAC-SHA256，60 万次迭代 + 每账户随机盐）"],
               ["保存密钥", "密钥加密落盘、界面默认掩码；可一键添加常用名称（OPENCODE_GO_API_KEY 等）"],
               ["自动注入", "启动 Agent 时把密钥注入环境变量，Agent 直接用，无需明文配置"],
               ["导出/导入", "生成 .afpack 单文件（口令保护，可选是否包含密钥），换机迁移很方便"]]) +
        '<div class="guide-tip">🔒 保险箱只在内存中解密；本机 Web 接口已加访问令牌与同源校验，浏览器里的其他网页无法读取。</div>') +

      guideSection("update", "⑧ 自动更新",
        "检测 → 下载 → 校验 → 静默安装 → 重启，全流程自动：",
        steps([["检测", "启动后自动检查，也可在「设置 → 关于」手动检查；并行探测多个源，优先自有镜像（国内直连）"],
               ["下载", "走镜像下载，失败自动回退 GitHub 与加速代理；下载完成校验 SHA256，不匹配直接拒绝"],
               ["安装", "退出旧版本 → 覆盖安装（配置与密钥保留）→ 自动重启并确认启动成功"],
               ["日志", "安装与更新日志在 %APPDATA%\\AgentFloat\\ 下（update_log.txt / install_log.txt）"]]) +
        '<div class="guide-tip">💡 更新包校验值来自 GitHub Release 资产或官方镜像清单，镜像被篡改也会被拦下。</div>',
        "assets/guide/guide-update.gif", "自动更新：检查（R2 优先）→ 下载 → 静默安装 → 重启") +

      guideSection("faq", "⑨ 常见问题与快捷键",
        "",
        '<div class="guide-faq">' +
        "<details><summary>浮球不见了怎么办？</summary>右键托盘图标 →「重置浮球位置」（或重启应用）；" +
        "拔掉显示器后浮球会自动回到可见屏幕。</details>" +
        "<details><summary>浏览器打开控制台提示需要访问令牌？</summary>" +
        "浮球右键菜单 →「复制 Web 控制台令牌」，粘贴即可。令牌每次启动随机生成，仅本机有效。</details>" +
        "<details><summary>启动 Agent 后没有注入密钥？</summary>" +
        "确认保险箱已解锁、密钥名与环境变量名一致；Agent 需由 AgentFloat 启动才会注入。</details>" +
        "<details><summary>快报生成很慢或失败？</summary>" +
        "AI 摘要是本机 Agent 在跑，可关闭「使用本地 AI 摘要」用标题列表（零成本、秒出）；" +
        "单个源失败可在快报页「重试」。</details>" +
        "<details><summary>余额显示不更新？</summary>" +
        "确认端点用的是 {{env:...}} 且对应环境变量已设置；「立即拉取」可手动刷新。</details>" +
        "</div>" +
        "<h4 style=\"margin:14px 0 6px;font-size:13px\">快捷操作</h4>" +
        keys([["Ctrl + Alt + C", "呼出 / 聚焦浮球"],
              ["长按 2 秒", "启动默认 Agent"],
              ["按住外滑", "环绕菜单"],
              ["快报页 j / k", "上下选择条目"],
              ["快报页 Enter", "打开原文"],
              ["快报页 s / r", "收藏 / 标已读"],
              ["快报页 /", "聚焦搜索"],
              ["Esc", "关闭面板 / 清空搜索 / 取消移动模式"]]));
    $$("#guideContent [data-goto]").forEach((a) => a.addEventListener("click", (ev) => {
      ev.preventDefault();
      const t = $("#" + a.dataset.goto);
      if (t) t.scrollIntoView({ behavior: "smooth", block: "start" });
    }));
  }

  // ── 模态框 / SSE / 启动 ─────────────────────────
  function openModal(html) {
    $("#modalBox").innerHTML = html;
    $("#modalMask").classList.remove("hidden");
  }
  function closeModal() {
    $("#modalMask").classList.add("hidden");
  }
  // v3.9.0：新用户横幅按钮（委托绑定，横幅在多个子页复用）
  document.addEventListener("click", (e) => {
    const id = e.target && e.target.id;
    if (id === "btnGoGuide") { goPage("guide"); }
    else if (id === "btnSkipOnboard") {
      cfg.onboarding_done = true;
      refreshDirty();
      renderSettings();
      toast("已关闭新用户提示（可在浮球右键菜单重看教程）", "ok");
    }
  });

  function wireEvents() {
    API.streamEvents((ev) => {
      if (ev.event === "news_started") { newsState.generating = true; newsState.phase = "抓取数据源…"; if (page === "news") loadNewsState(); }
      else if (ev.event === "news_progress") {
        // v3.9.0：阶段化进度（节流 300ms，避免刷爆渲染）
        newsState.generating = true;
        newsState.progress = ev.payload || {};
        newsState.phase = (ev.payload && ev.payload.label) || newsState.phase;
        scheduleNewsProgressRender();
      }
      else if (ev.event === "news_cancelling") toast("正在取消快报生成…", "ok");
      else if (ev.event === "news_done") {
        newsState.generating = false;
        newsState.progress = {};
        toast("AI 快报已生成（" + (ev.payload.count || 0) + " 条）", "ok");
        if (cfg.news && cfg.news.auto_show_panel && page !== "news") goPage("news");
        if (page === "news") loadNewsState();
      }
      else if (ev.event === "news_failed") { newsState.generating = false; newsState.progress = {}; toast("快报生成失败：" + (ev.payload.error || ""), "err"); if (page === "news") loadNewsState(); }
      else if (ev.event === "api_updated") { if (page === "api") loadApiState(); }
      else if (ev.event === "theme_changed") { if (cfg) { cfg.theme = ev.payload.theme || cfg.theme; applyTheme(); refreshDirty(); } }
      else if (ev.event === "ai_service_done") toast("AI 自检完成：" + (ev.payload.summary || ""), "ok");
      else if (ev.event === "ai_service_failed") toast("AI 自检失败：" + (ev.payload.error || ""), "err");
      else if (ev.event === "auto_translate_done") toast("自动翻译：" + (ev.payload.message || ""), "ok");
      else if (ev.event === "auto_translate_failed") toast("自动翻译失败：" + (ev.payload.error || ""), "err");
    });
  }

  // 快报进度节流渲染（抓取阶段逐源回调较密）
  let newsProgressTimer = null;
  function scheduleNewsProgressRender() {
    if (page !== "news" || newsProgressTimer) return;
    newsProgressTimer = setTimeout(() => {
      newsProgressTimer = null;
      if (page === "news") loadNewsState();
    }, 300);
  }

  async function init() {
    $$("#nav .nav-item").forEach((a) => a.addEventListener("click", () => goPage(a.dataset.page)));
    $$("#settingsSubnav .sub").forEach((b) => b.addEventListener("click", () => goSub(b.dataset.sub)));
    $("#btnSave").addEventListener("click", save);
    // PATCH 3.1.1：统一委托监听（此前普通开关没有 change 监听 → 不置脏 → 保存按钮禁用 →
    //「切换选项无法保存」）。__ 前缀为虚拟控件（扇区槽位/主 Agent/计时器开关）由各自处理器负责。
    document.addEventListener("change", (e) => {
      const el = e.target;
      if (el && el.dataset && el.dataset.bind && !el.dataset.bind.startsWith("__")) bindRead(el);
    });
    document.addEventListener("input", (e) => {
      const el = e.target;
      if (!el || !el.dataset || !el.dataset.bind || el.dataset.bind.startsWith("__")) return;
      if (el.type === "range" || el.type === "number" || el.type === "text" || el.tagName === "TEXTAREA") bindRead(el);
    });
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
    if (["api", "news", "settings", "install"].indexOf(h) >= 0) goPage(h);
    else goPage("settings");
  }

  window.App = {
    save: save, goPage: goPage, goSub: goSub,
    guide: renderGuide,          // v3.9.2：供调试/自动化测试直接渲染指南页
    renderNews: renderNews,
    rangeLabel: (el, id) => {
      const t = $("#" + id);
      if (!t) return;
      const unit = (id === "opLabel" || id === "boLabel" || id === "ppLabel" || id === "ivLabel") ? "%"
        : ((id === "bsLabel" || id === "psLabel") ? "×" : "px");
      t.textContent = el.value + unit;
    },
    resetDir: () => { cfg.working_directory = ""; refreshDirty(); renderPage(); },
    setPrimary: (i) => { (cfg.agents || []).forEach((a, j) => { a.primary = (i === j); }); refreshDirty(); renderAgents($("#settingsContent")); },
    addAgent: () => agentModal(null),
    editAgent: (i) => agentModal(i),
    delAgent: (i) => { if (confirm("确定删除 Agent「" + cfg.agents[i].name + "」？")) { cfg.agents.splice(i, 1); refreshDirty(); renderAgents($("#settingsContent")); } },
    openDsh: () => API.api("/api/open_url", { method: "POST", body: { url: "http://127.0.0.1:3080" } }).catch(() => toast("请先启动 DeepSeek Harness", "err")),
    installAgent: installAgent,
    uninstallAgent: uninstallAgent,
    toggleInstallLog: toggleInstallLog,
    runAiServices: () => API.api("/api/run_ai_services", { method: "POST", body: { auto: false } }).then(() => toast("已发起本地 AI 自检服务", "ok")).catch((e) => toast("启动失败：" + e.message, "err")),
    checkUpdate: () => API.api("/api/check_update", { method: "POST" }).then(() => toast("已发起检查更新", "ok")).catch((e) => toast("检查失败：" + e.message, "err")),
    addTimer: () => timerModal(null),
    editTimer: (i) => timerModal(i),
    delTimer: (i) => { if (confirm("确定删除计时器？")) { cfg.water.timers.splice(i, 1); refreshDirty(); renderWater($("#settingsContent")); } },
    addEndpoint: () => endpointModal(null),
    addApiPreset: async (id) => {
      try {
        await loadApiPresets();
        let p = (apiState.presets || []).find((x) => x.id === id);
        if (!p) {
          const r = await API.api("/api/api_monitor/presets");
          apiState.presets = r.presets || [];
          apiState.rowPresets = r.row_presets || [];
          p = (apiState.presets || []).find((x) => x.id === id);
        }
        if (!p) { toast("预设不存在：" + id, "err"); return; }
        cfg.api_monitor = cfg.api_monitor || {};
        const eps = cfg.api_monitor.endpoints = cfg.api_monitor.endpoints || [];
        const url = String((p.endpoint || {}).url || "");
        const idx = eps.findIndex((e) => String(e.url || "").trim() === url);
        if (idx >= 0 && url) {
          eps[idx] = deep(p.endpoint);      // 已存在同地址端点 → 用预设更新，避免重复堆积
          toast("已有相同地址的端点：已用「" + p.name + "」预设更新", "ok");
        } else {
          eps.push(deep(p.endpoint));
          toast("已添加预设：" + p.name + "（点保存后生效）", "ok");
        }
        cfg.api_monitor.enabled = true;
        refreshDirty();
        renderApiCached();
      } catch (e) { toast("添加预设失败：" + e.message, "err"); }
    },
    editEndpoint: (i) => endpointModal(i),
    delEndpoint: (i) => { if (confirm("确定删除端点？")) { cfg.api_monitor.endpoints.splice(i, 1); refreshDirty(); renderApiCached(); } },
    addBadgeRow: () => {
      cfg.api_monitor = cfg.api_monitor || {};
      cfg.api_monitor.badge_rows = (cfg.api_monitor.badge_rows || []).concat([
        { title: "", source: "progress:remain_pct", decimals: 0, suffix: "%" }]);
      refreshDirty();
      renderApiCached();
    },
    delBadgeRow: (i) => {
      (cfg.api_monitor.badge_rows || []).splice(i, 1);
      refreshDirty();
      renderApiCached();
    },
    resetBadgePos: () => {
      cfg.api_monitor = cfg.api_monitor || {};
      cfg.api_monitor.badge_dx = 0;
      cfg.api_monitor.badge_dy = 0;
      refreshDirty();
      toast("已重置拖动偏移（保存后生效）", "ok");
    },
    clearBadgeRows: () => {
      cfg.api_monitor = cfg.api_monitor || {};
      cfg.api_monitor.badge_rows = [];
      refreshDirty();
      renderApiCached();
      toast("已清空显示行 → 回到单行模式（保存后生效）", "ok");
    },
    duplicateEndpoint: (i) => {
      const src = (cfg.api_monitor.endpoints || [])[i];
      if (!src) return;
      const item = deep(src);
      item.name = String(src.name || "端点") + " 副本";
      cfg.api_monitor.endpoints.splice(i + 1, 0, item);
      refreshDirty();
      renderApiCached();
      toast("已复制端点（记得改名字/Key 后保存）", "ok");
    },
    cleanupEndpoints: () => {
      const eps = (cfg.api_monitor || {}).endpoints || [];
      const seen = {};
      let removed = 0;
      cfg.api_monitor.endpoints = eps.filter((e) => {
        const u = String(e.url || "").trim();
        if (u.indexOf("api.example.com") >= 0) { removed++; return false; }
        const key = String(e.name || "").trim() + "|" + u;
        if (seen[key]) { removed++; return false; }
        seen[key] = true;
        return true;
      });
      refreshDirty();
      renderApiCached();
      toast(removed ? ("已整理：移除 " + removed + " 个端点（保存后生效）") : "没有需要整理的端点", "ok");
    },
    refreshApi: async () => {
      try {
        await API.api("/api/api_monitor/refresh", { method: "POST" });
        toast("已请求立即拉取…", "ok");
        setTimeout(() => { loadApiState(); }, 1500);
      } catch (e) { toast("拉取失败：" + e.message, "err"); }
    },
    addBadgeRowPreset: async (id) => {
      try {
        await loadApiPresets();
        const p = (apiState.rowPresets || []).find((x) => x.id === id);
        if (!p) { toast("行预设不存在：" + id, "err"); return; }
        cfg.api_monitor = cfg.api_monitor || {};
        const rows = cfg.api_monitor.badge_rows = cfg.api_monitor.badge_rows || [];
        (p.rows || []).forEach((r) => {
          const item = deep(r);
          if (p.endpoint) item.endpoint = p.endpoint;
          rows.push(item);
        });
        refreshDirty();
        renderApiCached();
        toast("已添加「" + p.name + "」显示行（保存后生效）", "ok");
      } catch (e) { toast("添加失败：" + e.message, "err"); }
    },
    vaultLogin: async () => {
      const name = vaultNameValue();
      const pw = ($("#vaultPw") || {}).value || "";
      const quick = $("#vaultQuick") ? $("#vaultQuick").checked : true;
      if (!name || !pw) { toast("请选择账户并输入口令", "err"); return; }
      try {
        await API.api("/api/vault/login", { method: "POST", body: { name: name, password: pw, quick: quick } });
        toast("已登录：" + name, "ok");
        await loadVault();
      } catch (e) { toast("登录失败：" + e.message, "err"); }
    },
    vaultCreate: async () => {
      const name = vaultNameValue();
      const pw = ($("#vaultPw") || {}).value || "";
      const quick = $("#vaultQuick") ? $("#vaultQuick").checked : true;
      if (!name) { toast("请输入账户名", "err"); return; }
      if (String(pw).length < 6) { toast("口令至少 6 位", "err"); return; }
      try {
        await API.api("/api/vault/create", { method: "POST", body: { name: name, password: pw, quick: quick } });
        toast("账户已创建并登录：" + name, "ok");
        await loadVault();
      } catch (e) { toast("创建失败：" + e.message, "err"); }
    },
    vaultQuickLogin: async () => {
      try {
        const r = await API.api("/api/vault/quick_login", { method: "POST" });
        toast(r.ok ? "快速登录成功" : "快速登录不可用（令牌已过期或换机）", r.ok ? "ok" : "err");
        await loadVault();
      } catch (e) { toast("快速登录失败：" + e.message, "err"); }
    },
    vaultLogout: async () => {
      try {
        await API.api("/api/vault/logout", { method: "POST" });
        toast("已登出（密钥已锁定，启动 Agent 时不再注入）", "ok");
        await loadVault();
      } catch (e) { toast("登出失败：" + e.message, "err"); }
    },
    vaultSwitch: async (id) => {
      try {
        const r = await API.api("/api/vault/active", { method: "POST", body: { id: id } });
        toast("已切换到「" + r.active + "」，请输入该账户口令登录", "ok");
        await loadVault();
      } catch (e) { toast("切换失败：" + e.message, "err"); }
    },
    vaultChangePw: () => {
      openModal("<h3>修改口令</h3>" +
        '<div class="f"><label>原口令</label><input type="password" id="cpw-old"></div>' +
        '<div class="f"><label>新口令（≥6 位）</label><input type="password" id="cpw-new"></div>' +
        '<div class="modal-actions"><button class="btn" data-close>取消</button><button class="btn primary" data-save>确定</button></div>');
      $("#modalBox [data-close]").addEventListener("click", closeModal);
      $("#modalBox [data-save]").addEventListener("click", async () => {
        try {
          await API.api("/api/vault/change_password", { method: "POST", body: {
            name: vaultState.active, old_password: $("#cpw-old").value, new_password: $("#cpw-new").value } });
          closeModal();
          toast("口令已修改（快速登录已清除）", "ok");
          await loadVault();
        } catch (e) { toast("修改失败：" + e.message, "err"); }
      });
    },
    keyEdit: (name) => {
      const cur = (vaultState.keys || []).find((k) => k.name === name) ||
        { name: name || "", value: "", note: "" };
      const editing = (vaultState.keys || []).some((k) => k.name === name);
      openModal("<h3>" + (editing ? "编辑密钥" : "添加密钥") + "</h3>" +
        '<div class="f"><label>名称（环境变量名）</label><input type="text" id="k-name" value="' + esc(cur.name) + '"' +
        (editing ? " readonly" : ' placeholder="OPENCODE_GO_API_KEY"') + "></div>" +
        '<div class="f"><label>值</label><input type="password" id="k-value" value="' + esc(editing ? "" : "") + '" placeholder="' +
        (editing ? "留空则不修改" : "sk-…") + '"></div>' +
        '<div class="f"><label>备注（可选）</label><input type="text" id="k-note" value="' + esc(cur.note || "") + '"></div>' +
        '<div class="modal-actions"><button class="btn" data-close>取消</button><button class="btn primary" data-save>保存</button></div>');
      $("#modalBox [data-close]").addEventListener("click", closeModal);
      $("#modalBox [data-save]").addEventListener("click", async () => {
        const n = $("#k-name").value.trim();
        const val = $("#k-value").value;
        if (!n) { toast("名称不能为空", "err"); return; }
        try {
          let value = val;
          if (editing && !val) {
            const r = await API.api("/api/vault/keys?reveal=1");
            const old = (r.keys || []).find((k) => k.name === n);
            value = old ? old.value : "";
          }
          await API.api("/api/vault/keys/set", { method: "POST", body: { name: n, value: value, note: $("#k-note").value.trim() } });
          closeModal();
          toast("已保存：" + n, "ok");
          await loadVault();
        } catch (e) { toast("保存失败：" + e.message, "err"); }
      });
    },
    keyCopy: async (name) => {
      try {
        const r = await API.api("/api/vault/keys?reveal=1");
        const k = (r.keys || []).find((x) => x.name === name);
        if (!k) { toast("未找到该密钥", "err"); return; }
        if (navigator.clipboard && navigator.clipboard.writeText) {
          await navigator.clipboard.writeText(k.value);
          toast("已复制到剪贴板：" + name, "ok");
        } else {
          App.keyReveal(name);          // 剪贴板不可用时退回「显示」
        }
      } catch (e) { App.keyReveal(name); }
    },
    keyDelete: async (name) => {
      if (!confirm("确定删除密钥「" + name + "」？")) return;
      try {
        await API.api("/api/vault/keys/delete", { method: "POST", body: { name: name } });
        toast("已删除：" + name, "ok");
        await loadVault();
      } catch (e) { toast("删除失败：" + e.message, "err"); }
    },
    keyReveal: async (name) => {
      try {
        const r = await API.api("/api/vault/keys?reveal=1");
        const k = (r.keys || []).find((x) => x.name === name);
        openModal("<h3>" + esc(name) + "</h3>" +
          '<div class="f"><label>值</label><div style="font-family:monospace;word-break:break-all;font-size:12px">' +
          esc(k ? k.value : "（未找到）") + "</div></div>" +
          '<div class="modal-actions"><button class="btn primary" data-close>关闭</button></div>');
        $("#modalBox [data-close]").addEventListener("click", closeModal);
      } catch (e) { toast("读取失败：" + e.message, "err"); }
    },
    exportBundle: async () => {
      const pw = ($("#expPw") || {}).value || "";
      const pw2 = ($("#expPw2") || {}).value || "";
      if (String(pw).length < 6) { toast("导出密码至少 6 位", "err"); return; }
      if (pw !== pw2) { toast("两次输入的密码不一致", "err"); return; }
      const includeKeys = $("#expKeys") ? $("#expKeys").checked : false;
      try {
        const r = await API.api("/api/vault/export", { method: "POST", body: { password: pw, include_secrets: includeKeys } });
        toast("已导出：" + r.path + "（" + Math.round(r.bytes / 1024) + " KB，含 " + (r.keys || []).length + " 个密钥）", "ok");
      } catch (e) { toast("导出失败：" + e.message, "err"); }
    },
    importPreview: async () => {
      const f = $("#impFile") && $("#impFile").files && $("#impFile").files[0];
      const pw = ($("#impPw") || {}).value || "";
      if (!f) { toast("请先选择 .afpack 文件", "err"); return; }
      if (!pw) { toast("请输入导入密码", "err"); return; }
      try {
        const b64 = await readFileB64(f);
        vaultState.importB64 = b64;
        const r = await API.api("/api/vault/import", { method: "POST", body: { data_b64: b64, password: pw, dry_run: true } });
        vaultState.importPreview = r.preview;
        toast("预览成功，确认后可导入", "ok");
        renderVault($("#settingsContent"));
      } catch (e) { toast("预览失败：" + e.message, "err"); }
    },
    importApply: async () => {
      const pw = ($("#impPw") || {}).value || "";
      if (!vaultState.importB64) { toast("请先预览要导入的文件", "err"); return; }
      try {
        const r = await API.api("/api/vault/import", { method: "POST", body: {
          data_b64: vaultState.importB64, password: pw, dry_run: false, apply_config: true, import_keys: true } });
        vaultState.importPreview = null;
        vaultState.importB64 = null;
        const resp = await API.api("/api/config");
        cfg = resp.config;
        baseStr = JSON.stringify(cfg);
        applyTheme();
        refreshDirty();
        toast("导入完成：配置 " + (r.applied.config ? "已应用" : "未应用") + " · 密钥 " + r.applied.keys + " 个", "ok");
        await loadVault();
        renderPage();
      } catch (e) { toast("导入失败：" + e.message, "err"); }
    },
    testEndpoint: async (i) => {
      const ep = cfg.api_monitor.endpoints[i];
      apiState.testing[i] = true;
      renderApiCached();
      try {
        const r = await API.api("/api/api_monitor/test", { method: "POST", body: { endpoint: ep } });
        if (r.ok) {
          // 测试结果临时覆盖到卡片（仅本次会话显示，不改配置）
          apiState.results = apiState.results || [];
          apiState.results[i] = r.result;
          apiState.fetchedAt = new Date();
          toast("测试成功：" + (r.result.fields || []).map((f) => f.label + "=" + f.value).join("，"), "ok");
        } else {
          toast("测试失败：" + (r.result && r.result.error ? r.result.error : "未知错误"), "err");
        }
      } catch (e) { toast("测试请求失败：" + e.message, "err"); }
      apiState.testing[i] = false;
      renderApiCached();
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
    renderPage: renderPage,
  };

  document.addEventListener("DOMContentLoaded", init);
})();