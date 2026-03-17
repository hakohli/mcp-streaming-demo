# MCP Live: Streaming Context to AI Agents

## Demo Setup (run in order)

### 1. Start Kafka
```bash
docker compose up -d
```

### 2. Install dependencies
```bash
pip install confluent-kafka websockets mcp
```

### 3. Start the Streaming MCP Server
```bash
python streaming_mcp_server.py
```

### 4. Start the Log Simulator (separate terminal)
```bash
python log_simulator.py
```

### 5. Start the AI Agent (separate terminal)
```bash
python agent_client.py
```

## What You'll See

- Normal log traffic flowing through the agent in real-time
- Every ~30 seconds, an error spike hits
- The agent detects the spike, flags the anomaly, and suggests fixes
- The agent queries the server for anomaly summaries mid-stream

## Architecture

```
log_simulator.py → Kafka (app-logs) → streaming_mcp_server.py → agent_client.py
                                              ↕ WebSocket
                                        subscribe / get_anomalies / get_context
```

## Key Patterns Demonstrated

1. **Event subscription** — agent subscribes once, gets continuous updates
2. **Hybrid protocol** — streaming + request/response on same connection
3. **Sliding window anomaly detection** — server tracks error rates in rolling buffer
4. **Backpressure handling** — bounded queues drop slow subscribers
5. **Kafka as durable event bus** — replayable, decoupled, scalable
