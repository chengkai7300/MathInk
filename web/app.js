(() => {
  "use strict";

  const canvas = document.getElementById("pad");
  const ctx = canvas.getContext("2d");
  const emptyHint = document.getElementById("empty-hint");
  const strokeInfo = document.getElementById("stroke-info");
  const latexBox = document.getElementById("latex");
  const renderBox = document.getElementById("render");
  const timingsEl = document.getElementById("timings");
  const messageEl = document.getElementById("message");
  const engineBadge = document.getElementById("engine-badge");
  const latencyBadge = document.getElementById("latency-badge");
  const confidenceEl = document.getElementById("confidence");
  const recognizeBtn = document.getElementById("recognize");
  const autoBox = document.getElementById("auto");

  const INK = "#1f2430";
  const WIDTH = 3;

  let strokes = [];
  let current = null;
  let drawing = false;
  let busy = false;
  let autoTimer = null;
  let W = 0;
  let H = 0;
  let dpr = 1;

  function resize() {
    const rect = canvas.getBoundingClientRect();
    W = Math.max(1, rect.width);
    H = Math.max(1, rect.height);
    dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(W * dpr);
    canvas.height = Math.round(H * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    redraw();
  }

  function pos(e) {
    const rect = canvas.getBoundingClientRect();
    return { x: e.clientX - rect.left, y: e.clientY - rect.top };
  }

  function redraw() {
    ctx.clearRect(0, 0, W, H);
    for (const s of strokes) drawStroke(s);
  }

  function drawStroke(s) {
    const pts = s.points;
    if (!pts.length) return;
    ctx.strokeStyle = INK;
    ctx.fillStyle = INK;
    ctx.lineWidth = s.width;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";

    if (pts.length === 1) {
      ctx.beginPath();
      ctx.arc(pts[0].x, pts[0].y, s.width / 2, 0, Math.PI * 2);
      ctx.fill();
      return;
    }
    if (pts.length === 2) {
      ctx.beginPath();
      ctx.moveTo(pts[0].x, pts[0].y);
      ctx.lineTo(pts[1].x, pts[1].y);
      ctx.stroke();
      return;
    }
    ctx.beginPath();
    ctx.moveTo(pts[0].x, pts[0].y);
    for (let i = 1; i < pts.length - 1; i++) {
      const mx = (pts[i].x + pts[i + 1].x) / 2;
      const my = (pts[i].y + pts[i + 1].y) / 2;
      ctx.quadraticCurveTo(pts[i].x, pts[i].y, mx, my);
    }
    const last = pts[pts.length - 1];
    ctx.lineTo(last.x, last.y);
    ctx.stroke();
  }

  function updateInfo() {
    if (!strokes.length) {
      strokeInfo.textContent = "0 笔";
      strokeInfo.classList.remove("warn");
    } else {
      let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
      for (const s of strokes) {
        for (const p of s.points) {
          if (p.x < minX) minX = p.x;
          if (p.y < minY) minY = p.y;
          if (p.x > maxX) maxX = p.x;
          if (p.y > maxY) maxY = p.y;
        }
      }
      const w = Math.round(maxX - minX);
      const h = Math.round(maxY - minY);
      const warn = h > 256 || h < 40;
      strokeInfo.textContent = `${strokes.length} 笔 · ${w}×${h} px${
        warn ? " · 建议高度 60–250" : ""
      }`;
      strokeInfo.classList.toggle("warn", warn);
    }
    emptyHint.classList.toggle("hidden", strokes.length > 0);
    recognizeBtn.disabled = strokes.length === 0 || busy;
  }

  function cancelAuto() {
    if (autoTimer) {
      clearTimeout(autoTimer);
      autoTimer = null;
    }
  }

  function scheduleAuto() {
    cancelAuto();
    if (!autoBox.checked || strokes.length === 0) return;
    autoTimer = setTimeout(() => {
      autoTimer = null;
      recognize();
    }, 900);
  }

  function setBusy(on) {
    busy = on;
    recognizeBtn.disabled = on || strokes.length === 0;
    recognizeBtn.textContent = on ? "识别中…" : "识别";
  }

  canvas.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 || busy) return;
    e.preventDefault();
    cancelAuto();
    canvas.setPointerCapture(e.pointerId);
    drawing = true;
    current = { points: [pos(e)], width: WIDTH };
    strokes.push(current);
    updateInfo();
    redraw();
  });

  canvas.addEventListener("pointermove", (e) => {
    if (!drawing || !current) return;
    const p = pos(e);
    const last = current.points[current.points.length - 1];
    if (Math.hypot(p.x - last.x, p.y - last.y) < 1.2) return;
    current.points.push(p);
    redraw();
  });

  function endStroke() {
    if (!drawing) return;
    drawing = false;
    current = null;
    scheduleAuto();
  }

  canvas.addEventListener("pointerup", endStroke);
  canvas.addEventListener("pointercancel", endStroke);
  canvas.addEventListener("pointerleave", (e) => {
    if (drawing && e.buttons === 0) endStroke();
  });

  document.getElementById("undo").addEventListener("click", () => {
    if (busy) return;
    cancelAuto();
    strokes.pop();
    updateInfo();
    redraw();
  });

  document.getElementById("clear").addEventListener("click", () => {
    if (busy) return;
    cancelAuto();
    strokes = [];
    updateInfo();
    redraw();
    clearResult();
  });

  document.getElementById("demo").addEventListener("click", () => {
    if (busy) return;
    cancelAuto();
    loadDemo();
  });

  recognizeBtn.addEventListener("click", () => {
    cancelAuto();
    recognize();
  });

  autoBox.addEventListener("change", () => {
    if (!autoBox.checked) cancelAuto();
  });

  document.getElementById("copy").addEventListener("click", async () => {
    const text = latexBox.value.trim();
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      flash("已复制", "ok");
    } catch {
      latexBox.select();
      document.execCommand("copy");
      flash("已复制", "ok");
    }
  });

  let renderTimer = null;
  latexBox.addEventListener("input", () => {
    clearTimeout(renderTimer);
    renderTimer = setTimeout(() => {
      renderLatex(latexBox.value.trim());
      confidenceEl.textContent = "";
      confidenceEl.className = "conf";
    }, 250);
  });

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

  function clearResult() {
    renderBox.innerHTML = '<span class="placeholder">识别后在此预览</span>';
    renderBox.classList.remove("error");
    latexBox.value = "";
    timingsEl.textContent = "—";
    latencyBadge.textContent = "—";
    latencyBadge.className = "badge badge-muted";
    confidenceEl.textContent = "";
    confidenceEl.className = "conf";
    messageEl.textContent = "";
    messageEl.className = "message";
  }

  function renderLatex(latex) {
    if (!latex) {
      renderBox.innerHTML = '<span class="placeholder">未识别出公式</span>';
      renderBox.classList.remove("error");
      return;
    }
    try {
      katex.render(latex, renderBox, {
        throwOnError: true,
        displayMode: true,
        strict: false,
      });
      renderBox.classList.remove("error");
    } catch (err) {
      renderBox.classList.add("error");
      renderBox.textContent = "LaTeX 渲染失败：" + err.message;
    }
  }

  async function recognize() {
    if (busy || strokes.length === 0) return;
    setBusy(true);
    messageEl.textContent = "";
    const payload = {
      strokes: strokes.map((s) => ({ points: s.points, width: s.width })),
      beam: 1,
    };
    const t0 = performance.now();
    try {
      const res = await fetch("/api/recognize", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const detail = await res.text();
        throw new Error(`服务返回 ${res.status}: ${detail.slice(0, 200)}`);
      }
      const data = await res.json();
      const wall = Math.round(performance.now() - t0);

      latexBox.value = data.latex || "";
      renderLatex(data.latex);

      if (typeof data.confidence === "number" && data.latex) {
        const pct = Math.round(data.confidence * 100);
        confidenceEl.textContent = `置信度 ${pct}%`;
        confidenceEl.className =
          "conf " + (pct >= 80 ? "ok" : pct >= 50 ? "warn" : "err");
      } else {
        confidenceEl.textContent = "";
        confidenceEl.className = "conf";
      }

      const t = data.timings || {};
      timingsEl.textContent = `编码 ${t.encode_ms ?? "?"} ms · 解码 ${
        t.decode_ms ?? "?"
      } ms · 服务端 ${t.server_total_ms ?? "?"} ms · 往返 ${wall} ms`;

      latencyBadge.textContent = `${wall} ms`;
      latencyBadge.className =
        "badge " + (wall < 1000 ? "badge-ok" : "badge-warn");

      if (!data.latex) {
        flash("没有识别出内容，写得再清楚一点", "err");
      } else if (!data.valid) {
        flash("结果可能不完整，请检查", "warn");
      }
    } catch (err) {
      console.error(err);
      messageEl.textContent = String(err.message || err);
      messageEl.className = "message err";
      latencyBadge.textContent = "失败";
      latencyBadge.className = "badge badge-err";
    } finally {
      setBusy(false);
    }
  }

  document.addEventListener("keydown", (e) => {
    if (e.ctrlKey && e.key === "Enter") {
      e.preventDefault();
      recognize();
    } else if (e.ctrlKey && e.key.toLowerCase() === "z") {
      e.preventDefault();
      document.getElementById("undo").click();
    }
  });

  new ResizeObserver(() => resize()).observe(canvas);
  window.addEventListener("resize", resize);
  resize();
  updateInfo();

  function loadDemo() {
    const sx = W / 900;
    const sy = H / 360;
    const scale = Math.min(sx, sy);
    const ox = (W - 900 * scale) / 2;
    const oy = (H - 360 * scale) / 2;
    const P = (x, y) => ({ x: ox + x * scale, y: oy + y * scale });
    const mk = (pts) => ({ points: pts.map(([x, y]) => P(x, y)), width: WIDTH });
    strokes = [
      mk([[60, 170], [130, 90]]),
      mk([[60, 90], [130, 170]]),
      mk([[180, 130], [250, 130]]),
      mk([[215, 95], [215, 165]]),
      mk([[320, 90], [320, 170]]),
    ];
    updateInfo();
    redraw();
    setTimeout(recognize, 250);
  }

  if (new URLSearchParams(location.search).get("demo") === "1") {
    loadDemo();
  }

  fetch("/api/health")
    .then((r) => r.json())
    .then((h) => {
      const prov = (h.providers || []).join(", ") || "CPU";
      engineBadge.textContent = `${h.engine || "engine"} · ${prov.replace(
        "ExecutionProvider",
        ""
      )}`;
      engineBadge.className = "badge badge-ok";
    })
    .catch(() => {
      engineBadge.textContent = "本地服务未连接";
      engineBadge.className = "badge badge-err";
    });
})();
