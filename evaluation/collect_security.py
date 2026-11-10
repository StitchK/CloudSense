"""Bounded security assessment in CloudShell; no IAM or resource-policy changes.

Uses the existing temporary role and synthetic probe data only. Findings are an
assessment, not a certificate or a claim that all effective permissions are safe.
"""

import hashlib
import json
import ssl
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from botocore.exceptions import ClientError

from cloud_lab import FUNCTIONS, client, read_item, resources
from run_low_load import normal_reading

HERE = Path(__file__).resolve().parent


def main():
    started = datetime.now(timezone.utc)
    probe_id = "security-" + started.strftime("%Y%m%dT%H%M%S")
    result = {"started_at": started.isoformat(), "region": "us-east-1", "probe_id": probe_id,
              "scope": "Configuration reads plus bounded synthetic HTTP probes; no access, encryption, IAM or policy changes.",
              "configuration": {}, "unavailable": [], "probes": [], "findings": []}
    config = result["configuration"]

    def call(label, action, **args):
        try:
            data = action(**args)
            data.pop("ResponseMetadata", None)
            return data
        except ClientError as error:
            result["unavailable"].append({"check": label, "code": error.response["Error"]["Code"]})
            return None

    def finding(key, status, severity, detail):
        result["findings"].append({"id": key, "status": status, "severity": severity, "detail": detail})

    outputs = resources()
    base = outputs["QueryApiBaseUrl"].rstrip("/")
    api_id = base.split("//", 1)[1].split(".", 1)[0]
    gateway = client("apigatewayv2")
    config["api"] = call("api", gateway.get_api, ApiId=api_id)
    config["routes"] = call("routes", gateway.get_routes, ApiId=api_id)
    config["stages"] = call("stages", gateway.get_stages, ApiId=api_id)
    routes = (config["routes"] or {}).get("Items", [])
    unprotected = [r["RouteKey"] for r in routes if r.get("AuthorizationType", "NONE") == "NONE"]
    finding("api_authentication", "GAP" if unprotected else "REVIEW", "HIGH",
            "Routes without API Gateway authorization: " + ", ".join(unprotected))

    roles = set()
    config["functions"] = {}
    for name in FUNCTIONS:
        details = call(name, client("lambda").get_function_configuration, FunctionName=name)
        if not details:
            continue
        roles.add(details["Role"])
        selected = {key: details.get(key) for key in ["FunctionName", "Role", "Runtime", "Handler", "CodeSha256", "KMSKeyArn", "VpcConfig", "LoggingConfig"]}
        selected["environment_variable_names"] = sorted(details.get("Environment", {}).get("Variables", {}))
        selected["resource_policy"] = call(name + " policy", client("lambda").get_policy, FunctionName=name)
        config["functions"][name] = selected
    config["roles"] = {}
    iam = client("iam")
    for arn in sorted(roles):
        name = arn.rsplit("/", 1)[1]
        entry = {"role": call(name, iam.get_role, RoleName=name), "attached": [], "inline": []}
        attached = call(name + " attached", iam.list_attached_role_policies, RoleName=name)
        for policy in (attached or {}).get("AttachedPolicies", []):
            metadata = call("managed policy", iam.get_policy, PolicyArn=policy["PolicyArn"])
            version = None
            if metadata:
                version = call("policy version", iam.get_policy_version, PolicyArn=policy["PolicyArn"], VersionId=metadata["Policy"]["DefaultVersionId"])
            entry["attached"].append({"name": policy["PolicyName"], "document": (version or {}).get("PolicyVersion", {}).get("Document")})
        inline = call(name + " inline", iam.list_role_policies, RoleName=name)
        for policy_name in (inline or {}).get("PolicyNames", []):
            policy = call("inline policy", iam.get_role_policy, RoleName=name, PolicyName=policy_name)
            entry["inline"].append({"name": policy_name, "document": (policy or {}).get("PolicyDocument")})
        entry["pagination_incomplete"] = bool((attached or {}).get("IsTruncated") or (inline or {}).get("IsTruncated"))
        config["roles"][name] = entry
    finding("execution_role_separation", "GAP" if len(roles) == 1 else "REVIEW", "MEDIUM",
            "All three functions share one execution role." if len(roles) == 1 else "Review service-specific privileges.")

    sqs = client("sqs")
    config["queues"] = {}
    for key in ["QueueUrl", "DeadLetterQueueUrl"]:
        config["queues"][key] = call(key, sqs.get_queue_attributes, QueueUrl=outputs[key], AttributeNames=["All"])
    table = outputs["AlertStateTableName"]
    ddb = client("dynamodb")
    config["table"] = call("table", ddb.describe_table, TableName=table)
    config["ttl"] = call("ttl", ddb.describe_time_to_live, TableName=table)
    config["backups"] = call("backups", ddb.describe_continuous_backups, TableName=table)
    topic = call("topic", client("sns").get_topic_attributes, TopicArn=outputs["AlertTopicArn"])
    config["topic"] = topic
    config["logs"] = {}
    for name in FUNCTIONS:
        groups = call("log groups", client("logs").describe_log_groups, logGroupNamePrefix="/aws/lambda/" + name)
        config["logs"][name] = [row for row in (groups or {}).get("logGroups", []) if row["logGroupName"] == "/aws/lambda/" + name]

    def http(name, path, expected, body=None, method=None, headers=None):
        request = urllib.request.Request(base + path, data=body, headers=headers or {}, method=method)
        before = time.monotonic()
        try:
            response = urllib.request.urlopen(request, context=ssl.create_default_context(), timeout=20)
        except urllib.error.HTTPError as error:
            response = error
        raw = response.read()
        try:
            parsed = json.loads(raw)
        except ValueError:
            parsed = None
        row = {"name": name, "status": response.code, "expected_status": expected,
               "passed": response.code == expected, "duration_ms": round((time.monotonic() - before) * 1000, 1),
               "headers": {key: value for key, value in response.headers.items() if key.lower() in ["content-type", "cache-control", "access-control-allow-origin", "access-control-allow-credentials", "access-control-allow-methods"]},
               "response_sha256": hashlib.sha256(raw).hexdigest(), "response_keys": sorted(parsed) if isinstance(parsed, dict) else [],
               "error_text_only": parsed if isinstance(parsed, dict) and response.code >= 400 else None}
        result["probes"].append(row)
        print(name, response.code, "PASS" if row["passed"] else "FAIL", flush=True)
        return parsed, row

    invalid_cases = [
        ("malformed_json", b'{"bad":', "application/json", 400),
        ("missing_fields", json.dumps({"reading_id": probe_id + "-invalid"}).encode(), "application/json", 400),
        ("json_array", b'[]', "application/json", 400),
        ("nonfinite_json", b'{"heart_rate_bpm":NaN}', "application/json", 400),
        ("wrong_content_type", b'{}', "text/plain", 415),
        ("oversized_body", b'{"padding":"' + b'x' * 17000 + b'"}', "application/json", 413),
    ]
    for name, body, media_type, status in invalid_cases:
        http(name, "/readings", status, body, "POST", {"Content-Type": media_type})
    for name, path in [
        ("invalid_device_id", "/devices/ab/latest"),
        ("invalid_limit", "/devices/" + probe_id + "/history?limit=0"),
        ("invalid_timestamp", "/devices/" + probe_id + "/history?from=bad"),
        ("invalid_cursor", "/devices/" + probe_id + "/history?next_token=bad"),
    ]:
        http(name, path, 400)

    reading = normal_reading(probe_id, probe_id + "-valid")
    _, write_row = http("anonymous_valid_write", "/readings", 202, json.dumps(reading).encode(), "POST", {"Content-Type": "application/json"})
    for attempt in range(15):
        if read_item(table, reading["reading_id"]).get("status") == "COMPLETE":
            break
        time.sleep(2)
    query, read_row = http("anonymous_read_own_synthetic_device", "/devices/" + probe_id + "/history", 200)
    read_row["synthetic_record_visible"] = any(item.get("reading", {}).get("reading_id") == reading["reading_id"] for item in (query or {}).get("items", []))
    finding("anonymous_data_access", "GAP" if write_row["status"] == 202 and read_row["synthetic_record_visible"] else "REVIEW", "HIGH",
            "No Authorization or API key was sent. Only the dedicated synthetic device was queried; existing devices were not read.")
    http("untrusted_origin_preflight", "/devices/" + probe_id + "/history", 204, method="OPTIONS", headers={"Origin": "https://untrusted.invalid", "Access-Control-Request-Method": "GET"})
    finding("https", "PASS", "INFO", "API probes used HTTPS with Python default certificate and hostname validation. Internal service TLS was not independently traced.")
    result["invalid_record_state"] = read_item(table, probe_id + "-invalid")
    finding("input_validation", "PASS" if all(row["passed"] for row in result["probes"][:10]) else "GAP", "MEDIUM", "Six ingest and four query validation probes; see exact HTTP statuses.")
    finding("query_cache", "PASS" if read_row["headers"].get("Cache-Control", read_row["headers"].get("cache-control")) == "no-store" else "REVIEW", "LOW", "Query response Cache-Control header checked.")
    result["ended_at"] = datetime.now(timezone.utc).isoformat()
    result["limitations"] = ["No account/root MFA, organization controls or formal compliance certification assessment.", "No brute force, load attack, penetration testing, or unrelated-device access.", "CORS is a browser rule and does not authenticate API callers.", "Existing historical logs can predate current source code; source review is separate from runtime configuration.", "Read-only IAM documents do not by themselves prove full effective permissions; boundaries, resource policies and organization controls may apply.", "Additional security probes happened after the saved cost experiment window and are excluded from its estimate."]
    destination = HERE / "cloud_evidence/security.json"
    destination.parent.mkdir(exist_ok=True)
    destination.write_text(json.dumps(result, indent=2, default=str))
    print("SECURITY_EVIDENCE", destination, flush=True)
    print("Findings are an assessment, not an all-pass security certification.", flush=True)


if __name__ == "__main__":
    main()
