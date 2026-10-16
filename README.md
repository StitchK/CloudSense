# CloudSense

CloudSense is a serverless health-monitoring prototype built on AWS.

Current implemented path:

```text
Simulator -> API Gateway -> Ingest Lambda -> SQS
```

## Project Layout

```text
src/common/     Shared validation helpers
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

## Run Tests

```bash
python3 -m unittest discover -s tests -v
```

The tests use mocks and do not send data to AWS.

## Deploy

```bash
sam build
sam deploy --guided
```

The SAM template uses the existing `LabRole`; it does not create a new IAM
execution role. AWS credentials must be configured outside the repository.

To build only the Ingest Lambda package:

```bash
python3 scripts/package_ingest.py
```

The generated file is `dist/cloudsense-ingest.zip`, with handler:

```text
ingest.app.lambda_handler
```
