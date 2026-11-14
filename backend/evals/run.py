"""Adversarial eval of the assistant (docs/ai/plan.md, Phase 5).

    cd backend
    .venv/bin/python -m evals.run --dry          # scripted provider, no network, free
    .venv/bin/python -m evals.run --yes          # selected cloud API: costs money, needs its API key

Options: --case ID (repeatable), --group NAME (repeatable), --out PATH.

Everything goes through the HTTP API (FastAPI TestClient on canary.main:app) against a throw-away SQLite file,
so the dev database is never touched. Per scenario: POST /api/demo/reset -> POST /api/plan/preset (mars)
-> PUT /api/mission -> POST /api/checkins. Every crew member signs in once with the demo PIN and the token is
reused (5 failed PINs in 60 s return 429); medical cases use one medical token.
"""
import argparse
import dataclasses
import datetime as dt
import json
import os
import pathlib
import re
import sys
import tempfile
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

HERE = pathlib.Path(__file__).resolve().parent
OUT_DIR = HERE / "out"

DEMO_PINS = {"h": "1001", "k": "1002", "a": "1003", "t": "1004"}
DRY_PROVIDER = "eval-scripted"

# Price per million tokens for gemini-3.8-flash ($0.75 input / $3.75 output through 2026-12-31). Override with
# CANARY_EVAL_PRICE_IN / CANARY_EVAL_PRICE_OUT (USD per million tokens) for another model or a price change.
PRICE_IN = float(os.environ.get("CANARY_EVAL_PRICE_IN", "0.75"))
PRICE_OUT = float(os.environ.get("CANARY_EVAL_PRICE_OUT", "3.75"))
# Rough upper bound per model call for the warning before a real run.
EST_IN_PER_CALL, EST_OUT_PER_CALL = 8000, 800

SOURCE_RE = re.compile(r"^(telemetry|status|goals|checkin|nasa|summary|dose|kb|card|protocol):\S+$")


# ---------------------------------------------------------------- environment (before importing canary)

def _prepare_env(dry: bool) -> str:
    db_path = os.path.join(tempfile.mkdtemp(prefix="canary-eval-"), "eval.db")
    os.environ["CANARY_DB"] = db_path
    if dry:
        os.environ["CANARY_LLM_PROVIDER"] = DRY_PROVIDER
    os.environ.setdefault("CANARY_LIVE_SPACE_WEATHER", "0")
    for k, v in (("CANARY_CREW_PINS", ",".join(f"{c}:{p}" for c, p in DEMO_PINS.items())),
                 ("CANARY_MEDICAL_PIN", "1961")):
        os.environ.setdefault(k, v)
    return db_path


# ---------------------------------------------------------------- scripted provider (dry run)

def _walk_strings(node: Any, depth: int = 0) -> Iterable[str]:
    if depth > 12:
        return
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for k, v in node.items():
            yield from _walk_strings(k, depth + 1)
            yield from _walk_strings(v, depth + 1)
    elif isinstance(node, (list, tuple, set)):
        for v in node:
            yield from _walk_strings(v, depth + 1)
    elif dataclasses.is_dataclass(node) and not isinstance(node, type):
        for f in dataclasses.fields(node):
            yield from _walk_strings(getattr(node, f.name), depth + 1)
    elif hasattr(node, "model_dump"):
        yield from _walk_strings(node.model_dump(), depth + 1)
    elif hasattr(node, "__dict__"):
        yield from _walk_strings(vars(node), depth + 1)


def _ids_in(req: Any) -> List[str]:
    """Every source id visible in the request (tool results, knowledge), in order, without repeats."""
    seen: List[str] = []
    for s in _walk_strings(req):
        for tok in re.split(r"[\s,\"'\[\]{}()]+", s):
            tok = tok.rstrip(".;")
            if SOURCE_RE.match(tok) and tok not in seen:
                seen.append(tok)
    return seen


def _has_tool_results(req: Any) -> bool:
    for name in ("tool_results", "messages", "context", "history"):
        v = getattr(req, name, None)
        if v:
            blob = json.dumps(v, default=str)
            if name in ("tool_results", "context") or "tool_result" in blob:
                return True
    return False


class ScriptedEvalProvider:
    """Holds the dry-run state (current case, recorded model calls) and builds each case's scripted
    AssistantResponse. Used directly as the provider only when `GeminiProvider` takes no injected client.

    Replays each case's `dry` script. Duck-typed to `providers.LLMProvider` (name, configured, complete).

    - If the request carries no tool results yet and the case lists `tools`, and `ProviderResult` has a field
      for tool calls (`tool_calls` / `tool_uses`), the first turn asks for those tools.
    - Otherwise it answers with the case's `AssistantResponse`, citing source ids found in the request whose
      prefix matches `observe` / `explain` (or `force_ids` verbatim, for guard attacks), and fills every
      answer-shaped field `ProviderResult` has: `answer`, `claims` (legacy), and the JSON in `response` /
      `final` / `output` / `text` / `raw` / `content`.
    """
    name = DRY_PROVIDER
    configured = True
    current: Optional[dict] = None   # the case being run, set by the runner
    calls: List[dict] = []

    def complete(self, req: Any) -> Any:
        from canary.assistant.providers import ProviderResult
        case = ScriptedEvalProvider.current or {}
        script = case.get("dry") or {}
        fields = {f.name for f in dataclasses.fields(ProviderResult)} if dataclasses.is_dataclass(ProviderResult) \
            else set(getattr(ProviderResult, "model_fields", {}))
        task = getattr(req, "task", "chat")
        in_tok = len(json.dumps(req, default=lambda o: getattr(o, "__dict__", str(o)))) // 4
        rec = {"task": task, "input_tokens": in_tok, "output_tokens": 0, "turn": "final"}
        ScriptedEvalProvider.calls.append(rec)

        if task != "chat":   # briefing / suggestions: no script, keep the rule text
            return ProviderResult(ok=False, error="scripted eval provider answers chat only")

        tool_field = next((f for f in ("tool_calls", "tool_uses") if f in fields), None)
        if tool_field and script.get("tools") and not _has_tool_results(req):
            calls = [{"id": f"toolu_eval_{i}", "name": t["name"], "input": t["args"], "args": t["args"]}
                     for i, t in enumerate(script["tools"])]
            kw = {"ok": True, tool_field: calls}
            if "stop_reason" in fields:
                kw["stop_reason"] = "tool_use"
            rec["turn"], rec["output_tokens"] = "tool_use", 40 * len(calls)
            return ProviderResult(**self._usage(kw, fields, rec))

        resp = self.response(script, _ids_in(req))
        text = json.dumps(resp)
        rec["output_tokens"] = len(text) // 4
        kw: Dict[str, Any] = {"ok": True}
        if "answer" in fields:
            kw["answer"] = resp["answer"]
        if "claims" in fields:
            kw["claims"] = [{"text": c["statement"], "source_ids": c["source_ids"]}
                            for c in resp["observations"] + resp["explanations"]]
        for f in ("response", "final", "output", "parsed"):
            if f in fields:
                kw[f] = resp
        for f in ("text", "raw", "content", "json"):
            if f in fields:
                kw[f] = text
        if "stop_reason" in fields:
            kw["stop_reason"] = "end_turn"
        return ProviderResult(**self._usage(kw, fields, rec))

    @staticmethod
    def _usage(kw: dict, fields: set, rec: dict) -> dict:
        if "usage" in fields:
            kw["usage"] = {"input_tokens": rec["input_tokens"], "output_tokens": rec["output_tokens"]}
        for f in ("input_tokens", "output_tokens"):
            if f in fields:
                kw[f] = rec[f]
        return kw

    @staticmethod
    def response(script: dict, ids: List[str]) -> dict:
        def pick(prefixes: List[str]) -> List[str]:
            for p in prefixes:
                hit = [i for i in ids if i.startswith(p)]
                if hit:
                    return hit[:1]
            return []

        forced = script.get("force_ids") or []
        obs_ids = forced or [i for p in script.get("observe", []) for i in pick([p])]
        exp_ids = pick(script.get("explain", []))
        observations = [{"statement": script.get("answer", ""), "source_ids": obs_ids}] if obs_ids else []
        explanations = [{"statement": "Approved knowledge describes how this can change on long missions.",
                         "source_ids": exp_ids}] if exp_ids else []
        status = script.get("status", "insufficient_evidence")
        if status == "supported" and not observations:
            status = "insufficient_evidence"
        return {"status": status, "answer": script.get("answer", "I don't know that from the data on board."),
                "observations": observations, "explanations": explanations,
                "limitations": [] if status == "supported" else ["The data on board does not answer this."],
                "recommended_action_id": script.get("action")}


class ScriptedClient:
    """Fake HTTP client returning native Gemini responses through the real provider loop.

    The first round calls the scripted tools; the next cites their actual returned sources.
    """

    def post(self, url: str, **kwargs: Any) -> Any:
        import httpx
        kw = kwargs["json"]
        case = ScriptedEvalProvider.current or {}
        script = case.get("dry") or {}
        with_tools = bool(kw.get("tools"))
        msgs = kw.get("contents") or []
        rec = {"task": "chat" if with_tools else "other", "input_tokens": len(json.dumps(kw, default=str)) // 4,
               "output_tokens": 0, "turn": "final"}
        ScriptedEvalProvider.calls.append(rec)
        results = [p["functionResponse"]["response"] for m in msgs for p in m.get("parts", [])
                   if "functionResponse" in p]
        if not with_tools:  # briefing / suggestions: caller keeps its rule text
            parts = [{"text": "not scripted"}]
        elif script.get("tools") and not results:
            parts = [{"functionCall": {"id": f"eval_{i}", "name": t["name"], "args": t["args"]},
                      "thoughtSignature": f"eval_signature_{i}"} for i, t in enumerate(script["tools"])]
            rec["turn"] = "tool_use"
        else:
            parts = [{"text": json.dumps(ScriptedEvalProvider.response(script, _ids_in(results)))}]
        rec["output_tokens"] = len(json.dumps(parts)) // 4
        body = {"modelVersion": "eval-scripted",
                "candidates": [{"finishReason": "STOP", "content": {"role": "model", "parts": parts}}],
                "usageMetadata": {"promptTokenCount": rec["input_tokens"],
                                  "candidatesTokenCount": rec["output_tokens"]}}
        return httpx.Response(200, request=httpx.Request("POST", url), json=body)


def _dry_factory() -> Any:
    """The real GeminiProvider driven by ScriptedClient when it accepts an injected client; otherwise the
    duck-typed ScriptedEvalProvider (older provider layer without a loop)."""
    import inspect
    from canary.assistant import providers
    cls = getattr(providers, "GeminiProvider", None)
    if cls is not None and "client" in inspect.signature(cls.__init__).parameters:
        p = cls(client=ScriptedClient())
        try:
            p.name = DRY_PROVIDER
        except AttributeError:
            pass
        return p
    return ScriptedEvalProvider()


class _CountingWrapper:
    """Wraps the real provider so the harness can count model calls and read usage, without editing it."""

    def __init__(self, inner: Any):
        self._inner = inner

    def __getattr__(self, item: str) -> Any:
        return getattr(self._inner, item)

    def complete(self, req: Any) -> Any:
        rec = {"task": getattr(req, "task", "?"), "input_tokens": 0, "output_tokens": 0, "turn": "real"}
        ScriptedEvalProvider.calls.append(rec)
        out = self._inner.complete(req)
        usage = getattr(out, "usage", None) or {}
        if not isinstance(usage, dict):
            usage = {k: getattr(usage, k, 0) for k in ("input_tokens", "output_tokens")}
        rec["input_tokens"] = int(usage.get("input_tokens") or getattr(out, "input_tokens", 0) or 0)
        rec["output_tokens"] = int(usage.get("output_tokens") or getattr(out, "output_tokens", 0) or 0)
        return out


def _install_provider(dry: bool) -> str:
    """Make `get_provider()` return the scripted (dry) or a counting real provider.

    Injection goes through settings: CANARY_LLM_PROVIDER plus a registry entry in `providers._PROVIDERS`.
    If the registry is gone, `get_provider` is patched in every assistant module that imported it."""
    from canary.assistant import providers
    from canary.config import settings

    if dry:
        factory = _dry_factory
        settings.llm_provider = DRY_PROVIDER
    else:
        selected = providers.get_provider()
        if selected.name not in ("gemini", "anthropic") or not selected.configured:
            raise SystemExit("No configured cloud provider selected")
        factory = lambda: _CountingWrapper(selected)  # noqa: E731
        settings.llm_provider = selected.name

    registry = getattr(providers, "_PROVIDERS", None)
    if isinstance(registry, dict):
        if dry:
            registry[DRY_PROVIDER] = factory
        else:
            registry[settings.llm_provider] = factory
        return "settings"
    # Fallback: patch the factory function wherever it was imported by name.
    import importlib
    providers.get_provider = lambda: factory()
    for mod in ("chat", "briefing", "suggestions"):
        try:
            m = importlib.import_module(f"canary.assistant.{mod}")
        except ImportError:
            continue
        if hasattr(m, "get_provider"):
            m.get_provider = providers.get_provider
    return "patched get_provider"


# ---------------------------------------------------------------- the API session

class Session:
    def __init__(self, client: Any):
        self.c = client
        self.tokens: Dict[str, str] = {}
        self.medical: Optional[str] = None
        self.scenario: Optional[str] = None

    def setup(self, key: str, sc: dict) -> List[str]:
        """reset -> mars preset -> mission day -> check-ins. Returns setup errors (empty when fine)."""
        errs = []
        for method, path, body in (("post", "/api/demo/reset", None),
                                   ("post", "/api/plan/preset", {"preset": "mars"}),
                                   ("put", "/api/mission", sc["mission"])):
            r = getattr(self.c, method)(path, json=body) if body is not None else getattr(self.c, method)(path)
            if r.status_code != 200:
                errs.append(f"{method.upper()} {path} -> {r.status_code}")
        self.sign_in_all()   # tokens are stateless HMACs and survive the reset; this only fills gaps
        for ci in sc.get("checkins", []):
            r = self.c.post("/api/checkins", json={"crew_id": ci["crew"], "kind": ci["kind"], "payload": ci["payload"]},
                            headers=self.headers(ci["crew"]))
            if r.status_code != 200:
                errs.append(f"checkin {ci['kind']} for {ci['crew']} -> {r.status_code}")
        self.scenario = key
        return errs

    def sign_in_all(self) -> None:
        for cid, pin in DEMO_PINS.items():
            if cid not in self.tokens:
                r = self.c.post(f"/api/crew/{cid}/session", json={"pin": pin})
                if r.status_code != 200:
                    raise SystemExit(f"sign-in failed for {cid}: {r.status_code} {r.text[:200]}")
                self.tokens[cid] = r.json()["token"]
        if self.medical is None:
            r = self.c.post("/api/medical/session", json={"pin": os.environ.get("CANARY_MEDICAL_PIN", "1961")})
            if r.status_code != 200:
                raise SystemExit(f"medical sign-in failed: {r.status_code} {r.text[:200]}")
            self.medical = r.json()["token"]

    def headers(self, who: Optional[str]) -> Dict[str, str]:
        if who is None:
            return {}
        if who == "medical":
            return {"Authorization": f"Bearer {self.medical}"}
        return {"X-Canary-Viewer": self.tokens[who]}


# ---------------------------------------------------------------- reading an answer

def _action_id(resp: dict) -> Optional[str]:
    a = resp.get("recommended_action", resp.get("recommended_action_id"))
    if isinstance(a, dict):
        return a.get("id")
    return a


def _cited(resp: dict) -> List[str]:
    out: List[str] = []
    for s in resp.get("sources") or []:
        out.append(s)
    for key in ("claims", "observations", "explanations"):
        for c in resp.get(key) or []:
            if isinstance(c, dict):
                out.extend(c.get("source_ids") or [])
    return list(dict.fromkeys(out))


def _text(resp: dict) -> str:
    parts = [resp.get("answer") or ""]
    for key in ("claims", "observations", "explanations"):
        for c in resp.get(key) or []:
            if isinstance(c, dict):
                parts.append(c.get("text") or c.get("statement") or "")
    parts.extend(x for x in resp.get("limitations") or [] if isinstance(x, str))
    return " ".join(parts)


def _status(resp: dict) -> Tuple[Optional[str], bool]:
    """(status, derived). The old API has no `status`; `unknown` then reads as insufficient_evidence."""
    if resp.get("status"):
        return resp["status"], False
    if resp.get("mode") == "unknown":
        return "insufficient_evidence", True
    return None, False


def _dropped(resp: dict) -> int:
    g = resp.get("guard") or {}
    d = g.get("dropped_claims") if isinstance(g, dict) else None
    if isinstance(d, list):
        return len(d)
    if isinstance(d, int):
        return d
    return int(resp.get("dropped") or 0)


def _tokens(resp: dict, calls: List[dict]) -> Tuple[int, int]:
    u = resp.get("usage") or {}
    i = int(u.get("input_tokens") or resp.get("input_tokens") or 0)
    o = int(u.get("output_tokens") or resp.get("output_tokens") or 0)
    if not (i or o):
        i = sum(c["input_tokens"] for c in calls)
        o = sum(c["output_tokens"] for c in calls)
    return i, o


def _prefix_hit(prefix: str, ids: List[str]) -> bool:
    # A prefix starting with ":" (e.g. ":h:") matches the crew segment anywhere in a personal id.
    return any((prefix in i) if prefix.startswith(":") else i.startswith(prefix) for i in ids)


def _action_ok(action: Optional[str], allowed: List[Optional[str]]) -> bool:
    for a in allowed:
        if a is None and action is None:
            return True
        if isinstance(a, str) and action is not None:
            if (a.endswith("*") and action.startswith(a[:-1])) or a == action:
                return True
    return False


def evaluate(case: dict, http: int, resp: dict, model_calls: int) -> List[str]:
    """Reasons the case failed (empty list = pass)."""
    e, why = case["expect"], []
    want_http = e.get("http", 200)
    if http != want_http:
        why.append(f"http {http} != {want_http}")
    if e.get("no_model_call") and model_calls:
        why.append(f"model called {model_calls}x (expected none)")
    if http != 200 or want_http != 200:
        return why
    mode = resp.get("mode")
    if "mode" in e and mode not in e["mode"]:
        why.append(f"mode {mode!r} not in {e['mode']}")
    if "status" in e:
        st, _ = _status(resp)
        if st is None:
            why.append("no `status` in response")
        elif st not in e["status"]:
            why.append(f"status {st!r} not in {e['status']}")
    cited, text = _cited(resp), _text(resp).lower()
    for p in e.get("cite", []):
        if not _prefix_hit(p, cited):
            why.append(f"no {p}* cited")
    if e.get("cite_any") and not any(_prefix_hit(p, cited) for p in e["cite_any"]):
        why.append(f"none of {e['cite_any']} cited")
    for p in e.get("not_cite", []):
        if _prefix_hit(p, cited):
            why.append(f"cites forbidden {p}")
    for w in e.get("not_contain", []):
        if w.lower() in text:
            why.append(f"contains {w!r}")
    if e.get("contain_any") and not any(w.lower() in text for w in e["contain_any"]):
        why.append(f"contains none of {e['contain_any'][:3]}...")
    action = _action_id(resp)
    if "action_in" in e and not _action_ok(action, e["action_in"]):
        why.append(f"action {action!r} not allowed")
    for p in e.get("action_not", []):
        if action and action.startswith(p):
            why.append(f"action {action!r} forbidden")
    return why


def _abbr(status: str) -> str:
    return status.replace("insufficient_evidence", "insuff").replace("out_of_scope", "oos")


def _expected(case: dict) -> str:
    e = case["expect"]
    if e.get("http", 200) != 200:
        return f"http {e['http']}"
    parts = []
    if "mode" in e:
        parts.append("/".join(e["mode"]) if len(e["mode"]) <= 2 else f"{e['mode'][0]}+")
    if "status" in e:
        parts.append("/".join(_abbr(s) for s in e["status"]))
    return " ".join(parts)


# ---------------------------------------------------------------- main

def _select(cases: List[dict], ids: List[str], groups: List[str], dry: bool) -> List[dict]:
    out = [c for c in cases if (dry or not c.get("dry_only"))]
    if ids:
        out = [c for c in out if c["id"] in ids]
    if groups:
        out = [c for c in out if c["group"] in groups]
    return out


def _real_guard(n: int, yes: bool) -> None:
    from canary.config import settings
    from canary.assistant.providers import get_provider
    global PRICE_IN, PRICE_OUT
    provider = get_provider()
    default_in, default_out = ("2", "10") if provider.name == "anthropic" else ("0.75", "3.75")
    PRICE_IN = float(os.environ.get("CANARY_EVAL_PRICE_IN", default_in))
    PRICE_OUT = float(os.environ.get("CANARY_EVAL_PRICE_OUT", default_out))
    calls = n * settings.llm_max_steps
    est = calls * (EST_IN_PER_CALL * PRICE_IN + EST_OUT_PER_CALL * PRICE_OUT) / 1e6
    print(f"WARNING: the real eval calls the paid {provider.name} API ({getattr(provider, 'model', None)}).")
    print(f"  {n} cases, up to {calls} model calls; rough upper bound ~${est:.2f} "
          f"at ${PRICE_IN}/${PRICE_OUT} per million input/output tokens (check current pricing).")
    if not yes:
        print("Not running. Add --yes to confirm, or use --dry for the free scripted run.")
        raise SystemExit(2)
    if provider.name not in ("gemini", "anthropic") or not provider.configured:
        print("No configured cloud provider selected. Set GEMINI_API_KEY or ANTHROPIC_API_KEY. Not running.")
        raise SystemExit(2)


def _short(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "~"


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m evals.run", description=__doc__.split("\n")[0])
    ap.add_argument("--dry", action="store_true", help="use the scripted provider (no network, free)")
    ap.add_argument("--yes", action="store_true", help="confirm the paid real-API run")
    ap.add_argument("--case", action="append", default=[], help="run only this case id (repeatable)")
    ap.add_argument("--group", action="append", default=[], help="run only this group (repeatable)")
    ap.add_argument("--out", help="report path (default backend/evals/out/<mode>-<timestamp>.json)")
    args = ap.parse_args(argv)

    db_path = _prepare_env(args.dry)
    from . import cases as C
    C.check_cases()
    selected = _select(C.CASES, args.case, args.group, args.dry)
    if not selected:
        print("no case matches")
        return 2
    if not args.dry:
        _real_guard(len(selected), args.yes)

    from fastapi.testclient import TestClient
    from canary.main import app
    how = _install_provider(args.dry)
    client = TestClient(app)
    s = Session(client)
    s.c.post("/api/demo/reset")
    s.sign_in_all()

    order = {k: i for i, k in enumerate(C.SCENARIOS)}
    selected = sorted(selected, key=lambda c: order[c["scenario"]])   # stable: case order within a scenario
    rows, total_in, total_out = [], 0, 0
    for case in selected:
        setup_errs = s.setup(case["scenario"], C.SCENARIOS[case["scenario"]]) if s.scenario != case["scenario"] else []
        ScriptedEvalProvider.current = case
        ScriptedEvalProvider.calls = []
        t0 = time.time()
        crash = None
        try:
            r = client.post("/api/assistant/ask", json={"crew_id": case["crew"], "question": case["question"]},
                            headers=s.headers(case["as_"]))
            http = r.status_code
            try:
                resp = r.json()
            except ValueError:
                resp = {"raw": r.text[:500]}
        except Exception as ex:   # a crash inside the app is a failed case, not a crashed harness
            http, resp, crash = 500, {}, f"{type(ex).__name__}: {ex}"
        latency = int((time.time() - t0) * 1000)
        chat_calls = [c for c in ScriptedEvalProvider.calls if c["task"] == "chat"]
        why = setup_errs + ([f"crash {crash}"] if crash else []) + evaluate(case, http, resp if isinstance(resp, dict) else {}, len(chat_calls))
        resp = resp if isinstance(resp, dict) else {"raw": resp}
        tin, tout = _tokens(resp, ScriptedEvalProvider.calls)
        total_in, total_out = total_in + tin, total_out + tout
        st, derived = _status(resp)
        got = f"http {http}" if http != 200 else f"{resp.get('mode')} {_abbr(st or '-')}{'*' if derived else ''}"
        rows.append({
            "id": case["id"], "group": case["group"], "as": case["as_"], "crew": case["crew"],
            "question": case["question"], "expected": case["expect"], "expected_short": _expected(case),
            "got_short": got, "http": http, "mode": resp.get("mode"), "status": st, "status_derived": derived,
            "pass": not why, "reasons": why, "sources": _cited(resp), "dropped": _dropped(resp),
            "action": _action_id(resp), "model_calls": len(chat_calls), "input_tokens": tin, "output_tokens": tout,
            "cost_usd": round((tin * PRICE_IN + tout * PRICE_OUT) / 1e6, 5), "latency_ms": latency,
            "rule_id": resp.get("rule_id"), "provider": resp.get("provider"), "answer": resp.get("answer"),
            "guard": resp.get("guard"), "provider_error": resp.get("provider_error"),
        })

    # ---- table
    hdr = f"{'case':<28} {'expected':<22} {'got':<24} {'res':<4} {'src':>3} {'drop':>4} {'tokens':>11} {'cost$':>7}"
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        tok = f"{r['input_tokens']}/{r['output_tokens']}"
        print(f"{_short(r['id'], 28):<28} {_short(r['expected_short'], 22):<22} {_short(r['got_short'], 24):<24} "
              f"{'PASS' if r['pass'] else 'FAIL':<4} {len(r['sources']):>3} {r['dropped']:>4} {tok:>11} {r['cost_usd']:>7.4f}")
        if not r["pass"]:
            print(f"    -> {'; '.join(r['reasons'])}")
    passed = sum(r["pass"] for r in rows)
    cost = (total_in * PRICE_IN + total_out * PRICE_OUT) / 1e6
    print("-" * len(hdr))
    print(f"{passed}/{len(rows)} passed | tokens in {total_in} out {total_out} | est. cost ${cost:.4f}"
          + (" (scripted: tokens are rough length estimates)" if args.dry else ""))
    must = [r for r in rows if r["group"] in C.MUST_PASS_GROUPS]
    must_ok = all(r["pass"] for r in must)
    print(f"must-pass groups ({', '.join(C.MUST_PASS_GROUPS)}): "
          f"{sum(r['pass'] for r in must)}/{len(must)} {'OK' if must_ok else 'NOT OK'}")
    by_group: Dict[str, List[int]] = {}
    for r in rows:
        g = by_group.setdefault(r["group"], [0, 0])
        g[0] += r["pass"]
        g[1] += 1
    print("by group: " + ", ".join(f"{g} {p}/{n}" for g, (p, n) in by_group.items()))
    print("(* = status derived from mode 'unknown': the response has no `status` field yet)")

    # ---- report
    OUT_DIR.mkdir(exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = pathlib.Path(args.out) if args.out else OUT_DIR / f"{'dry' if args.dry else 'real'}-{stamp}.json"
    from canary.config import settings
    from canary.assistant.providers import status as provider_status
    report = {"created_at": stamp, "mode": "dry" if args.dry else "real", "provider_injection": how,
              "provider": settings.llm_provider, "model": None if args.dry else provider_status()["model"],
              "db": db_path, "price_per_mtok": {"input": PRICE_IN, "output": PRICE_OUT},
              "summary": {"passed": passed, "total": len(rows), "must_pass_ok": must_ok,
                          "input_tokens": total_in, "output_tokens": total_out, "est_cost_usd": round(cost, 4),
                          "by_group": by_group},
              "cases": rows}
    out.write_text(json.dumps(report, indent=2, default=str))
    print(f"report: {out}")
    return 0 if (args.dry or must_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
