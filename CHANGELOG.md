# Changelog

## v0.1.1-test — 2026-11-16

### Fixed

- **平板横屏/竖屏画布边缘无法书写**：逻辑画布不再固定 1000×600，而是按输入设备视口比例动态生成
  （横屏 1000×~684、竖屏 ~630×900），整块画布都可写，不再有 letterbox 空白边
- 设备旋转时自动重算画布，已有笔画按比例缩放，不会错位
- 主机端镜像的非可写边距加了浅色遮罩，避免误以为可以写

### Added

- **PC 主机端可直接书写**：鼠标 / 触屏 / 触控笔都能在主机镜像区书写，与平板共用同一画布
- 主机端显示当前逻辑画布尺寸
- 恢复 GitHub Actions CI（单元测试）

### Changed

- 平板端预览也广播给其他输入端，主机书写时平板可实时看到

## v0.1.0-test — 2026-11-16

First public test release.

### Features

- **Two-device mode**: tablet writes, desktop displays and copies LaTeX
  - `/` desktop host: live ink mirror, KaTeX preview, editable source, copy, history, QR pairing
  - `/pad` tablet: full-screen stylus canvas, pressure-sensitive width, palm rejection, undo/clear/recognize, auto-recognize, fullscreen
- **Two engines**
  - Uni-MuMER 2B (Qwen3-VL, GGUF Q4, llama.cpp Vulkan, GPU) — default
  - CoMER INT8 (7.2 MB ONNX, CPU) — fallback / low-spec
- Real-time WebSocket sync (strokes, preview, results, peer status)
- Logical canvas 1000×600 shared by both ends; both scale to fit
- Local model download scripts (`download_models.py`), including llama.cpp runtime
- Local KaTeX assets — works fully offline

### Measured (CROHME 2019)

- ≤5 tokens (209 samples): 81.3% exact, 93.3% within one edit, p50 61 ms (VLM)
- 400-sample all lengths: 72.3% exact, p50 120 ms (VLM)
- End-to-end tablet → desktop result: ~200 ms

### Known limitations

- Single-line formulas; matrices / multi-line / Chinese mixed text are not guaranteed
- Symbol-level ambiguity (`a/α`, `8/g`, case) still occurs; use the editor
- LAN mode has no authentication — do not expose to the public internet
- Windows-first (Vulkan llama.cpp build); Linux/macOS need a matching llama.cpp build
- First VLM request after start is slower (model load + warmup)

### Licensing

- Source: MIT
- Model weights and evaluation datasets are downloaded separately and keep their own licenses; see `THIRD_PARTY.md`
