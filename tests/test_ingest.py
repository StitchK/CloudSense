from __future__ import annotations

import base64
import json
import os
import sys
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


CLOUDSENSE_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = CLOUDSENSE_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from common.validation import validate_reading  # noqa: E402
from ingest import app as ingest_app  # noqa: E402


NOW = datetime(2026, 10, 16, 3, 0, tzinfo=timezone.utc)


class FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return NOW.replace(tzinfo=None)
        return NOW.astimezone(tz)


class FakeSQSClient:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def send_message(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return {"MessageId": "test-message-id"}


def normal_reading():
    return {
        "device_id": "dev-001",
        "reading_id": "reading-0001",
        "timestamp": "2026-10-16T02:59:30Z",
        "heart_rate_bpm": 78,
        "body_temperature_c": 36.7,
        "spo2_pct": 98,
        "blood_pressure": {
            "systolic": 118,
            "diastolic": 76,
        },
        "activity": "rest",
    }


def api_event(reading, headers=None, is_base64=False):
    body = json.dumps(reading, separators=(",", ":"))
    if is_base64:
        body = base64.b64encode(body.encode("utf-8")).decode("ascii")

    return {
        "body": body,
        "isBase64Encoded": is_base64,
        "headers": headers or {"content-type": "application/json"},
        "requestContext": {"requestId": "request-0001"},
    }


class IngestLambdaTests(unittest.TestCase):
    def setUp(self):
        self.context = SimpleNamespace(aws_request_id="aws-request-0001")
        self.queue_url = "https://sqs.us-east-1.amazonaws.com/123/test-queue"

    def invoke(self, event, sqs_client=None):
        fake_sqs = sqs_client or FakeSQSClient()
        with patch.dict(
            os.environ,
            {"READING_QUEUE_URL": self.queue_url},
            clear=False,
        ):
            with patch.object(
                ingest_app,
                "get_sqs_client",
                return_value=fake_sqs,
            ):
                with patch.object(ingest_app, "datetime", FrozenDateTime):
                    with redirect_stdout(StringIO()):
                        result = ingest_app.lambda_handler(
                            event,
                            self.context,
                        )
        return result, fake_sqs

    def test_valid_reading_is_enriched_and_enqueued(self):
        result, fake_sqs = self.invoke(api_event(normal_reading()))

        self.assertEqual(result["statusCode"], 202)
        response_body = json.loads(result["body"])
        self.assertEqual(response_body["reading_id"], "reading-0001")
        self.assertEqual(response_body["request_id"], "request-0001")
        self.assertEqual(len(fake_sqs.calls), 1)

        enqueued = json.loads(fake_sqs.calls[0]["MessageBody"])
        self.assertEqual(enqueued["source"], "api-gateway")
        self.assertEqual(enqueued["request_id"], "request-0001")
        self.assertEqual(enqueued["schema_version"], "1.0")
        self.assertFalse(enqueued["is_late"])
        self.assertEqual(enqueued["ingest_age_seconds"], 30)

    def test_over_120_heart_rate_is_valid_and_enqueued(self):
        reading = normal_reading()
        reading["heart_rate_bpm"] = 150

        result, fake_sqs = self.invoke(api_event(reading))

        self.assertEqual(result["statusCode"], 202)
        self.assertEqual(len(fake_sqs.calls), 1)

    def test_invalid_json_is_rejected(self):
        event = api_event(normal_reading())
        event["body"] = "{not-json"

        result, fake_sqs = self.invoke(event)

        self.assertEqual(result["statusCode"], 400)
        self.assertEqual(fake_sqs.calls, [])

    def test_missing_field_is_rejected(self):
        reading = normal_reading()
        del reading["heart_rate_bpm"]

        result, fake_sqs = self.invoke(api_event(reading))

        self.assertEqual(result["statusCode"], 400)
        self.assertIn(
            "heart_rate_bpm",
            json.loads(result["body"])["errors"],
        )
        self.assertEqual(fake_sqs.calls, [])

    def test_wrong_type_is_rejected(self):
        reading = normal_reading()
        reading["heart_rate_bpm"] = "78"

        result, _ = self.invoke(api_event(reading))

        self.assertEqual(result["statusCode"], 400)
        self.assertIn(
            "must be an integer",
            json.loads(result["body"])["errors"]["heart_rate_bpm"],
        )

    def test_physically_impossible_value_is_rejected(self):
        reading = normal_reading()
        reading["heart_rate_bpm"] = 999

        result, fake_sqs = self.invoke(api_event(reading))

        self.assertEqual(result["statusCode"], 400)
        self.assertEqual(fake_sqs.calls, [])

    def test_invalid_blood_pressure_relationship_is_rejected(self):
        reading = normal_reading()
        reading["blood_pressure"] = {
            "systolic": 80,
            "diastolic": 120,
        }

        result, _ = self.invoke(api_event(reading))

        self.assertEqual(result["statusCode"], 400)
        self.assertIn(
            "systolic must be greater than diastolic",
            json.loads(result["body"])["errors"]["blood_pressure"],
        )

    def test_future_timestamp_is_rejected(self):
        reading = normal_reading()
        reading["timestamp"] = "2026-10-16T03:10:00Z"

        result, _ = self.invoke(api_event(reading))

        self.assertEqual(result["statusCode"], 400)
        self.assertIn(
            "5 minutes",
            json.loads(result["body"])["errors"]["timestamp"],
        )

    def test_late_reading_is_accepted_and_marked(self):
        reading = normal_reading()
        reading["timestamp"] = "2026-10-16T02:00:00Z"

        result, fake_sqs = self.invoke(api_event(reading))

        self.assertEqual(result["statusCode"], 202)
        enqueued = json.loads(fake_sqs.calls[0]["MessageBody"])
        self.assertTrue(enqueued["is_late"])
        self.assertEqual(enqueued["ingest_age_seconds"], 3600)

    def test_unsupported_content_type_is_rejected(self):
        event = api_event(
            normal_reading(),
            headers={"content-type": "text/plain"},
        )

        result, _ = self.invoke(event)

        self.assertEqual(result["statusCode"], 415)

    def test_oversized_body_is_rejected(self):
        event = api_event(normal_reading())
        event["body"] = "x" * (ingest_app.MAX_BODY_BYTES + 1)

        result, _ = self.invoke(event)

        self.assertEqual(result["statusCode"], 413)

    def test_sqs_failure_returns_503(self):
        result, fake_sqs = self.invoke(
            api_event(normal_reading()),
            sqs_client=FakeSQSClient(error=RuntimeError("queue unavailable")),
        )

        self.assertEqual(result["statusCode"], 503)
        self.assertEqual(len(fake_sqs.calls), 1)

    def test_base64_json_body_is_supported(self):
        result, fake_sqs = self.invoke(
            api_event(normal_reading(), is_base64=True)
        )

        self.assertEqual(result["statusCode"], 202)
        self.assertEqual(len(fake_sqs.calls), 1)

    def test_validation_normalizes_timestamp_to_utc(self):
        reading = normal_reading()
        reading["timestamp"] = "2026-10-16T11:00:00+08:00"

        result = validate_reading(reading, now=NOW)

        self.assertEqual(result.reading["timestamp"], "2026-10-16T03:00:00Z")


if __name__ == "__main__":
    unittest.main()
