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
