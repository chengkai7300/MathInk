(() => {
  "use strict";

  const LW_DEFAULT = 1000;
  const LH_DEFAULT = 600;
  let LW = LW_DEFAULT;
  let LH = LH_DEFAULT;

  const canvas = document.getElementById("mirror");
  const ctx = canvas.getContext("2d");
  const hint = document.getElementById("hint");
  const strokeInfo = document.getElementById("stroke-info");
  const canvasInfo = document.getElementById("canvas-info");
  const latexBox = document.getElementById("latex");
  const renderBox = document.getElementById("render");
  const timingsEl = document.getElementById("timings");
  const messageEl = document.getElementById("message");
  const engineBadge = document.getElementById("engine-badge");
  const peerBadge = document.getElementById("peer-badge");
  const confidenceEl = document.getElementById("confidence");
  const copyBtn = document.getElementById("copy");
  const recognizeBtn = document.getElementById("recognize");
  const clearBtn = document.getElementById("clear");
  const historyBox = document.getElementById("history");
  const modeButtons = Array.from(document.querySelectorAll(".seg-btn"));

  let strokes = [];
  let preview = null;
  let current = null;
  let drawing = false;
  let mode = "vlm";
  let ws = null;
  let lastLatex = "";
  let history = [];
  let W = 0, H = 0, dpr = 1;
  let previewTimer = 0;

  function toLogical(e) {
    const r = canvas.getBoundingClientRect();
    const { scale, ox, oy } = fit();
    const x = (e.clientX - r.left - ox) / scale;
    const y = (e.clientY - r.top - oy) / scale;
    return { x: Math.max(0, Math.min(LW, x)), y: Math.max(0, Math.min(LH, y)) };
  }

  function send(obj) {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
  }

  function resize() {
    const r = canvas.getBoundingClientRect();
    W = Math.max(1, r.width);
    H = Math.max(1, r.height);
    dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(W * dpr);
    canvas.height = Math.round(H * dpr);
    draw();
  }

  function fit() {
    const scale = Math.min(W / LW, H / LH);
    return { scale, ox: (W - LW * scale) / 2, oy: (H - LH * scale) / 2 };
  }

  function pathStroke(s) {
    const pts = s.points;
    if (!pts.length) return;
    ctx.lineWidth = s.width || 3;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.strokeStyle = "#1f2430";
    if (pts.length === 1) {
      ctx.beginPath();
      ctx.arc(pts[0].x, pts[0].y, (s.width || 3) / 2, 0, Math.PI * 2);
      ctx.fillStyle = "#1f2430";
      ctx.fill();
      return;
    }
    ctx.beginPath();
    ctx.moveTo(pts[0].x, pts[0].y);
    if (pts.length === 2) {
      ctx.lineTo(pts[1].x, pts[1].y);
    } else {
      for (let i = 1; i < pts.length - 1; i++) {
        const mx = (pts[i].x + pts[i + 1].x) / 2;
        const my = (pts[i].y + pts[i + 1].y) / 2;
        ctx.quadraticCurveTo(pts[i].x, pts[i].y, mx, my);
      }
      const last = pts[pts.length - 1];
      ctx.lineTo(last.x, last.y);
    }
    ctx.stroke();
  }

  function draw() {
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, W, H);

    const { scale, ox, oy } = fit();
    ctx.setTransform(dpr * scale, 0, 0, dpr * scale, dpr * ox, dpr * oy);

    // light baseline
    ctx.strokeStyle = "#eef1f7";
    ctx.lineWidth = 1 / scale;
    ctx.beginPath();
    ctx.moveTo(40, LH * 0.72);
    ctx.lineTo(LW - 40, LH * 0.72);
    ctx.stroke();

    for (const s of strokes) pathStroke(s);
    if (preview) pathStroke(preview);
    if (current) pathStroke(current);

    // logical canvas border + dim the non-writable margins
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const rx = ox, ry = oy, rw = LW * scale, rh = LH * scale;
    ctx.fillStyle = "rgba(15, 23, 42, .04)";
    ctx.fillRect(0, 0, W, ry);
    ctx.fillRect(0, ry + rh, W, H - (ry + rh));
    ctx.fillRect(0, ry, rx, rh);
    ctx.fillRect(rx + rw, ry, W - (rx + rw), rh);
    ctx.strokeStyle = "#dfe4ef";
    ctx.lineWidth = 1;
    ctx.strokeRect(rx, ry, rw, rh);
  }

  function updateInfo() {
    strokeInfo.textContent = `${strokes.length} 笔`;
    canvasInfo.textContent = `逻辑画布 ${Math.round(LW)} × ${Math.round(LH)}`;
    hint.classList.toggle("hidden", strokes.length > 0 || drawing);
    recognizeBtn.disabled = strokes.length === 0;
    clearBtn.disabled = strokes.length === 0;
  }

  function renderLatex(latex) {
    if (!latex) {
      renderBox.innerHTML = '<span class="placeholder">平板上写完，结果会出现在这里</span>';
      renderBox.classList.remove("error");
      return;
    }
    try {
      katex.render(latex, renderBox, { throwOnError: true, displayMode: true, strict: false });
      renderBox.classList.remove("error");
    } catch (err) {
      renderBox.classList.add("error");
      renderBox.textContent = "LaTeX 渲染失败：" + err.message;
    }
  }

  function flash(text, kind) {
    messageEl.textContent = text;
    messageEl.className = "message " + (kind || "");
    setTimeout(() => {
      if (messageEl.textContent === text) {
        messageEl.textContent = "";
        messageEl.className = "message";
      }
    }, 1800);
  }

  function showResult(data) {
    lastLatex = data.latex || "";
    latexBox.value = lastLatex;
    renderLatex(lastLatex);
    copyBtn.disabled = !lastLatex;

    if (lastLatex && data.confidence != null) {
      const pct = Math.round(data.confidence * 100);
      confidenceEl.textContent = `置信度 ${pct}%`;
      confidenceEl.className = "conf " + (pct >= 80 ? "ok" : pct >= 50 ? "warn" : "err");
    } else {
      confidenceEl.textContent = "";
      confidenceEl.className = "conf";
    }

    const t = data.timings || {};
    const engine = data.engine === "vlm" ? "VLM" : "CoMER";
    timingsEl.textContent =
      `${engine} · ${t.server_total_ms ?? t.total_ms ?? "?"} ms` +
      (t.vlm_ms ? `（VLM ${t.vlm_ms} ms）` : "") +
      (t.encode_ms ? `（编码 ${t.encode_ms} ms）` : "");

    if (lastLatex) {
      addHistory(lastLatex, data.engine);
    } else {
      flash("没有识别出内容", "err");
    }
  }

  function addHistory(latex, engine) {
    if (history[0] && history[0].latex === latex) return;
    history.unshift({ latex, engine });
    history = history.slice(0, 8);
    renderHistory();
  }

  function renderHistory() {
    if (!history.length) {
      historyBox.innerHTML = '<span class="history-empty">暂无</span>';
      return;
    }
    historyBox.innerHTML = "";
    for (const item of history) {
      const div = document.createElement("div");
      div.className = "history-item";
      div.title = "点击复制";
      const span = document.createElement("span");
      span.textContent = item.latex;
      div.appendChild(span);
      div.addEventListener("click", () => copyText(item.latex));
      historyBox.appendChild(div);
    }
  }

  async function copyText(text) {
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      flash("已复制", "ok");
    } catch {
      latexBox.select();
      document.execCommand("copy");
      flash("已复制", "ok");
    }
  }

  copyBtn.addEventListener("click", () => copyText(latexBox.value.trim()));

  latexBox.addEventListener("input", () => {
    clearTimeout(latexBox._t);
    latexBox._t = setTimeout(() => renderLatex(latexBox.value.trim()), 200);
  });

  recognizeBtn.addEventListener("click", () => {
    if (!ws || ws.readyState !== WebSocket.OPEN) return flash("未连接", "err");
    flash("识别中…");
    ws.send(JSON.stringify({ type: "recognize", engine: mode }));
  });

  clearBtn.addEventListener("click", () => {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "clear" }));
  });

  modeButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      mode = btn.dataset.mode;
      modeButtons.forEach((b) => b.classList.toggle("active", b === btn));
    });
  });

  // ------------------------------------------------------------ desktop input

  canvas.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    e.preventDefault();
    canvas.setPointerCapture(e.pointerId);
    const p = toLogical(e);
    current = { points: [{ x: p.x, y: p.y }], width: e.pointerType === "pen" ? 3.5 : 3.5 };
    drawing = true;
    hint.classList.add("hidden");
    draw();
  });

  canvas.addEventListener("pointermove", (e) => {
    if (!drawing || !current) return;
    const p = toLogical(e);
    const last = current.points[current.points.length - 1];
    if (Math.hypot(p.x - last.x, p.y - last.y) < 1.2) return;
    current.points.push({ x: p.x, y: p.y });
    draw();
    const now = performance.now();
    if (now - previewTimer > 70) {
      previewTimer = now;
      send({ type: "preview", stroke: current });
    }
  });

  function endHostStroke() {
    if (!drawing || !current) return;
    drawing = false;
    const stroke = { points: current.points, width: current.width };
    strokes.push(stroke);
    current = null;
    send({ type: "stroke", stroke });
    send({ type: "preview", stroke: null });
    updateInfo();
    draw();
  }

  canvas.addEventListener("pointerup", endHostStroke);
  canvas.addEventListener("pointercancel", endHostStroke);

  // ------------------------------------------------------------ websocket

  function setPeer(connected) {
    peerBadge.textContent = connected ? "平板已连接" : "等待平板";
    peerBadge.className = "badge " + (connected ? "badge-ok" : "badge-warn");
  }

  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/ws`);
    ws.onopen = () => {
      engineBadge.textContent = "已连接";
      engineBadge.className = "badge badge-ok";
      ws.send(JSON.stringify({ type: "hello", role: "host" }));
    };
    ws.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch { return; }
      if (msg.type === "state") {
        if (msg.canvas) {
          LW = msg.canvas.w;
          LH = msg.canvas.h;
        }
        strokes = msg.strokes || [];
        preview = null;
        draw();
        updateInfo();
      } else if (msg.type === "canvas") {
        LW = msg.w;
        LH = msg.h;
        draw();
      } else if (msg.type === "stroke") {
        strokes.push(msg.stroke);
        preview = null;
        draw();
        updateInfo();
      } else if (msg.type === "preview") {
        preview = msg.stroke;
        draw();
      } else if (msg.type === "result") {
        showResult(msg);
      } else if (msg.type === "peers") {
        setPeer((msg.pads || 0) > 0);
      } else if (msg.type === "error") {
        flash(msg.message || "识别失败", "err");
      }
    };
    ws.onclose = () => {
      setPeer(false);
      engineBadge.textContent = "服务未连接";
      engineBadge.className = "badge badge-err";
      setTimeout(connect, 2000);
    };
    ws.onerror = () => {};
  }

  // ------------------------------------------------------------ init

  fetch("/api/lan-info")
    .then((r) => r.json())
    .then((info) => {
      const url = info.pad_url || `http://${info.ip}:${info.port}/pad`;
      document.getElementById("pad-url").textContent = url;
      document.getElementById("qr").src = `/api/qr.png?data=${encodeURIComponent(url)}`;
    })
    .catch(() => {});

  fetch("/api/health")
    .then((r) => r.json())
    .then((h) => {
      const vlmReady = Boolean(h.vlm && h.vlm.ready);
      engineBadge.textContent = vlmReady ? "VLM · GPU" : "CoMER · CPU";
      engineBadge.className = "badge badge-ok";
    })
    .catch(() => {});

  new ResizeObserver(resize).observe(canvas);
  window.addEventListener("resize", resize);
  resize();
  updateInfo();
  connect();
})();
