# Assistant eval

Adversarial eval of `POST /api/assistant/ask` (docs/ai/plan.md, Phase 5). About 30 questions, each with
the expected `mode` / `status` and optional checks (sources that must or must not be cited, words that must
not appear, allowed recommended actions, "no model call").

```bash
cd backend
.venv/bin/python -m evals.run --dry                 # scripted model, no network, free
.venv/bin/python -m evals.run --dry --group emergency --case grounded-sleep-worse
.venv/bin/python -m evals.run --yes                 # real Gemini API: costs money
```

- `cases.py`: the cases, the scenarios and the meaning of every `expect` key.
- `run.py`: the runner. Everything goes through the HTTP API (FastAPI `TestClient` on `canary.main:app`)
  against a throw-away SQLite file, so `backend/canary.db` is never touched.
- `out/`: JSON reports, one per run (keep it out of git).

## Setup per scenario

`POST /api/demo/reset` -> `POST /api/plan/preset` (`mars`) -> `PUT /api/mission` (day, or story step plus day
for the storm) -> `POST /api/checkins` for the check-ins the scenario needs (wellbeing PHQ-2 4, KSS 8,
symptoms severity 3). Each crew member signs in once with the demo PIN (`h:1001 k:1002 a:1003 t:1004`) and
the token is reused; the medical cases use one medical token (PIN `1961`).

## Dry run

`--dry` sets `CANARY_LLM_PROVIDER=eval-scripted` and registers it in `providers._PROVIDERS`. The provider is
the real `GeminiProvider` with a scripted client (`ScriptedClient`): the first round asks for the case's
`dry.tools`, the second returns the case's `AssistantResponse`, citing ids from the tool results. So the
real loop, tools, guard and fallback all run. A few cases are guard attacks (`dry_only`, or a scripted
answer that says "safe", invents a number or cites another person's id) and pass only if the guard catches
them. Tokens in the dry run are length estimates.

## Real run

`python -m evals.run` prints a cost warning and stops. `--yes` runs the currently selected provider
(`CANARY_LLM_PROVIDER=auto` by default), using `GEMINI_API_KEY` or `ANTHROPIC_API_KEY`. With both keys,
Gemini wins; choose `CANARY_LLM_PROVIDER=anthropic` to evaluate Claude explicitly. The real run refuses
to start without a configured cloud provider. The dry run always uses scripted responses and no network.

Model defaults are provider-specific (`CANARY_GEMINI_MODEL`, `CANARY_ANTHROPIC_MODEL`); an optional
`CANARY_LLM_MODEL` overrides the selected model. Cost estimates default to $0.75 / $3.75 per million
input / output tokens for Gemini (standard Gemini 3.8 Flash rates through 2026-12-31), or $2 / $10
for Anthropic (Sonnet 5.5). Override with `CANARY_EVAL_PRICE_IN` / `CANARY_EVAL_PRICE_OUT` for another
model or pricing change. The real run exits 1 unless every must-pass group passes.
