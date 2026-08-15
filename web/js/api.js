/**
 * api.js — AgentFloat Web 壳后端封装（fetch + SSE）。
 */
(function (global) {
  "use strict";

  async function api(path, options) {
    options = options || {};
    const init = {
      method: options.method || "GET",
      headers: { "Content-Type": "application/json" },
    };
    if (options.body !== undefined) init.body = JSON.stringify(options.body);
    const resp = await fetch(path, init);
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
      const es = new EventSource("/api/events");
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

  global.API = { api: api, streamEvents: streamEvents };
})(window);