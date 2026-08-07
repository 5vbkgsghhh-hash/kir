#!/usr/bin/env python3
"""Corpus CI gate — Wave-2 batch H (2026-07-08).

The RAG recipe corpus (``data/revit_api_db.json``) was audited and repaired
by hand across waves S1-S5 (see ``/root/kukai-rag-audit/WORK_BACKLOG.md``
§H). This script is the *system-level backstop* so that quality can't quietly
regress again: it runs the same checks the audit did, as one repeatable
command, so every future recipe edit gets re-verified instead of trusted on
faith.

Checks (see `CHECKS` docstring on each `_check_*` function for detail):
  1. compile      — every recipe compiles on every `compiles_on` version via
                     the live Roslyn compile-service (localhost:52412).
  2. gate-verify   — every recipe's code passes `kukai.security.validation
                     .validate_code_safety` (same function prod calls
                     pre-execution).
  3. prose-lint    — draft markers / empty user-facing fields / truncated
                     pitfalls.
  4. idiom-lint    — `.IntegerValue`, `BuiltInParameter.LEVEL_PARAM`,
                     `PickObject(` idiom bans (allowlist-exemptible) + a
                     report-only destructive-fallback advisory list.
  5. consistency   — doc2query 1:1 with recipes, no duplicate recipe names,
                     corpus manifest freshness, `intent` field coverage
                     (advisory).

compile / gate-verify / consistency are FAIL-class (nonzero exit on
violation). prose-lint / idiom-lint are WARN-class by default; pass
``--strict`` to promote them to FAIL-class too. The destructive-fallback
advisory list is *always* advisory (never elevated by --strict) — it is a
deliberately broad, unfiltered net for human wave-3 triage, not a precise
verdict (see `_check_idiom_lint` docstring).

Usage
-----
    venv/bin/python scripts/corpus_gate.py ci [--fast] [--strict] [--json OUT]

    # individual checks (same JSON/table machinery, useful standalone):
    venv/bin/python scripts/corpus_gate.py compile [--fast]
    venv/bin/python scripts/corpus_gate.py gate-verify
    venv/bin/python scripts/corpus_gate.py prose-lint
    venv/bin/python scripts/corpus_gate.py idiom-lint
    venv/bin/python scripts/corpus_gate.py consistency

Extending this tool
--------------------
Add a new `_check_*(db) -> CheckResult` function and wire it into `CHECKS`
plus a subparser in `main()` — do not build a parallel corpus-CI script.

State/config files this tool owns (created on first run, never hand-edited):
  data/corpus_ci_state.json  — per-recipe code-sha + last compile result,
                               used by `compile --fast` to skip unchanged
                               recipes. Updated ONLY on a fully-green compile
                               run (a run with any FAIL never persists state,
                               so a broken recipe keeps getting re-checked).
  data/corpus_ci_allow.json  — idiom-lint allowlist (per-check list of exempt
                               recipe names). Seeded empty; wave-3 triage
                               populates it as specific hits are hand-verified
                               legitimate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

from kukai.rag import corpus_manifest as cm  # noqa: E402

DATA_DIR = _BACKEND / "data"
DB_PATH = DATA_DIR / "revit_api_db.json"
DOC2QUERY_PATH = DATA_DIR / "doc2query_v1.jsonl"
STATE_PATH = DATA_DIR / "corpus_ci_state.json"
ALLOW_PATH = DATA_DIR / "corpus_ci_allow.json"

ROSLYN_URL = "http://localhost:52412/compile"
ROSLYN_TIMEOUT = 25.0

# Byte-identical to kukai/modeling/bridge/exec_wrapper.py's wrapper (verified
# against /root/kukai-rag-audit/exec_scripts/s5_compile_sweep.py, S5's own
# compile-sweep tool, which cites the same provenance).
WRAPPER_HEADER = (
    "using System;\n"
    "using System.Linq;\n"
    "using System.Collections.Generic;\n"
    "using System.Text;\n"
    "using System.Text.RegularExpressions;\n"
    "using Autodesk.Revit.DB;\n"
    "using Autodesk.Revit.DB.Architecture;\n"
    "using Autodesk.Revit.DB.Structure;\n"
    "using Autodesk.Revit.DB.Mechanical;\n"
    "using Autodesk.Revit.DB.Electrical;\n"
    "using Autodesk.Revit.DB.Plumbing;\n"
    "using Autodesk.Revit.UI;\n"
    "\n"
    "namespace Kukai\n"
    "{\n"
    "    public class UserCode\n"
    "    {\n"
    "        public static object Execute(Document doc, UIDocument uidoc)\n"
    "        {\n"
)
WRAPPER_FOOTER = "\n        }\n    }\n}\n"

FAIL_CLASS = {"compile", "gate-verify", "consistency"}
WARN_CLASS = {"prose-lint", "idiom-lint"}


# ═══════════════════════════════════════════════════════════════════════════
# Shared plumbing
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class CheckResult:
    name: str
    status: str  # PASS | FAIL | WARN | ADVISORY
    detail: str
    items: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"name": self.name, "status": self.status, "detail": self.detail,
                "n_items": len(self.items), "items": self.items}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_db() -> dict:
    return json.loads(DB_PATH.read_text(encoding="utf-8"))


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {"version": 1, "updated_at": None, "recipes": {}}


def save_state(state: dict) -> None:
    state = dict(state)
    state["updated_at"] = _now_iso()
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_allow() -> dict:
    if ALLOW_PATH.exists():
        return json.loads(ALLOW_PATH.read_text(encoding="utf-8"))
    default = {
        "schema_version": 1,
        "idiom_lint": {"integer_value": [], "level_param": [], "pick_object": []},
    }
    ALLOW_PATH.write_text(json.dumps(default, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return default


# ═══════════════════════════════════════════════════════════════════════════
# Check 1 — compile
# ═══════════════════════════════════════════════════════════════════════════


def _roslyn_compile(code: str, version: str) -> tuple[bool, Optional[str]]:
    wrapped = WRAPPER_HEADER + code + WRAPPER_FOOTER
    payload = json.dumps({"code": wrapped, "revitVersion": version}).encode("utf-8")
    req = urllib.request.Request(
        ROSLYN_URL, data=payload, headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=ROSLYN_TIMEOUT) as resp:
            r = json.loads(resp.read().decode("utf-8"))
        ok = bool(r.get("success"))
        return ok, (None if ok else json.dumps(r.get("errors"), ensure_ascii=False)[:800])
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return False, f"ROSLYN_UNREACHABLE: {e}"
    except Exception as e:  # defensive: malformed response etc.
        return False, f"ROSLYN_REQUEST_ERROR: {e}"


def _check_compile(db: dict, *, fast: bool) -> CheckResult:
    """Every recipe compiles on every one of its `compiles_on` Revit versions
    against the live Roslyn compile-service, using the exact wrapper header/
    footer the runtime bridge wraps user code in.

    `--fast`: skip recipes whose `sha256(code)` matches the LAST KNOWN-GOOD
    entry in `data/corpus_ci_state.json` (a prior run that finished with zero
    compile FAILs). New/changed recipes are always compiled. State is
    persisted ONLY when this run's compile check is fully green — a run that
    finds a FAIL never writes state, so the broken recipe is re-checked every
    time until it's fixed (it can never get "stuck" cached as PASS).
    """
    recipes = db["recipes"]
    state = load_state()
    cached = state.get("recipes", {})

    to_check: list[tuple[dict, str]] = []
    n_cached = 0
    for r in recipes:
        sha = _sha256(r.get("code", ""))
        if fast:
            prev = cached.get(r["name"])
            if prev and prev.get("code_sha256") == sha and prev.get("result") == "PASS":
                n_cached += 1
                continue
        to_check.append((r, sha))

    fails: list[tuple[str, dict]] = []
    new_results: dict[str, dict] = {}
    n_calls = 0
    t0 = time.time()
    for r, sha in to_check:
        code = r.get("code", "")
        versions = r.get("compiles_on") or ["2024"]
        per_version_fail = {}
        for v in versions:
            ok, err = _roslyn_compile(code, v)
            n_calls += 1
            if not ok:
                per_version_fail[v] = err
        result = "PASS" if not per_version_fail else "FAIL"
        new_results[r["name"]] = {
            "code_sha256": sha,
            "compiles_on": versions,
            "result": result,
            "checked_at": _now_iso(),
        }
        if per_version_fail:
            fails.append((r["name"], per_version_fail))
    elapsed = time.time() - t0

    status = "FAIL" if fails else "PASS"
    detail = (
        f"{len(recipes)} recipes: {n_cached} cached-pass skipped"
        f"{' (--fast)' if fast else ''}, {len(to_check)} compiled "
        f"({n_calls} Roslyn calls, {elapsed:.1f}s), {len(fails)} FAIL"
    )
    if status == "PASS":
        merged = dict(cached)
        merged.update(new_results)
        state["recipes"] = merged
        save_state(state)

    return CheckResult("compile", status, detail, fails)


# ═══════════════════════════════════════════════════════════════════════════
# Check 2 — gate-verify
# ═══════════════════════════════════════════════════════════════════════════


def _check_gate_verify(db: dict) -> CheckResult:
    """Every recipe's code passes `kukai.security.validation
    .validate_code_safety` — the exact function the live bridge calls
    pre-execution.

    Deliberately forces `KUKAI_WEAK_SANDBOX` OFF for the duration of this
    check regardless of the ambient environment (prod .env currently sets
    it to "1", the operator's live permissive override — see
    `validation.py`'s own docstring). A CI gate that silently no-ops because
    of *today's* runtime toggle is not a real gate: this check exists to
    verify the corpus against the validator's DESIGNED safety posture, which
    must hold even if the live override changes tomorrow.
    """
    prev = os.environ.pop("KUKAI_WEAK_SANDBOX", None)
    try:
        # Import AFTER clearing the env var and inside the guarded block so a
        # module-level cache (there is none today, but this stays correct if
        # one is ever added) can't capture the wrong value.
        from kukai.security.validation import validate_code_safety

        blocked = []
        for r in db["recipes"]:
            violations = validate_code_safety(r.get("code", ""))
            if violations:
                blocked.append((r["name"], violations))
    finally:
        if prev is not None:
            os.environ["KUKAI_WEAK_SANDBOX"] = prev

    status = "FAIL" if blocked else "PASS"
    detail = f"{len(db['recipes'])} recipes checked, {len(blocked)} blocked by validate_code_safety"
    return CheckResult("gate-verify", status, detail, blocked)


# ═══════════════════════════════════════════════════════════════════════════
# Check 3 — prose-lint
# ═══════════════════════════════════════════════════════════════════════════

DRAFT_MARKERS = ["черновик", "TODO", "FIXME", "TODO-reviewer"]
PROSE_TEXT_FIELDS = ["description", "use_when_ru", "explanation_ru"]

_TRUNC_LAST_TOKEN_RE = re.compile(r"(\S+)$")
_TRUNC_SLASH_RE = re.compile(r"/([A-Za-z]{1,4})$")
_TRUNC_PURE_LATIN_RE = re.compile(r"[A-Za-z/]{2,20}")
_TRUNC_INTERNAL_CAPS_RE = re.compile(r"^.[A-Z]")


def _pitfall_truncated(p: str) -> Optional[tuple[str, str]]:
    """Heuristic for a hard-truncated pitfall string (cut mid-word), tuned
    against the historical instance this corpus actually had: recipe #264
    (old numbering, fixed in wave-1 S1) had pitfalls cut at "Floor/Ce" and
    "IColl".

    NOT simply "ends without punctuation" — this corpus's normal style is
    short RU sentences with NO trailing period (verified: ~50/479 pitfalls
    across the current corpus end in a bare Latin word with no punctuation,
    and ALL of them are complete words/sentences, e.g. "...через API.",
    "...RU API" as a normal noun phrase — that naive rule alone was checked
    against the live corpus and produces ~220/479 false positives, i.e. no
    signal). This heuristic requires the trailing token to look like a CUT
    API-identifier specifically: either a slash-joined alternative cut short
    (`Floor/Ce`) or an internal-capitalization break mid-identifier
    (`IColl`, `GetFie`) — verified 0 false positives on the current corpus.
    """
    s = p.rstrip()
    if not s or not s[-1].isalpha():
        return None
    m = _TRUNC_LAST_TOKEN_RE.search(s)
    if not m:
        return None
    tok = m.group(1)
    if len(tok) <= 3 or not _TRUNC_PURE_LATIN_RE.fullmatch(tok):
        return None
    sm = _TRUNC_SLASH_RE.search(tok)
    if sm:
        return ("slash-fragment", tok)
    if _TRUNC_INTERNAL_CAPS_RE.search(tok):
        return ("internal-caps", tok)
    return None


def _check_prose_lint(db: dict) -> CheckResult:
    """Draft markers, empty/missing user-facing prose fields, and
    hard-truncated pitfalls — the "cheap lint" auditor 3 proposed
    (agent_reports.md CORPUS AUDITOR 3, systematic problem #2).

    Does NOT attempt prose<->code API-name consistency (explicitly out of
    scope per the wave-2H brief: "too hard, skip").
    """
    findings: list[tuple[str, list[str]]] = []
    for r in db["recipes"]:
        issues: list[str] = []
        texts = {f: (r.get(f) or "") for f in PROSE_TEXT_FIELDS}
        texts["pitfalls"] = " ".join(p for p in (r.get("pitfalls") or []) if isinstance(p, str))
        for field_name, text in texts.items():
            if not text:
                continue
            low = text.lower()
            for marker in DRAFT_MARKERS:
                if marker.lower() in low:
                    issues.append(f"draft-marker '{marker}' in {field_name}")

        for f in PROSE_TEXT_FIELDS:
            v = r.get(f)
            if v is None or (isinstance(v, str) and not v.strip()):
                issues.append(f"empty/missing {f}")
        if not r.get("pitfalls"):
            issues.append("empty/missing pitfalls")

        for p in r.get("pitfalls") or []:
            if isinstance(p, str):
                res = _pitfall_truncated(p)
                if res:
                    kind, tok = res
                    issues.append(f"pitfall looks truncated ({kind}: '...{tok}')")

        if issues:
            findings.append((r["name"], issues))

    status = "WARN" if findings else "PASS"
    detail = f"{len(db['recipes'])} recipes checked, {len(findings)} with prose issues"
    return CheckResult("prose-lint", status, detail, findings)


# ═══════════════════════════════════════════════════════════════════════════
# Check 4 — idiom-lint
# ═══════════════════════════════════════════════════════════════════════════

# Exact idiom only — word-boundary matched so it does NOT match compound
# enum members that merely CONTAIN the substring (STAIRS_BASE_LEVEL_PARAM,
# FAMILY_TOP_LEVEL_PARAM, ...), which are unrelated, legitimate parameters.
# Verified against the live corpus 2026-07-08: a naive substring scan hit 4
# recipes, only 2 of which (#50, #51 — door/window schedule export) use the
# real bare idiom; the other 2 were FAMILY_*_LEVEL_PARAM / STAIRS_*_LEVEL_PARAM.
_LEVEL_PARAM_RE = re.compile(r"\bBuiltInParameter\.LEVEL_PARAM\b")
_PICKOBJECT_RE = re.compile(r"\bPickObject\s*\(")

# Destructive-fallback advisory: the precise version (WhereElementIsNotElementType
# + doc.Delete/ElementTransformUtils inside an empty-selection-guarded branch)
# is "too clever" per the wave-2H brief — a static regex can't reliably prove
# branch-guarding. This is the deliberately blunter, broader net the brief
# authorizes instead: flag ANY recipe with a destructive/committing operation
# and NO textual sign it resolved its target via selection/id/name lookup.
# This is INTENTIONALLY noisy (it also flags plain "create X from these
# parameters" recipes, which never needed a selection) — it is a report-only
# advisory list for wave-3 human triage, never a FAIL, and not narrowed
# further per the brief's own instruction not to over-engineer it.
_DESTRUCTIVE_RE = re.compile(r"\bdoc\.Delete\s*\(|\.Commit\s*\(")
_TARGET_RESOLUTION_RE = re.compile(
    r"\bSelection\b|\bGetElementIds\b|\.Name\s*==|\.Name\.(?:Equals|Contains|StartsWith)\s*\(|\bLookupParameter\s*\("
)


def _check_idiom_lint(db: dict) -> tuple[CheckResult, CheckResult]:
    """`.IntegerValue` / `BuiltInParameter.LEVEL_PARAM` / `PickObject(` idiom
    bans (each allowlist-exemptible via `data/corpus_ci_allow.json`), plus
    the destructive-fallback advisory list (see block comment above;
    ALWAYS advisory, never promoted by --strict).
    """
    allow = load_allow().get("idiom_lint", {})
    allow_iv = set(allow.get("integer_value", []))
    allow_lp = set(allow.get("level_param", []))
    allow_po = set(allow.get("pick_object", []))

    iv_hits: list[tuple[str, int]] = []
    lp_hits: list[str] = []
    po_hits: list[str] = []
    destructive_advisory: list[str] = []

    for r in db["recipes"]:
        name = r["name"]
        code = r.get("code", "")
        if ".IntegerValue" in code and name not in allow_iv:
            iv_hits.append((name, code.count(".IntegerValue")))
        if _LEVEL_PARAM_RE.search(code) and name not in allow_lp:
            lp_hits.append(name)
        if _PICKOBJECT_RE.search(code) and name not in allow_po:
            po_hits.append(name)
        if _DESTRUCTIVE_RE.search(code) and not _TARGET_RESOLUTION_RE.search(code):
            destructive_advisory.append(name)

    items: list[tuple[str, list]] = []
    if iv_hits:
        items.append(("IntegerValue", iv_hits))
    if lp_hits:
        items.append(("LEVEL_PARAM", lp_hits))
    if po_hits:
        items.append(("PickObject", po_hits))
    status = "WARN" if items else "PASS"
    detail = (
        f"IntegerValue={len(iv_hits)} LEVEL_PARAM={len(lp_hits)} "
        f"PickObject={len(po_hits)} (allowlist-exempt already applied; "
        f"see data/corpus_ci_allow.json)"
    )
    idiom_result = CheckResult("idiom-lint", status, detail, items)

    adv_detail = (
        f"{len(destructive_advisory)}/{len(db['recipes'])} recipes contain "
        f"doc.Delete(/.Commit( with no textual Selection/GetElementIds/"
        f"name-lookup reference — report-only, NEVER fails (see docstring)"
    )
    advisory_result = CheckResult(
        "destructive-fallback-advisory", "ADVISORY", adv_detail, destructive_advisory
    )
    return idiom_result, advisory_result


# ═══════════════════════════════════════════════════════════════════════════
# Check 5 — consistency
# ═══════════════════════════════════════════════════════════════════════════

_DOC2QUERY_ENTRY_RE = re.compile(r"^recipe:\.(.*)$")


def _check_consistency(db: dict) -> tuple[CheckResult, list[str]]:
    """doc2query 1:1 with recipes by name, no duplicate recipe names, corpus
    manifest freshness (`kukai.rag.corpus_manifest.check_manifest`, quick
    mode), and `intent` field coverage (advisory count only — wave-2G's
    concern, does not affect this check's PASS/FAIL).
    """
    recipes = db["recipes"]
    names = [r["name"] for r in recipes]
    problems: list[tuple[str, list]] = []

    dup = {n: c for n, c in Counter(names).items() if c > 1}
    if dup:
        problems.append(("duplicate recipe names", sorted(dup.items())))

    lines = [
        json.loads(line) for line in DOC2QUERY_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    entry_names: set[str] = set()
    malformed: list[str] = []
    for entry in lines:
        m = _DOC2QUERY_ENTRY_RE.match(entry.get("entry_id", ""))
        if m:
            entry_names.add(m.group(1))
        else:
            malformed.append(entry.get("entry_id"))
    missing = sorted(set(names) - entry_names)
    extra = sorted(entry_names - set(names))
    if missing:
        problems.append(("recipes missing a doc2query entry", missing))
    if extra:
        problems.append(("doc2query entries with no matching recipe", extra))
    if malformed:
        problems.append(("doc2query malformed entry_id", malformed))

    try:
        ok, manifest_detail = cm.check_manifest(DATA_DIR, quick=True)
    except FileNotFoundError as e:
        ok, manifest_detail = False, f"manifest absent: {e}"
    if not ok:
        problems.append(("corpus manifest stale/mismatched", [manifest_detail]))

    missing_intent = [r["name"] for r in recipes if not r.get("intent")]

    status = "FAIL" if problems else "PASS"
    detail = (
        f"{len(recipes)} recipes, {len(problems)} consistency problem group(s); "
        f"{len(missing_intent)}/{len(recipes)} missing 'intent' field "
        f"(advisory only, wave-2G concern)"
    )
    return CheckResult("consistency", status, detail, problems), missing_intent


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════

CHECKS = ("compile", "gate-verify", "prose-lint", "idiom-lint", "consistency")


def _print_result_table(results: list[CheckResult]) -> None:
    name_w = max(len(r.name) for r in results) + 2
    print(f"\n{'CHECK':<{name_w}}{'STATUS':<10}DETAIL")
    print("-" * 100)
    for r in results:
        print(f"{r.name:<{name_w}}{r.status:<10}{r.detail}")
    print()


def _print_items(result: CheckResult, *, limit: Optional[int] = None) -> None:
    if not result.items:
        return
    print(f"--- {result.name} ({result.status}): {len(result.items)} item(s) ---")
    shown = result.items if limit is None else result.items[:limit]
    for item in shown:
        print(" -", item)
    if limit is not None and len(result.items) > limit:
        print(f"   ... {len(result.items) - limit} more (see --json output)")
    print()


def _run_all(*, fast: bool) -> tuple[list[CheckResult], CheckResult, list[str]]:
    db = load_db()
    results = [
        _check_compile(db, fast=fast),
        _check_gate_verify(db),
        _check_prose_lint(db),
    ]
    idiom_result, advisory_result = _check_idiom_lint(db)
    results.append(idiom_result)
    consistency_result, missing_intent = _check_consistency(db)
    results.append(consistency_result)
    return results, advisory_result, missing_intent


def _exit_code(results: list[CheckResult], *, strict: bool) -> int:
    for r in results:
        if r.name in FAIL_CLASS and r.status == "FAIL":
            return 1
        if strict and r.name in WARN_CLASS and r.status == "WARN":
            return 1
    return 0


def cmd_ci(args: argparse.Namespace) -> int:
    results, advisory_result, missing_intent = _run_all(fast=args.fast)
    _print_result_table(results)
    for r in results:
        if r.status in ("FAIL", "WARN"):
            _print_items(r, limit=None if args.verbose else 30)
    print(f"--- destructive-fallback-advisory ({advisory_result.status}) ---")
    print(advisory_result.detail)
    if args.verbose:
        for name in advisory_result.items:
            print(" -", name)
    print()

    if args.json:
        payload = {
            "generated_at": _now_iso(),
            "fast": args.fast,
            "strict": args.strict,
            "checks": [r.to_dict() for r in results],
            "destructive_fallback_advisory": advisory_result.to_dict(),
            "missing_intent_field": missing_intent,
        }
        Path(args.json).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {args.json}")

    code = _exit_code(results, strict=args.strict)
    print(f"=== exit code {code} ({'FAIL' if code else 'PASS'}) ===")
    return code


def _cmd_single(check_name: str):
    def _cmd(args: argparse.Namespace) -> int:
        db = load_db()
        if check_name == "compile":
            result = _check_compile(db, fast=args.fast)
            results = [result]
        elif check_name == "gate-verify":
            results = [_check_gate_verify(db)]
        elif check_name == "prose-lint":
            results = [_check_prose_lint(db)]
        elif check_name == "idiom-lint":
            idiom_result, advisory_result = _check_idiom_lint(db)
            results = [idiom_result, advisory_result]
        elif check_name == "consistency":
            result, missing_intent = _check_consistency(db)
            results = [result]
            print(f"(missing 'intent' field: {len(missing_intent)}/{len(db['recipes'])} — advisory)")
        else:  # pragma: no cover - argparse restricts choices
            raise ValueError(check_name)

        _print_result_table(results)
        for r in results:
            _print_items(r)
        strict = getattr(args, "strict", False)
        return _exit_code(results, strict=strict)

    return _cmd


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="corpus_gate.py",
        description="Corpus CI gate (wave-2 batch H) — compile + gate-verify + "
        "prose-lint + idiom-lint + consistency over data/revit_api_db.json.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_ci = sub.add_parser("ci", help="run all 5 checks and print the summary table")
    p_ci.add_argument("--fast", action="store_true", help="compile check: skip sha-unchanged recipes cached PASS in data/corpus_ci_state.json")
    p_ci.add_argument("--strict", action="store_true", help="promote prose-lint/idiom-lint WARN to FAIL (nonzero exit)")
    p_ci.add_argument("--json", metavar="PATH", help="also write full results (incl. all items) to this JSON path")
    p_ci.add_argument("--verbose", action="store_true", help="print full item lists instead of truncating to 30")
    p_ci.set_defaults(func=cmd_ci)

    p_compile = sub.add_parser("compile", help="run only the compile check")
    p_compile.add_argument("--fast", action="store_true")
    p_compile.set_defaults(func=_cmd_single("compile"))

    p_gv = sub.add_parser("gate-verify", help="run only the gate-verify check")
    p_gv.set_defaults(func=_cmd_single("gate-verify"))

    p_prose = sub.add_parser("prose-lint", help="run only the prose-lint check")
    p_prose.add_argument("--strict", action="store_true")
    p_prose.set_defaults(func=_cmd_single("prose-lint"))

    p_idiom = sub.add_parser("idiom-lint", help="run only the idiom-lint check + destructive-fallback advisory")
    p_idiom.add_argument("--strict", action="store_true")
    p_idiom.set_defaults(func=_cmd_single("idiom-lint"))

    p_cons = sub.add_parser("consistency", help="run only the consistency check")
    p_cons.set_defaults(func=_cmd_single("consistency"))

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
