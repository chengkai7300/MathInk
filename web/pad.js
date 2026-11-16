(() => {
  "use strict";

  const LW_DEFAULT = 1000;
  const LH_DEFAULT = 600;
  let LW = LW_DEFAULT;
  let LH = LH_DEFAULT;

  const canvas = document.getElementById("pad");
  const ctx = canvas.getContext("2d");
  const hint = document.getElementById("hint");
  const info = document.getElementById("info");
  const connText = document.getElementById("conn-text");
  const dot = document.getElementById("dot");
  const toast = document.getElementById("toast");
  const modeSel = document.getElementById("mode");
  const autoBox = document.getElementById("auto");
  const recognizeBtn = document.getElementById("recognize");

  let strokes = [];
  let current = null;
  let drawing = false;
  let penSeen = false;
  let ws = null;
  let autoTimer = null;
  let previewTimer = 0;
  let busy = false;
  let W = 0, H = 0, dpr = 1;

  function resize() {
    const r = canvas.getBoundingClientRect();
    W = Math.max(1, r.width);
    H = Math.max(1, r.height);
    dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(W * dpr);
    canvas.height = Math.round(H * dpr);
    draw();
    scheduleViewport();
  }

  let vpTimer = null;
  function scheduleViewport() {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    clearTimeout(vpTimer);
    vpTimer = setTimeout(() => {
      send({ type: "viewport", w: Math.round(W), h: Math.round(H) });
    }, 350);
  }

  function fit() {
    const scale = Math.min(W / LW, H / LH);
    return { scale, ox: (W - LW * scale) / 2, oy: (H - LH * scale) / 2 };
  }

  function toLogical(e) {
    const r = canvas.getBoundingClientRect();
    const { scale, ox, oy } = fit();
    const x = (e.clientX - r.left - ox) / scale;
    const y = (e.clientY - r.top - oy) / scale;
    return { x: Math.max(0, Math.min(LW, x)), y: Math.max(0, Math.min(LH, y)) };
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

    // grid
    ctx.strokeStyle = "#f1f3f8";
    ctx.lineWidth = 1 / scale;
    for (let x = 0; x <= LW; x += 50) {
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, LH); ctx.stroke();
    }
    for (let y = 0; y <= LH; y += 50) {
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(LW, y); ctx.stroke();
    }
    // baseline
    ctx.strokeStyle = "#e3e8f2";
    ctx.lineWidth = 1.2 / scale;
    ctx.beginPath();
    ctx.moveTo(40, LH * 0.72);
    ctx.lineTo(LW - 40, LH * 0.72);
    ctx.stroke();

    for (const s of strokes) pathStroke(s);
    if (current) pathStroke(current);

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.strokeStyle = "#e8ebf3";
    ctx.lineWidth = 1;
    ctx.strokeRect(dpr * ox, dpr * oy, dpr * LW * scale, dpr * LH * scale);
  }

  function updateInfo() {
    info.textContent = `${strokes.length} 笔`;
    hint.classList.toggle("hidden", strokes.length > 0 || drawing);
  }

  function showToast(text, isError) {
    toast.textContent = text;
    toast.className = "toast show" + (isError ? " err" : "");
    clearTimeout(showToast._t);
    showToast._t = setTimeout(() => (toast.className = "toast"), 2200);
  }

  function send(obj) {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
  }

  function scheduleAuto() {
    cancelAuto();
    if (!autoBox.checked || busy || !strokes.length) return;
    autoTimer = setTimeout(() => {
      autoTimer = null;
      recognize();
    }, 900);
  }

  function cancelAuto() {
    if (autoTimer) {
      clearTimeout(autoTimer);
      autoTimer = null;
    }
  }

  function recognize() {
    if (busy || !strokes.length) return;
    cancelAuto();
    busy = true;
    recognizeBtn.disabled = true;
    recognizeBtn.textContent = "识别中";
    send({ type: "recognize", engine: modeSel.value });
    clearTimeout(recognize._t);
    recognize._t = setTimeout(() => {
      if (!busy) return;
      busy = false;
      recognizeBtn.disabled = false;
      recognizeBtn.textContent = "识别";
      showToast("识别超时，请重试", true);
    }, 20000);
  }

  // ------------------------------------------------------------ pointer

  canvas.addEventListener("pointerdown", (e) => {
    if (e.pointerType === "touch" && penSeen) return; // palm rejection
    if (e.pointerType === "pen") penSeen = true;
    if (busy) return;
    e.preventDefault();
    cancelAuto();
    canvas.setPointerCapture(e.pointerId);
    drawing = true;
    const p = toLogical(e);
    const pressure = e.pointerType === "pen" ? e.pressure || 0.5 : 0.5;
    const width = e.pointerType === "pen" ? 2.2 + 3.4 * pressure : 3.6;
    current = { points: [{ x: p.x, y: p.y }], width: Math.round(width * 10) / 10 };
    updateInfo();
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

  function endStroke(e) {
    if (!drawing || !current) return;
    drawing = false;
    const stroke = { points: current.points, width: current.width };
    strokes.push(stroke);
    current = null;
    send({ type: "stroke", stroke });
    send({ type: "preview", stroke: null });
    updateInfo();
    draw();
    scheduleAuto();
  }

  canvas.addEventListener("pointerup", endStroke);
  canvas.addEventListener("pointercancel", endStroke);

  // ------------------------------------------------------------ buttons

  document.getElementById("undo").addEventListener("click", () => {
    if (busy) return;
    cancelAuto();
    strokes.pop();
    updateInfo();
    draw();
    send({ type: "undo" });
  });

  document.getElementById("clear").addEventListener("click", () => {
    if (busy) return;
    cancelAuto();
    strokes = [];
    current = null;
    updateInfo();
    draw();
    send({ type: "clear" });
    showToast("已清空");
  });

  recognizeBtn.addEventListener("click", recognize);

  document.getElementById("full").addEventListener("click", async () => {
    try {
      if (!document.fullscreenElement) await document.documentElement.requestFullscreen();
      else await document.exitFullscreen();
    } catch {}
  });

  // ------------------------------------------------------------ websocket

  function setConn(kind, text) {
    dot.className = "dot " + kind;
    connText.textContent = text;
  }

  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/ws`);
    ws.onopen = () => {
      setConn("ok", "已连接");
      send({
        type: "hello",
        role: "pad",
        viewport: { w: Math.round(W), h: Math.round(H) },
      });
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
        current = null;
        drawing = false;
        updateInfo();
        draw();
      } else if (msg.type === "canvas") {
        LW = msg.w;
        LH = msg.h;
        draw();
      } else if (msg.type === "peers") {
        if ((msg.hosts || 0) > 0) setConn("ok", "主机已连接");
        else setConn("warn", "等待主机");
      } else if (msg.type === "result") {
        busy = false;
        recognizeBtn.disabled = false;
        recognizeBtn.textContent = "识别";
        clearTimeout(recognize._t);
        if (msg.latex) {
          showToast("已识别：" + msg.latex.slice(0, 42));
        } else {
          showToast("没有识别出内容", true);
        }
      } else if (msg.type === "error") {
        busy = false;
        recognizeBtn.disabled = false;
        recognizeBtn.textContent = "识别";
        showToast(msg.message || "识别失败", true);
      }
    };
    ws.onclose = () => {
      setConn("err", "已断开，重连中…");
      busy = false;
      recognizeBtn.disabled = false;
      recognizeBtn.textContent = "识别";
      setTimeout(connect, 1500);
    };
    ws.onerror = () => {};
  }

  new ResizeObserver(resize).observe(canvas);
  window.addEventListener("resize", resize);
  resize();
  updateInfo();
  connect();
})();
