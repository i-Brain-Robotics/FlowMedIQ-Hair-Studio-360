# Hair Studio 360

A separate FlowMediQ application that retains the original Hair Studio transplant workflow and adds six-month non-surgical modeling, side-by-side visual comparisons, and a combined plan with estimated graft savings.

Source repository: [i-Brain-Robotics/FlowMedIQ-Hair-Studio-360](https://github.com/i-Brain-Robotics/FlowMedIQ-Hair-Studio-360). The app preserves the original Hair Studio transplant workflow and adds its own comparison module.

## Features

- Four modes: original transplant studio, non-surgical month six, transplant versus non-surgical, and combined treatment.
- Three editable protocols using the owner's supplied density and thickness scenarios.
- Shared photo and scalp selections across the original and new interfaces.
- Region-specific measured area, terminal density, native shaft diameter, response fraction and transplant graft count.
- Separate percentage and absolute micron thickness methods; they never compound.
- Consistent transplant survival and visibility assumptions for both surgical paths.
- Deterministic hair counts, density, diameter and graft savings, plus downloadable JSON reports.
- Gemini image generation through the existing provider and shared-credit integrations. New comparison images have owner checks, cached results and a visible simulation label.

[Clinical methodology and sources](CLINICAL_METHODOLOGY.md) · [Deployment instructions](DEPLOYMENT.md)

## Verification

```bash
python -m unittest discover -s tests -p test_treatment_model.py -v
python -m unittest discover -s tests -p test_studio360_routes.py -v
ADMIN_URL='' python tests/test_gemini_image_migration.py
node tests/test_usage_display.js
node --check static/js/studio360.js
node --check static/js/studio360-bridge.js
```

The new tests use synthetic images and mocked authentication, provider and billing calls. They do not establish production SSO, live image quality or billing behavior. The original live application and Suite remained accessible with the authorized test account during this work. The new service still needs logged-in UI and live-provider verification after administrator configuration.

Run locally with the required configuration from `.env.example` and `gunicorn app:app --workers 1 --worker-class gevent --bind 0.0.0.0:5000`. Launch through the registered Suite app for normal authentication. No development authentication bypass is included.

Patient uploads, outputs, databases, secrets and temporary test files are excluded from version control. The original workflow retains its existing media and sharing behavior; access protection on the new comparison routes is not a claim that the entire inherited app has been security-audited.
