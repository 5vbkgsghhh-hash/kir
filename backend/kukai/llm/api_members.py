"""G2.3 — deterministic repair enrichment from the per-version Revit API surface.

On a CS0117/CS1061/CS0246 compile error, look up the named type's REAL members
in the active knowledge release's ``api_surface/api_surface_{ver}.json``,
built by tools/api-extractor) and produce a precise hint: the actual members,
the closest valid member (fuzzy), and cross-version availability ("X.Value is
2024+, on 2023 use IntegerValue"). No model opt-in — fed straight into the repair
loop. Attacks the dominant prod error class (CS1061+CS0117+CS0246, audit 2026-06-06).
"""
from __future__ import annotations

import difflib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional

from kukai.knowledge.release import current_release

_SURFACE_DIR = current_release().api_surface_root
_VERSIONS = ("2021", "2022", "2023", "2024", "2025", "2026")

_CS_MEMBER = re.compile(
    r"CS(?:0117|1061): '([^']+)' does not contain a definition for '([^']+)'"
)
_CS_TYPE = re.compile(r"CS0246: The type or namespace name '([^']+)'")


@lru_cache(maxsize=8)
def _load(version: str) -> dict:
    p = _SURFACE_DIR / f"api_surface_{version}.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:
        return {}


def _norm_version(v) -> str:
    try:
        y = int(str(v)[:4])
    except (ValueError, TypeError):
        return "2024"
    return str(min(2026, max(2021, y)))


@lru_cache(maxsize=8)
def builtin_category_names(version: str = "2026") -> frozenset:
    """The set of valid ``OST_*`` BuiltInCategory field names for a version.

    Data-driven category resolution: lets query_model accept any real
    BuiltInCategory base-name (e.g. ``DuctCurves`` → ``OST_DuctCurves``) without
    a hand-maintained alias list (the s17 hard-fail). Newest version by default
    (category names are near-stable and the newest is the superset).
    """
    surface = _load(_norm_version(version))
    tk = _find_type(surface, "BuiltInCategory")  # key is fully-qualified
    bic = surface.get(tk) if tk else None
    fields = bic.get("fields") if isinstance(bic, dict) else None
    return frozenset(n for n in (fields or []) if isinstance(n, str) and n.startswith("OST_"))


def _find_type(surface: dict, name: str) -> Optional[str]:
    if name in surface:
        return name
    short = name.rsplit(".", 1)[-1]
    for k in surface:
        if k.rsplit(".", 1)[-1] == short:
            return k
    return None


def _find_types(surface: dict, name: str) -> list:
    """Like `_find_type`, but returns EVERY key matching (exact FQN first,
    then all short-name collisions, e.g. both `Autodesk.Revit.DB.Document`
    and `Autodesk.Revit.Creation.Document` for bare "Document" -- a real,
    unavoidable ambiguity of the bare-name convention frontmatter/prompts
    use everywhere in this codebase (`members_for` has the exact same
    collision, silently resolved by picking whichever sorts first; see
    `method_signatures_for`, which instead tries every collision in order
    and lets "does it actually have the requested method" be the arbiter)."""
    out = []
    if name in surface:
        out.append(name)
    short = name.rsplit(".", 1)[-1]
    for k in surface:
        if k != name and k.rsplit(".", 1)[-1] == short:
            out.append(k)
    return out


def _members(info: dict) -> set:
    return (set(info.get("fields", [])) | set(info.get("methods", []))
            | set(info.get("properties", [])))


def _member_exists(version: str, typ: str, member: str) -> bool:
    s = _load(version)
    tk = _find_type(s, typ)
    return bool(tk) and member in _members(s[tk])


def members_for(namespace: str, name: str, revit_version, limit: int = 40) -> Optional[str]:
    """Real, version-correct members (methods+properties) of a CLASS, formatted
    as a comma list — for generation-time grounding (prevent CS1061). Returns
    None for enums (too many members → stay repair-side) or unknown types
    (caller falls back to the corpus methods)."""
    v = _norm_version(revit_version)
    surface = _load(v)
    if not surface:
        return None
    full = (namespace + "." + name) if namespace else name
    tk = _find_type(surface, full) or _find_type(surface, name)
    if not tk:
        return None
    info = surface[tk]
    if info.get("Enum") or info.get("enum"):
        return None
    mem = sorted(set(info.get("methods", [])) | set(info.get("properties", [])))
    return ", ".join(mem[:limit]) if mem else None


# ---------------------------------------------------------------------------
# REF_GAP fix (2026-07-12, /root/kukai-rag-audit/ab_codegen/REFGAP_FIX_REPORT.md):
# enum VALUES + method SIGNATURES, additive to the members_for() surface
# above. members_for() itself is UNCHANGED (still None for enums, still
# names-only) -- every existing caller (rag_prompt.py's G2 grounding,
# enrich_compile_error's repair hints) sees zero behavior change. These two
# functions are NEW, only called from wiki_query.py's new
# KUKAI_WIKI_APIREF_ENUMS sub-flag path (default off).
#
# Data sources (both additive, neither ever mutates the pre-existing
# api_surface_{v}.json this module already reads):
#   - enum values: SAME api_surface_{v}.json this module already loads (the
#     "fields" list on an Enum-typed entry -- already there, members_for()
#     just chose not to surface it). Full, version-correct, authoritative
#     (System.Reflection.Metadata over the real RevitAPI.dll).
#   - method signatures: NEW sidecar api_signatures_{v}.json (one per
#     version, tools/api-extractor/extract_method_signatures.py), parsed
#     from Autodesk's own RevitAPI[UI].xml doc-comment member IDs, which
#     encode the FULL per-overload parameter-TYPE list
#     ("M:Ns.Class.Method(Ns.T1,Ns.T2)") -- the one thing name-only
#     api_surface_*.json structurally cannot answer (it dedupes all
#     overloads of a method down to one bare name).
# ---------------------------------------------------------------------------
_SIG_DIR = _SURFACE_DIR  # same data/api_surface/ dir, sidecar filename
_SMALL_ENUM_MAX = 40      # <= this many real values -> surface them all
_ENUM_VALUE_CAP = 20       # hard cap on values shown for a LARGE enum
_ENUM_CHAR_CAP = 400        # hard cap on rendered chars for one enum's values
_SIG_OVERLOAD_CAP = 3        # max overloads shown for one method
_SIG_CHAR_CAP = 300           # hard cap on rendered chars for one method's signature(s)

_WORD_RE = re.compile(r"[a-zа-яё0-9]+")


@lru_cache(maxsize=8)
def _load_signatures(version: str) -> dict:
    p = _SIG_DIR / f"api_signatures_{version}.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:
        return {}


@lru_cache(maxsize=1)
def _load_enum_ru_keywords() -> dict:
    """enum FIELD NAME (e.g. "ALL_MODEL_MARK") -> RU keyword tokens, sourced
    from the compact generated ``enum_keywords_ru.json`` asset. This is NOT
    version-specific and NOT a source of truth for existence: it is only a
    relevance signal. Every candidate is still checked against the real,
    version-correct API surface before being surfaced."""
    path = _SURFACE_DIR / "enum_keywords_ru.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {}
        return {
            str(enum_name): sorted({str(token).lower() for token in tokens if token})
            for enum_name, tokens in raw.items()
            if isinstance(tokens, list)
        }
    except Exception:
        return {}


def _english_tokens(field_name: str) -> set:
    """'ROOM_TAG_ORIENTATION_PARAM' -> {'room','tag','orientation','param'}."""
    return {p.lower() for p in re.split(r"[_\W]+", field_name) if p}


def enum_values_for(
    namespace: str, name: str, revit_version, query_tokens=None,
    value_cap: int = _ENUM_VALUE_CAP, char_cap: int = _ENUM_CHAR_CAP,
    require_relevance: bool = False,
) -> Optional[list]:
    """Real, version-correct enum MEMBER VALUES -- the surface members_for()
    deliberately excludes ("too many members -> stay repair-side"). Returns
    None (never fabricates) when: unknown version/type, the type isn't an
    enum in this version's surface, or (for a LARGE enum, or any enum when
    `require_relevance`) no relevance signal picks out a non-empty bounded
    subset.

    Small enums (<= _SMALL_ENUM_MAX real values, e.g. ViewType/
    ViewDiscipline/ViewDetailLevel) are returned WHOLE, sorted -- a partial
    list of a 25-value enum is worse than the full one -- UNLESS
    `require_relevance` (default False): a page's own explicitly-curated
    frontmatter `api_classes` entry has already declared this enum relevant
    by naming it, so no further gating applies; but wiki_query's
    `_UNIVERSAL_ENUM_WATCHLIST` checks (BuiltInParameter/BuiltInCategory/
    ViewType on EVERY page regardless of frontmatter) pass
    `require_relevance=True` so a small watchlist enum doesn't unconditionally
    render on every unrelated page -- it still must earn its slot via the
    same seed-token logic as a large enum.

    Large enums (BuiltInParameter ~3.6k, BuiltInCategory ~800) are NEVER
    dumped whole. Two independent relevance signals seed a bounded subset:
      1. RU: `_load_enum_ru_keywords()` -- a curated field's RU keywords
         overlap `query_tokens`.
      2. EN: the real field's own `_english_tokens()` overlap `query_tokens`
         directly (fires for English/mixed-language queries).
    Every seed is a REAL field of THIS version's surface already (the loop
    below only ever iterates `fields`, never the keyword index) --
    version-correctness and the never-invent contract both fall out of that
    for free. Each seed also pulls in sibling real values sharing its
    "PREFIX_" (name up to the last "_") -- e.g. a "марка" hit on
    ROOM_TAG_ORIENTATION_PARAM also surfaces the other real ROOM_TAG_*
    fields, which is exactly the grounding an invented ROOM_TAG_ROOM_ID
    needs: the model sees the real ROOM_TAG_* family and that _ROOM_ID isn't
    in it. Bounded to `value_cap` values / `char_cap` chars; zero seeds on a
    large enum -> None (never dump the other ~3500)."""
    v = _norm_version(revit_version)
    surface = _load(v)
    if not surface:
        return None
    full = (namespace + "." + name) if namespace else name
    tk = _find_type(surface, full) or _find_type(surface, name)
    if not tk:
        return None
    info = surface[tk]
    if not (info.get("Enum") or info.get("enum")):
        return None
    fields = sorted(f for f in (info.get("fields") or []) if isinstance(f, str))
    if not fields:
        return None

    if len(fields) <= _SMALL_ENUM_MAX and not require_relevance:
        out: list = []
        total = 0
        for f in fields:
            total += len(f) + 2
            if out and total > char_cap:
                break
            out.append(f)
        return out or None

    qt = set(query_tokens) if query_tokens else set()
    if not qt:
        return None  # large enum, no relevance signal at all -> never dump

    ru_kw = _load_enum_ru_keywords()
    seeds: list = []
    for f in fields:
        kw = ru_kw.get(f)
        if kw and (set(kw) & qt):
            seeds.append(f)
        elif _english_tokens(f) & qt:
            seeds.append(f)
    if not seeds:
        return None

    picked: list = []
    picked_set: set = set()
    for s in seeds:
        if len(picked) >= value_cap:
            break
        if s not in picked_set:
            picked.append(s)
            picked_set.add(s)
        prefix = s.rsplit("_", 1)[0] if "_" in s else None
        if prefix:
            for sib in fields:
                if len(picked) >= value_cap:
                    break
                if sib not in picked_set and sib.startswith(prefix + "_"):
                    picked.append(sib)
                    picked_set.add(sib)

    out = []
    total = 0
    for f in picked[:value_cap]:
        total += len(f) + 2
        if out and total > char_cap:
            break
        out.append(f)
    return out or None


def method_signatures_for(
    namespace: str, class_name: str, method_name: str, revit_version,
    overload_cap: int = _SIG_OVERLOAD_CAP, char_cap: int = _SIG_CHAR_CAP,
) -> Optional[list]:
    """Real, version-correct parameter-TYPE signature(s) for ONE named
    method of ONE named class (e.g. class_name="Document" (or
    "Creation.Document"), method_name="NewZone" -> ["(Level, Phase)"]).
    Source: `api_signatures_{v}.json` (tools/api-extractor/
    extract_method_signatures.py, parsed from Autodesk's own RevitAPI[UI].xml
    doc-comment member IDs) -- NEVER the name-only api_surface_{v}.json,
    which collapses every overload of a method down to one bare name and
    structurally cannot answer "how many args does this take".

    Returns None (never invents) when: unknown version, the class isn't in
    the sidecar, or the named method isn't found on it -- caller (wiki_query
    .build_api_reference) is expected to only ask about a method it already
    has independent reason to believe exists (e.g. named in a page's
    frontmatter `api_classes` as "Class.Method" or in a recipe's own code),
    same "lookup is the arbiter" discipline as _candidate_base_names.
    Bounded to `overload_cap` overloads / `char_cap` chars -- callers pass
    ONE specific method (never "all methods of a class"), so this is
    inherently narrow; the caps only guard a pathological many-overload
    method (e.g. Document.Export has 10+).

    Bare class names collide (e.g. "Document" is both
    `Autodesk.Revit.DB.Document` and `Autodesk.Revit.Creation.Document`,
    which owns a disjoint method set incl. NewZone) -- every FQN sharing the
    bare name is tried (`_find_types`) and the first one that actually HAS
    `method_name` wins; a `namespace` hint (when the caller has one) narrows
    straight to the exact FQN instead of guessing."""
    v = _norm_version(revit_version)
    sigs = _load_signatures(v)
    if not sigs:
        return None
    full = (namespace + "." + class_name) if namespace else class_name
    tk = None
    overloads = None
    for cand in (_find_types(sigs, full) or _find_types(sigs, class_name)):
        ov = sigs[cand].get(method_name)
        if ov:
            tk, overloads = cand, ov
            break
    if not overloads:
        return None
    out: list = []
    total = 0
    for sig in overloads[:overload_cap]:
        total += len(sig) + 2
        if out and total > char_cap:
            break
        out.append(sig)
    return out or None


def enrich_compile_error(error_text: str, revit_version) -> str:
    """Return a deterministic API-fact hint for member/type errors, or ''."""
    if not error_text:
        return ""
    v = _norm_version(revit_version)
    surface = _load(v)
    if not surface:
        return ""
    hints: list[str] = []
    seen: set = set()

    for m in _CS_MEMBER.finditer(error_text):
        typ, mem = m.group(1), m.group(2)
        if (typ, mem) in seen:
            continue
        seen.add((typ, mem))
        tk = _find_type(surface, typ)
        if not tk:
            continue
        info = surface[tk]
        members = _members(info)
        close = difflib.get_close_matches(mem, members, n=4, cutoff=0.6)
        other = [vv for vv in _VERSIONS if vv != v and _member_exists(vv, typ, mem)]
        line = f"- `{typ}.{mem}` НЕ существует в Revit {v}."
        if other:
            line += f" Есть в {', '.join(other)} (другая версия API)."
        if close:
            line += f" Возможно ты имел в виду: {', '.join(close)}."
        elif info.get("Enum") or info.get("enum"):
            line += " Это enum — используй точное имя существующего члена."
        hints.append(line)

    for m in _CS_TYPE.finditer(error_text):
        typ = m.group(1)
        if typ in seen:
            continue
        seen.add(typ)
        if _find_type(surface, typ):
            continue  # type exists in this version → not the cause
        other = [vv for vv in _VERSIONS if vv != v and _find_type(_load(vv), typ)]
        if other:
            hints.append(f"- Тип `{typ}` отсутствует в Revit {v} (есть в {', '.join(other)} "
                         f"— другая версия). Используй аналог для {v}.")

    if not hints:
        return ""
    return (f"## РЕАЛЬНЫЙ API Revit {v} (исправь строго по этим фактам):\n"
            + "\n".join(hints[:8]))
