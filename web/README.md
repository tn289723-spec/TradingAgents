# TradingAgents-TW Mobile-First Web (read-only)

Static UI at `web/index.html`. It consumes **only** the serialized `DashboardProjection` v1 contract from `render_dashboard_projection_json(report)`.

## Local use
```sh
node --test web/dashboard.test.mjs
python -m http.server 8080 --directory web
```
Open the local HTTP server in a browser. With no `web/projection.json`, the screen remains **BLOCKED / no data**. You may load an actual v1 projection JSON through the file picker. A manually imported JSON is schema-checked but **not cryptographically authenticated**.

## Deployment
Deploy `web/` as a static directory (Cloudflare Pages build command: none; output directory: `web`). Keep the origin HTTPS. For an authorized real data pipeline, atomically publish the exact validated `render_dashboard_projection_json(report)` bytes as same-origin `projection.json`; never substitute synthetic fixtures or expose raw provider secrets.

The page intentionally contains **no** default `projection.json` or embedded sample prices. A missing, invalid, future-version or contradictory projection shows no scores. The UI cannot independently certify historical PIT completeness, verify signed archive attestations or reconstruct upstream Truth/State; those gates must run before publishing. A green light only means the upstream report's **evidence-readiness gate**, not a trading signal or a claim of historical PIT certification.

Do not put the local file-picker content into analytics, localStorage, or network upload. The current implementation does not persist the selected file.

## Acceptance
```sh
node --test web/dashboard.test.mjs
pytest
```
CI runs both Python matrices and the Node 22 dashboard smoke tests. Production hosting and genuine signed PIT capture remain separate release gates.

## GitHub Pages alternative (no Cloudflare project creation)
A deployment workflow at `.github/workflows/pages.yml` builds the audited, read-only static client from `web/index.html` and `web/dashboard.mjs` only. It does **not** publish synthetic or user-uploaded `projection.json`, secrets, or test fixtures.

The repository administrator must enable **Settings → Pages → Build and deployment → Source: GitHub Actions** once, if Pages is not yet enabled. The workflow then runs on changes to `web/**` or the Pages workflow on `main`, or manually via `workflow_dispatch`. The expected URL shape is `https://tn289723-spec.github.io/TradingAgents/` **only after** a successful deployment and independent HTTP reachability check; do not claim it is live from workflow creation alone.

Until a separately authorized, independently verified PIT data pipeline publishes a valid same-origin `projection.json`, the hosted dashboard intentionally shows **BLOCKED / no trusted data**. Manual JSON import is for local inspection, not verified live market data. The release gate remains open until HTTPS and deployment success are observed.
