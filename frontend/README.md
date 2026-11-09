# CloudSense Dashboard

React + Vite Dashboard for the CloudSense Lambda3 query API.

## Local development

```bash
cp .env.example .env
npm ci
npm run dev
```

Set `VITE_API_BASE_URL` to the `QueryApiBaseUrl` value printed by the SAM
stack. Do not include `/readings` in this URL.
Use a private `.env.local` for your actual URL; it is ignored by Git. Never put
personal API URLs or AWS credentials in `.env.example` or screenshots.
Requires Node.js 20.19+ (or 22.12+) and Python 3 for the contract test.
Open `http://localhost:5173`, which matches the existing API CORS configuration.
The development server requires port 5173 and stops if it is occupied, preventing
an automatic switch to a port outside the API's allowed origins.

The default demonstration device is `device-001`, matching both simulator send
scripts. Set `VITE_DEFAULT_DEVICE_ID=device-001` in your private `.env.local` too.
Saved device selections are scoped to the configured default, so changing that
default starts with the new device rather than a previous demonstration's ID.
The page still remembers later manual device selections; select `device-001`
again when returning to the default senders. Open a second terminal and run
`python3 simulator/simulator_send.py` from the repository root for six samples,
or `python3 simulator/simulator_send_random.py` for continuous cycles.

To preview the interface without AWS, set:

```text
VITE_USE_MOCK_DATA=true
```

## Production build

```bash
npm run build
```

Deploy the generated `dist/` directory to AWS Amplify Hosting or another
static hosting service. The browser only calls API Gateway and does not contain
AWS credentials.

## Behavior and validation

```bash
npm test
npm run build
```

Tests include invoking the real Python Lambda3 Handler locally with a mock table;
no AWS credentials or CloudShell are needed. `PYTHON` can select another Python interpreter.

- Converts Lambda3 `data` / `items` and snake_case fields into the view model.
- Uses whole-second `from/to` timestamps and `limit=100`; follows `next_token`,
  including empty filtered pages. History is sorted oldest first and alerts newest first.
  If more than 100 pages are required, the UI asks for a smaller time window rather
  than showing a partial result as complete.
- Refreshes latest, history and alerts together after each completed polling batch.
  Switching device, range or refreshing cancels the previous batch and ignores late results.
  Pause stops subsequent automatic batches; an in-flight batch may still finish.
  Manual refresh works while paused. Hidden browser tabs skip automatic batches.
- Shows the saved Normal / Warning / Critical level separately from stale data
  (default 300 seconds, aligned with the backend). A stale Critical reading retains
  its Critical badge and has an additional stale notice; old data does not open a new popup.
- The interface, status labels, dialogs and error messages are in English.
- Alert reasons use Warning → “high/low”, Critical → “very high/very low”, followed by
  the recorded value. Mixed blood-pressure directions name systolic and diastolic
  separately. Severity is always the backend's saved level; wording does not reclassify it.
- Popups occur for new or escalated abnormalities, with per-device browser storage
  preventing unchanged readings from repeating. Recovery permits a later recurrence.
- Missing latest data (404) shows a waiting state. Failed list queries show an error,
  never a misleading “no abnormalities” result. Existing historical measurements
  require selecting a time range that includes their measurement time.

The existing Lambda2 SQS trigger must be enabled for newly uploaded readings to be
processed into DynamoDB. The dashboard can read existing records independently.
For deployed `vite preview` (port 4173) or a hosted site, configure that origin in
API Gateway CORS before connecting to the AWS API.
