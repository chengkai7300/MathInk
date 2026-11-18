# Changelog

## v0.1.3-test — 2026-11-18

### Added

- **单文件 `MathInk.exe`**：双击启动，内置托盘图标、Web 服务与 CoMER 模型（约 58 MB）
  - 可执行文件在项目根目录时，自动使用旁边的 `models/vlm` 和 `tools/llama`（高精度模式）
  - 单独拷走 exe 也能用 CoMER（CPU），VLM 不可用时自动隐藏/降级
  - `MathInk.exe --stop` 可命令行彻底关闭
- **PC 主机端自动识别**：在主机画布上停笔约 0.9 秒自动识别，工具栏可关闭「自动」
- `build_exe.ps1` + `MathInk.spec` + 图标生成脚本，可复现构建

### Fixed

- 主机端此前只发送笔画，必须手动点「重新识别」；现在与平板端行为一致

## v0.1.2-test — 2026-11-18

### Fixed

- **退出后 `llama-server` 残留、显存不释放**：根因是子进程只依赖 FastAPI 的 lifespan 收尾，
  关闭窗口/强杀主程序时不会执行，于是 llama-server 成为孤儿并持续占用约 1.9 GB 显存
- 启动时自动清理上次遗留的 `llama-server`（按命令行匹配本项目模型路径）
- `stop` 现在同时清理 launcher、uvicorn、llama-server，并校验 PID 确实是 `llama-server.exe`

### Added

- **系统托盘图标**（pystray）：打开主机端、复制平板地址、查看状态、释放显存、打开日志、彻底退出
- **后台启动**：`start.ps1` 拉起托盘程序后立即返回；`-Console` 可前台调试
- **Windows Job Object（KILL_ON_JOB_CLOSE）**：主程序被强杀/崩溃时，llama-server 也会被回收
- 单实例互斥锁，重复执行 `start.ps1` 只会打开已有页面
- CLI：`python launcher.py --stop` / `--selftest-quit`

### Changed

- llama-server 上下文 4096 → **2048**，并行槽位 → **1**，降低 KV 缓存占用
- `stop.ps1` 优先调用 launcher 的停止逻辑，再兜底清理端口和进程

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
