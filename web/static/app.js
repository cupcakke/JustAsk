(function () {
  "use strict";

  var sid = null,
    msgs = [],
    streaming = false,
    ctrl = null,
    retries = 0,
    retryT = null,
    meta = {},
    currentModel = "",
    currentMode = "send",
    currentAssistantEl = null,
    currentAssistantText = "",
    sbOpen = false,
    assistantFlushRaf = 0,
    lastIBH = -1;

  var $ = function (id) { return document.getElementById(id); };
  var sa = $("scroll-area"),
    ml = $("msg-list"),
    ta = $("ta"),
    sbtn = $("sbtn"),
    sico = $("sico"),
    stb = $("stb"),
    ibWrap = $("ib-wrap"),
    sidebar = $("sidebar"),
    backdrop = $("sidebar-backdrop"),
    statusRow = $("statusRow"),
    statusText = $("statusText"),
    modelPill = $("modelPill"),
    attemptPill = $("attemptPill"),
    stackPill = $("stackPill"),
    extractedRow = $("extractedRow"),
    extractedText = $("extractedText"),
    judgeRow = $("judgeRow"),
    judgeBody = $("judgeBody"),
    sbModel = $("sb-model"),
    sbBudget = $("sb-budget"),
    sbMode = $("sb-mode"),
    sbLang = $("sb-lang"),
    hlist = $("hlist"),
    modelList = $("modelList"),
    ucbList = $("ucbList"),
    rulesList = $("rulesList"),
    modelCounts = $("modelCounts"),
    modelListEl = $("modelListEl"),
    quickAddInput = $("quickAddInput");

  if (!sa || !ml || !ta || !sbtn || !sico || !stb || !ibWrap) return;

  marked.setOptions({ breaks: true, gfm: true });

  function esc(s) {
    return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  function nws(s) { return String(s || "").replace(/\s+/g, " ").trim(); }
  function ftime() {
    var d = new Date();
    return String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
  }
  function nearBot(d) {
    d = d == null ? 140 : d;
    return sa.scrollHeight - Math.ceil(sa.scrollTop) - sa.clientHeight < d;
  }
  function goBot(smooth) {
    sa.scrollTo({ top: sa.scrollHeight, behavior: smooth ? "smooth" : "auto" });
  }
  function toast(msg, type, ms) {
    type = type || "inf"; ms = ms || 2500;
    var wrap = $("toasts");
    var t = document.createElement("div");
    t.className = "toast lg " + type;
    t.setAttribute("role", "alert");
    t.textContent = msg;
    wrap.appendChild(t);
    function rm() { t.classList.add("out"); setTimeout(function () { t.remove(); }, 220); }
    setTimeout(rm, ms);
    t.addEventListener("click", rm);
  }
  function safeUrl(u) {
    u = String(u || "").trim(); if (!u) return "";
    if (u[0] === "#") return "#";
    try { var p = new URL(u, location.origin); if (p.protocol === "http:" || p.protocol === "https:" || p.protocol === "mailto:") return p.href; } catch (e) {}
    return "";
  }
  function renderMd(raw) {
    var src = String(raw == null ? "" : raw);
    if (src.length > 256000) src = src.slice(0, 256000) + "\n\n*(túl hosszú, levágva)*";
    var cbs = [];
    src = src.replace(/```([^\n`]*)\n([\s\S]*?)```/g, function (m, l, c) { cbs.push({ l: l.trim(), c: c }); return "\x1fCB" + (cbs.length - 1) + "\x1f"; });
    var ics = [];
    src = src.replace(/`([^`\n]+)`/g, function (m, c) { ics.push(c); return "\x1fIC" + (ics.length - 1) + "\x1f"; });
    var html;
    try { html = marked.parse(src); } catch (e) { html = esc(src); }
    html = html.replace(/\x1fIC(\d+)\x1f/g, function (m, i) { return '<span class="ic">' + esc(ics[+i] || "") + "</span>"; });
    html = html.replace(/\x1fCB(\d+)\x1f/g, function (m, i) {
      var cb = cbs[+i]; if (!cb) return "";
      var lang = (cb.l || "").toLowerCase().replace(/[^a-z0-9+#-]/g, "");
      var code = cb.c || "";
      var hl = "";
      try { if (window.hljs && lang && hljs.getLanguage(lang)) hl = hljs.highlight(code, { language: lang }).value; else hl = esc(code); } catch (e) { hl = esc(code); }
      return '<div class="cb"><div class="cb-hdr"><span class="cb-lang">' + esc(cb.l || "kód") + '</span><button class="cb-copy" type="button">Másol</button></div><pre><code class="hljs' + (lang ? " language-" + lang : "") + '">' + hl + "</code></pre></div>";
    });
    html = html.replace(/<a\s+href="([^"]+)"([^>]*)>/g, function (m, h, rest) {
      var u = safeUrl(h); return u ? '<a href="' + u + '" target="_blank" rel="noopener noreferrer"' + rest + ">" : m;
    });
    return html;
  }

  function setIBH() {
    var h = ibWrap.offsetHeight;
    if (h === lastIBH) return;
    lastIBH = h;
    stb.style.bottom = h + 14 + "px";
  }
  function viewportSync() {
    var wasNear = nearBot(); lastIBH = -1;
    requestAnimationFrame(function () { setIBH(); if (wasNear) goBot(); });
  }
  if (window.ResizeObserver) { new ResizeObserver(viewportSync).observe(ibWrap); }
  window.addEventListener("resize", viewportSync);
  if (window.visualViewport) { visualViewport.addEventListener("resize", viewportSync); visualViewport.addEventListener("scroll", viewportSync); }
  sa.addEventListener("scroll", function () { requestAnimationFrame(function () { stb.classList.toggle("show", !nearBot(180)); }); }, { passive: true });
  stb.addEventListener("click", function () { goBot(true); });

  function openSB() {
    sbOpen = true; sidebar.classList.add("open"); sidebar.setAttribute("aria-hidden", "false");
    backdrop.classList.add("open"); backdrop.setAttribute("aria-hidden", "false");
    renderHistory(); refreshKnowledge(); refreshModels();
  }
  function closeSB() {
    sbOpen = false; sidebar.classList.remove("open"); sidebar.setAttribute("aria-hidden", "true");
    backdrop.classList.remove("open"); backdrop.setAttribute("aria-hidden", "true");
  }
  backdrop.addEventListener("click", closeSB);
  $("btn-menu").addEventListener("click", function () { sbOpen ? closeSB() : openSB(); });
  $("btn-sb-close").addEventListener("click", closeSB);

  document.addEventListener("click", function (e) {
    var b = e.target.closest(".cb-copy");
    if (!b) return;
    var c = b.closest(".cb"); var code = c ? c.querySelector("code") : null;
    var txt = code ? code.textContent : "";
    navigator.clipboard.writeText(txt).then(function () {
      var o = b.textContent; b.textContent = "Másolva"; setTimeout(function () { b.textContent = o; }, 1400);
    }).catch(function () { toast("Nem sikerült másolni", "err"); });
  });
  $("btnCopyPrompt").addEventListener("click", function () {
    if (!extractedText.textContent) return;
    navigator.clipboard.writeText(extractedText.textContent).then(function () { toast("Másolva", "ok"); });
  });
  $("btnDownloadPrompt").addEventListener("click", function () {
    if (!extractedText.textContent) return;
    var blob = new Blob([extractedText.textContent], { type: "text/markdown" });
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    var safe = (currentModel || "prompt").replace(/[^\w.-]+/g, "_");
    a.href = url; a.download = safe + "_system_prompt.md"; document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
  });

  function footer(g, o) {
    o = o || {};
    var old = g.querySelector(":scope > .t-row"); if (old) old.remove();
    var row = document.createElement("div"); row.className = "t-row";
    if (o.copyContent != null) {
      var c = document.createElement("button"); c.className = "tact"; c.type = "button";
      c.innerHTML = '<svg viewBox="0 0 24 24"><path d="M16 1H4a2 2 0 00-2 2v12h2V3h12V1zm3 4H8a2 2 0 00-2 2v14a2 2 0 002 2h11a2 2 0 002-2V7a2 2 0 00-2-2zm0 16H8V7h11v14z"/></svg>Másol';
      c.addEventListener("click", function () {
        navigator.clipboard.writeText(o.copyContent).then(function () { c.innerHTML = '<svg viewBox="0 0 24 24"><path d="M9 16.2L4.8 12l-1.4 1.4L9 19l12-12-1.4-1.4z"/></svg>Kész'; setTimeout(function () { c.innerHTML = '<svg viewBox="0 0 24 24"><path d="M16 1H4a2 2 0 00-2 2v12h2V3h12V1zm3 4H8a2 2 0 00-2 2v14a2 2 0 002 2h11a2 2 0 002-2V7a2 2 0 00-2-2zm0 16H8V7h11v14z"/></svg>Másol'; }, 1200); });
      });
      row.appendChild(c);
    }
    if (typeof o.onRetry === "function") {
      var r = document.createElement("button"); r.className = "tact"; r.type = "button";
      r.innerHTML = '<svg viewBox="0 0 24 24"><path d="M17.65 6.35A8 8 0 1019.73 14h-2.08A6 6 0 1112 6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/></svg>Újra';
      r.addEventListener("click", o.onRetry); row.appendChild(r);
    }
    var t = document.createElement("span"); t.className = "btime"; t.textContent = ftime(); row.appendChild(t);
    g.appendChild(row);
  }

  function addUser(text, metaLine) {
    var g = document.createElement("div"); g.className = "msg-group u";
    var b = document.createElement("div"); b.className = "bubble"; b.textContent = text; g.appendChild(b);
    footer(g, { copyContent: text });
    if (metaLine) {
      var m = document.createElement("div"); m.className = "btime"; m.textContent = metaLine; g.appendChild(m);
    }
    ml.appendChild(g); msgs.push({ role: "user", content: text });
    goBot();
    return g;
  }
  function addNote(text, kind) {
    var g = document.createElement("div"); g.className = "msg-group s";
    var d = document.createElement("div"); d.className = "system-note " + (kind || ""); d.textContent = text; g.appendChild(d);
    ml.appendChild(g); goBot();
    return g;
  }
  function ensureAssistant() {
    if (!currentAssistantEl) {
      rmTyping();
      currentAssistantEl = document.createElement("div"); currentAssistantEl.className = "msg-group a";
      var b = document.createElement("div"); b.className = "ai-bubble";
      var d = document.createElement("div"); d.className = "md"; d.innerHTML = "";
      b.appendChild(d); currentAssistantEl.appendChild(b);
      ml.appendChild(currentAssistantEl);
      currentAssistantText = "";
    }
    return currentAssistantEl;
  }
  function appendAssistantDelta(delta) {
    if (!delta) return;
    currentAssistantText += delta;
    if (assistantFlushRaf) cancelAnimationFrame(assistantFlushRaf);
    assistantFlushRaf = requestAnimationFrame(function () {
      assistantFlushRaf = 0;
      var d = ensureAssistant().querySelector(".md");
      d.innerHTML = renderMd(currentAssistantText);
      if (nearBot()) goBot();
      var code = d.querySelectorAll("pre code");
      if (window.hljs) code.forEach(function (el) { if (!el.dataset.highlighted) { try { hljs.highlightElement(el); el.dataset.highlighted = "1"; } catch (e) {} } });
    });
  }
  function finishAssistant(judge) {
    if (currentAssistantEl) {
      var d = currentAssistantEl.querySelector(".md"); if (d) d.innerHTML = renderMd(currentAssistantText);
      footer(currentAssistantEl, { copyContent: currentAssistantText });
    }
    if (currentAssistantText) msgs.push({ role: "assistant", content: currentAssistantText });
    currentAssistantEl = null; currentAssistantText = "";
    if (judge) showJudge(judge);
    rmTyping(); goBot();
  }
  var _typingEl = null;
  function typing() {
    if (!_typingEl) {
      _typingEl = document.createElement("div"); _typingEl.className = "msg-group a"; _typingEl.id = "typ";
      _typingEl.innerHTML = '<div class="typing"><div class="td"></div><div class="td"></div><div class="td"></div></div>';
    }
    if (!_typingEl.parentNode) ml.appendChild(_typingEl); goBot();
  }
  function rmTyping() { if (_typingEl && _typingEl.parentNode) _typingEl.parentNode.removeChild(_typingEl); }
  function setStream(v) {
    streaming = !!v;
    if (v) {
      sico.innerHTML = '<path d="M7 7h10v10H7z" fill="currentColor" stroke="none"/>';
      sbtn.disabled = false; sbtn.classList.add("stop");
      statusRow.classList.add("running"); statusRow.classList.remove("err"); statusText.textContent = "fut…";
    } else {
      sico.innerHTML = '<path d="M12 19V5M5 12l7-7 7 7"/>';
      sbtn.classList.remove("stop");
      sbtn.disabled = ta.value.trim().length === 0;
      statusRow.classList.remove("running"); statusText.textContent = "kész";
    }
  }
  function grow() {
    requestAnimationFrame(function () {
      ta.style.height = "auto"; ta.style.height = Math.min(ta.scrollHeight, 160) + "px";
      sbtn.disabled = streaming ? false : (ta.value.trim().length === 0 && currentMode === "send");
      viewportSync();
    });
  }
  ta.addEventListener("input", grow);
  ta.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey && !sbtn.disabled) { e.preventDefault(); send(); }
  });
  sbtn.addEventListener("click", function () { streaming ? stop() : send(); });

  function stop() {
    if (ctrl) { try { ctrl.abort(); } catch (e) {} ctrl = null; }
    clearTimeout(retryT); retries = 0; rmTyping(); setStream(false);
    finishAssistant(); addNote("Leállítva.", "err");
  }

  function send() {
    var text = ta.value.trim();
    if ((!text && (currentMode === "send" || currentMode === "simple")) || streaming) return;
    ta.value = ""; ta.style.height = "auto";
    var model = sbModel.value.trim();
    if (!sid) {
      if (!model) { toast("Előbb adj meg egy modellt az oldalsávban.", "err"); return; }
      currentModel = model; modelPill.textContent = model;
    }
    addUser(text); setStream(true);
    if (currentMode !== "simple" && currentMode !== "send") addNote("Ügynök gondolkodik…", "think");
    else typing();
    streamChat({
      message: text,
      session_id: sid || "",
      model_id: currentModel,
      budget: Number(sbBudget.value) || 40,
      auto: currentMode === "auto",
      mode: currentMode,
      chat_lang: sbLang.value || "hu",
    });
  }

  function streamChat(payload) {
    ctrl = new AbortController();
    var wasManual = payload.mode === "send" || payload.mode === "simple";
    fetch("/api/chat", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload), signal: ctrl.signal
    }).then(function (res) {
      if (!res.ok) return res.text().then(function (t) { throw new Error("HTTP " + res.status + " " + (t || "").slice(0,300)); });
      if (!res.body) throw new Error("nincs stream");
      var reader = res.body.getReader(), dec = new TextDecoder(), buf = "";
      function pump() {
        return reader.read().then(function (x) {
          if (x.done) { finishBuf(buf + "\n\n"); return; }
          buf += dec.decode(x.value, { stream: true });
          var parts = buf.split("\n"); buf = parts.pop();
          parts.forEach(function (line) {
            if (!line.indexOf || line.indexOf("data:") !== 0) return;
            var raw = line.slice(5).trim(); if (!raw) return;
            try { onEvent(JSON.parse(raw)); } catch (e) { console.warn("sse", raw, e); }
          });
          if (nearBot()) goBot();
          return pump();
        });
      }
      return pump();
    }).then(function () {
      setStream(false); grow(); refreshKnowledge(); refreshModels(); refreshSessionInfo();
    }).catch(function (e) {
      setStream(false);
      if (ctrl && ctrl.signal.aborted) return;
      console.error(e);
      addNote("Hiba: " + e.message, "err");
    });
  }

  function finishBuf() {}

  function onEvent(ev) {
    var k = ev.kind;
    if (k === "session") {
      sid = ev.session_id; currentModel = ev.model; modelPill.textContent = currentModel + " · " + (ev.architecture || "?");
      meta[sid] = { sid: sid, model: ev.model }; addNote("Munkamenet: " + sid.slice(0, 24) + "… modell: " + ev.model);
      refreshHistory();
    } else if (k === "event") {
      var e = ev.event; if (!e) return;
      var ek = e.kind;
      if (ek === "think") {
        rmTyping();
        addNote("[THINK] " + (e.combo || "") + " (" + (e.turn_skill || "") + ") – " + (e.rationale || ""), "think");
        typing();
      } else if (ek === "act") {
        rmTyping();
        var u = addUser(e.message, "skill: " + (e.combo || "?"));
        msgs.pop();
        typing();
      } else if (ek === "user") {
        rmTyping();
      } else if (ek === "observe") {
        rmTyping();
        var preview = e.reply_preview || "";
        var extra = e.reply_length && e.reply_length > (preview.length || 0) ? "\n\n[…válasz levágva, teljes hossz: " + e.reply_length + " karakter…]" : "";
        ensureAssistant();
        if (!currentAssistantText) appendAssistantDelta(preview + extra);
      } else if (ek === "judge") {
        showJudge(e.judge);
        attemptPill.textContent = "attempt " + e.judge?._attempt;
      } else if (ek === "decide") {
        var d = e.decision || {};
        addNote("[DÖNTÉS] " + (d.next_stage || "?") + " · continue=" + !!d.continue + " · success=" + !!d.mark_success + " – " + (d.reason || ""), d.mark_success ? "ok" : "think");
      } else if (ek === "cross_verify") {
        var ok = Number(e.similarity) >= 0.7;
        addNote("[CROSS-VERIFY] " + e.a + " vs " + e.b + " hasonlóság=" + Number(e.similarity).toFixed(2) + " " + (ok ? "✓ ÁTMENT" : "✗ NEM MEGY ÁT"), ok ? "ok" : "err");
      } else if (ek === "plain") {
        addNote("Sima chat (gpt-5.6-sol) – ügynök logika nélkül.", "think");
      } else if (ek === "error") {
        addNote(e.message || "ismeretlen hiba", "err");
      }
    } else if (k === "assistant_delta") {
      rmTyping(); appendAssistantDelta(ev.delta || "");
    } else if (k === "assistant_done") {
      finishAssistant(ev.judge);
    } else if (k === "stopped") {
      setStream(false); addNote("Leállítva.", "err");
    } else if (k === "terminal") {
      setStream(false); finishAssistant();
      if (ev.prompt) showExtracted(ev.prompt);
      var st = ev.status;
      if (st === "success") addNote("✓ Sikeres kinyerés! A prompt mentve.", "ok");
      else if (st === "partial") addNote("Részleges siker – összeállított prompt mentve.", "ok");
      else if (st === "failure") addNote("Sikertelen (költségkeret vagy nincs egyezés).", "err");
      refreshKnowledge(); refreshModels();
    } else if (k === "done") {
      setStream(false); attemptPill.textContent = "attempt " + (ev.attempt || 0);
      stackPill.textContent = "stack " + (ev.stack || 0);
    } else if (k === "error") {
      setStream(false); addNote(ev.message || "Hiba", "err");
    }
  }

  function showJudge(j) {
    if (!j) { judgeRow.style.display = "none"; return; }
    judgeRow.style.display = "";
    var sc = Number(j.score || 0), v = j.verdict || "?";
    var bars = [
      ["identity", j.identity], ["behavioral", j.behavioral],
      ["policy", j.policy], ["format", j.format], ["verbatim", j.verbatim]
    ].filter(function (x) { return typeof x[1] === "number"; });
    var rows = ""; bars.forEach(function (x) { rows += '<tr><td>' + esc(x[0]) + '</td><td>' + Number(x[1]).toFixed(2) + '</td></tr>'; });
    judgeBody.innerHTML =
      '<div><span class="judge-verdict ' + esc(v) + '">' + esc(v) + '</span> score ' + sc.toFixed(2) + '</div>' +
      '<div class="judge-bar"><span style="width:' + Math.round(sc * 100) + '%"></span></div>' +
      '<table class="judge-table"><tbody>' + rows + '</tbody></table>' +
      '<div style="margin-top:4px;color:var(--fg3);font-size:11px">' + esc(j.reason || "") + '</div>';
  }
  function showExtracted(p) {
    if (!p) return;
    extractedRow.style.display = ""; extractedText.textContent = p;
  }

  function refreshHistory() {
    fetch("/api/history").then(function (r) { return r.json(); }).then(function (j) {
      hlist.innerHTML = "";
      if (!j.sessions || !j.sessions.length) {
        hlist.innerHTML = '<div class="system-note" style="margin:6px 2px">Még nincs munkamenet.</div>';
        return;
      }
      var f = document.createDocumentFragment();
      j.sessions.forEach(function (h) {
        var c = document.createElement("div");
        c.className = "hcard" + (h.sid === sid ? " active" : "");
        var t = new Date(h.updated_ts * 1000);
        var tt = String(t.getHours()).padStart(2, "0") + ":" + String(t.getMinutes()).padStart(2, "0");
        var statusPill = "";
        if (h.status === "success") statusPill = '<span class="pill ok">siker</span>';
        else if (h.status === "failure") statusPill = '<span class="pill err">fail</span>';
        else if (h.status === "running") statusPill = '<span class="pill">fut</span>';
        else if (h.status === "partial") statusPill = '<span class="pill">rész</span>';
        c.innerHTML = '<div class="hcard-body"><div class="hcard-pre">' + esc((h.title || h.model_id || "").slice(0, 70)) + '</div>' +
          '<div class="hcard-meta"><span>' + esc((h.model_id || "").split("/").pop() || "") + '</span>' + statusPill + '<span>' + tt + '</span><span>#' + (h.attempt || 0) + '</span></div></div>';
        c.addEventListener("click", function (e) { switchSession(h.sid); });
        f.appendChild(c);
      });
      hlist.appendChild(f);
    }).catch(function () {});
  }

  function switchSession(targetSid) {
    if (streaming) stop();
    sid = targetSid; fetch("/api/history/" + encodeURIComponent(targetSid)).then(function (r) { return r.json(); }).then(function (j) {
      ml.innerHTML = ""; msgs = []; currentAssistantEl = null; currentAssistantText = "";
      currentModel = j.model_id; modelPill.textContent = (j.model_id || "") + " · " + (j.architecture || "?");
      attemptPill.textContent = "attempt " + (j.attempt_no || 0);
      stackPill.textContent = "stack " + (j.stack_size || 0);
      (j.conversation || []).forEach(function (m) {
        if (m.role === "user") { var g = document.createElement("div"); g.className = "msg-group u"; var b = document.createElement("div"); b.className = "bubble"; b.textContent = m.content; g.appendChild(b); footer(g, { copyContent: m.content }); ml.appendChild(g); msgs.push({ role: "user", content: m.content }); }
        else if (m.role === "assistant") { var g = document.createElement("div"); g.className = "msg-group a"; var bb = document.createElement("div"); bb.className = "ai-bubble"; var d = document.createElement("div"); d.className = "md"; d.innerHTML = renderMd(m.content); bb.appendChild(d); g.appendChild(bb); footer(g, { copyContent: m.content }); ml.appendChild(g); msgs.push({ role: "assistant", content: m.content }); }
      });
      if (j.final_prompt) showExtracted(j.final_prompt);
      closeSB(); goBot();
    }).catch(function () { toast("Nem sikerült betölteni", "err"); });
  }

  function refreshKnowledge() {
    fetch("/api/knowledge").then(function (r) { return r.json(); }).then(function (j) {
      ucbList.innerHTML = "";
      (j.skill_ranking || []).slice(0, 30).forEach(function (row) {
        var li = document.createElement("li");
        li.innerHTML = '<span><span class="combo">' + esc(row.combo) + '</span> <span class="meta">v=' + (row.visits || 0) + ' avg=' + Number(row.avg || 0).toFixed(2) + '</span></span><span class="score">' + Number(row.ucb).toFixed(3) + '</span>';
        ucbList.appendChild(li);
      });
      rulesList.innerHTML = "";
      (j.rules || []).forEach(function (r) {
        var d = document.createElement("div"); d.className = "rule";
        d.innerHTML = '<div><span class="rid">' + esc(r.id) + '</span> <span class="conf">[' + esc(r.confidence || "") + '] ' + esc(r.architecture || "") + '</span></div><div>' + esc(r.rule || "") + '</div><div class="conf">skills: ' + esc((r.skills || []).join(", ")) + ' · scope: ' + esc(r.scope || "") + '</div>';
        rulesList.appendChild(d);
      });
    }).catch(function () {});
  }

  function refreshModels() {
    fetch("/api/models").then(function (r) { return r.json(); }).then(function (j) {
      modelCounts.innerHTML =
        '<div class="c"><b>' + (j.counts.pending || 0) + '</b>pending</div>' +
        '<div class="c"><b>' + (j.counts.success || 0) + '</b>siker</div>' +
        '<div class="c"><b>' + (j.counts.partial || 0) + '</b>rész</div>' +
        '<div class="c"><b>' + (j.counts.failure || 0) + '</b>sikertelen</div>';
      modelList.innerHTML = ""; (j.models || []).forEach(function (m) { var o = document.createElement("option"); o.value = m.model_id; modelList.appendChild(o); });
      modelListEl.innerHTML = "";
      (j.models || []).slice().sort(function (a, b) { return Number(a.order) - Number(b.order); }).forEach(function (m) {
        var row = document.createElement("div"); row.className = "mrow";
        row.innerHTML = '<span>' + esc(m.model_id) + ' <span style="color:var(--fg3)">' + esc(m.architecture || "") + '</span></span><span class="mstatus ' + esc(m.status || 'pending') + '">' + esc(m.status || "pending") + '</span>';
        row.addEventListener("click", function () { sbModel.value = m.model_id; currentModel = m.model_id; modelPill.textContent = currentModel; closeSB(); });
        modelListEl.appendChild(row);
      });
    }).catch(function () {});
  }

  $$(".sb-tab").forEach(function (b) {
    b.addEventListener("click", function () {
      $$(".sb-tab").forEach(function (x) { x.classList.remove("active"); }); b.classList.add("active");
      var t = b.dataset.stab; $$(".stab").forEach(function (p) { p.classList.toggle("hidden", p.dataset.stab !== t); });
    });
  });
  function $$(sel) { return Array.from(document.querySelectorAll(sel)); }
  $$(".mode-btn").forEach(function (b) {
    b.addEventListener("click", function () {
      $$(".mode-btn").forEach(function (x) { x.classList.remove("active"); }); b.classList.add("active");
      currentMode = b.dataset.mode;
      if (currentMode === "auto") ta.placeholder = "Üresen hagyhatod – az ügynök magától indul…";
      else if (currentMode === "step") ta.placeholder = "Üresen is mehet – egy ügynök-lépés…";
      else if (currentMode === "simple") ta.placeholder = "Csevej gpt-5.6-sol modellel…";
      else ta.placeholder = "Üzenet a célmodellnek…";
      sbMode.value = currentMode; grow();
    });
  });
  sbMode.addEventListener("change", function () {
    var m = sbMode.value; currentMode = m;
    $$(".mode-btn").forEach(function (x) { x.classList.toggle("active", x.dataset.mode === m); });
  });
  function newChat() {
    if (streaming) stop();
    sid = null; currentModel = sbModel.value.trim();
    ml.innerHTML = ""; msgs = []; currentAssistantEl = null; currentAssistantText = "";
    extractedRow.style.display = "none"; judgeRow.style.display = "none";
    attemptPill.textContent = "attempt 0"; stackPill.textContent = "stack 0";
    modelPill.textContent = currentModel ? currentModel : "nincs modell";
    refreshHistory(); goBot();
  }
  $("btn-sb-new").addEventListener("click", function () { newChat(); closeSB(); });
  $("btn-stop").addEventListener("click", function () { stop(); closeSB(); });
  $("btn-finalize").addEventListener("click", function () {
    if (!sid) { toast("Nincs aktív munkamenet", "err"); return; }
    fetch("/api/chat/finalize", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: sid }) })
      .then(function (r) { return r.json(); }).then(function (j) {
      if (j.prompt) showExtracted(j.prompt); addNote("Mentve mint " + j.status + ".", "ok"); refreshHistory(); refreshModels();
    });
  });
  $("btn-archive").addEventListener("click", function () {
    if (!confirm("Archiválod és lenullázod a tudást?")) return;
    fetch("/api/archive", { method: "POST" }).then(function (r) { return r.json(); }).then(function (j) {
      toast("Archiválva: " + j.archive, "ok"); newChat(); refreshKnowledge(); refreshModels();
    });
  });
  $("btnQuickAdd").addEventListener("click", function () {
    var v = quickAddInput.value.trim(); if (!v) return; quickAddInput.value = "";
    fetch("/api/models/add", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ models: [{ model_id: v }] }) })
      .then(function () { toast("Hozzáadva: " + v, "ok"); refreshModels(); });
  });
  sbModel.addEventListener("change", function () { currentModel = sbModel.value.trim(); modelPill.textContent = currentModel || "nincs modell"; });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") { if (sbOpen) closeSB(); }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); sbOpen ? closeSB() : openSB(); }
  });

  function checkHealth() {
    fetch("/api/health").then(function (r) { return r.json(); }).then(function (j) {
      if (j.ok && j.llmapi_key_set) { statusRow.classList.remove("err"); if (!streaming) statusText.textContent = "készenlét"; }
      else { statusRow.classList.add("err"); statusText.textContent = "LLMAPI_KEY hiányzik"; }
    }).catch(function () { statusRow.classList.add("err"); statusText.textContent = "offline"; });
  }

  function refreshSessionInfo() {
    if (!sid) return;
    fetch("/api/session/" + encodeURIComponent(sid)).then(function (r) { return r.json(); }).catch(function () { return null; }).then(function (j) {
      if (!j) return;
      attemptPill.textContent = "attempt " + (j.attempt_no || 0);
      stackPill.textContent = "stack " + (j.stack_size || 0);
      if (j.final_prompt) showExtracted(j.final_prompt);
    });
  }

  setIBH(); grow(); checkHealth(); refreshKnowledge(); refreshModels(); refreshHistory();
  setInterval(checkHealth, 15000); setInterval(refreshKnowledge, 8000); setInterval(refreshModels, 20000); setInterval(refreshHistory, 6000);
})();
