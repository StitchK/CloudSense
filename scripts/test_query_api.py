"""Read-only smoke test for the deployed query API; standard library only."""

import argparse
import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="QueryApiBaseUrl stack output")
    parser.add_argument("--device-id", required=True, help="Device with existing stored readings")
    parser.add_argument("--from", dest="start", help="ISO 8601 time, e.g. 2026-10-01T00:00:00Z")
    parser.add_argument("--to", dest="end", help="ISO 8601 time, e.g. 2026-11-07T00:00:00Z")
    args = parser.parse_args()
    if urlsplit(args.base_url).scheme != "https":
        parser.error("--base-url must be an HTTPS URL")
    base = args.base_url.rstrip("/") + "/devices/" + quote(args.device_id, safe="")
    params = {"limit": "2"}
    if args.start:
        params["from"] = args.start
    if args.end:
        params["to"] = args.end

    def get(view, query=None):
        url = base + "/" + view + ("?" + urlencode(query) if query else "")
        with urlopen(url, timeout=20) as response:
            body = json.load(response)
            if response.status != 200 or body.get("device_id") != args.device_id:
                raise ValueError("Unexpected status or device_id")
        return body

    try:
        latest = get("latest")
        print("latest: HTTP 200")
        print(" reading_id:", latest["data"]["reading"]["reading_id"])
        print(" overall_status:", latest["data"]["overall_status"])
        print(" is_stale:", latest["is_stale"])
        print(" alerts:", json.dumps(latest["data"]["alerts"], ensure_ascii=False))
        for view in ("history", "alerts"):
            body = get(view, params)
            if not isinstance(body["items"], list) or body["count"] != len(body["items"]):
                raise ValueError("Invalid list response")
            print(f'{view}: HTTP 200, count={body["count"]}, has_next_page={bool(body["next_token"])}')
        print("PASS: three deployed GET routes responded successfully")
        print("List checks cover the first page; full database comparison uses verify_live_queries.py.")
    except HTTPError as exc:
        parser.exit(1, f"FAIL: HTTP {exc.code}: {exc.read().decode()}\n")
    except (URLError, TimeoutError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f"FAIL: {exc}\n")


if __name__ == "__main__":
    main()
