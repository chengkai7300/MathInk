from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

import numpy as np
import onnxruntime as ort

from .. import image_ops, latex_utils
from .base import Recognition


class ComerEngine:
    """CoMER INT8 ONNX (encoder + decoder), 7.2 MB total."""

    name = "comer"

    def __init__(self, model_dir: Path, provider: str = "auto", beam_width: int = 1, max_steps: int = 40):
        self.model_dir = Path(model_dir)
        self.beam_width = max(1, beam_width)
        self.max_steps = max(8, max_steps)
        self.repeat_limit = 3

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = int(os.environ.get("MATHINK_THREADS", "8"))
        self._opts = opts
        providers = self._providers(provider)
        self.encoder = ort.InferenceSession(
            str(self.model_dir / "encoder_int8.onnx"), sess_options=opts, providers=providers
        )
        self.decoder = ort.InferenceSession(
            str(self.model_dir / "decoder_int8.onnx"), sess_options=opts, providers=providers
        )
        vocab = json.loads((self.model_dir / "vocab.json").read_text(encoding="utf-8"))
        self.idx2word: dict[str, str] = vocab["idx2word"]
        self.sos = vocab["special_tokens"]["sos"]
        self.eos = vocab["special_tokens"]["eos"]
        self.vocab_size = vocab["vocab_size"]
        self.providers = self.encoder.get_providers()

    @staticmethod
    def _providers(pref: str) -> list[str]:
        available = ort.get_available_providers()
        if pref == "cpu":
            return ["CPUExecutionProvider"]
        if "CUDAExecutionProvider" in available:
            return ["CUDAExecutionProvider", "CPUExecutionProvider"]
        return ["CPUExecutionProvider"]

    # ---- inference -------------------------------------------------

    def _run_decoder(self, feats: np.ndarray, emask: np.ndarray, ids: list[int]) -> np.ndarray:
        out = self.decoder.run(
            None,
            {
                "encoder_features": feats,
                "encoder_mask": emask,
                "input_ids": np.asarray([ids], dtype=np.int64),
            },
        )
        return out[0]

    def recognize_strokes(self, strokes: Sequence[image_ops.Stroke], beam_width: int | None = None) -> Recognition:
        t0 = time.perf_counter()
        tensor, mask = image_ops.strokes_to_input(strokes)
        return self._recognize_tensor(tensor, mask, t0, beam_width)

    def recognize_image(self, img, beam_width: int | None = None) -> Recognition:
        t0 = time.perf_counter()
        tensor, mask = image_ops.image_to_input(img)
        return self._recognize_tensor(tensor, mask, t0, beam_width)

    def recognize_tensor(self, tensor, mask, beam_width: int | None = None) -> Recognition:
        return self._recognize_tensor(tensor, mask, time.perf_counter(), beam_width)

    def _recognize_tensor(self, tensor, mask, t0, beam_width=None):
        feats, emask = self._encode(tensor, mask)
        t1 = time.perf_counter()

        bw = self.beam_width if beam_width is None else max(1, beam_width)
        if bw <= 1:
            ids, logprob = self._greedy(feats, emask)
        else:
            ids, logprob = self._beam(feats, emask, bw)

        tokens = [self.idx2word[str(i)] for i in ids if str(i) in self.idx2word]
        repaired = latex_utils.repair(tokens)
        latex = latex_utils.normalize(latex_utils.tokens_to_latex(repaired))
        t2 = time.perf_counter()
        return Recognition(
            latex=latex,
            tokens=repaired,
            logprob=float(logprob),
            timings={
                "encode_ms": round((t1 - t0) * 1000, 1),
                "decode_ms": round((t2 - t1) * 1000, 1),
                "total_ms": round((t2 - t0) * 1000, 1),
            },
            engine=self.name,
        )

    def _encode(self, tensor, mask):
        feats, emask = self.encoder.run(
            None, {"pixel_values": tensor, "pixel_mask": mask}
        )
        return feats, emask

    def _greedy(self, feats, emask):
        ids = [self.sos]
        logprob = 0.0
        last = -1
        repeat = 0
        for _ in range(self.max_steps):
            logits = self._run_decoder(feats, emask, ids)[0, -1, :]
            lp = _log_softmax(logits)
            nxt = int(np.argmax(lp))
            if nxt == self.eos:
                break
            logprob += float(lp[nxt])
            if nxt == last:
                repeat += 1
                if repeat >= self.repeat_limit:
                    break
            else:
                repeat = 0
            last = nxt
            ids.append(nxt)
        return ids[1:], logprob

    def _beam(self, feats, emask, width):
        beams = [([self.sos], 0.0, False)]
        for _ in range(self.max_steps):
            cand = []
            for ids, lp_sum, finished in beams:
                if finished:
                    cand.append((ids, lp_sum, True))
                    continue
                logits = self._run_decoder(feats, emask, ids)[0, -1, :]
                lp = _log_softmax(logits)
                top = np.argsort(lp)[-width * 2 :][::-1]
                for idx in top:
                    new_lp = lp_sum + float(lp[idx])
                    if idx == self.eos:
                        cand.append((ids, new_lp, True))
                        continue
                    r = 0
                    for j in range(len(ids) - 1, 0, -1):
                        if ids[j] == idx:
                            r += 1
                        else:
                            break
                    if r >= self.repeat_limit:
                        cand.append((ids, new_lp, True))
                    else:
                        cand.append((ids + [int(idx)], new_lp, False))
            cand.sort(key=lambda b: b[1] / max(len(b[0]), 1), reverse=True)
            beams = cand[:width]
            if all(b[2] for b in beams):
                break
        done = [b for b in beams if b[2]] or beams
        done.sort(key=lambda b: b[1] / max(len(b[0]), 1), reverse=True)
        ids, lp, _ = done[0]
        return ids[1:], lp


def _log_softmax(x: np.ndarray) -> np.ndarray:
    x = x.astype(np.float64)
    m = np.max(x)
    return x - m - np.log(np.sum(np.exp(x - m)))
