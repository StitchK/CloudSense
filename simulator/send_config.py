"""Load the private simulator endpoint independently of the working directory."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit


LOCAL_CONFIG = Path(__file__).resolve().with_name("simulator.local.json")


def resolve_api_url(explicit_url=None):
    endpoint = explicit_url or os.getenv("CLOUDSENSE_API_URL")
    if not endpoint:
        try:
            settings = json.loads(LOCAL_CONFIG.read_text(encoding="utf-8"))
            base = settings["api_base_url"]
            if not isinstance(base, str) or not base.strip():
                raise ValueError
            endpoint = base.strip().rstrip("/")
            if not endpoint.endswith("/readings"):
                endpoint += "/readings"
        except FileNotFoundError as exc:
            raise ValueError(
                "Copy simulator.local.example.json to simulator.local.json beside "
                "the sender scripts and set api_base_url, or provide --api-url."
            ) from exc
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ValueError(
                "simulator.local.json must contain a valid api_base_url string."
            ) from exc
    parsed = urlsplit(endpoint)
    if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError("The simulator endpoint must be an HTTPS URL without query or fragment.")
    if "<" in endpoint or ">" in endpoint:
        raise ValueError("Replace the API placeholder in simulator.local.json with your API base URL.")
    return endpoint
