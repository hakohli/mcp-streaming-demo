# MCP Live Streaming Demo — FAQ

## General

**1. What is this project?**
A working demo of streaming MCP (Model Context Protocol) — instead of the traditional request/response model where agents poll for stale snapshots, this pushes real-time log events to AI agents via Kafka + WebSockets. Agents detect anomalies in under a second and suggest fixes automatically.

**2. Who is this for?**
Anyone interested in extending MCP beyond request/response — particularly developers building AI agents that need live, continuous context rather than point-in-time snapshots.

**3. What problem does it solve?**
Standard MCP is pull-based: agents ask for context and get a static snapshot. In operational scenarios (monitoring, incident response), context goes stale immediately. This demo shows how to push events to agents as they happen.

---

## Architecture

**4. What's the data flow?**
`log_simulator.py` → Kafka (`app-logs` topic) → `streaming_mcp_server.py` → WebSocket → `agent_client.py`

**5. Why Kafka instead of just WebSockets end-to-end?**
Kafka provides durability, replayability, and decoupling. If the MCP server restarts, events aren't lost. Multiple consumers can independently read the same stream. You also get consumer groups for load balancing or fan-out.

**6. What's the "hybrid protocol"?**
The agent uses a single WebSocket connection for both streaming (continuous event push) and request/response (on-demand queries like `get_anomalies` and `get_context`). This avoids needing separate channels for real-time data vs. ad-hoc queries.

**7. How does anomaly detection work?**
Two levels:
- **Server-side**: Maintains a rolling 100-event window and tracks error rates + top error patterns via `get_anomaly_summary()`.
- **Agent-side**: Tracks a 20-event sliding window. When the error rate exceeds 30%, it flags an anomaly and queries the server for a full summary.

---

## Authorization

**8. What is Cedar and why is it here?**
Cedar is a policy language (created by AWS) for fine-grained authorization. The demo uses it to control which agents can subscribe to which streams and call which methods — e.g., only `ops-agent` roles can call `get_anomalies`, only `senior-ops` can call `get_context`.

**9. What are the default Cedar policies?**
- Any authenticated agent can subscribe to `app-logs`
- Only `ops-agent` role can request anomaly summaries
- Only `senior-ops` role can access the full context window
- `readonly` agents are forbidden from subscribing to `audit-logs`
- Default deny — if no policy matches, access is denied

**10. Is the Cedar integration production-ready?**
No. `cedar_authz.py` is a lightweight regex-based parser for demo purposes. In production, you'd use the official `cedarpy` SDK or the Cedar service for policy evaluation.

---

## Running the Demo

**11. What are the prerequisites?**
Python 3.9+, Docker (for Kafka), and `pip install confluent-kafka websockets`.

**12. Do I need a real Kafka cluster?**
For the full demo, yes — a single-node Kafka runs via `docker compose up -d` (Confluent cp-kafka 7.6.0 in KRaft mode, no ZooKeeper). For testing, `mock_kafka.py` provides an in-process drop-in replacement.

**13. What's the difference between `agent_client.py` and `agent_client_interactive.py`?**
- `agent_client.py` — passive monitor. Subscribes, prints events, detects anomalies, suggests fixes. No user input.
- `agent_client_interactive.py` — same monitoring, but you can type commands mid-stream (`anomalies`, `context`, `status`, `help`, `quit`).

**14. Output looks delayed/buffered — what do I do?**
Run with `PYTHONUNBUFFERED=1 python agent_client.py` to disable Python's output buffering.

**15. How do I run everything in one terminal?**
Use the tmux one-liner from the README — it splits into three panes (server, simulator, agent).

---

## Design Patterns

**16. How does backpressure work?**
Each subscriber gets a bounded `asyncio.Queue` (max 500 events). If a slow consumer's queue fills up, it's automatically dropped from the subscriber set. This prevents one slow agent from blocking the entire server.

**17. What error patterns does the agent recognize?**
Six patterns with mapped remediation suggestions:
- `Connection refused` → check service status, security groups
- `Timeout waiting` → increase timeout, add circuit breaker
- `OutOfMemoryError` → increase heap, check for leaks
- `SSL handshake failed` → renew certificate
- `Deadlock detected` → review isolation levels
- `Disk usage critical` → clean logs, expand volume

**18. How are error spikes simulated?**
`log_simulator.py` runs on a 45-second cycle. Between ticks 30–40, it injects 3–6 ERROR events per second (with a 30% chance of a FATAL). Outside that window, it's normal INFO traffic with occasional WARNs.

---

## Extending the Demo

**19. Can I add my own log sources?**
Yes — anything that produces JSON to the `app-logs` Kafka topic will flow through. Match the schema: `{"timestamp", "level", "service", "message", "request_id"}`.

**20. Can I add new Cedar policies?**
Add policy strings to the `CEDAR_POLICIES` list in `cedar_authz.py`. Use `streaming_mcp_server_cedar.py` (the Cedar-enabled server variant) to enforce them.

**21. How would I connect a real LLM agent?**
Replace the hardcoded `FIX_SUGGESTIONS` dict in the agent client with an LLM call. The streaming event data and anomaly summaries become the context window for the model. The WebSocket protocol stays the same.

---

## Advanced / Complex Questions

**22. How would this scale to thousands of concurrent agents?**
The current design has one WebSocket per agent, each with its own `asyncio.Queue`. At scale, this hits memory limits (500 events × N agents) and a single-threaded event loop bottleneck. To scale:
- Horizontally shard the MCP server behind a load balancer — use Kafka consumer groups so each server instance handles a partition subset.
- Replace per-agent queues with a pub/sub broker (Redis Streams, NATS) between Kafka and WebSocket layer.
- Consider Server-Sent Events (SSE) for one-way streaming to reduce connection overhead if agents don't need the hybrid request/response path.

**23. What happens if the MCP server crashes mid-stream? Do agents lose events?**
Yes — events in-flight in the asyncio queues are lost. However, Kafka retains the full log. On restart, the server's consumer group offset determines where it resumes. Since `auto.offset.reset` is set to `latest`, it skips events produced during downtime. To guarantee no event loss:
- Change `auto.offset.reset` to `earliest` and commit offsets manually after successful delivery to all subscribers.
- Agents should track the last event timestamp they received and request a replay via a `get_context` call on reconnect.

**24. The Kafka consumer uses `group.id: "mcp-streaming-server"`. What happens with multiple server instances?**
Kafka partitions the topic across consumers in the same group — each instance gets a subset of partitions. This means each agent only sees a fraction of events unless you either:
- Give each server instance a unique `group.id` (fan-out — every instance gets all events), or
- Use a single partition (no parallelism), or
- Add a coordination layer that merges partitioned streams before pushing to agents.

**25. The sliding window anomaly detection is purely count-based. How would you make it time-aware?**
The current 100-event window conflates high-throughput periods with low-throughput ones — 30% errors in 2 seconds is very different from 30% errors over 10 minutes. Improvements:
- Switch to a time-based window (e.g., last 60 seconds) using a deque with timestamp-based eviction.
- Use exponential weighted moving average (EWMA) for error rate to smooth out short bursts.
- Add rate-of-change detection — a sudden jump from 2% to 15% is more significant than a steady 20%.

**26. How would you handle multi-tenant isolation — multiple customers' logs on the same server?**
Currently there's one Kafka topic and one subscriber pool. For multi-tenancy:
- Use per-tenant Kafka topics (`app-logs-tenant-a`, `app-logs-tenant-b`) and have agents subscribe to their tenant's topic.
- Extend the Cedar policies to bind principals to tenant IDs: `permit(principal, action == Action::"subscribe", resource) when { principal.tenant == resource.tenant };`
- Add tenant context to the WebSocket handshake (JWT or API key) and validate before allowing subscription.

**27. The Cedar policy engine parses policies with regex. What breaks?**
Several things:
- Nested `when` clauses with boolean logic (`&&`, `||`) aren't handled.
- Set-based conditions (`principal.tags.containsAll(...)`) are ignored.
- The regex parser can't handle multi-line policies or comments.
- There's no schema validation — typos in entity types silently produce no-match rules (default deny).
- In production, use the official Cedar SDK which handles the full grammar, entity stores, and schema validation.

**28. Could this replace polling-based MCP for all use cases?**
No. Streaming is ideal for high-frequency, time-sensitive data (logs, metrics, alerts). But polling/request-response is simpler and better for:
- Low-frequency context (customer profiles, config snapshots) where freshness isn't critical.
- Large context payloads that would overwhelm a WebSocket stream.
- Stateless agents that spin up, grab context, and terminate.
The hybrid protocol in this demo is the pragmatic answer — stream what's time-sensitive, request/response for everything else.

**29. What's the failure mode if Kafka is down but the WebSocket server is still running?**
The `poll()` method returns `None` on Kafka errors, so the server stays alive but stops pushing events. Agents remain connected but see silence. There's no health signal — agents can't distinguish "no events happening" from "Kafka is dead." Fix:
- Add a heartbeat mechanism — server sends a `{"type": "heartbeat"}` every N seconds. If agents don't receive one, they know the pipeline is broken.
- Expose a `/health` endpoint on the server that checks Kafka connectivity.

**30. How would you add event replay — letting an agent request historical events?**
Currently `get_context` returns the in-memory 100-event window. For true replay:
- Store events in a durable secondary store (DynamoDB, S3, or Kafka with long retention).
- Add a `replay` method: `{"method": "replay", "params": {"from": "2026-04-24T10:00:00", "to": "2026-04-24T10:05:00"}}`.
- Stream replayed events with a `{"type": "replay_event"}` tag so agents can distinguish live from historical.
- Consider backpressure — replaying 10,000 events at once will blow the 500-event queue. Batch and pace delivery.

**31. The agent's `FIX_SUGGESTIONS` is a static lookup. How would you integrate an LLM without adding latency to the event stream?**
Don't block the event stream on LLM calls. Instead:
- Buffer errors into a batch (e.g., 5 errors or 10-second window).
- Send the batch to the LLM asynchronously as a background task.
- Print the LLM's remediation when it returns, tagged with the original event timestamps.
- Keep the static lookup as a fast fallback for known patterns — only invoke the LLM for unrecognized errors or when the agent needs root-cause correlation across multiple error types.

**32. What ordering guarantees does this architecture provide?**
Kafka guarantees ordering within a partition. Since the demo uses a single-partition topic, events arrive in producer order. But:
- The asyncio queue per subscriber is FIFO, so ordering is preserved to the agent.
- If you scale to multiple partitions, ordering is only guaranteed per-partition. Events from different services could interleave differently per consumer.
- WebSocket delivery is ordered (TCP), so no reordering between server and agent.
- The weak link is the `notify_subscribers` fan-out — if one queue is near-full and another is empty, they'll diverge in how far behind they are.
