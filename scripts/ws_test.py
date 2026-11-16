"""End-to-end WebSocket smoke test: a fake pad talks to a fake host."""

import asyncio
import json

import websockets

URL = "ws://127.0.0.1:8848/ws"

STROKES = [
    {"points": [{"x": 100, "y": 300}, {"x": 160, "y": 200}], "width": 3.5},
    {"points": [{"x": 100, "y": 200}, {"x": 160, "y": 300}], "width": 3.5},
    {"points": [{"x": 220, "y": 250}, {"x": 280, "y": 250}], "width": 3.5},
    {"points": [{"x": 250, "y": 210}, {"x": 250, "y": 290}], "width": 3.5},
    {"points": [{"x": 340, "y": 200}, {"x": 340, "y": 300}], "width": 3.5},
]


async def pad_task(host_ready: asyncio.Event):
    async with websockets.connect(URL) as ws:
        await ws.send(json.dumps({"type": "hello", "role": "pad"}))
        # wait until the host shows up (peers broadcast)
        while not host_ready.is_set():
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            print("PAD  <-", msg.get("type"), msg.get("hosts"), msg.get("pads"))
            if msg.get("type") == "peers" and msg.get("hosts", 0) > 0:
                host_ready.set()
        await asyncio.sleep(0.2)
        for s in STROKES:
            await ws.send(json.dumps({"type": "stroke", "stroke": s}))
        await asyncio.sleep(0.2)
        await ws.send(json.dumps({"type": "recognize", "engine": "vlm"}))
        await asyncio.sleep(3)


async def host_task(results: list):
    await asyncio.sleep(0.3)
    async with websockets.connect(URL) as ws:
        await ws.send(json.dumps({"type": "hello", "role": "host"}))
        seen_strokes = 0
        deadline = asyncio.get_event_loop().time() + 25
        while asyncio.get_event_loop().time() < deadline:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=25))
            extra = f" strokes={len(msg.get('strokes', []))}" if msg.get("type") == "state" else ""
            print("HOST <-", msg.get("type"), msg.get("latex", ""), extra)
            if msg.get("type") == "stroke":
                seen_strokes += 1
            if msg.get("type") == "result":
                results.append(msg)
                print(f"strokes received live: {seen_strokes}")
                return


async def main():
    results = []
    host_ready = asyncio.Event()
    await asyncio.gather(host_task(results), pad_task(host_ready))
    assert results, "no result received"
    print("RESULT:", results[0]["latex"], results[0]["timings"])


if __name__ == "__main__":
    asyncio.run(main())
