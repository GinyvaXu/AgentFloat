/**
 * api.js — AgentFloat Web 壳后端封装（fetch + SSE）。
 *
 * v3.8.0 安全加固：本地 3087 接口需要访问令牌。
 * - Web 壳窗口/浏览器以 ?token=xxx 打开 → 存入 sessionStorage 并清理地址栏；
 * - 所有 /api 请求带 X-AgentFloat-Token（SSE 因无法自定义头，用 ?token=）；
 * - 缺令牌时 API 返回 401，此处弹出引导层让用户粘贴令牌。
 */
(function (global) {
  "use strict";

  var TOKEN_KEY = "agentfloat_token";

  function readToken() {
    var tok = "";
    try {
      var m = /[?&]token=([^&#]+)/.exec(global.location.search || "");
      if (m) {
        tok = decodeURIComponent(m[1]);
        try { global.sessionStorage.setItem(TOKEN_KEY, tok); } catch (e) { /* ignore */ }
        try {
          // 清理地址栏令牌（避免截图/历史记录留存）
          global.history.replaceState(null, "", global.location.pathname + (global.location.hash || ""));
        } catch (e) { /* ignore */ }
        return tok;
      }
    } catch (e) { /* ignore */ }
    try { return global.sessionStorage.getItem(TOKEN_KEY) || ""; } catch (e) { return ""; }
  }

  var TOKEN = readToken();

  function setToken(t) {
    TOKEN = t || "";
    try { global.sessionStorage.setItem(TOKEN_KEY, TOKEN); } catch (e) { /* ignore */ }
  }

  function authHeaders() {
    return TOKEN ? { "X-AgentFloat-Token": TOKEN } : {};
  }

  function withToken(path) {
    if (!TOKEN) return path;
    return path + (path.indexOf("?") >= 0 ? "&" : "?") + "token=" + encodeURIComponent(TOKEN);
  }

  async function api(path, options) {
    options = options || {};
    const init = {
      method: options.method || "GET",
      headers: Object.assign({ "Content-Type": "application/json" }, authHeaders()),
    };
    if (options.body !== undefined) init.body = JSON.stringify(options.body);
    const resp = await fetch(path, init);
    if (resp.status === 401) {
      showTokenGate();
      throw new Error("需要访问令牌（请在浮球右键菜单复制后粘贴）");
    }
    if (!resp.ok) {
      let detail = resp.statusText;
      try {
        const j = await resp.json();
        if (j.detail) detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
        if (j.error) detail = j.error;
      } catch (e) { /* ignore */ }
      throw new Error(detail);
    }
    return resp.json();
  }

  /** 订阅 SSE：onEvent({event,payload,ts})；断线自动重连。 */
  function streamEvents(onEvent) {
    function connect() {
      const es = new EventSource(withToken("/api/events"));
      es.onmessage = function (e) {
        try {
          const ev = JSON.parse(e.data);
          onEvent(ev);
        } catch (err) { /* ignore */ }
      };
      es.onerror = function () {
        es.close();
        setTimeout(connect, 2500);
      };
    }
    connect();
  }

  /** 缺令牌引导层：粘贴令牌后写入 sessionStorage 并重载 */
  function showTokenGate() {
    if (document.getElementById("af-token-gate")) return;
    const wrap = document.createElement("div");
    wrap.id = "af-token-gate";
    wrap.style.cssText = "position:fixed;inset:0;z-index:99999;display:flex;" +
      "align-items:center;justify-content:center;background:rgba(20,20,24,0.72);" +
      "backdrop-filter:blur(6px);font:14px/1.6 system-ui,'Microsoft YaHei',sans-serif";
    wrap.innerHTML =
      '<div style="width:min(460px,90vw);background:var(--surface,#fff);color:var(--text,#1d1d1f);' +
      'border-radius:16px;padding:24px 26px;box-shadow:0 24px 60px rgba(0,0,0,.35)">' +
      '<div style="font-size:17px;font-weight:700;margin-bottom:6px">需要访问令牌</div>' +
      '<div style="color:var(--text2,#6e6e73);margin-bottom:14px">' +
      '本地接口已启用鉴权（防止网页隔空读取密钥）。<br>' +
      '请在<b>浮球右键菜单 → 复制 Web 控制台令牌</b>，或在此粘贴令牌。</div>' +
      '<input id="af-token-input" placeholder="粘贴访问令牌" style="width:100%;box-sizing:border-box;' +
      'padding:10px 12px;border-radius:10px;border:1px solid var(--input-border,#d1d1d6);' +
      'background:var(--surface2,#f7f7fa);color:inherit;font-size:13px">' +
      '<div style="display:flex;gap:10px;justify-content:flex-end;margin-top:16px">' +
      '<button id="af-token-ok" style="padding:8px 18px;border:0;border-radius:10px;cursor:pointer;' +
      'background:var(--accent,#0a84ff);color:#fff;font-weight:600">确定</button></div></div>';
    document.body.appendChild(wrap);
    const input = document.getElementById("af-token-input");
    const submit = function () {
      const v = (input.value || "").trim();
      if (!v) return;
      setToken(v);
      global.location.reload();
    };
    document.getElementById("af-token-ok").addEventListener("click", submit);
    input.addEventListener("keydown", function (e) { if (e.key === "Enter") submit(); });
    input.focus();
  }

  global.API = {
    api: api,
    streamEvents: streamEvents,
    setToken: setToken,
    token: function () { return TOKEN; },
    hasToken: function () { return !!TOKEN; },
    tokenGate: showTokenGate,
  };
})(window);
