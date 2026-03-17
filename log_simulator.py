"""
Simulates an application producing log events to Kafka.
Generates normal traffic with periodic error spikes to demo anomaly detection.
"""

import json
import random
import time
from confluent_kafka import Producer

SERVICES = ["api-gateway", "auth-service", "payment-service", "order-service", "inventory-db"]
NORMAL_MESSAGES = [
    "Request processed successfully",
    "Cache hit for user session",
    "Database query completed in 12ms",
    "Health check passed",
    "Connection pool: 23/50 active",
]
ERROR_MESSAGES = [
    "Connection refused to inventory-db:5432",
    "Timeout waiting for payment-service response (30s)",
    "OutOfMemoryError: Java heap space",
    "SSL handshake failed: certificate expired",
    "Deadlock detected in transaction pool",
    "Disk usage critical: /var/log at 97%",
]

producer = Producer({"bootstrap.servers": "localhost:9092"})

def make_log(level="INFO", spike=False):
    service = random.choice(SERVICES)
    if spike or level in ("ERROR", "FATAL"):
        msg = random.choice(ERROR_MESSAGES)
    else:
        msg = random.choice(NORMAL_MESSAGES)
    return {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "level": level,
        "service": service,
        "message": msg,
        "request_id": f"req-{random.randint(10000,99999)}",
    }

def run():
    print("Log simulator running. Ctrl+C to stop.")
    tick = 0
    while True:
        # Normal traffic
        for _ in range(random.randint(1, 3)):
            event = make_log("INFO")
            producer.produce("app-logs", json.dumps(event).encode())

        # Occasional warnings
        if random.random() < 0.15:
            event = make_log("WARN")
            producer.produce("app-logs", json.dumps(event).encode())

        # Error spike every ~30 seconds for ~10 seconds
        tick += 1
        if 30 <= (tick % 45) <= 40:
            for _ in range(random.randint(3, 6)):
                event = make_log("ERROR", spike=True)
                producer.produce("app-logs", json.dumps(event).encode())
            if random.random() < 0.3:
                event = make_log("FATAL", spike=True)
                producer.produce("app-logs", json.dumps(event).encode())

        producer.flush()
        time.sleep(1)

if __name__ == "__main__":
    run()
