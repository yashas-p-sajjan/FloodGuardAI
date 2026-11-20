# FloodGuard AI — Regional Dashboard

A four-state experimental retrospective flood-risk screening dashboard covering Andhra Pradesh, Karnataka, Kerala and Tamil Nadu.

## Important limitations

- This is historical screening, not a calibrated flood probability.
- It is not an operational flood forecast or live alert system.
- No trained machine-learning model is included.
- Runtime datasets and boundary assets are intentionally excluded from this source-only release.
- Data redistribution and hosting permission are still pending.

Required dashboard disclaimer:

`EXPERIMENTAL RISK SCORE – NOT A CALIBRATED FLOOD PROBABILITY`

## Runtime status

This repository contains application source code only. The application requires its approved runtime datasets and boundary asset before it can run correctly.

Do not deploy this repository as a functioning public dashboard until the required data and redistribution permissions have been obtained.

## Dependencies

Install dependencies with:

```bash
pip install -r requirements.txt
```

## Run (after approved runtime data is supplied)

```bash
streamlit run app.py
```
