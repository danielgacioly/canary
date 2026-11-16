# Operations

Running Canary anywhere other than a laptop demo: modes, processes, security, backups, and how input is checked. The [README](../README.md#configuration) lists every setting.

## Demo mode and flight mode

`CANARY_MODE` is `demo` (the default) or `flight`.

| | `demo` | `flight` |
| --- | --- | --- |
| First start | loads the demo mission package (`CANARY_MISSION_PACKAGE`) | loads nothing; Mission Control registers the crew |
| Demo-only routes (`/api/demo/*`, the demo form, setting the story day) | available | 404 |
| Demo story scenes | from the package | none |
| Communication delay | runs `CANARY_DELAY_SPEEDUP` times faster (default 20) | real time |
| Fallback crew PINs (`CANARY_CREW_PINS`) | `h:1001,k:1002,a:1003,t:1004` | empty |
| Shared ingest key `CANARY_INGEST_KEY` | accepted | refused: only registered device keys |
| `sample` readings | accepted, never used for baselines or alerts | refused |
| Start-up | always | **refuses to start** without `CANARY_TOKEN_SECRET` and `CANARY_CONTROL_BOOTSTRAP_PIN` |

`CANARY_CONTROL_BOOTSTRAP_PIN` is the first-access PIN of Canary Control (demo default `4242`). It is accepted only while no Mission Control account exists; once Mission Control registers its accounts (the ground accounts in the registration, or a package's `ground.csv`), people sign in with their own account and PIN.

## One process

Run the API as **one process with one worker** (`make serve`, or `uvicorn canary.main:app` without `--workers`). The assistant's rate limits, the suggestion cache and the request metrics live in memory, so each worker would keep its own counts. The PIN lock-outs and the audit trail are in SQLite and survive a restart. Two processes on one database file are not supported.

## Sessions across restarts

Sessions are signed with `CANARY_TOKEN_SECRET`. Without it the server draws a new secret at every start, so every session ends at a restart. Set it in any deployment, and keep it with the backup's configuration.

## Health and metrics

| Route | Who | What it says |
| --- | --- | --- |
| `GET /api/health/live` | anyone | the process answers (use for liveness: restart only when this fails) |
| `GET /api/health/ready` | anyone | the database and the knowledge base can be read; `503` with the failing check otherwise (use for load-balancer traffic) |
| `GET /api/metrics` | Mission Control | request counts, errors and p50/p95 latency per route since the process started (in memory) |

Background work (the warm-up, the day sync, the evaluation after an ingest, a knowledge-base rebuild) logs failures with a traceback to the `canary` logger; a failed knowledge-base rebuild logs a warning and the API keeps running.

## Security headers and TLS

Every response carries a Content-Security-Policy that allows only the app's own origin, `X-Frame-Options: DENY` with `frame-ancestors 'none'`, `Referrer-Policy: no-referrer` and `X-Content-Type-Options: nosniff`. Every `/api` response is `Cache-Control: no-store`. The app loads no fonts or scripts from another server: it uses the system's fonts.

The app does not terminate TLS and does not send `Strict-Transport-Security`. Anywhere but a laptop:

- put a reverse proxy in front (nginx, Caddy or a cloud load balancer), serve HTTPS only, and set HSTS at the proxy;
- forward only to the one process; do not expose port 8000 directly;
- the lock-outs count wrong PINs per client address, so run `uvicorn canary.main:app --proxy-headers --forwarded-allow-ips=<proxy address>`; otherwise one wrong-PIN streak can lock out everyone behind the proxy;
- set the proxy's body limit above the largest upload the app accepts (120 MB for a mission package, `MAX_UPLOAD_BYTES` in `domain/data.py`);
- set `CANARY_CORS_ORIGINS` only when the web app is served from another origin than the API.

## The audit trail

Who did what, when, to what, with the value before and after, is written to an insert-only audit trail in SQLite: each row carries a SHA-256 hash of the previous row's hash and its own fields, so editing or deleting a row breaks the chain. PINs, tokens and keys are never written there. `GET /api/audit` pages through it (the medical team; Mission Control sees the same entries with health values redacted), and `GET /api/audit/verify` walks the chain and reports `{ok, broken_at}`: the first entry that was altered or removed.

## Data: where it lives, backup and restore

All the mission data is one SQLite file: `CANARY_DB` (default `backend/canary.db`). Keep it on a persistent volume, never inside the container image or the source tree.

- **Backup** while the server runs: `sqlite3 backend/canary.db ".backup '/backups/canary-YYYYMMDD.db'"`. That is a consistent copy; do not copy the live file with `cp`.
- **Restore**: stop the server, put the backup at `CANARY_DB`, start the server, then check `GET /api/health/ready` and, signed in as Mission Control or a flight surgeon, `GET /api/audit/verify` (it must say `ok: true`).
- The knowledge base `backend/kb.db` is not backed up: it is built from the shipped corpus (`make index`) and rebuilt at start-up when it does not match the code.

## Input checks

Every input is checked twice, and the server never trusts the page.

- **In the page.** The rules live in [`frontend/src/lib/validate.ts`](../frontend/src/lib/validate.ts). [`useForm.ts`](../frontend/src/lib/useForm.ts) runs a form: a field shows its error when it is left or on the first Save, a Save with errors sends nothing and focuses the first wrong field, and the button reads "Saving…" and ignores a second press. Buttons outside a form go through `useAction.ts`, which shows the error next to the button or as a toast.
- **On the server.** The same rules sit in [`backend/canary/domain/validation.py`](../backend/canary/domain/validation.py), in `selftests.validate` (one rule set per kind of check-in) and in the Pydantic models of `main.py`. A bad value returns **422** with `detail: [{"field": "crew.1.dob", "message": "Date of birth is required"}]` and nothing is written; the web client puts each message under its field.
- **Tests** send one bad value per form and check the 422, the field, and that the database did not change.

The accepted ranges are plausibility limits (prototype assumptions): they catch typos and impossible numbers and say nothing about health. Examples:

- vital signs: pulse 25 to 250 bpm, systolic pressure 60 to 260 mmHg, temperature 30 to 45 °C, oxygen 50 to 100%;
- sleep diary: 1 to 16 h;
- messages: 1 to 1,000 characters; questions to Ask Canary: 1 to 500;
- registration: one to six people, a unique four-digit PIN each, age 25 to 70 at launch, height 140 to 210 cm, weight 40 to 150 kg;
- photos: PNG, JPEG or WebP, checked by their first bytes.

## Continuous integration (recipe, not yet in the repository)

A GitHub Actions job that runs the same checks as `make test` and builds the app:

```yaml
name: ci
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    env:
      CANARY_EMBEDDER: none
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - uses: actions/setup-node@v4
        with: { node-version: "20" }
      - run: make setup
      - run: make test
      - run: make build
```

## End-to-end tests (planned)

A browser suite (Playwright) against `make serve` on a fresh database:

1. The intro ends on the crew screen with no sign-in, and that screen shows no health values.
2. A crew PIN opens My space; five wrong PINs pause sign-in with the wait shown.
3. Only the medical console can approve a briefing.
4. Opening Guided Response shows the red alarm bar on every screen with the name and protocol only; Cancel removes it.
5. Leaving the medical console ends its session; coming back asks for the PIN.
6. Stopping the API shows the offline banner; starting it again clears it.
