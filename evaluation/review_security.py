"""Summarize saved AWS security evidence and bounded local source checks."""

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def main():
    evidence = json.loads((HERE / "cloud_evidence/security.json").read_text())
    configuration = evidence["configuration"]
    candidates = subprocess.check_output(["git", "ls-files", "-co", "--exclude-standard"], cwd=ROOT, text=True).splitlines()
    patterns = {
        "aws_access_key_id": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
        "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        "aws_secret_assignment": re.compile(r"(?i)aws_secret_access_key\s*[:=]\s*['\"][A-Za-z0-9/+=]{40}['\"]"),
    }
    checked, matches = [], []
    for name in sorted(set(candidates)):
        path = ROOT / name
        if not path.is_file() or path.suffix not in {".py", ".js", ".jsx", ".yaml", ".json"}:
            continue
        if not (name.startswith(("src/", "frontend/src/", "simulator/", "scripts/")) or name == "template.yaml"):
            continue
        checked.append(name)
        for line_number, line in enumerate(path.read_text().splitlines(), 1):
            for category, pattern in patterns.items():
                if pattern.search(line):
                    matches.append({"path": name, "line": line_number, "category": category})
    ignored = subprocess.run(["git", "check-ignore", "simulator/simulator.local.json"], cwd=ROOT, capture_output=True, text=True).returncode == 0
    logs = json.loads((HERE / "cloud_evidence/logs.json").read_text())
    payload_events = 0
    structured_events = 0
    for row in logs:
        try:
            event = json.loads(row.get("message", ""))
        except ValueError:
            continue
        if isinstance(event, dict):
            structured_events += 1
            payload_events += "payload" in event
    probes = {row["name"]: row for row in evidence["probes"]}
    result = {
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "runtime_evidence": "cloud_evidence/security.json",
        "source_scan": {"files": checked, "matches_without_values": matches, "local_simulator_config_ignored": ignored,
                        "limits": "Current selected source files only; no Git history, dependencies, archives, private configuration or entropy-based scan."},
        "log_review": {"window": "2026-11-09T12:03:00Z to 12:18:00Z", "exported_events": len(logs), "structured_events": structured_events, "top_level_payload_events": payload_events,
                       "limits": "Only saved filtered experiment logs; historical logs and other field names can still contain sensitive information."},
        "checks": [
            {"id": "validation", "result": "PASS", "evidence": "Ten malformed input and query cases returned expected 400/413/415."},
            {"id": "api_authorization", "result": "GAP", "priority": "HIGH", "evidence": "Four routes use NONE; anonymous POST=202 and GET=200 with own synthetic record visible.", "improvement": "Add authenticated device ingestion and user authentication with device-level authorization."},
            {"id": "transport", "result": "PASS", "evidence": "HTTPS probe certificate and hostname validation succeeded."},
            {"id": "cors", "result": "PASS", "evidence": "Allowed origin is localhost:5173; untrusted preflight returned no allow-origin header. CORS does not protect against direct HTTP clients."},
            {"id": "cache", "result": "PASS", "evidence": "Query response contains Cache-Control: no-store."},
            {"id": "roles", "result": "GAP", "priority": "MEDIUM", "evidence": "Three functions share LabRole with attached EKS, ECR and SSM policies. Three Lab policy documents could not be read.", "improvement": "Use separate ingestion, processing and query roles scoped to required resources; permissions beyond Lab control are unassessed."},
            {"id": "queue_encryption", "result": "PASS", "evidence": "Main and DLQ SqsManagedSseEnabled=true."},
            {"id": "resource_policies", "result": "REVIEWED", "evidence": "No explicit SQS queue policy returned. SNS wildcard principal is constrained by account SourceOwner; API-to-Lambda grants have SourceArn conditions. These observations are not a proof of all effective permissions."},
            {"id": "database_encryption", "result": "SERVICE_DEFAULT", "evidence": "DynamoDB returned no SSEDescription. AWS documents encryption at rest by default; no customer-managed key was established by this snapshot."},
            {"id": "sns_kms", "result": "GAP", "priority": "MEDIUM", "evidence": "No KmsMasterKeyId in SNS topic attributes.", "improvement": "Evaluate SNS KMS encryption and authorized subscriber handling before real health data use."},
            {"id": "retention", "result": "GAP", "priority": "MEDIUM", "evidence": "TTL enabled on expires_at; all three log groups omit retentionInDays and therefore never expire. TTL deletion is asynchronous.", "improvement": "Define justified data and log retention periods and implement deletion procedures."},
            {"id": "secrets", "result": "PASS" if not matches and ignored else "REVIEW", "evidence": "Bounded source-pattern scan; see exact scanned file list. This does not prove no secret exists anywhere."},
            {"id": "logs", "result": "PASS" if payload_events == 0 else "GAP", "evidence": "Saved experiment JSON logs were checked for a top-level payload field; older logs were not removed or comprehensively audited."},
        ],
        "blocked_checks": [row for row in evidence["unavailable"] if row["code"] == "AccessDenied"],
        "notes": ["ResourceNotFoundException for processor resource policy means no such policy was returned; it is not an IAM permission denial.",
                  "No authentication, IAM or encryption configuration was changed. Findings remain open.",
                  "No account-level MFA, organization controls, formal medical compliance, S3 hosting or supply-chain audit was completed.",
                  "Security activity is outside the original cost experiment window."]
    }
    assert probes["anonymous_read_own_synthetic_device"]["synthetic_record_visible"]
    path = HERE / "cloud_evidence/security_review.json"
    path.write_text(json.dumps(result, indent=2))
    print(path)
    print("Scanned", len(checked), "source files; matching locations", len(matches))


if __name__ == "__main__":
    main()
