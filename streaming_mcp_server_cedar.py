"""
Streaming MCP Server with Cedar authorization.
Uses mock_kafka for local testing, real confluent_kafka in production.
"""

import asyncio
import json
import os
from collections import deque
from typing import Optional, Dict, Set

# Use mock Kafka for local testing, real Kafka in production
if os.environ.get("USE_REAL_KAFKA"):
    from confluent_kafka import Consumer, Producer
else:
    from mock_kafka import Consumer, Producer

import websockets
from cedar_authz import CedarAuthz


class LogStreamConsumer:
    def __init__(self, broker="localhost:9092", topic="app-logs"):
        self.topic = topic
        self.consumer = Consumer({
            "bootstrap.servers": broker,
            "group.id": "mcp-streaming-server",
            "auto.offset.reset": "latest",
        })
        self.consumer.subscribe([topic])
        self.subscribers = set()  # type: Set[asyncio.Queue]
        self.recent = deque(maxlen=100)
        self.error_counts = {}  # type: Dict[str, int]

    def poll(self):
        # type: () -> Optional[dict]
        msg = self.consumer.poll(0.1)
        if msg is None or (hasattr(msg, 'error') and callable(msg.error) and msg.error()):
            return None
        event = json.loads(msg.value().decode("utf-8"))
        self.recent.append(event)
        if event.get("level") in ("ERROR", "FATAL"):
            key = event.get("message", "")[:80]
            self.error_counts[key] = self.error_counts.get(key, 0) + 1
        return event

    def get_anomaly_summary(self):
        # type: () -> dict
        if not self.recent:
            return {"status": "no_data"}
        errors = [e for e in self.recent if e.get("level") in ("ERROR", "FATAL")]
        error_rate = len(errors) / len(self.recent)
        top_errors = sorted(self.error_counts.items(), key=lambda x: -x[1])[:5]
        return {
            "window_size": len(self.recent),
            "error_rate": round(error_rate, 3),
            "spike": error_rate > 0.3,
            "top_errors": [{"message": m, "count": c} for m, c in top_errors],
            "total_errors": len(errors),
        }

    async def notify_subscribers(self, event):
        dead = set()
        for q in self.subscribers:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                dead.add(q)
        self.subscribers -= dead

    def subscribe(self):
        # type: () -> asyncio.Queue
        q = asyncio.Queue(maxsize=500)
        self.subscribers.add(q)
        return q

    def unsubscribe(self, q):
        self.subscribers.discard(q)


class StreamingMCPServer:
    def __init__(self, log_stream):
        self.log_stream = log_stream
        self.authz = CedarAuthz()

    async def handle_client(self, ws, path=None):
        principal = {"id": "anonymous", "role": "viewer"}
        sub_queue = None
        stream_task = None
        try:
            async for raw in ws:
                msg = json.loads(raw)
                method = msg.get("method")

                if method == "auth":
                    principal = msg.get("principal", principal)
                    await ws.send(json.dumps({"type": "authenticated", "principal": principal}))
                    continue

                resource = msg.get("params", {}).get("topic", self.log_stream.topic)
                if not self.authz.is_authorized(principal, method, resource):
                    explanation = self.authz.explain(principal, method, resource)
                    await ws.send(json.dumps({
                        "type": "error", "code": "FORBIDDEN", "message": explanation,
                    }))
                    continue

                if method == "subscribe":
                    sub_queue = self.log_stream.subscribe()
                    stream_task = asyncio.create_task(self._stream_events(ws, sub_queue))
                    await ws.send(json.dumps({"type": "subscribed", "topic": self.log_stream.topic}))

                elif method == "unsubscribe":
                    if sub_queue:
                        self.log_stream.unsubscribe(sub_queue)
                        if stream_task:
                            stream_task.cancel()
                    await ws.send(json.dumps({"type": "unsubscribed"}))

                elif method == "get_anomalies":
                    await ws.send(json.dumps({
                        "type": "response", "method": "get_anomalies",
                        "data": self.log_stream.get_anomaly_summary(),
                    }))

                elif method == "get_context":
                    await ws.send(json.dumps({
                        "type": "response", "method": "get_context",
                        "data": list(self.log_stream.recent),
                    }))
        finally:
            if sub_queue:
                self.log_stream.unsubscribe(sub_queue)
            if stream_task:
                stream_task.cancel()

    async def _stream_events(self, ws, queue):
        try:
            while True:
                event = await queue.get()
                await ws.send(json.dumps({"type": "event", "data": event}))
        except (asyncio.CancelledError, websockets.ConnectionClosed):
            pass


async def kafka_poll_loop(log_stream):
    loop = asyncio.get_event_loop()
    while True:
        event = await loop.run_in_executor(None, log_stream.poll)
        if event:
            await log_stream.notify_subscribers(event)
        else:
            await asyncio.sleep(0.05)


async def main():
    log_stream = LogStreamConsumer()
    server = StreamingMCPServer(log_stream)
    ws_server = await websockets.serve(server.handle_client, "0.0.0.0", 8765)
    print("Streaming MCP Server (Cedar-authorized) on ws://localhost:8765")
    await asyncio.gather(kafka_poll_loop(log_stream), ws_server.wait_closed())

if __name__ == "__main__":
    asyncio.run(main())
