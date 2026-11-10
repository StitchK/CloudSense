"""Run Code: send a bounded normal workload and open the live results page."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import threading
import time
import uuid
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

HERE = Path(__file__).resolve().parent


def utc(epoch=None):
    return datetime.fromtimestamp(time.time() if epoch is None else epoch, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def percentile(values, percent):
    ordered = sorted(value for value in values if value is not None)
    if not ordered:
        return None
    position = (len(ordered) - 1) * percent / 100
    lower = math.floor(position)
    upper = math.ceil(position)
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower), 3)


def request_json(url, body=None, timeout=15):
    payload = json.dumps(body).encode() if body is not None else None
    request = Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        return error.code, {}


def history(base, device, start, end, on_request=None):
    parameters = {"from": start, "to": end, "limit": 100}
    records = []
    tokens = set()
    for page in range(100):
        if on_request:
            on_request()
        status, body = request_json(f"{base}/devices/{device}/history?{urlencode(parameters)}")
        if status != 200:
            raise RuntimeError(f"history HTTP {status}")
        records.extend(body["items"])
        token = body.get("next_token")
        if not token:
            return records
        if token in tokens:
            raise RuntimeError("Repeated history cursor")
        tokens.add(token)
        parameters["next_token"] = token
    raise RuntimeError("History exceeded 100 pages; result is incomplete")


def normal_reading(device, reading_id):
    return {"device_id": device, "reading_id": reading_id, "timestamp": utc(), "heart_rate_bpm": 78, "body_temperature_c": 36.7, "spo2_pct": 98, "blood_pressure": {"systolic": 118, "diastolic": 76}, "activity": "rest"}


class Experiment:
    def __init__(self, endpoint, rate, duration, devices, settle):
        self.endpoint = endpoint
        self.base = endpoint.removesuffix("/readings")
        self.rate, self.duration, self.settle = rate, duration, settle
        self.run_id = datetime.now(timezone.utc).strftime("eval-%Y%m%dT%H%M%S-") + uuid.uuid4().hex[:6]
        self.devices = [f"{self.run_id}-{number:02d}" for number in range(devices)]
        self.directory = HERE / "results" / self.run_id
        self.directory.mkdir(parents=True)
        self.rows = {}
        self.samples = []
        self.errors = []
        self.lock = threading.RLock()
        self.phase = "Starting"
        self.started = time.time()
        self.stop = threading.Event()
        self.finished = threading.Event()
        self.query_requests = 0
        self.accepting = True
        self.sent_done_at = None
        self.ended_at = None

    def summary(self):
        with self.lock:
            rows = [dict(row) for row in self.rows.values()]
            accepted = [row for row in rows if row.get("http_status") == 202]
            complete = [row for row in rows if row.get("processing_status") in ("COMPLETE", "LATE")]
            return {"run_id": self.run_id, "started_at": utc(self.started), "ended_at": self.ended_at, "phase": self.phase, "target_rate": self.rate, "target_duration_seconds": self.duration, "device_count": len(self.devices), "planned": round(self.rate * self.duration), "sent": len(rows), "accepted": len(accepted), "completed": len(complete), "late": sum(row.get("processing_status") == "LATE" for row in rows), "unaccepted_or_unknown": sum(row.get("http_status", 0) != 202 for row in rows if row.get("http_ms") is not None), "pending_accepted": sum(row.get("http_status") == 202 and row.get("processing_status") not in ("COMPLETE", "LATE") for row in rows), "api_p50_ms": percentile([row.get("http_ms") for row in accepted], 50), "api_p95_ms": percentile([row.get("http_ms") for row in accepted], 95), "backend_p50_ms": percentile([row.get("backend_ms") for row in complete], 50), "backend_p95_ms": percentile([row.get("backend_ms") for row in complete], 95), "observed_p95_ms": percentile([row.get("observed_ms") for row in complete], 95), "actual_send_rate": round(len(rows) / max(0.001, (self.sent_done_at or time.time()) - self.started), 3), "query_requests": self.query_requests, "query_errors": list(self.errors[-20:]), "samples": list(self.samples), "records": rows, "measurement_notes": ["API latency includes the client network; HTTP 202 is acceptance only.", "Backend latency uses AWS completed_at_ms minus ingest received_at; absent instrumentation is null.", "Observed latency includes GSI visibility, history requests and polling; it is an upper bound.", "Only bounded normal synthetic readings are sent; no fault operations are started by Run Code."]}

    def persist(self):
        with self.lock:
            data = self.summary()
            path = self.directory / "summary.json"
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
            temporary.replace(path)
            fields = ["reading_id", "device_id", "sent_at", "sent_epoch", "http_status", "http_ms", "processing_status", "backend_ms", "observed_ms", "completed_at_ms", "error_type"]
            with (self.directory / "requests.csv").open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(data["records"])
            html = (HERE / "dashboard.html").read_text(encoding="utf-8")
            embedded = json.dumps(data).replace("<", "\\u003c")
            (self.directory / "dashboard.html").write_text(html.replace("window.ARCHIVE_DATA = null", f"window.ARCHIVE_DATA = {embedded}"), encoding="utf-8")

    def send(self, number):
        device = self.devices[number % len(self.devices)]
        reading_id = f"{self.run_id}-{number:05d}"
        started = time.perf_counter()
        sent_epoch = time.time()
        row = {"reading_id": reading_id, "device_id": device, "sent_at": utc(sent_epoch), "sent_epoch": sent_epoch}
        with self.lock:
            self.rows[reading_id] = row
        try:
            status, _ = request_json(self.endpoint, normal_reading(device, reading_id))
            outcome = {"http_status": status}
        except Exception as error:
            outcome = {"http_status": 0, "error_type": type(error).__name__}
        with self.lock:
            row.update(outcome, http_ms=round((time.perf_counter() - started) * 1000, 3))

    def verify(self):
        while not self.stop.is_set():
            with self.lock:
                pending_devices = {row["device_id"] for row in self.rows.values() if row.get("processing_status") not in ("COMPLETE", "LATE")}
            for device in sorted(pending_devices):
                if self.stop.is_set():
                    break
                try:
                    items = history(self.base, device, utc(self.started - 2), utc(), self.count_query)
                    with self.lock:
                        for item in items:
                            row = self.rows.get(item["reading"]["reading_id"])
                            if row is None or row.get("processing_status") in ("COMPLETE", "LATE"):
                                continue
                            row["processing_status"] = item["processing_status"]
                            if item["processing_status"] in ("COMPLETE", "LATE"):
                                row["observed_ms"] = round((time.time() - row["sent_epoch"]) * 1000, 3)
                                completed = item.get("completed_at_ms")
                                received = item["reading"].get("received_at")
                                row["completed_at_ms"] = completed
                                if completed is not None and received:
                                    row["backend_ms"] = round(completed - datetime.fromisoformat(received.replace("Z", "+00:00")).timestamp() * 1000, 3)
                except Exception as error:
                    with self.lock:
                        self.errors.append(f"{utc()} {type(error).__name__}: {error}")
            self.record_sample()
            self.persist()
            self.stop.wait(5)

    def count_query(self):
        with self.lock:
            self.query_requests += 1

    def record_sample(self):
        with self.lock:
            current = self.summary()
            self.samples.append({"seconds": round(time.time() - self.started, 2), "sent": current["sent"], "accepted": current["accepted"], "completed": current["completed"]})

    def run(self):
        self.phase = "Sending"
        verifier = threading.Thread(target=self.verify, daemon=True)
        verifier.start()
        try:
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = []
                for number in range(round(self.rate * self.duration)):
                    delay = self.started + number / self.rate - time.time()
                    if self.stop.wait(max(0, delay)):
                        break
                    futures.append(pool.submit(self.send, number))
                for future in futures:
                    future.result()
            self.sent_done_at = time.time()
            self.phase = "Waiting for completion"
            deadline = time.monotonic() + self.settle
            while time.monotonic() < deadline and not self.stop.is_set():
                data = self.summary()
                if data["sent"] == data["completed"]:
                    break
                self.stop.wait(1)
            data = self.summary()
            self.phase = "PASS" if data["sent"] == data["planned"] == data["accepted"] == data["completed"] and not data["late"] else "INCOMPLETE"
        except Exception as error:
            self.errors.append(type(error).__name__)
            self.phase = "FAILED"
        finally:
            self.stop.set()
            verifier.join()
            self.ended_at = utc()
            self.finished.set()
            self.record_sample()
            self.persist()
            data = self.summary()
            print(f"{self.phase}: sent={data['sent']}, accepted={data['accepted']}, completed={data['completed']}", flush=True)
            print(f"Results: {self.directory}", flush=True)


def serve(experiment):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/data":
                payload = json.dumps(experiment.summary()).encode()
                content_type = "application/json"
            elif self.path in ("/", "/dashboard.html"):
                payload = (HERE / "dashboard.html").read_bytes()
                content_type = "text/html; charset=utf-8"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rate", type=float, default=1)
    parser.add_argument("--duration", type=int, default=120)
    parser.add_argument("--devices", type=int, default=10)
    parser.add_argument("--settle", type=int, default=180)
    parser.add_argument("--api-url")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--exit-after", action="store_true")
    args = parser.parse_args()
    if not 0 < args.rate <= 5 or not 1 <= args.duration <= 300 or not 2 <= args.devices <= 20 or not 10 <= args.settle <= 600 or args.rate * args.duration > 1500:
        parser.error("Use rate 0–5/s, duration 1–300s, devices 2–20, settle 10–600s and at most 1500 readings.")
    if args.devices / args.rate < 1.2:
        parser.error("Use more devices: each device needs at least 1.2 seconds between measurements.")
    try:
        from simulator.send_config import resolve_api_url

        endpoint = resolve_api_url(args.api_url)
    except ValueError as error:
        parser.exit(2, str(error) + "\n")
    experiment = Experiment(endpoint, args.rate, args.duration, args.devices, args.settle)
    server = serve(experiment)
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"CloudSense low load: {args.rate}/s for {args.duration}s, normal data only.", flush=True)
    print(f"Live visualization: {url}", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    worker = threading.Thread(target=experiment.run, daemon=True)
    worker.start()
    try:
        worker.join()
        if not args.exit_after:
            print("Results remain open. Press Ctrl+C in the terminal to close the viewer.", flush=True)
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        experiment.stop.set()
        worker.join(timeout=30)
    finally:
        server.shutdown()
    return 0 if experiment.phase == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
