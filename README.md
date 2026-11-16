# MathInk

鼠标手写数学公式 → LaTeX。本地服务 + 浏览器界面，模型全部离线，单公式 **< 1 秒**。

![界面截图](docs/assets/screenshot.png)

> 状态：MVP 可运行（v0.2，2026-11-16）。当前引擎为 CoMER INT8（7.2 MB），CPU 推理约 110 ms。
> 非商用项目；CROHME 数据与权重仅限研究/自用。

## 快速开始

```powershell
# Windows，一键：建虚拟环境 → 装依赖 → 下模型 → 启动
powershell -ExecutionPolicy Bypass -File start.ps1
```

打开 <http://127.0.0.1:8848>，按住鼠标左键写公式，停笔约 0.9 s 自动识别；
也可以点「示例」先看效果。

手动方式：

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r backend\requirements.txt
.\.venv\Scripts\python scripts\download_models.py --engine comer
$env:PYTHONPATH="backend"
.\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8848
```

## 功能

- 鼠标/触屏画布：多笔、撤销、清空、示例、Ctrl+Enter 识别、Ctrl+Z 撤销
- 停笔自动识别（可关）
- KaTeX 本地预览 + 可编辑 LaTeX 源码 + 一键复制
- 实时显示编码/解码/往返耗时，超过 1 s 变黄
- 页脚显示内容尺寸，写得过小/过大时提示
- 全离线：KaTeX、模型、前端资源都在本地

## 架构

```
浏览器画布 ──strokes JSON──▶ FastAPI ──▶ 预处理(渲染/缩放/mask)
                                   │
                                   ▼
                            CoMER INT8 ONNX
                          encoder + decoder (beam)
                                   │
                     LaTeX 修复/归一化 ◀── 解码 tokens
                                   │
浏览器 KaTeX 预览 ◀── JSON ─────────┘
```

| 目录 | 说明 |
| --- | --- |
| `backend/app/main.py` | FastAPI、`/api/recognize`、静态站点 |
| `backend/app/image_ops.py` | 笔画渲染与 CoMER 官方预处理 |
| `backend/app/latex_utils.py` | 括号/参数修复、归一化 |
| `backend/app/engines/comer.py` | ONNX 会话、贪心/beam 解码、计时 |
| `web/` | 单页前端（原生 JS + KaTeX） |
| `models/comer/` | encoder/decoder/vocab，共 7.2 MB |
| `scripts/` | 模型下载、CROHME 评测 |
| `docs/` | 调研与设计文档 |

## 实测

| 项目 | 结果 |
| --- | --- |
| CROHME 2019，≤5 符号（全量 209 张） | **ExpRate 73.7%，≤1 次编辑 91.4%**，p50 224 ms |
| CROHME 2019，6–10 符号 | ExpRate 69.0%，≤1 次编辑 82.8% |
| CROHME 2019 整体（400 张抽样） | ExpRate 58.0%（长公式拉低，见文档） |
| 画布 `x + 1`（211×65） | 端到端 105 ms |
| 画布长公式（700×70） | 端到端 360 ms |
| 模型体积 / 显存 | 7.2 MB / 不需要（CPU） |

解读：**短公式是主场景**——74% 不需修改，91% 改一处即可；长公式和深嵌套明显掉点，
这是 CoMER 的边界，也是二期 VLM 的切入点。

评测脚本：

```powershell
# 短公式全量
.\.venv\Scripts\python scripts\eval_crohme.py --gt-max-len 5 --limit 300 --variants official
# 抽样对比不同预处理
.\.venv\Scripts\python scripts\eval_crohme.py --stride 3 --limit 400 --variants official,crop,inkon
```

## 能力边界

词表 113 个 token：四则、分式、根号、上下标、`\int \sum \lim \sin \cos \log`、常用希腊字母。
**不支持**矩阵、偏导 `\partial`、`\hat/\vec`、多行、中文。复杂公式请等二期的 2B VLM 引擎。

## 文档

- [方案调研（全景对比）](docs/01-调研与方案.md)
- [方案收敛与实现记录](docs/02-方案收敛与实现记录.md)

## 许可与致谢

- CoMER: ECCV 2022，代码仓库未声明许可；ONNX 权重由 [ink-on](https://github.com/kimseungdae/ink-on)（Apache-2.0）打包。
- CROHME 数据：仅限研究，禁止商用。
- KaTeX: MIT。
- 本项目仅用于学习/研究，非商用。
