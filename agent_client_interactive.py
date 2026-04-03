"""
Interactive AI Agent — subscribes to live stream + accepts user questions.
"""
import asyncio
import json
import sys
import websockets

ANOMALY_THRESHOLD = 0.3

FIX_SUGGESTIONS = {
    "Connection refused": "Check if the target service is running. Verify security groups and network ACLs.",
    "Timeout waiting": "Increase timeout or check downstream service health. Add circuit breaker.",
    "OutOfMemoryError": "Increase JVM heap: `-Xmx4g`. Check for memory leaks.",
    "SSL handshake failed": "Renew certificate: `certbot renew`.",
    "Deadlock detected": "Review transaction isolation levels. Consider optimistic locking.",
    "Disk usage critical": "Clean old logs. Add log rotation. Expand volume.",
}

def suggest_fix(message: str) -> str:
    for pattern, fix in FIX_SUGGESTIONS.items():
        if pattern in message:
            return fix
    return "Investigate service logs and recent deployments."

async def stream_listener(ws, state):
    """Listen to live events from the MCP server."""
    async for raw in ws:
        msg = json.loads(raw)
        if msg["type"] != "event":
            continue
        event = msg["data"]
        state["total"] += 1
        level = event.get("level", "INFO")
        text = event.get("message", "")
        ts = event.get("timestamp", "")
        svc = event.get("service", "")

        icon = {"INFO": "·", "WARN": "⚠", "ERROR": "❌", "FATAL": "💀"}.get(level, "·")
        print(f"  {icon} [{ts}] {svc}: {text}")

        if level in ("ERROR", "FATAL"):
            state["errors"].append(event)
            print(f"    🔧 {suggest_fix(text)}")

        if state["total"] % 20 == 0 and state["errors"]:
            rate = len(state["errors"]) / 20
            if rate > ANOMALY_THRESHOLD:
                print(f"\n  🚨 ANOMALY — error rate {rate:.0%} in last 20 events\n")
            state["errors"].clear()

async def user_input(ws, state):
    """Read user commands from stdin and query the MCP server."""
    loop = asyncio.get_event_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        cmd = line.strip().lower()
        if not cmd:
            continue
        if cmd == "anomalies":
            await ws.send(json.dumps({"method": "get_anomalies"}))
            resp = json.loads(await ws.recv())
            summary = resp.get("data", {})
            print(f"\n📊 Anomaly Summary: {json.dumps(summary, indent=2)}\n")
        elif cmd == "context":
            await ws.send(json.dumps({"method": "get_context"}))
            resp = json.loads(await ws.recv())
            print(f"\n📋 Context: {json.dumps(resp.get('data', {}), indent=2)}\n")
        elif cmd == "status":
            print(f"\n📈 Events seen: {state['total']}, Errors in window: {len(state['errors'])}\n")
        elif cmd == "help":
            print("\n  Commands: anomalies | context | status | help | quit\n")
        elif cmd == "quit":
            return
        else:
            print(f"\n  Unknown command: {cmd}. Type 'help' for options.\n")

async def run_agent():
    uri = "ws://localhost:8765"
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({"method": "subscribe", "params": {"topic": "app-logs"}}))
        ack = json.loads(await ws.recv())
        print(f"✅ {ack['type']} to {ack.get('topic', 'stream')}")
        print("💬 Type a command (anomalies | context | status | help | quit)\n")

        state = {"total": 0, "errors": []}
        await asyncio.gather(
            stream_listener(ws, state),
            user_input(ws, state),
        )

if __name__ == "__main__":
    print("🤖 Interactive AI Agent — Live Log Monitor")
    print("=" * 50)
    asyncio.run(run_agent())
