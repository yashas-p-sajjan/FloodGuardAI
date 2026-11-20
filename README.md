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

## Streamlit Community Cloud deployment (not yet ready)

Deployment is blocked until runtime-data hosting, redistribution, and
evaluation-period permissions are approved. The GitHub asset repository is
private, but values rendered by the dashboard are visible to its users; a
private source repository or token does not make displayed data private.

After those permissions and access controls are confirmed:

1. Confirm that the approved runtime assets are present at the allowlisted
   paths in the private asset repository, and pin the exact commit SHA.
2. In Streamlit Community Cloud, create an app from the source repository,
   select its branch, and set the app file to `app.py` at the repository root.
3. In Advanced settings, select a currently supported Python version compatible
   with `requirements.txt`, then enter the `[runtime_assets]` configuration
   shown below in the Secrets field. Never put real credentials in this repo.
4. Deploy only after confirming that the app's audience is permitted to view
   the rendered runtime data. Check the deployment logs and validate the
   configured asset version before sharing the app.

See the official [Community Cloud deployment guide](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy)
and [secrets management guide](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management).
This procedure has not been run for this release; a fresh Cloud install,
private-repository access, and browser rendering remain unverified.

## Runtime asset configuration

The loader supports two explicit modes. It defaults to local mode when no
`runtime_assets` Streamlit Secrets section is configured.

### Local mode

Local mode reads the existing paths relative to the dashboard module:
`data/dashboard_cache_metadata.json`, `data/annual_scores/`,
`data/district_history/`, and `assets/four_state_rainfall_boundaries.geojson`.
It does not require GitHub credentials. To point a local release checkout at an
existing local Stage 10 dashboard folder, use an uncommitted local
`.streamlit/secrets.toml` file:

```toml
[runtime_assets]
mode = "local"
local_data_root = "PATH_TO_LOCAL_STAGE10_DASHBOARD_FOLDER"
```

Omit `local_data_root` when the data and `assets` folders are beside
`dashboard_data.py`.

### GitHub mode

For a later approved deployment, place the runtime files in a separate private
GitHub repository and configure Streamlit Community Cloud's app Secrets with
the following placeholder-only structure:

```toml
[runtime_assets]
mode = "github"
owner = "your-github-owner"
repository = "your-private-runtime-assets"
ref = "0000000000000000000000000000000000000000"
path_prefix = ""

[runtime_assets.github]
token = "github_pat_REPLACE_WITH_READ_ONLY_TOKEN"
```

Create a fine-grained token restricted to that private runtime repository with
**Contents: read-only** permission. Enter the real values only in Community
Cloud's Secrets settings or an uncommitted local secrets file. Never commit a
token or place it in a URL. GitHub mode does not fall back to local files when
credentials or remote assets are unavailable. The loader fetches the pinned
commit and its recursive tree to resolve the approved asset path to a blob SHA,
then downloads only that blob through the Git Blobs API. The commit tree and
parsed assets are cached using repository, pinned commit, and asset path; data
blobs remain lazy-loaded for the selected year or district.

`path_prefix` may be empty or a relative, slash-separated folder path such as
`runtime-assets/v1`. Do not include a leading or trailing slash, backslashes,
`.`/`..` segments, or arbitrary file paths. Commit, tree, and blob requests all
use `https://api.github.com`; redirects are rejected. The fine-grained token
needs only **Contents: read** for the private runtime-assets repository.

### Synthetic loader tests

Run the focused tests without contacting GitHub or using real runtime data:

```bash
python -m unittest discover -s tests -p "test_github_asset_loader.py" -v
```

The tests use mocked HTTP responses and temporary synthetic local fixtures.

**Data permission warning:** Do not upload or host any real rainfall data,
derived score/history files, or boundary GeoJSON until data redistribution,
third-party hosting, and evaluation-period permissions have been approved.
