# CloudSense

CloudSense is a serverless health-monitoring prototype built on AWS.

Current implemented path:

```text
Simulator -> API Gateway -> Ingest Lambda -> SQS
          -> Process Lambda -> DynamoDB
                            -> SNS
```

## Project Layout

```text
src/common/     Validation, alert rules, idempotency, and DynamoDB helpers
src/ingest/     API Gateway ingestion Lambda
src/process/    SQS processing Lambda
src/query/      Dashboard query Lambda (Lambda3)
simulator/      Local synthetic-data producer
tests/          Unit tests
events/         Lambda test events
template.yaml   AWS SAM infrastructure
```

## Run Simulator

Auto mode without sending:

```bash
python3 simulator/simulator.py \
  --mode auto \
  --scenario normal \
  --count 5 \
  --pretty
```

Auto mode with API Gateway:

```bash
python3 simulator/simulator.py \
  --mode auto \
  --scenario normal \
  --count 1 \
  --api-url "<API_GATEWAY_URL>" \
  --send \
  --timeout 15 \
  --retries 0
```

Interactive mode:

```bash
python3 simulator/simulator.py \
  --mode interactive \
  --api-url "<API_GATEWAY_URL>" \
  --send \
  --timeout 15 \
  --retries 0
```

Interactive commands include `n`, `w`, `c`, `ch`, `ct`, `co`, `cb`, `d`, and `q`.

Send one complete demo sequence:

```bash
python3 simulator/Simulator_send.py \
  --api-url "<API_ENDPOINT>"
```

The sequence is three normal readings, one warning, then two consecutive
critical readings from the same device.

Run the continuous random sender:

```bash
python3 simulator/Simulator_send_random.py \
  --api-url "<API_ENDPOINT>"
```

The random sender alternates between these cycles:

```text
warning -> normal -> normal -> normal
critical -> critical -> normal -> normal -> normal
```

Use `Ctrl+C` to stop it. Both send scripts also support `--dry-run` for local
inspection without sending data.

## Run Tests

```bash
python3 -m pytest -q tests
```

The tests use mocks and do not send data to AWS.

For local Lambda3 unit tests, direct HTTP API checks, and optional live DynamoDB
comparison without CloudShell, see [本机测试指南](LOCAL_TESTING.md).
Deployment steps, test results, and screenshots are in
[Lambda3 复现资料](Project%20Reproduction/04QueryLambda/QueryLambda.md).

## Deploy

```bash
sam build
sam deploy --guided
```

The SAM template uses the existing `LabRole`; it does not create a new IAM
execution role. AWS credentials must be configured outside the repository.

The stack includes:

- HTTP API and Ingest Lambda.
- SQS queue, retry policy, and dead-letter queue.
- Process Lambda triggered by SQS.
- Query Lambda with latest, history, and abnormal-reading HTTP GET routes.
- DynamoDB table for readings, deduplication, and alert cooldown state.
- SNS topic for warning and critical alerts.

An optional alert email can be supplied during deployment:

```bash
sam deploy --guided --parameter-overrides AlertEmail="<EMAIL_ADDRESS>"
```

To build only the Ingest Lambda package:

```bash
python3 scripts/package_ingest.py
```

The generated file is `dist/cloudsense-ingest.zip`, with handler:

```text
ingest.app.lambda_handler
```

## Dashboard Query API (Lambda3)

Lambda3 reads the existing `AlertStateTable` through `DeviceTimeIndex`; it does
not write readings or send notifications. Its handler is
`query.app.lambda_handler`. The SAM template wires these routes to the same HTTP
API as ingestion:

| Route | Result |
| --- | --- |
| `GET /devices/{device_id}/latest` | Latest unexpired reading, classifications, abnormal metrics, data age and stale flag |
| `GET /devices/{device_id}/history` | Readings within a time window, newest first |
| `GET /devices/{device_id}/alerts` | Abnormal readings within that window, including suppressed/pending notifications |

History and alerts accept `from` and `to` as timezone-aware ISO 8601 timestamps
with whole seconds, `limit` (1–100, default 50), and `next_token` for the next
page. The default window is the 24 hours ending now (or at `to`, if supplied).
Bounds are inclusive. Keep the same device, route, `from` and `to` parameters
when using `next_token`; the original default window is preserved across pages.
Use URL encoding for `+08:00` offsets, or use UTC `Z` timestamps.

`limit` caps the number of database records evaluated, not the number of matching
alerts. An alerts page can be empty and still have a `next_token`; continue until
the token is null. Each alerts item is one reading with an `alerts` array, not a
separate row for every abnormal metric. This endpoint reports recorded abnormal
measurements, not an acknowledged/resolved incident lifecycle.

Example after deployment (use the `QueryApiBaseUrl` stack output):

```bash
curl '<QUERY_API_BASE_URL>/devices/dev-001/latest'
curl --get '<QUERY_API_BASE_URL>/devices/dev-001/history' \
  --data-urlencode 'from=2026-10-30T00:00:00Z' \
  --data-urlencode 'to=2026-10-31T00:00:00Z' \
  --data-urlencode 'limit=50'
curl --get '<QUERY_API_BASE_URL>/devices/dev-001/alerts' \
  --data-urlencode 'from=2026-10-30T00:00:00Z' \
  --data-urlencode 'to=2026-10-31T00:00:00Z'
```

Latest returns this shape (shortened):

```json
{
  "device_id": "dev-001",
  "data": {
    "reading": {"device_id": "dev-001", "reading_id": "reading-001", "spo2_pct": 89},
    "evaluations": [{"metric": "spo2_pct", "level": "critical", "message": "Blood oxygen: 89%, level: critical"}],
    "overall_status": "critical",
    "alerts": [{"metric": "spo2_pct", "level": "critical", "message": "Blood oxygen: 89%, level: critical", "notification_status": "CRITICAL_PENDING"}],
    "is_late": false,
    "measured_at_epoch": 1793361600,
    "processing_status": "COMPLETE",
    "updated_at": 1793361601
  },
  "age_seconds": 10,
  "is_stale": false
}
```

`overall_status` selects the worst **stored** metric classification; Lambda3 does
not rerun health rules. `notification_status` is separate: a critical metric may
be `CRITICAL_PENDING` until the second consecutive critical reading. The UI must
still show its critical classification. Records can be visible while
`processing_status` is `PROCESSING`; notification decisions may update afterward.
Missing classifications produce `unknown`, never an assumed normal result.

`DATA_STALE_SECONDS` defaults to 300. A stale reading keeps its recorded health
status, but the UI should prominently display that data is no longer current.
Expired records are excluded even before DynamoDB TTL physically removes them.
The GSI is eventually consistent, so newly processed data can take a short time
to appear. No data returns 404 for latest and an empty list for history/alerts;
invalid parameters return 400, and database failures return 503.

Set `DashboardAllowedOrigins` during SAM deployment to the browser application's
origin(s); its default is `http://localhost:5173`. CORS is managed by API Gateway.
Like the current ingestion prototype, these SAM query routes have no login
authorizer. CORS does not restrict direct API clients; use simulated data for
this lab prototype. An application serving private real readings needs an API
authorizer and device ownership checks before public deployment.

The existing LabRole must permit `dynamodb:Query` on the table's
`index/DeviceTimeIndex` ARN and CloudWatch logging. Outside Learner Lab, use a
dedicated read-only execution role. The SAM template continues using the existing
LabRole rather than creating or broadening IAM permissions.

Build the standalone ZIP for manual deployment:

```bash
python3 scripts/package_query.py
```

This writes `dist/cloudsense-query.zip`. Configure `ALERT_STATE_TABLE` to the
existing table name, and optionally set `DATA_STALE_SECONDS`. For a Lambda console
test, use `events/query_latest.json`, replacing `dev-001` with a stored device ID.
For history/alerts tests, change `routeKey` accordingly and add the query string
parameters described above.
