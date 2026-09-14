# Deploying Hair Studio 360

## Repository

Deploy only from `i-Brain-Robotics/FlowMedIQ-Hair-Studio-360`. The similarly named `Hair-Studio-360` repository is a different app.

## Created Render service

- [Service dashboard](https://dashboard.render.com/web/srv-dak63d3l550s73a22apg)
- Service ID: `srv-dak63d3l550s73a22apg`
- Workspace: Santosh Katekari (confirmed by the owner)
- App URL: https://flowmediq-hair-studio-360.onrender.com
- Suite callback: https://flowmediq-hair-studio-360.onrender.com/auth/sso
- Suite app identifier: `flowmediq-hair-studio-360`
- Free instance, Oregon, manual deploys

The service was created without setting environment variables. The administrator must enter the required values below and register the new Suite app before end-to-end image-generation verification. The health endpoint is `/healthz`; direct MCP service creation uses Render's default port health check, while the committed Blueprint also specifies this HTTP path.

## Render configuration

The workspace already has a different Hair Studio 360 app. This deployment uses the distinct service name FlowMedIQ Hair Studio 360 and Suite identifier `flowmediq-hair-studio-360`.

Use the user's confirmed Render workspace and first check whether a Hair Studio 360 service already exists to avoid duplicates. The prepared Blueprint describes:

- Name: FlowMedIQ Hair Studio 360
- Python runtime, free review instance, one gevent worker
- Repository: i-Brain-Robotics/FlowMedIQ-Hair-Studio-360
- Branch: main
- Build: `pip install -r requirements.txt`
- Start: `gunicorn app:app --worker-class gevent --workers 1 --worker-connections 100 --timeout 300 --bind 0.0.0.0:$PORT`
- Health check: `/healthz`
- Automatic deploys: off during review

`render.yaml` intentionally contains no `envVars` or environment groups. Do not add, change or delete Render environment values automatically. The administrator must configure them manually.

| Variable | Administrator action |
|---|---|
| SECRET_KEY | Set a new strong session secret before public deployment. |
| APP_KEY | Register this new child app and enter its distinct Suite credential. |
| APP_SLUG | Set to the registered identifier, planned as `flowmediq-hair-studio-360`. |
| ADMIN_URL | Confirm `https://admin.flowgeniq.io`. |
| SUITE_URL | Confirm `https://suite.flowmediq.io`. |
| GEMINI_API_KEY | Set the authorized image-provider credential. |
| OPENAI_API_KEY | Optional; required for inherited voice output features. |
| PUBLIC_BASE_URL | Optional; set to the new confirmed URL for branded sharing. |

Register the new child app and callback in Suite Admin and the launcher through authorized configuration. Do not modify their source code. The inherited demo workflow uses the distinct app type `flowmediq_hair_studio_360`; demo integration requires matching support/configuration before use.

The free review instance has temporary local storage. Comparison images and the SQLite cache under `instance/studio360` disappear on redeploy; original uploads/results are also temporary. This is suitable for review, not durable patient storage. Durable storage and appropriate access controls need a separately reviewed production configuration. One worker avoids session-key drift if an administrator has not yet set SECRET_KEY; production still requires a stable configured secret.

## Release verification

Model tests (9), new route tests (8), legacy Gemini regressions (16), the shared-credit display test, and JavaScript syntax checks passed locally using synthetic fixtures. The local browser could not connect to the preview, so no new-app browser pass is claimed.

After configuration, verify `/healthz`, Suite launch with the authorized test account, photo upload, original transplant generation, all non-surgical presets, side-by-side and combined images, report download, displayed credit deductions, and cached image reuse. Confirm both original live apps remain reachable. Live-provider generation spends configured credits; no live image generation has been performed for this app yet.

## Design assets

The logo, favicon and scalp-zone reference diagram are included in `static/images`. The new app serves them directly and does not require the existing Hair Studio service for design assets.

The inherited personal notification address was removed. Demo notifications use the tenant address and an optional administrator-configured `DEMO_MASTER_NOTIFY_EMAIL`; no Render value was changed.
