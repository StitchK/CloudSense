import json
import time


def emit(event, **fields):
    print(json.dumps({"event": event, "logged_at_ms": time.time_ns() // 1_000_000, **fields}, separators=(",", ":"), default=str))
