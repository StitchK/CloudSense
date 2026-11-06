# CloudSense Dashboard

React + Vite Dashboard for the CloudSense Lambda3 query API.

## Local development

```bash
cp .env.example .env
npm install
npm run dev
```

Set `VITE_API_BASE_URL` to the `QueryApiBaseUrl` value printed by the SAM
stack. Do not include `/readings` in this URL.

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
