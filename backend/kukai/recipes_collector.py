"""Verified-Recipes Collector — auto-build RAG corpus from production successes.

When a user query → generated code → executed successfully on the Bridge in
real Revit, we capture the (query, code, intent, version) tuple to an
ISOLATED SQLite database. The corpus grows automatically as users use the
product.

Design contract (per user direction 2026-05-11):
  - Separate DB file: backend/data/verified_recipes.db
  - Does NOT touch the main RAG index. Promotion into the corpus happens
    through the QUALITY gate (plan 019): cluster → cross-compile ×6 → promote
    clusters with >=K independent successes via
    scripts/verified_recipes_promote.py, then merge through the one door
    scripts/mint_campaign.py merge-new-recipes (016, IRON 5). The old
    2000-row COUNT gate (scripts/verified_recipes_merge.py) is superseded.
  - Privacy: PII sanitizer scrubs project paths, emails, phone numbers,
    Russian names (best-effort) before writing.
  - Feature-flagged via KUKAI_COLLECT_VERIFIED_RECIPES (default ON since it
    is fully isolated and cheap — disable only if PII concerns).
  - Best-effort: any failure here MUST NOT break the main code path.
  - Capture quality gate (plan 019): junk/continuation utterances are
    rejected at write time via assess_query_quality() — the SAME predicate
    that gates historical promotion (one predicate, two doors). The fallback
    junk lexicon lives in DATA (data/capture_filters.json), not code, so the
    semantic judgment (intent == "converse") comes from the model and the
    fallback values come from operator-editable data.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default DB location — overridable via env for tests / dev.
_DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "verified_recipes.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS verified_recipes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    session_hash TEXT,
    query_ru TEXT NOT NULL,
    query_en TEXT,
    code TEXT NOT NULL,
    code_hash TEXT NOT NULL,
    code_length INTEGER NOT NULL,
    intent TEXT,
    complexity TEXT,
    domain TEXT,
    primary_class TEXT,
    revit_version TEXT,
    exec_time_ms INTEGER DEFAULT 0,
    n_repairs INTEGER DEFAULT 0,
    query_id TEXT,               -- plan 019: join key to rag_retrieval telemetry
    retrieval_keys TEXT,         -- plan 019: top-10 retrieved entry keys (JSON)
    capture_v INTEGER DEFAULT 1, -- plan 019: capture schema version (2 = post-fix)
    UNIQUE(code_hash)            -- write-time dedup; same code never stored twice
);

CREATE INDEX IF NOT EXISTS idx_vr_timestamp ON verified_recipes(timestamp);
CREATE INDEX IF NOT EXISTS idx_vr_intent ON verified_recipes(intent);
CREATE INDEX IF NOT EXISTS idx_vr_primary_class ON verified_recipes(primary_class);
"""

# Per-process lock — SQLite handles concurrent writers fine but we add a lock
# to dedupe-by-hash within a single process burst (e.g., user reruns same query).
_db_lock = threading.Lock()


# ---------------------------------------------------------------------------
# PII sanitizer
# ---------------------------------------------------------------------------

# Russian-looking proper nouns (Capitalized followed by Capitalized — "Иван Петров")
# This is a HEURISTIC — over-redacts safe text like "Wall Foundation" but is
# safer than under-redacting names. The downstream merge step does manual review.
_PII_NAME_RU = re.compile(r"\b[А-ЯЁ][а-яё]{1,15}\s+[А-ЯЁ][а-яё]{1,15}\b")
_PII_EMAIL = re.compile(r"[a-zA-Z0-9._+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,6}")
_PII_PHONE = re.compile(r"\+?\d{1,3}[\s\-]?\(?\d{2,4}\)?[\s\-]?\d{2,4}[\s\-]?\d{2,4}")
_PII_PATH_WIN = re.compile(r"[A-Z]:\\Users\\[^\\]+\\")  # C:\Users\Иван\
_PII_PATH_NIX = re.compile(r"/home/[^/]+/")
_PII_GUID = re.compile(r"\{?[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\}?",
                        re.IGNORECASE)
_PII_PROJ_NUMBER = re.compile(r"\b(?:проект|project|проект-|p-)\s*[№#]?\s*\d{2,6}\b",
                                re.IGNORECASE)


def sanitize_pii(text: str) -> str:
    """Best-effort PII redaction. Returns redacted text.

    Categories scrubbed:
      - Russian-looking names (PII_NAME_RU heuristic — over-redacts but safe)
      - Emails, phone numbers
      - Windows/Linux path with username
      - GUIDs
      - Project numbers
    """
    if not text:
        return text
    s = text
    # Order matters: GUID before PHONE (phone regex would greedy-eat GUID
    # digit groups). EMAIL before path (paths may contain @).
    s = _PII_EMAIL.sub("<EMAIL>", s)
    s = _PII_GUID.sub("<GUID>", s)
    s = _PII_PHONE.sub("<PHONE>", s)
    s = _PII_PATH_WIN.sub(r"C:\\Users\\<USER>\\", s)
    s = _PII_PATH_NIX.sub("/home/<USER>/", s)
    s = _PII_PROJ_NUMBER.sub("<PROJECT_NUM>", s)
    # Run name redaction LAST (other rules may have produced ALL_CAPS markers)
    s = _PII_NAME_RU.sub("<NAME>", s)
    return s


# ---------------------------------------------------------------------------
# Capture quality gate (plan 019) — one predicate, two doors.
#
# This predicate gates BOTH live capture (record_verified_recipe, write time)
# and historical promotion (verified_recipes_promote.py filter step). The
# semantic junk judgment is intent == "converse" — made by whatever LLM runs
# the IntentClassifier, never by a hardcoded word list. The fallback lexicon
# (needed while prod runs KUKAI_AGENT_INTENT=0 so intent is NULL) lives in a
# DATA file, exact-match on normalized strings, operator-extendable.
# ---------------------------------------------------------------------------

# Built-in defaults — used when data/capture_filters.json is missing/corrupt
# (the never-raises contract extends to config loading). Mirror the seed file.
_DEFAULT_CAPTURE_FILTERS: dict[str, Any] = {
    "version": 1,
    "min_query_chars": 15,
    "reject_intents": ["converse"],
    "junk_exact": [
        "продолжаем", "продолажем", "продолжай", "продолжить", "дальше",
        "добиваем", "давай", "да", "ок", "окей", "ага", "хорошо", "поехали",
        "делаем", "делаем!", "сделай", "подтверждаю", "подтверждаю.",
        "ну что там", "ты как", "не получилось", "не работает", "открой",
        "выдели их", "анализ модели", "amalda bajar", "go", "yes", "continue",
    ],
    "junk_substrings": [
        "[continue from where you stopped",
        "[system_auto_greet]",
    ],
}

_CAPTURE_FILTERS_PATH = Path(__file__).resolve().parent.parent / "data" / "capture_filters.json"
# Module-level cache; a sentinel distinguishes "not loaded" from a loaded value.
_capture_filters_cache: dict[str, Any] | None = None


def _capture_filters_file() -> Path:
    """Resolve the filters file path (overridable via env for tests)."""
    override = os.environ.get("KUKAI_CAPTURE_FILTERS")
    return Path(override) if override else _CAPTURE_FILTERS_PATH


def _load_capture_filters(*, force: bool = False) -> dict[str, Any]:
    """Load the junk lexicon once (cached). Falls back to built-in defaults on
    any error — config loading must never raise into the hot path."""
    global _capture_filters_cache
    if _capture_filters_cache is not None and not force:
        return _capture_filters_cache
    data = dict(_DEFAULT_CAPTURE_FILTERS)
    try:
        path = _capture_filters_file()
        if path.exists():
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                # Merge over defaults so a partial/edited file is still safe.
                for k in ("min_query_chars", "reject_intents", "junk_exact", "junk_substrings", "version"):
                    if k in loaded:
                        data[k] = loaded[k]
    except Exception as e:  # noqa: BLE001 — never raise on config load
        logger.debug("capture filters load failed; using defaults (non-fatal): %s", e)
        data = dict(_DEFAULT_CAPTURE_FILTERS)
    _capture_filters_cache = data
    return data


_QUOTE_CHARS = "\"'«»“”‘’`"
_TRAILING_PUNCT = ".!?…)…"


def _normalize_query(q: str) -> str:
    """Casefold, collapse whitespace, strip surrounding quotes and trailing
    punctuation. Used for both junk-match and clustering (one normalizer)."""
    if not q:
        return ""
    s = str(q).strip()
    s = s.strip(_QUOTE_CHARS).strip()
    s = re.sub(r"\s+", " ", s)
    s = s.casefold()
    s = s.rstrip(_TRAILING_PUNCT).strip()
    return s


def assess_query_quality(query_ru: str, intent: str | None = None) -> tuple[bool, str]:
    """Decide whether a (query, intent) pair is worth capturing/promoting.

    Returns (keep: bool, reason: str). The shared predicate (plan 019):
      - (False, "short")        — normalized query shorter than min_query_chars
      - (False, "converse")     — intent in reject_intents (the model's judgment)
      - (False, "junk_lexicon") — exact junk match or any junk-substring hit
      - (True,  "ok")           — otherwise

    Never raises (best-effort config load + pure-Python checks).
    """
    try:
        filt = _load_capture_filters()
        norm = _normalize_query(query_ru)
        # 1) Semantic judgment (from the model) — strongest signal.
        reject_intents = {str(i).casefold() for i in filt.get("reject_intents", [])}
        if intent and str(intent).casefold() in reject_intents:
            return (False, "converse")
        # 2) Data-driven junk lexicon. Checked BEFORE the length floor so an
        #    explicitly-listed junk utterance is attributed to the lexicon
        #    (the disclosure bucket the operator curates), not lumped into
        #    "short". A genuinely short, non-listed query falls through to (3).
        junk_exact = {_normalize_query(j) for j in filt.get("junk_exact", [])}
        if norm in junk_exact:
            return (False, "junk_lexicon")
        raw_cf = str(query_ru or "").casefold()
        for sub in filt.get("junk_substrings", []):
            if str(sub).casefold() in raw_cf:
                return (False, "junk_lexicon")
        # 3) Length floor — too short to be a task description.
        min_chars = int(filt.get("min_query_chars", 15))
        if len(norm) < min_chars:
            return (False, "short")
        return (True, "ok")
    except Exception as e:  # noqa: BLE001 — predicate must never raise
        logger.debug("assess_query_quality failed; defaulting to keep (non-fatal): %s", e)
        return (True, "ok")


# Process-level capture disclosure (IRON 10) — counts every write decision.
# Surfaced by count_recipes() → verified_recipes_stats.py for free.
CAPTURE_STATS: dict[str, int] = {
    "recorded": 0,
    "rejected_short": 0,
    "rejected_converse": 0,
    "rejected_junk_lexicon": 0,
    "rejected_dup": 0,
    "rejected_size": 0,
}


# ---------------------------------------------------------------------------
# Primary-class extraction (best-effort regex)
# ---------------------------------------------------------------------------

_CLASS_USAGE_RE = re.compile(
    r"\b(Wall|Floor|Roof|Ceiling|Beam|Column|Door|Window|Stairs|Ramp|"
    r"Level|Grid|Room|Area|Space|FamilyInstance|FamilySymbol|"
    r"ViewSchedule|ScheduleSheetInstance|ViewSheet|View3D|ViewPlan|"
    r"Element|ElementId|ElementType|Parameter|BuiltInParameter|"
    r"FilteredElementCollector|Transaction|Document|"
    r"Toposolid|TopographySurface|FilledRegion|DetailLine|"
    r"Pipe|Duct|Conduit|CableTray|MEPSystem|"
    r"IndependentTag|TextNote|Dimension|"
    r"Reference|ReferencePlane|ReferencePoint|"
    r"ImportInstance|RevitLinkInstance|RevitLinkType)\b"
)


def extract_primary_class(code: str) -> str | None:
    """Find the most-mentioned Revit class in the code. Returns name or None."""
    if not code:
        return None
    matches = _CLASS_USAGE_RE.findall(code)
    if not matches:
        return None
    # Most-frequent class wins
    counts: dict[str, int] = {}
    for m in matches:
        counts[m] = counts.get(m, 0) + 1
    return max(counts.items(), key=lambda kv: kv[1])[0]


# ---------------------------------------------------------------------------
# DB plumbing
# ---------------------------------------------------------------------------


def _get_db_path() -> Path:
    """Resolve DB path from env or default. Creates parent dir."""
    path_str = os.environ.get("KUKAI_VERIFIED_RECIPES_DB", "")
    path = Path(path_str) if path_str else _DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


# Columns added after the original 15-column schema (plan 019). CREATE TABLE
# IF NOT EXISTS will NOT add columns to a pre-existing DB, so migrate explicitly.
_MIGRATION_COLUMNS: tuple[tuple[str, str], ...] = (
    ("query_id", "TEXT"),
    ("retrieval_keys", "TEXT"),
    ("capture_v", "INTEGER DEFAULT 1"),
    # Corpus-integrity gate (KUKAI_RECIPE_WITNESS, 2026-07-07): the witnessed
    # expects-verdict at capture time ("pass"/"unverifiable"/None...). NULL for
    # every pre-gate row and every flag-OFF write, so promotion/federation can
    # require a witnessed-pass recipe without touching legacy rows.
    ("witness_verdict", "TEXT"),
)


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    # Idempotent column migration for DBs created before plan 019.
    existing = {row[1] for row in conn.execute("PRAGMA table_info(verified_recipes)")}
    for col, decl in _MIGRATION_COLUMNS:
        if col not in existing:
            conn.execute(f"ALTER TABLE verified_recipes ADD COLUMN {col} {decl}")
    conn.commit()


def _code_hash(code: str) -> str:
    """Stable hash for dedup. Normalize whitespace + lowercase identifiers."""
    # Conservative dedup: collapse whitespace, then SHA-256.
    normalized = re.sub(r"\s+", " ", code).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


def _is_enabled() -> bool:
    """Default ON. Set KUKAI_COLLECT_VERIFIED_RECIPES=0 to disable."""
    return os.environ.get("KUKAI_COLLECT_VERIFIED_RECIPES", "1") != "0"


def recipe_witness_enabled() -> bool:
    """Corpus-integrity gate flag (KUKAI_RECIPE_WITNESS), read at call time.

    Default OFF ⇒ byte-identical legacy capture (a recipe is stored whenever the
    execute did not error) AND no witness_verdict is written. ON ⇒ the pipeline
    refuses to store a recipe whose DECLARED expects-contract was witnessed NOT
    met (verdict fail/partial), and stamps the witnessed verdict on the row.
    """
    return os.environ.get("KUKAI_RECIPE_WITNESS", "0") == "1"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def record_verified_recipe(
    *,
    query_ru: str,
    code: str,
    query_en: str | None = None,
    intent_metadata: dict | None = None,
    revit_version: str | None = None,
    session_hash: str | None = None,
    exec_time_ms: int = 0,
    n_repairs: int = 0,
    query_id: str | None = None,
    retrieval_keys: list[str] | None = None,
    session_id: str | None = None,
    witness_verdict: str | None = None,
) -> bool:
    """Persist a successful (query, code) pair. Returns True on insert.

    Best-effort: any exception is logged and swallowed. Never raises.
    No-op when KUKAI_COLLECT_VERIFIED_RECIPES=0 or required fields missing.

    New writes set ``capture_v = 2`` and pass the capture quality gate
    (``assess_query_quality``) BEFORE any DB work — junk/continuation
    utterances and converse-intent turns are counted and dropped (plan 019).
    ``query_id``/``retrieval_keys`` join the row to the retrieval telemetry;
    ``session_id`` is hashed HERE (privacy logic stays in this module) when
    ``session_hash`` is not given.
    """
    if not _is_enabled():
        return False
    if not query_ru or not code:
        return False

    # Capture quality gate (plan 019) — BEFORE any DB work. One predicate,
    # two doors (the promotion filter imports this same function).
    keep, reason = assess_query_quality(query_ru, (intent_metadata or {}).get("intent"))
    if not keep:
        if reason == "short":
            CAPTURE_STATS["rejected_short"] += 1
        elif reason == "converse":
            CAPTURE_STATS["rejected_converse"] += 1
        else:
            CAPTURE_STATS["rejected_junk_lexicon"] += 1
        return False

    # Reject trivial code (likely doesn't accomplish anything useful)
    if len(code.strip()) < 30:
        CAPTURE_STATS["rejected_size"] += 1
        return False
    # Reject very large code (likely contains noise / paste)
    if len(code) > 4000:
        CAPTURE_STATS["rejected_size"] += 1
        return False

    try:
        sanitized_query_ru = sanitize_pii(query_ru)[:1000]
        sanitized_query_en = sanitize_pii(query_en or "")[:1000] if query_en else None
        sanitized_code = sanitize_pii(code)[:4000]
        intent = (intent_metadata or {}).get("intent")
        complexity = (intent_metadata or {}).get("complexity")
        domain = (intent_metadata or {}).get("domain")
        primary_class = extract_primary_class(sanitized_code)
        h = _code_hash(sanitized_code)

        # Privacy hashing lives HERE (the module that owns PII). Derive
        # session_hash from session_id when an explicit hash was not supplied.
        eff_session_hash = session_hash
        if eff_session_hash is None and session_id:
            eff_session_hash = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]

        # retrieval_keys → compact JSON, capped at 10 keys.
        keys_json: str | None = None
        if retrieval_keys:
            keys_json = json.dumps(list(retrieval_keys)[:10], ensure_ascii=False)

        with _db_lock:
            conn = sqlite3.connect(str(_get_db_path()), timeout=2.0)
            try:
                _ensure_schema(conn)
                try:
                    conn.execute(
                        """INSERT INTO verified_recipes
                           (session_hash, query_ru, query_en, code, code_hash,
                            code_length, intent, complexity, domain,
                            primary_class, revit_version, exec_time_ms, n_repairs,
                            query_id, retrieval_keys, capture_v, witness_verdict)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            eff_session_hash, sanitized_query_ru, sanitized_query_en,
                            sanitized_code, h, len(sanitized_code), intent,
                            complexity, domain, primary_class, revit_version,
                            exec_time_ms, n_repairs,
                            query_id, keys_json, 2, witness_verdict,
                        ),
                    )
                    conn.commit()
                    CAPTURE_STATS["recorded"] += 1
                    return True
                except sqlite3.IntegrityError:
                    # UNIQUE(code_hash) — duplicate, silently skip
                    CAPTURE_STATS["rejected_dup"] += 1
                    return False
            finally:
                conn.close()
    except Exception as e:  # noqa: BLE001 — best-effort, never block main flow
        logger.debug("verified-recipe record failed (non-fatal): %s", e)
        return False


def count_recipes() -> dict[str, Any]:
    """Quick stats for monitoring. Returns counts. Safe to call always."""
    try:
        conn = sqlite3.connect(str(_get_db_path()), timeout=2.0)
        try:
            _ensure_schema(conn)
            total = conn.execute("SELECT COUNT(*) FROM verified_recipes").fetchone()[0]
            by_intent = dict(
                conn.execute(
                    "SELECT intent, COUNT(*) FROM verified_recipes "
                    "WHERE intent IS NOT NULL GROUP BY intent"
                ).fetchall()
            )
            by_class = dict(
                conn.execute(
                    "SELECT primary_class, COUNT(*) FROM verified_recipes "
                    "WHERE primary_class IS NOT NULL "
                    "GROUP BY primary_class ORDER BY COUNT(*) DESC LIMIT 20"
                ).fetchall()
            )
            # plan 019 disclosure (IRON 10): feedstock-quality fields.
            null_intent = conn.execute(
                "SELECT COUNT(*) FROM verified_recipes WHERE intent IS NULL"
            ).fetchone()[0]
            by_capture_v = dict(
                conn.execute(
                    "SELECT capture_v, COUNT(*) FROM verified_recipes "
                    "GROUP BY capture_v"
                ).fetchall()
            )
            return {
                "total": total,
                "by_intent": by_intent,
                "top_20_classes": by_class,
                "null_intent": null_intent,
                "by_capture_v": by_capture_v,
                "capture_stats": dict(CAPTURE_STATS),
                "db_path": str(_get_db_path()),
            }
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001
        return {"error": str(e), "db_path": str(_get_db_path())}
