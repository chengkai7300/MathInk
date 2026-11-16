"""End-to-end WebSocket smoke test: a fake pad talks to a fake host."""

import argparse
import asyncio
import json

import websockets

STROKES = [
    {"points": [{"x": 100, "y": 300}, {"x": 160, "y": 200}], "width": 3.5},
    {"points": [{"x": 100, "y": 200}, {"x": 160, "y": 300}], "width": 3.5},
    {"points": [{"x": 220, "y": 250}, {"x": 280, "y": 250}], "width": 3.5},
    {"points": [{"x": 250, "y": 210}, {"x": 250, "y": 290}], "width": 3.5},
    {"points": [{"x": 340, "y": 200}, {"x": 340, "y": 300}], "width": 3.5},
]


async def pad_task(url: str, engine: str, host_ready: asyncio.Event):
    async with websockets.connect(url) as ws:
        await ws.send(json.dumps({"type": "hello", "role": "pad"}))
        while not host_ready.is_set():
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            if msg.get("type") == "peers" and msg.get("hosts", 0) > 0:
                host_ready.set()
        await asyncio.sleep(0.2)
        for s in STROKES:
            await ws.send(json.dumps({"type": "stroke", "stroke": s}))
        await asyncio.sleep(0.2)
        await ws.send(json.dumps({"type": "recognize", "engine": engine}))
        await asyncio.sleep(3)


async def host_task(url: str, results: list, seen: dict):
    await asyncio.sleep(0.3)
    async with websockets.connect(url) as ws:
        await ws.send(json.dumps({"type": "hello", "role": "host"}))
        deadline = asyncio.get_event_loop().time() + 25
        while asyncio.get_event_loop().time() < deadline:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=25))
            print("HOST <-", msg.get("type"), msg.get("latex", ""))
            if msg.get("type") == "stroke":
                seen["strokes"] += 1
            if msg.get("type") == "result":
                results.append(msg)
                return


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="ws://127.0.0.1:8848/ws")
    ap.add_argument("--engine", default="auto")
    args = ap.parse_args()

    results: list = []
    seen = {"strokes": 0}
    host_ready = asyncio.Event()
    await asyncio.gather(
        host_task(args.url, results, seen), pad_task(args.url, args.engine, host_ready)
    )
    assert results, "no result received"
    print("strokes received live:", seen["strokes"])
    print("RESULT:", results[0]["latex"], results[0]["timings"])
    assert seen["strokes"] == len(STROKES), "live stroke broadcast failed"


if __name__ == "__main__":
    asyncio.run(main())
