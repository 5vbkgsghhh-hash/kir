"""Everything Autodesk documents about how its API refuses — one place to ask.

We lost 2 846 groups out of 2 941 in EVERY model, for years, to one faceless
line: "group read failed: InvalidOperationException".  The reason had been
written down all along -- not by us anywhere, and by Autodesk exactly -- in a
file already sitting on this disk:

    P:Autodesk.Revit.DB.LocationPoint.Rotation
    "This property is not supported for some elements supporting LocationPoints,
     such as AssemblyInstances, Groups, ModelText, Room, and SpotDimensions."

Nobody asked, because asking had no address.  RevitAPI.xml is 10-12 MB per
version, six versions of it, and no human opens that to check one property.
This tool gives the question an address: for every documented member of the
API, which exceptions Autodesk documents, under WHICH CONDITION, in WHICH
VERSIONS.

Three things this index refuses to lose:

  * The wording.  A condition paraphrased is a condition half-known -- "such as
    AssemblyInstances, Groups, ModelText, Room" IS the value of that sentence,
    and no summary of it would have saved the groups.  Text here is Autodesk's,
    verbatim; the only edit is folding the line breaks their XML pretty-printer
    inserted mid-sentence.
  * The rare shape.  The group trap is documented with <throws>, a tag used 8
    times in a file that uses <exception> 10 300 times.  An indexer reading
    only the common tag would have reproduced the original blindness exactly,
    and reported a confident 10 300 while missing the one member that mattered.
    Both tags are read, and which one carried the fact is kept.
  * The version.  We ship one codebase against six Revits.  A member that
    appears only in 2024, a member gone after 2023, and a condition ADDED to a
    member that already existed are not footnotes -- they are the shape of the
    next bug.  Members are merged across versions by identity, so drift and
    removal fall out of the data instead of needing to be hunted for.

Drift is compared on a fingerprint, not on the bytes, and that is deliberate:
in 2022 Autodesk recased "A non-optional argument was NULL" to "...was null"
across the whole API.  Compared byte-wise that is 3 600 members "changed" and
the twenty real changes are buried under it.  Compared on fingerprint it is
what it is -- cosmetic -- and stays out of the way while both spellings remain
stored verbatim.

The index is facts only: what Autodesk wrote, and where.  It draws no
conclusions about our code.  Reading it against our own emissions is a separate
tool (api_trap_audit.py), deliberately separate so the two never blur.

    python tools/api_trap_index.py build
    python tools/api_trap_index.py member LocationPoint.Rotation
    python tools/api_trap_index.py type Group
    python tools/api_trap_index.py exception InvalidOperationException
    python tools/api_trap_index.py phrase "is not supported"
    python tools/api_trap_index.py drift
    python tools/api_trap_index.py versions --new-in 2024 --removed
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import sqlite3
import sys
import time
from typing import Iterator

try:  # house preference; these XMLs are local and trusted, so a fallback is ok
    from defusedxml.ElementTree import fromstring as _xml_fromstring
except Exception:  # pragma: no cover - only when defusedxml is absent
    from xml.etree.ElementTree import fromstring as _xml_fromstring

SCHEMA_VERSION = "kir.api_trap_index/1"

VERSIONS = ("2021", "2022", "2023", "2024", "2025", "2026")

# Where the six shipped documentation sets live.  2025 and 2026 moved to
# net8.0 while the older three stayed on net48, so the framework is discovered
# rather than hard-coded per version -- a seventh Revit should land here
# without an edit.  Override with --docs or KIR_REVIT_DOCS.
NUGET_ROOT = pathlib.Path(os.environ.get(
    "KIR_REVIT_DOCS",
    str(pathlib.Path.home() / ".nuget" / "packages"
        / "revit_all_main_versions_api_x64")))
FRAMEWORKS = ("net48", "net8.0")

DEFAULT_DB = (pathlib.Path(__file__).resolve().parent.parent
              / "data" / "api_traps" / "revit_api_traps.sqlite")

# Phrases that hide a precondition inside prose which otherwise reads like
# description.  This is not a taxonomy of the API -- it is the list of sentence
# shapes an author skims past.  "is not supported" is the one that cost us the
# groups; the rest earn their place the same way.  Any other phrase is
# searchable directly via `phrase`, this list only drives the pre-flagging.
MARKERS = (
    "is not supported",
    "are not supported",
    "not supported for",
    "only valid",
    "only supported",
    "must be",
    "will throw",
    "cannot be",
    "is not permitted",
    "is not allowed",
    "read-only",
    "does not apply",
    "regenerate",
    "has no effect",
    "is required",
    "unless",
)

# The documentation body is pretty-printed: one sentence wraps across lines
# with leading indentation.  Folding that back is not paraphrase -- no word is
# added, removed or reordered -- and without it every quote carries stray
# newlines that break both reading and search.
_WS = re.compile(r"\s+")


def _fold(text: str | None) -> str:
    """Autodesk's wording with the pretty-printer's line breaks folded out."""
    if not text:
        return ""
    return _WS.sub(" ", text).strip()


def _short_exception(cref: str) -> str:
    """`T:Autodesk.Revit.Exceptions.InvalidOperationException` -> the type."""
    return cref[2:] if cref[1:2] == ":" else cref


def markers_in(text: str) -> list[str]:
    low = text.lower()
    return [m for m in MARKERS if m in low]


_ALNUM = re.compile(r"[^a-z0-9]+")


def fingerprint(text: str) -> str:
    """What has to change before we call a condition genuinely re-worded.

    Case and punctuation are dropped.  Everything else -- every word, and the
    order of the words -- is kept, so "such as Groups" differing from "such as
    Groups and Rooms" is still a change, while NULL/null is not.
    """
    return _ALNUM.sub(" ", text.lower()).strip()


# --------------------------------------------------------------------------
# reading
# --------------------------------------------------------------------------

_MEMBER_OPEN = re.compile(r"^\s*<member\s+name=")
_SELF_CLOSED = re.compile(r"/>\s*$")


def iter_member_blocks(path: pathlib.Path) -> Iterator[tuple[int, str]]:
    """Yield (line number, raw XML) per <member>, holding one at a time.

    The files are 10-12 MB each and this box also runs production, so nothing
    accumulates: the scan keeps a single member in memory and forgets it.  The
    line number rides along because a fact you cannot walk back to its source
    line is a fact nobody will trust enough to act on.
    """
    with path.open(encoding="utf-8") as handle:
        block: list[str] = []
        start = 0
        for number, line in enumerate(handle, 1):
            if block:
                block.append(line)
                if "</member>" in line:
                    yield start, "".join(block)
                    block = []
                continue
            if _MEMBER_OPEN.match(line):
                if "</member>" in line or _SELF_CLOSED.search(line):
                    yield number, line
                    continue
                block = [line]
                start = number
        if block:  # truncated file: surface it rather than silently drop it
            yield start, "".join(block) + "</member>"


def parse_member(raw: str) -> dict | None:
    """One <member> element as plain fields, or None when it will not parse."""
    try:
        node = _xml_fromstring(raw)
    except Exception:
        return None
    key = node.get("name") or ""
    if not key:
        return None
    traps = []
    for child in node:
        # <exception> is the documented norm; <throws> is used 8 times per file
        # and one of those eight is the property that cost us the groups.
        if child.tag not in ("exception", "throws"):
            continue
        traps.append({
            "tag": child.tag,
            "exception": _short_exception(child.get("cref") or ""),
            "text": _fold("".join(child.itertext())),
        })
    return {
        "key": key,
        "since": _fold(node.findtext("since")),
        "summary": _fold(node.findtext("summary")),
        "remarks": _fold(node.findtext("remarks")),
        "traps": traps,
    }


_NAME_RE = re.compile(r'<member\s+name="([^"]*)"')
_SINCE_RE = re.compile(r"<since>(.*?)</since>", re.S)


def read_member(raw: str) -> dict | None:
    """parse_member, but only paying for XML on the members that can bite.

    Four fifths of the file is members that document no exception and hide no
    precondition; those need nothing but their name, their <since> and the fact
    that they exist in this version.  Full parsing of all 213 000 member
    elements costs four minutes, which is enough friction that the index stops
    being rebuilt after a Revit release -- and a stale trap index is worse than
    none, because it answers confidently.  The cheap path is taken only when
    the raw text provably contains no <exception>, no <throws> and no marker
    phrase, so it can never skip something the slow path would have found.
    """
    # The marker test runs on FOLDED text, not on the raw block.  Autodesk
    # wraps prose mid-phrase, so "is not\n   supported" is in the file and not
    # in the raw string, and testing the raw form silently skipped three
    # members on the first run -- the same shape of loss this index was built
    # to end, reintroduced by its own optimisation.
    if "<exception" in raw or "<throws" in raw or markers_in(_fold(raw)):
        return parse_member(raw)
    name = _NAME_RE.search(raw)
    if name is None:
        return None
    since = _SINCE_RE.search(raw)
    return {"key": name.group(1), "since": _fold(since.group(1) if since
                                                 else ""),
            "summary": "", "remarks": "", "traps": []}


def split_key(key: str) -> tuple[str, str, str]:
    """`P:Autodesk.Revit.DB.LocationPoint.Rotation` -> (P, owner, simple).

    Methods carry their signature in parentheses, so the owner is whatever
    precedes the last dot OUTSIDE them.  Type entries (`T:`) own themselves.
    """
    kind, _, full = key.partition(":")
    head = full.split("(", 1)[0]
    if kind == "T":
        return kind, head, head.rsplit(".", 1)[-1]
    owner, _, simple = head.rpartition(".")
    return kind, owner, simple


def documentation_files(root: pathlib.Path = NUGET_ROOT
                        ) -> list[tuple[str, str, pathlib.Path]]:
    """(version, assembly, path) for every documentation XML we can find."""
    found = []
    for version in VERSIONS:
        for framework in FRAMEWORKS:
            directory = root / f"{version}.0.0" / "lib" / framework
            if not directory.is_dir():
                continue
            for path in sorted(directory.glob("*.xml")):
                found.append((version, path.stem, path))
            break
    return found


# --------------------------------------------------------------------------
# building
# --------------------------------------------------------------------------

DDL = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE source (
    version TEXT, assembly TEXT, path TEXT, bytes INTEGER, sha256 TEXT,
    members INTEGER, traps INTEGER, unparsed INTEGER);
CREATE TABLE blob (id INTEGER PRIMARY KEY, sha TEXT UNIQUE, text TEXT);
CREATE TABLE member (
    key TEXT PRIMARY KEY, kind TEXT, owner TEXT, simple TEXT, assembly TEXT,
    versions TEXT, first_version TEXT, last_version TEXT, since TEXT,
    trap_count INTEGER, drift TEXT, markers TEXT);
CREATE TABLE trap (
    id INTEGER PRIMARY KEY, key TEXT, tag TEXT, exception TEXT,
    blob_id INTEGER, versions TEXT, markers TEXT, fingerprint TEXT);
CREATE TABLE prose (key TEXT, field TEXT, blob_id INTEGER, versions TEXT);
CREATE TABLE seen (
    key TEXT, version TEXT, assembly TEXT, line INTEGER, since TEXT);
CREATE TABLE staged_trap (
    key TEXT, version TEXT, tag TEXT, exception TEXT, text TEXT);
CREATE TABLE staged_prose (key TEXT, version TEXT, field TEXT, text TEXT);
"""

INDEXES = """
CREATE INDEX idx_trap_key ON trap(key);
CREATE INDEX idx_trap_exc ON trap(exception);
CREATE INDEX idx_member_owner ON member(owner);
CREATE INDEX idx_member_simple ON member(simple);
CREATE INDEX idx_seen_key ON seen(key);
"""


def _digest(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build(db_path: pathlib.Path, root: pathlib.Path = NUGET_ROOT,
          verbose: bool = True) -> dict:
    """Read every version into one merged index; return the build report."""
    files = documentation_files(root)
    if not files:
        raise SystemExit(f"no documentation XML under {root}")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    db = sqlite3.connect(db_path)
    db.executescript(DDL)

    report = {
        "schema": SCHEMA_VERSION,
        "built_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "docs_root": str(root),
        "sources": [],
    }

    for version, assembly, path in files:
        members = traps = unparsed = 0
        seen_rows: list[tuple] = []
        trap_rows: list[tuple] = []
        prose_rows: list[tuple] = []
        for line, raw in iter_member_blocks(path):
            parsed = read_member(raw)
            if parsed is None:
                # A member we cannot read is the exact failure mode this tool
                # exists to end, so it is counted and reported, never dropped.
                unparsed += 1
                continue
            members += 1
            key = parsed["key"]
            seen_rows.append((key, version, assembly, line, parsed["since"]))
            for trap in parsed["traps"]:
                traps += 1
                trap_rows.append((key, version, trap["tag"],
                                  trap["exception"], trap["text"]))
            can_refuse = bool(parsed["traps"])
            for field in ("summary", "remarks"):
                text = parsed[field]
                if not text:
                    continue
                # Prose is kept for members that can refuse, and for members
                # whose prose hides a precondition.  A member with neither
                # answers no question this index is for, and mirroring the
                # whole documentation would cost hundreds of MB to say nothing.
                if can_refuse or markers_in(text):
                    prose_rows.append((key, version, field, text))
            if len(seen_rows) >= 2000:
                _flush(db, seen_rows, trap_rows, prose_rows)
                seen_rows, trap_rows, prose_rows = [], [], []
        _flush(db, seen_rows, trap_rows, prose_rows)
        db.commit()
        entry = {"version": version, "assembly": assembly, "path": str(path),
                 "bytes": path.stat().st_size, "sha256": _digest(path),
                 "members": members, "traps": traps, "unparsed": unparsed}
        report["sources"].append(entry)
        db.execute("INSERT INTO source VALUES (?,?,?,?,?,?,?,?)",
                   (version, assembly, str(path), entry["bytes"],
                    entry["sha256"], members, traps, unparsed))
        db.commit()
        if verbose:
            print(f"  {version} {assembly:<12} members={members:>6} "
                  f"traps={traps:>6} unparsed={unparsed}", file=sys.stderr)

    _merge(db)
    _build_search(db)

    report.update(totals(db))
    db.execute("INSERT INTO meta VALUES ('report', ?)",
               (json.dumps(report, ensure_ascii=False),))
    db.execute("INSERT INTO meta VALUES ('schema', ?)", (SCHEMA_VERSION,))
    db.commit()
    db.execute("VACUUM")
    db.close()
    report["db"] = str(db_path)
    report["db_bytes"] = db_path.stat().st_size
    return report


def _flush(db, seen_rows, trap_rows, prose_rows) -> None:
    if seen_rows:
        db.executemany("INSERT INTO seen VALUES (?,?,?,?,?)", seen_rows)
    if trap_rows:
        db.executemany("INSERT INTO staged_trap VALUES (?,?,?,?,?)", trap_rows)
    if prose_rows:
        db.executemany("INSERT INTO staged_prose VALUES (?,?,?,?)", prose_rows)


def _blob_id(db, text: str, cache: dict) -> int:
    sha = hashlib.sha1(text.encode("utf-8")).hexdigest()
    if sha in cache:
        return cache[sha]
    row = db.execute("SELECT id FROM blob WHERE sha=?", (sha,)).fetchone()
    if row is None:
        blob = db.execute("INSERT INTO blob (sha, text) VALUES (?,?)",
                          (sha, text)).lastrowid
    else:
        blob = row[0]
    cache[sha] = blob
    return blob


def _merge(db) -> None:
    """Collapse six per-version readings into one row per member identity.

    Identity is the documented member key; a condition is identified by its
    exact wording.  Two rows for one member and one exception, with different
    wording and disjoint version sets, is not noise -- that IS a condition
    Autodesk changed, which is why drift needs no separate detector.
    """
    cache: dict = {}

    members = []
    for key, assembly, versions, since_min, since_max in db.execute(
            "SELECT key, assembly, GROUP_CONCAT(DISTINCT version), "
            "       MIN(since), MAX(since) FROM seen "
            "GROUP BY key, assembly").fetchall():
        present = sorted(set(versions.split(",")))
        kind, owner, simple = split_key(key)
        since = since_min if since_min == since_max else (
            f"{since_min}|{since_max}")
        members.append((key, kind, owner, simple, assembly,
                        ",".join(present), present[0], present[-1],
                        since, 0, "", ""))
    db.executemany(
        "INSERT OR REPLACE INTO member VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        members)

    for key, tag, exception, text, versions in db.execute(
            "SELECT key, tag, exception, text, GROUP_CONCAT(DISTINCT version) "
            "FROM staged_trap GROUP BY key, tag, exception, text").fetchall():
        db.execute(
            "INSERT INTO trap (key, tag, exception, blob_id, versions, markers,"
            " fingerprint) VALUES (?,?,?,?,?,?,?)",
            (key, tag, exception, _blob_id(db, text, cache),
             ",".join(sorted(set(versions.split(",")))),
             ",".join(markers_in(text)), fingerprint(text)))

    for key, field, text, versions in db.execute(
            "SELECT key, field, text, GROUP_CONCAT(DISTINCT version) "
            "FROM staged_prose GROUP BY key, field, text").fetchall():
        db.execute("INSERT INTO prose VALUES (?,?,?,?)",
                   (key, field, _blob_id(db, text, cache),
                    ",".join(sorted(set(versions.split(","))))))

    # Before the correlated updates below, not after: without this index each
    # of them is a full scan of trap per member, which is 35 000 × 16 000 and
    # turns a twenty-second build into a five-minute one.
    db.executescript(INDEXES)
    db.execute("UPDATE member SET trap_count = (SELECT COUNT(*) FROM trap "
               "WHERE trap.key = member.key)")
    _classify_drift(db)
    db.execute("""
        UPDATE member SET markers = COALESCE((
            SELECT GROUP_CONCAT(DISTINCT t.markers) FROM trap t
            WHERE t.key = member.key AND t.markers != ''), '')""")
    db.execute("DROP TABLE staged_trap")
    db.execute("DROP TABLE staged_prose")
    db.commit()


def _classify_drift(db) -> None:
    """Say WHICH way a condition moved, because the three ways differ for us.

    added    — Autodesk documented a new way for an existing member to refuse.
               Code written against the older doc is now incomplete.
    removed  — a condition documented earlier is gone.  Either it cannot happen
               any more, or it was undocumented; both are worth knowing.
    reworded — the same exception, described differently, with the versions
               split cleanly between the wordings.  This is the one that hides
               a changed MEANING behind an apparently cosmetic edit.

    A member is silent here when every condition it documents holds across
    exactly the versions the member itself exists in.
    """
    presence = {key: set(versions.split(","))
                for key, versions in db.execute(
                    "SELECT key, versions FROM member")}
    by_member: dict = {}
    for key, exception, versions, mark in db.execute(
            "SELECT key, exception, versions, fingerprint FROM trap"):
        (by_member.setdefault(key, {}).setdefault(exception, {})
         .setdefault(mark, set()).update(versions.split(",")))

    updates = []
    for key, per_exception in by_member.items():
        member_versions = presence.get(key)
        if not member_versions:
            continue
        kinds: set[str] = set()
        for wordings in per_exception.values():
            sets = list(wordings.values())
            if len(sets) > 1:
                union = set().union(*sets)
                disjoint = sum(len(s) for s in sets) == len(union)
                if disjoint and union == member_versions:
                    # Every version accounted for, no version holding two
                    # wordings at once: the sentence was replaced, not added.
                    kinds.add("reworded")
                    continue
            for seen_in in sets:
                if seen_in == member_versions:
                    continue
                if min(seen_in) > min(member_versions):
                    kinds.add("added")
                if max(seen_in) < max(member_versions):
                    kinds.add("removed")
        if kinds:
            updates.append((",".join(sorted(kinds)), key))
    db.executemany("UPDATE member SET drift=? WHERE key=?", updates)


def _build_search(db) -> None:
    """One FTS table over conditions and prose: phrase search is the door in."""
    db.execute("CREATE VIRTUAL TABLE search USING fts5("
               "key, owner, simple, exception, field, text, versions, "
               "tokenize='unicode61')")
    db.execute("""
        INSERT INTO search (key, owner, simple, exception, field, text,
                            versions)
        SELECT t.key, m.owner, m.simple, t.exception, t.tag, b.text, t.versions
        FROM trap t JOIN blob b ON b.id = t.blob_id
        LEFT JOIN member m ON m.key = t.key""")
    db.execute("""
        INSERT INTO search (key, owner, simple, exception, field, text,
                            versions)
        SELECT p.key, m.owner, m.simple, '', p.field, b.text, p.versions
        FROM prose p JOIN blob b ON b.id = p.blob_id
        LEFT JOIN member m ON m.key = p.key""")
    db.commit()


def totals(db) -> dict:
    one = lambda q: db.execute(q).fetchone()[0]  # noqa: E731
    return {
        "members_indexed": one("SELECT COUNT(*) FROM member"),
        "members_with_traps": one(
            "SELECT COUNT(*) FROM member WHERE trap_count > 0"),
        "traps": one("SELECT COUNT(*) FROM trap"),
        "traps_via_throws_tag": one(
            "SELECT COUNT(*) FROM trap WHERE tag='throws'"),
        "distinct_exceptions": one(
            "SELECT COUNT(DISTINCT exception) FROM trap"),
        "members_with_drift": one("SELECT COUNT(*) FROM member WHERE drift!=''"),
        "drift_added": one("SELECT COUNT(*) FROM member "
                           "WHERE drift LIKE '%added%'"),
        "drift_removed": one("SELECT COUNT(*) FROM member "
                             "WHERE drift LIKE '%removed%'"),
        "drift_reworded": one("SELECT COUNT(*) FROM member "
                              "WHERE drift LIKE '%reworded%'"),
        "members_not_in_2021": one(
            "SELECT COUNT(*) FROM member WHERE first_version != '2021'"),
        "members_gone_by_2026": one(
            "SELECT COUNT(*) FROM member WHERE last_version != '2026'"),
        "prose_rows": one("SELECT COUNT(*) FROM prose"),
        "unparsed_total": one("SELECT COALESCE(SUM(unparsed),0) FROM source"),
    }


# --------------------------------------------------------------------------
# asking
# --------------------------------------------------------------------------

def open_db(path: pathlib.Path) -> sqlite3.Connection:
    if not path.exists():
        raise SystemExit(f"no index at {path} — run: "
                         f"python tools/api_trap_index.py build")
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    return db


def span(versions: str) -> str:
    """`2021,2022,…,2026` -> `all`; a gap stays visible instead of collapsing."""
    present = sorted(set(versions.split(","))) if versions else []
    if not present:
        return "-"
    if present == list(VERSIONS):
        return "all"
    contiguous = [v for v in VERSIONS if present[0] <= v <= present[-1]]
    if present == contiguous and len(present) > 1:
        return f"{present[0]}-{present[-1]}"
    return ",".join(present)


def traps_of(db, key: str) -> list[sqlite3.Row]:
    return db.execute(
        "SELECT t.*, b.text AS text FROM trap t JOIN blob b ON b.id=t.blob_id "
        "WHERE t.key=? ORDER BY t.exception, t.versions", (key,)).fetchall()


def conditions_of(db, key: str) -> list[dict]:
    """One entry per condition, with cosmetic re-spellings folded together.

    Two rows saying "argument was NULL" and "argument was null" are one
    condition Autodesk recased, and printing them as two teaches an author that
    something changed in 2022 when nothing did.  The current wording leads; any
    earlier spelling is kept underneath it rather than thrown away.
    """
    grouped: dict = {}
    for row in traps_of(db, key):
        entry = grouped.setdefault(
            (row["exception"], row["fingerprint"]),
            {"exception": row["exception"], "tag": row["tag"],
             "versions": set(), "wordings": []})
        entry["versions"].update(row["versions"].split(","))
        entry["wordings"].append((row["versions"], row["text"]))
    out = []
    for entry in grouped.values():
        newest = max(entry["wordings"], key=lambda w: max(w[0].split(",")))
        out.append({
            "exception": entry["exception"],
            "tag": entry["tag"],
            "versions": ",".join(sorted(entry["versions"])),
            "text": newest[1],
            "earlier": [w for w in entry["wordings"] if w is not newest],
        })
    return sorted(out, key=lambda e: (e["exception"], e["versions"]))


def print_conditions(db, key: str, indent: str = "    ") -> None:
    for entry in conditions_of(db, key):
        print(f"{indent}{entry['exception']}  [{span(entry['versions'])}]"
              f"  <{entry['tag']}>")
        print(f"{indent}  “{entry['text']}”")
        for versions, text in entry["earlier"]:
            print(f"{indent}  (earlier spelling, {span(versions)}: “{text}”)")


def print_member(db, key: str, show_prose: bool = True) -> None:
    row = db.execute("SELECT * FROM member WHERE key=?", (key,)).fetchone()
    if row is None:
        print(f"{key}: not documented in any indexed version")
        return
    print(row["key"])
    since = f"   (Autodesk <since> {row['since']})" if row["since"] else ""
    print(f"  versions   {span(row['versions'])}{since}")
    if row["first_version"] != "2021":
        missing = ", ".join(v for v in VERSIONS if v < row["first_version"])
        print(f"  NEW IN     {row['first_version']} — absent from {missing}")
    if row["last_version"] != "2026":
        print(f"  REMOVED    after {row['last_version']}")
    # Where to read it in Autodesk's own file: a quote nobody can walk back to
    # its source is a quote that will eventually be doubted and re-litigated.
    source = db.execute(
        "SELECT s.path, n.line FROM seen n JOIN source s "
        "ON s.version = n.version AND s.assembly = n.assembly "
        "WHERE n.key = ? ORDER BY n.version DESC LIMIT 1", (key,)).fetchone()
    if source:
        print(f"  source     {source['path']}:{source['line']}")
    if show_prose:
        for prose in db.execute(
                "SELECT p.field, b.text AS text, p.versions FROM prose p "
                "JOIN blob b ON b.id=p.blob_id WHERE p.key=? "
                "ORDER BY p.field DESC", (key,)).fetchall():
            marks = markers_in(prose["text"])
            flag = f"   [{', '.join(marks)}]" if marks else ""
            print(f"  {prose['field']} ({span(prose['versions'])}){flag}")
            print(f"    “{prose['text']}”")
    entries = conditions_of(db, key)
    if not entries:
        print("  no documented exceptions")
        return
    drift = f"   *** {row['drift'].upper()} BETWEEN VERSIONS ***" if row[
        "drift"] else ""
    print(f"  documented conditions: {len(entries)}{drift}")
    print_conditions(db, key)


def cmd_member(db, args) -> None:
    if db.execute("SELECT 1 FROM member WHERE key=?", (args.name,)).fetchone():
        print_member(db, args.name)
        return
    rows = db.execute(
        "SELECT key FROM member WHERE key LIKE ? "
        "ORDER BY trap_count DESC, key LIMIT ?",
        (f"%{args.name}%", args.limit)).fetchall()
    if not rows:
        print(f"no member matching {args.name!r}")
        return
    for index, row in enumerate(rows):
        if index:
            print()
        print_member(db, row["key"], show_prose=not args.brief)


def cmd_type(db, args) -> None:
    """What can refuse on this type — the question to ask before writing an op."""
    # `type Group` must answer about Group before it answers about
    # LightGroupManager, however many more ways the latter can refuse.
    owners = [r["owner"] for r in db.execute(
        "SELECT owner, SUM(trap_count) AS traps FROM member "
        "WHERE owner LIKE ? OR owner = ? GROUP BY owner "
        "ORDER BY (LOWER(owner) = LOWER(?)) DESC, "
        "         (LOWER(owner) LIKE LOWER(?)) DESC, traps DESC LIMIT ?",
        (f"%{args.name}%", args.name, args.name, f"%.{args.name}",
         args.types)).fetchall()]
    if not owners:
        print(f"no type matching {args.name!r}")
        return
    for owner in owners:
        rows = db.execute(
            "SELECT key, kind, simple, versions, drift FROM member "
            "WHERE owner = ? AND trap_count > 0 ORDER BY kind, simple",
            (owner,)).fetchall()
        total = db.execute("SELECT COUNT(*) FROM member WHERE owner=?",
                           (owner,)).fetchone()[0]
        print(f"\n=== {owner}   ({len(rows)} of {total} documented members "
              f"can refuse)")
        for row in rows:
            mark = f"   *{row['drift']}*" if row["drift"] else ""
            print(f"  {row['kind']}:{row['simple']}  "
                  f"[{span(row['versions'])}]{mark}")
            print_conditions(db, row["key"], indent="      ")


def cmd_exception(db, args) -> None:
    like = f"%{args.name}%"
    total = db.execute("SELECT COUNT(*) FROM trap WHERE exception LIKE ?",
                       (like,)).fetchone()[0]
    rows = db.execute(
        "SELECT t.key, t.exception, t.versions, b.text AS text "
        "FROM trap t JOIN blob b ON b.id=t.blob_id "
        "WHERE t.exception LIKE ? ORDER BY t.key LIMIT ?",
        (like, args.limit)).fetchall()
    print(f"{total} documented conditions raise an exception matching "
          f"{args.name!r}; showing {len(rows)}")
    for row in rows:
        print(f"\n  {row['key']}  [{span(row['versions'])}]")
        print(f"    {row['exception']}")
        print(f"      “{row['text']}”")


def cmd_phrase(db, args) -> None:
    """Free phrase search over conditions and prose, quotes intact."""
    match = f'"{args.text}"'
    total = db.execute("SELECT COUNT(*) FROM search WHERE search MATCH ?",
                       (match,)).fetchone()[0]
    rows = db.execute(
        "SELECT key, exception, field, text, versions FROM search "
        "WHERE search MATCH ? ORDER BY rank LIMIT ?",
        (match, args.limit)).fetchall()
    print(f"{total} documented places contain {args.text!r}; "
          f"showing {len(rows)}")
    for row in rows:
        where = row["exception"] or row["field"]
        print(f"\n  {row['key']}  [{span(row['versions'])}]  {where}")
        print(f"      “{row['text']}”")


def cmd_drift(db, args) -> None:
    """Conditions that do not hold across every version of their member."""
    where = "drift != ''" if not args.kind else f"drift LIKE '%{args.kind}%'"
    total = db.execute(
        f"SELECT COUNT(*) FROM member WHERE {where}").fetchone()[0]
    rows = db.execute(
        f"SELECT key, drift, versions FROM member WHERE {where} "
        "ORDER BY trap_count DESC, key LIMIT ?", (args.limit,)).fetchall()
    print(f"{total} members document a condition that does not hold across "
          f"every version they exist in; showing {len(rows)}")
    for row in rows:
        print(f"\n  {row['key']}   [{span(row['versions'])}]  → "
              f"{row['drift']}")
        # Only the conditions that actually moved.  A member like
        # OpenDocumentFile documents eighteen of them and printing all
        # eighteen to show the one that changed in 2023 buries the answer.
        for entry in conditions_of(db, row["key"]):
            if entry["versions"] == row["versions"] and not entry["earlier"]:
                continue
            print(f"    {entry['exception']}  [{span(entry['versions'])}]"
                  f"{'  (of ' + span(row['versions']) + ')'}")
            print(f"      “{entry['text']}”")
            for versions, text in entry["earlier"]:
                print(f"      (earlier spelling, {span(versions)}: “{text}”)")


def cmd_versions(db, args) -> None:
    """Members that are not in all six — our real compatibility surface."""
    if args.new_in:
        total = db.execute("SELECT COUNT(*) FROM member WHERE first_version=?",
                           (args.new_in,)).fetchone()[0]
        rows = db.execute(
            "SELECT key, versions, trap_count FROM member "
            "WHERE first_version = ? ORDER BY trap_count DESC, key LIMIT ?",
            (args.new_in, args.limit)).fetchall()
        print(f"{total} members appear first in {args.new_in} (absent "
              f"earlier); showing {len(rows)}")
        for row in rows:
            print(f"  {row['key']}  [{span(row['versions'])}]  "
                  f"traps={row['trap_count']}")
    if args.removed:
        total = db.execute(
            "SELECT COUNT(*) FROM member WHERE last_version != '2026'"
        ).fetchone()[0]
        rows = db.execute(
            "SELECT key, versions, last_version FROM member "
            "WHERE last_version != '2026' ORDER BY last_version DESC, key "
            "LIMIT ?", (args.limit,)).fetchall()
        print(f"\n{total} members documented in an older Revit are gone by "
              f"2026; showing {len(rows)}")
        for row in rows:
            print(f"  {row['key']}  [{span(row['versions'])}]  "
                  f"last={row['last_version']}")
    if not args.new_in and not args.removed:
        for version in VERSIONS:
            first = db.execute(
                "SELECT COUNT(*) FROM member WHERE first_version=?",
                (version,)).fetchone()[0]
            gone = 0 if version == "2026" else db.execute(
                "SELECT COUNT(*) FROM member WHERE last_version=?",
                (version,)).fetchone()[0]
            tail = f",  {gone:>5} last appear" if version != "2026" else ""
            print(f"  {version}: {first:>6} members first appear{tail}")


def cmd_stats(db, args) -> None:
    report = json.loads(db.execute(
        "SELECT value FROM meta WHERE key='report'").fetchone()[0])
    for entry in report["sources"]:
        print(f"  {entry['version']} {entry['assembly']:<12} "
              f"members={entry['members']:>6} traps={entry['traps']:>6} "
              f"unparsed={entry['unparsed']}")
    print()
    for name in ("members_indexed", "members_with_traps", "traps",
                 "traps_via_throws_tag", "distinct_exceptions",
                 "members_with_drift", "drift_added", "drift_removed",
                 "drift_reworded", "members_not_in_2021",
                 "members_gone_by_2026", "unparsed_total"):
        print(f"  {name:<22} {report[name]}")
    print("\n  by exception class")
    for row in db.execute(
            "SELECT exception, COUNT(*) n FROM trap GROUP BY exception "
            "ORDER BY n DESC LIMIT 15"):
        print(f"    {row['n']:>6}  {row['exception']}")
    print("\n  by marker phrase (documented conditions only)")
    for marker in MARKERS:
        count = db.execute(
            "SELECT COUNT(*) FROM trap t JOIN blob b ON b.id=t.blob_id "
            "WHERE LOWER(b.text) LIKE ?", (f"%{marker}%",)).fetchone()[0]
        if count:
            print(f"    {count:>6}  {marker!r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=pathlib.Path, default=DEFAULT_DB)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("build", help="read the six XMLs into the index")
    p.add_argument("--docs", type=pathlib.Path, default=NUGET_ROOT)
    p.add_argument("--json", type=pathlib.Path, help="write the build report")

    p = sub.add_parser("member", help="everything documented about one member")
    p.add_argument("name")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--brief", action="store_true")

    p = sub.add_parser("type", help="what can refuse on this type")
    p.add_argument("name")
    p.add_argument("--types", type=int, default=3)

    p = sub.add_parser("exception", help="every member raising this exception")
    p.add_argument("name")
    p.add_argument("--limit", type=int, default=40)

    p = sub.add_parser("phrase", help="search the wording itself")
    p.add_argument("text")
    p.add_argument("--limit", type=int, default=40)

    p = sub.add_parser("drift", help="conditions that moved between versions")
    p.add_argument("--kind", choices=("added", "removed", "reworded"))
    p.add_argument("--limit", type=int, default=40)

    p = sub.add_parser("versions", help="members that are not in all six")
    p.add_argument("--new-in", choices=VERSIONS)
    p.add_argument("--removed", action="store_true")
    p.add_argument("--limit", type=int, default=40)

    sub.add_parser("stats", help="what the index contains")

    args = parser.parse_args(argv)

    if args.command == "build":
        started = time.time()
        print(f"building {args.db} from {args.docs}", file=sys.stderr)
        report = build(args.db, args.docs)
        report["seconds"] = round(time.time() - started, 1)
        text = json.dumps(report, indent=2, ensure_ascii=False)
        print(text)
        if args.json:
            args.json.write_text(text, encoding="utf-8")
        return 0

    db = open_db(args.db)
    {"member": cmd_member, "type": cmd_type, "exception": cmd_exception,
     "phrase": cmd_phrase, "drift": cmd_drift, "versions": cmd_versions,
     "stats": cmd_stats}[args.command](db, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
