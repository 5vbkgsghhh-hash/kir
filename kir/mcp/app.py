"""MCP APP: A FLOOR PLAN LIVE IN THE DIALOGUE (the `io.modelcontextprotocol/ui`
extension).

Stage 3 of the plan. NOT A SINGLE LINE IS DRAWN HERE: `preview.render_svg`
already prints a deterministic SVG, and `PreviewCensus` already carries a
census of what is NOT in the picture. The app presents them — and adds
exactly what a picture in text cannot have: scale, sheet selection, and a
return channel of "the human tapped — the model found out."

🔴 LAW #4 RIDES INTO THE HOST WHOLE, NOT AS A PICTURE. The census is not
panel decoration: "412 of 480 drawn, 68 not drawn for named reasons" is a
statement of the same force as the drawing itself. An app that showed the
plan and stayed silent about what was not drawn would lie more
convincingly than text does.

🔴 NOT ONE EXTERNAL RESOURCE. The host renders the document in a sandboxed
iframe with its own CSP; any outward `<script src>` and `<link href>`
either silently fails to load, or requires declared domains. Everything
here is internal, so there is nothing to declare: `_meta.ui.csp` is never
issued at all.

🔴 DEGRADATION IS NAMED (SEP-2133). A client without the extension gets
THE SAME tool result — an SVG string and a census dictionary. The app adds
nothing to the CONTENT of the response; it adds how it is handled.
"""
from __future__ import annotations

#: The resource URI. The `ui://` scheme is mandatory — the host uses it
#: to tell the app's document apart from an ordinary resource.
APP_URI = "ui://kir/floorplan.html"

#: The MIME type ext-apps uses to mark the app's document. The literal
#: repeats `mcp.server.apps.APP_MIME_TYPE`, and this is NOT a second
#: carrier of the truth: our server sits at the SDK's lower level, where
#: the extension is assembled by hand, and pulling the constant from
#: `mcp.server.apps` would mean importing the SDK into a module that has no
#: right to it (the door's boundary, `BOUNDARY.md`: the SDK lives in one
#: file). An instrument checks both values against each other —
#: `tests/test_the_app_is_wired.py`.
APP_MIME_TYPE = "text/html;profile=mcp-app"

#: The extension's identifier (SEP-2133). The same argument about the
#: literal.
UI_EXTENSION_ID = "io.modelcontextprotocol/ui"

#: The version of the iframe↔host protocol the app presents itself with.
UI_PROTOCOL_VERSION = "2026-01-26"


HTML = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>KIR — план этажа</title>
<style>
  :root {
    --bg: #ffffff; --fg: #16181d; --muted: #62676f; --line: #e2e5ea;
    --accent: #1f6feb; --warn: #9a5b00; --warn-bg: #fff5e6; --panel: #f7f8fa;
    --sel: #d4380d;
  }
  :root[data-theme="dark"] {
    --bg: #14161a; --fg: #e8eaed; --muted: #9aa1ab; --line: #2b2f36;
    --accent: #5aa0ff; --warn: #e0a03a; --warn-bg: #2a2110; --panel: #1b1e23;
    --sel: #ff7a5c;
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--fg); font: 13px/1.5
         ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
  header { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap;
           padding: 10px 14px; border-bottom: 1px solid var(--line); }
  h1 { font-size: 14px; margin: 0; font-weight: 600; letter-spacing: .2px; }
  .assertion { font-size: 11px; color: var(--warn); background: var(--warn-bg);
               border: 1px solid var(--line); border-radius: 999px;
               padding: 2px 9px; }
  .tabs { display: flex; gap: 6px; overflow-x: auto; padding: 8px 14px;
          border-bottom: 1px solid var(--line); }
  .tabs button { font: inherit; color: var(--fg); background: transparent;
                 border: 1px solid var(--line); border-radius: 6px;
                 padding: 4px 10px; cursor: pointer; white-space: nowrap; }
  .tabs button[aria-selected="true"] { border-color: var(--accent);
                 color: var(--accent); font-weight: 600; }
  main { display: grid; grid-template-columns: minmax(0,1fr) 300px; gap: 0;
         align-items: stretch; min-height: 320px; }
  @media (max-width: 720px) { main { grid-template-columns: minmax(0,1fr); } }
  #stage { position: relative; overflow: hidden; background: var(--bg);
           cursor: grab; touch-action: none; }
  #stage.dragging { cursor: grabbing; }
  #stage svg { display: block; width: 100%; height: 100%; }
  #zoombar { position: absolute; right: 10px; bottom: 10px; display: flex;
             gap: 4px; }
  #zoombar button { width: 28px; height: 28px; font: 15px/1 ui-monospace,
             monospace; border: 1px solid var(--line); background: var(--panel);
             color: var(--fg); border-radius: 6px; cursor: pointer; }
  aside { border-left: 1px solid var(--line); background: var(--panel);
          padding: 12px 14px; overflow: auto; max-height: 70vh; }
  @media (max-width: 720px) { aside { border-left: 0;
          border-top: 1px solid var(--line); } }
  aside h2 { font-size: 12px; text-transform: uppercase; letter-spacing: .6px;
             color: var(--muted); margin: 0 0 8px; font-weight: 600; }
  .bar { height: 6px; border-radius: 3px; background: var(--line);
         overflow: hidden; margin: 6px 0 10px; }
  .bar i { display: block; height: 100%; background: var(--accent); }
  .num { font: 600 20px/1.2 ui-monospace, monospace; }
  .sub { color: var(--muted); font-size: 12px; }
  ul { list-style: none; margin: 8px 0 0; padding: 0; }
  li { border-top: 1px solid var(--line); padding: 7px 0; }
  li .k { display: flex; justify-content: space-between; gap: 10px; }
  li .why { color: var(--muted); font-size: 12px; }
  li .ex { color: var(--muted); font-size: 11px; font-family: ui-monospace,
           monospace; overflow-wrap: anywhere; }
  .empty { color: var(--muted); padding: 24px 14px; }
  [data-el].kir-sel { outline: 2px solid var(--sel); outline-offset: 1px; }
  footer { padding: 8px 14px; border-top: 1px solid var(--line);
           color: var(--muted); font-size: 11px; }
</style>
</head>
<body>
<header>
  <h1 id="title">KIR — план этажа</h1>
  <span class="assertion" id="assertion" hidden></span>
  <span class="sub" id="docname"></span>
</header>
<div class="tabs" id="tabs" hidden></div>
<main>
  <div id="stage">
    <div class="empty" id="empty">Жду результат инструмента <code>kir_preview</code>…</div>
    <div id="zoombar" hidden>
      <button id="zin" title="Крупнее">+</button>
      <button id="zout" title="Мельче">&minus;</button>
      <button id="zfit" title="Вписать">&#9633;</button>
    </div>
  </div>
  <aside id="census"></aside>
</main>
<footer id="foot"></footer>
<script>
(function () {
  "use strict";
  var nextId = 1, pending = {}, sheets = [], current = 0;

  function send(method, params) {
    var id = nextId++;
    return new Promise(function (resolve, reject) {
      pending[id] = { resolve: resolve, reject: reject };
      window.parent.postMessage(
        { jsonrpc: "2.0", id: id, method: method, params: params || {} }, "*");
    });
  }
  function notify(method, params) {
    window.parent.postMessage(
      { jsonrpc: "2.0", method: method, params: params || {} }, "*");
  }

  window.addEventListener("message", function (event) {
    var m = event.data;
    if (!m || m.jsonrpc !== "2.0") { return; }
    if (m.id !== undefined && pending[m.id]) {
      var slot = pending[m.id]; delete pending[m.id];
      if (m.error) { slot.reject(new Error(m.error.message || "ошибка хоста")); }
      else { slot.resolve(m.result); }
      return;
    }
    if (m.method === "ui/notifications/tool-result") { onResult(m.params); }
    else if (m.method === "ui/notifications/tool-cancelled") {
      say("Вызов отменён хостом: " + ((m.params && m.params.reason) || "без причины"));
    }
  });

  function say(text) {
    var e = document.getElementById("empty");
    if (e) { e.hidden = false; e.textContent = text; }
  }

  function applyTheme(ctx) {
    var theme = ctx && (ctx.theme || (ctx.styles && ctx.styles.theme));
    if (theme === "dark" || theme === "light") {
      document.documentElement.setAttribute("data-theme", theme);
    }
  }

  send("ui/initialize", {
    appCapabilities: {},
    clientInfo: { name: "kir-floorplan", version: "1" },
    protocolVersion: "2026-01-26"
  }).then(function (res) {
    applyTheme(res && res.hostContext);
    notify("ui/notifications/initialized", {});
  }).catch(function (err) {
    say("Хост не ответил на ui/initialize: " + err.message);
  });

  // ── результат инструмента ────────────────────────────────────────────
  function onResult(result) {
    var body = result && (result.structuredContent || result.structured_content);
    if (!body) { say("Ответ без структурной части — рисовать нечего."); return; }
    if (body.ok === false) {
      say((body.err && body.err.message_ru) || "Инструмент отказал.");
      return;
    }
    sheets = body.sheets || [];
    document.getElementById("docname").textContent = body.doc_name || "";
    var a = document.getElementById("assertion");
    if (body.assertion === "self_reported") {
      a.hidden = false;
      a.textContent = "заявлено автором — модель не читалась";
    } else if (body.assertion) { a.hidden = false; a.textContent = body.assertion; }
    if (!sheets.length) { say("Программа не дала ни одного плана этажа."); return; }
    buildTabs(); show(0);
  }

  function buildTabs() {
    var box = document.getElementById("tabs");
    box.innerHTML = ""; box.hidden = sheets.length < 2;
    sheets.forEach(function (s, i) {
      var b = document.createElement("button");
      b.textContent = s.level || ("лист " + (i + 1));
      b.setAttribute("aria-selected", String(i === current));
      b.addEventListener("click", function () { show(i); });
      box.appendChild(b);
    });
  }

  // ── масштаб и панорама ───────────────────────────────────────────────
  var view = { x: 0, y: 0, k: 1 }, svgEl = null;

  function paint() {
    if (!svgEl) { return; }
    svgEl.style.transformOrigin = "0 0";
    svgEl.style.transform = "translate(" + view.x + "px," + view.y + "px) scale(" + view.k + ")";
  }
  function fit() { view = { x: 0, y: 0, k: 1 }; paint(); }

  var stage = document.getElementById("stage"), drag = null;
  stage.addEventListener("pointerdown", function (e) {
    if (!svgEl) { return; }
    drag = { x: e.clientX - view.x, y: e.clientY - view.y };
    stage.classList.add("dragging"); stage.setPointerCapture(e.pointerId);
  });
  stage.addEventListener("pointermove", function (e) {
    if (!drag) { return; }
    view.x = e.clientX - drag.x; view.y = e.clientY - drag.y; paint();
  });
  stage.addEventListener("pointerup", function () {
    drag = null; stage.classList.remove("dragging");
  });
  stage.addEventListener("wheel", function (e) {
    if (!svgEl) { return; }
    e.preventDefault();
    var f = e.deltaY < 0 ? 1.12 : 1 / 1.12,
        r = stage.getBoundingClientRect(),
        px = e.clientX - r.left, py = e.clientY - r.top;
    view.x = px - (px - view.x) * f; view.y = py - (py - view.y) * f;
    view.k *= f; paint();
  }, { passive: false });
  document.getElementById("zin").addEventListener("click", function () { view.k *= 1.2; paint(); });
  document.getElementById("zout").addEventListener("click", function () { view.k /= 1.2; paint(); });
  document.getElementById("zfit").addEventListener("click", fit);

  // ── лист ─────────────────────────────────────────────────────────────
  function show(i) {
    current = i;
    var sheet = sheets[i];
    Array.prototype.forEach.call(
      document.getElementById("tabs").children, function (b, j) {
        b.setAttribute("aria-selected", String(j === i));
      });
    var old = stage.querySelector("svg"); if (old) { old.remove(); }
    document.getElementById("empty").hidden = true;
    document.getElementById("zoombar").hidden = false;

    if (!sheet.svg) {
      document.getElementById("zoombar").hidden = true;
      say(sheet.svg_withheld_ru || "Чертёж не вложен.");
    } else {
      var holder = document.createElement("div");
      holder.innerHTML = sheet.svg;
      svgEl = holder.querySelector("svg");
      if (svgEl) {
        stage.insertBefore(svgEl, document.getElementById("zoombar"));
        svgEl.addEventListener("click", onPick);
        fit();
      }
    }
    renderCensus(sheet.census);
    document.getElementById("foot").textContent =
      "лист " + (i + 1) + " из " + sheets.length +
      (sheet.chars ? " · " + sheet.chars + " знаков SVG" : "");
  }

  // ── обратный канал: человек ткнул — модель узнала ────────────────────
  var picked = null;
  function onPick(e) {
    var node = e.target;
    while (node && node !== svgEl && !node.getAttribute("data-el")) {
      node = node.parentNode;
    }
    if (!node || node === svgEl) { return; }
    if (picked) { picked.classList.remove("kir-sel"); }
    picked = node; picked.classList.add("kir-sel");
    var id = node.getAttribute("data-el"),
        cat = node.getAttribute("data-cat") || "";
    send("ui/update-model-context", {
      structuredContent: {
        picked_element: id, category: cat,
        level: sheets[current] && sheets[current].level
      }
    }).catch(function () { /* хост вправе не принять — план от этого не ломается */ });
  }

  // ── перепись: ЗАКОН №4 на экране ─────────────────────────────────────
  function group(title, rows, kind) {
    if (!rows || !rows.length) { return ""; }
    var out = "<h2>" + title + "</h2><ul>";
    rows.forEach(function (g) {
      out += "<li><div class='k'><span class='why'>" + esc(g.reason) +
             (g.category ? " · " + esc(g.category) : "") +
             "</span><b>" + g.count + "</b></div>";
      if (g.examples && g.examples.length) {
        out += "<div class='ex'>" + esc(g.examples.slice(0, 4).join(", ")) + "</div>";
      }
      out += "</li>";
    });
    return out + "</ul>";
  }
  function esc(s) {
    return String(s === undefined || s === null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
  function renderCensus(c) {
    var box = document.getElementById("census");
    if (!c) { box.innerHTML = "<h2>перепись</h2><p class='sub'>не подана</p>"; return; }
    var pct = c.vacuous ? 0 : (c.coverage_pct || 0);
    box.innerHTML =
      "<h2>нарисовано</h2>" +
      "<div class='num'>" + c.drawn + " <span class='sub'>из " + c.considered + "</span></div>" +
      "<div class='bar'><i style='width:" + Math.max(0, Math.min(100, pct)) + "%'></i></div>" +
      (c.vacuous
        ? "<p class='sub'>рассматривать было нечего — это не 100 % покрытия</p>"
        : "<p class='sub'>" + pct.toFixed(1) + " % · не нарисовано " + c.omitted_total + "</p>") +
      group("чего на чертеже НЕТ", c.omitted) +
      group("нарисовано приближённо", c.approx) +
      group("аномалии", c.anomalies);
  }
})();
</script>
</body>
</html>
"""
