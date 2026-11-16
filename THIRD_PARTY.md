# Third-party components and licenses

MathInk's own source code is MIT-licensed (see `LICENSE`). Model weights and
datasets are **not** included in this repository; they are downloaded by the user
and remain under their respective licenses.

| Component | Used for | License | Notes |
| --- | --- | --- | --- |
| [Uni-MuMER-Qwen3-VL-2B](https://huggingface.co/phxember/Uni-MuMER-Qwen3-VL-2B) | default recognition model | Apache-2.0 | fine-tuned on CROHME/HME100K/MathWriting; those datasets are research/non-commercial, so treat the weights as research-use |
| [Qwen3-VL-2B-Instruct](https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct) | VLM base | Apache-2.0 | |
| [llama.cpp](https://github.com/ggml-org/llama.cpp) | local VLM runtime | MIT | Windows Vulkan build |
| [CoMER](https://github.com/Green-Wood/CoMER) | CPU fallback engine | repository has no explicit license | ONNX weights packaged by ink-on; research use |
| [ink-on](https://github.com/kimseungdae/ink-on) | CoMER ONNX packaging | Apache-2.0 | |
| [KaTeX](https://katex.org/) | LaTeX rendering | MIT | vendored under `web/vendor/katex` |
| [CROHME](https://www.isical.ac.in/~crohme/CROHME_data.html) | evaluation data (not shipped) | research only, no commercial use | |
| [HME100K](https://ai.100tal.com/dataset) | evaluation data (not shipped) | check with publisher | |
| [FastAPI](https://fastapi.tiangolo.com/) | HTTP/WebSocket server | MIT | |
| [uvicorn](https://www.uvicorn.org/) | ASGI server | BSD-3-Clause | |
| [ONNX Runtime](https://onnxruntime.ai/) | CoMER inference | MIT | |
| [Pillow](https://python-pillow.org/) | stroke rasterization | HPND | |
| [NumPy](https://numpy.org/) | arrays | BSD-3-Clause | |
| [qrcode](https://github.com/lincolnloop/python-qrcode) | pairing QR | BSD | |
| [websockets](https://github.com/python-websockets/websockets) | test client only | BSD-3-Clause | |

If you intend to use this project commercially, replace the CoMER/VLM weights
with models trained on data you are allowed to use, and review every license above.
