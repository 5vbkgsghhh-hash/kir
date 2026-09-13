"""THE SCENE CACHE — because the scene is one per BUILDING, not per person.

════════════════════════════════════════════════════════════════════════════
MEASUREMENT 11.08.2026, `демо-v3` with the graph layer, BY STAGE
════════════════════════════════════════════════════════════════════════════
Cold open is broken down, not named as a single number (19.7 s in this
run; the same path without the breakdown gave 17.4 s — runs differ, and a
number must name its own):

    L0 #1 (read_decompile)              4.45 s   22.6 %
    L1 (tree.json)                      3.60 s   18.3 %
    graph_from_l0                       3.28 s   16.6 %
    L0 #2 (graph ONLY)                  3.20 s   16.2 %
    shells (build_from_elements)        2.32 s   11.8 %
    graph_view                          1.86 s    9.4 %
    codec (packing)                     0.99 s    5.0 %

**THIS OVERTURNED MY OWN HYPOTHESIS.** I had named the second pass over L0 as
the cause and was about to ask the owner for a `decompile` interface that
hands lines out once to both consumers. The measurement says: the second
pass is **16.2 %**, that is 3.20 s out of 19.7. The interface would have
removed a sixth of the trouble. Optimizing without measuring is assigning
the bottleneck by decree, and I nearly did exactly that.

════════════════════════════════════════════════════════════════════════════
THE CACHE REMOVES ALL OF IT, NOT A SIXTH
════════════════════════════════════════════════════════════════════════════
    cold build             20.0 s
    cache read               1 ms          -> 20 584x
    key check               0.1 ms        -> 217 848x cheaper than a build

And this is legitimate exactly because the parse is an IMMUTABLE ARCHIVE, and
the scene is DETERMINISTIC. The second claim is verified, not assumed: two
consecutive builds produced **a byte-identical BODY** (5 154 042 bytes), and
exactly five header fields diverged — `timing_ms.*` and `graph.elapsed_ms`,
i.e. the stopwatch readings, which are bound to differ.

This gives a direct answer to the question about ten users: the cold open
is paid by the FIRST one, not by everyone.

════════════════════════════════════════════════════════════════════════════
WHAT GOES INTO THE KEY — AND WHY EACH PART
════════════════════════════════════════════════════════════════════════════
* **the parse's input files** (name, size, mtime IN NANOSECONDS). The
  archive is immutable, but
  "immutable" is a promise made by the operator, not a property of the
  filesystem;
* **the `KUKAI_IR_BUILDING_GRAPH` flag**. It CHANGES THE CONTENTS of the
  scene: with it, elements get `materialized`/`declared`; without it —
  `unknown`. A cache without the flag in its key would hand a grey building
  to whoever turned the graph on, and vice versa;
* **the format version** (`CACHE_VERSION`). When the packing code changes,
  all entries must go stale, otherwise the client would get yesterday's
  format from today's parse.

════════════════════════════════════════════════════════════════════════════
A CACHED SCENE SAYS THAT IT IS CACHED
════════════════════════════════════════════════════════════════════════════
The header carries the stopwatch reading of the BUILD IT CAME FROM.
Presenting it as its own would mean reporting "built in 20 s" about a read
that took a millisecond — that is, lying via the instrument. That is why
the response is annotated with `cache`: the hit, the age of the entry, and
the fact that the timings belong to the original build. Silence here would
read as "that's how fast it builds."
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from kir import env  # noqa: E402  (a submodule with no dependencies — introduces no cycle)
import pathlib
import time
from typing import Any, Optional, Sequence

logger = logging.getLogger(__name__)

__all__ = ("CACHE_VERSION", "cache_dir", "enabled", "key_for",
           "key_inputs", "load", "preflight", "purge", "stats", "store")

#: The scene's FORMAT version. When the codec changes, this changes too,
#: and all entries go stale at once. Without this the client would get
#: yesterday's format.
CACHE_VERSION = "kir-viewer-scene-cache/1"

_COUNTERS = {"hit": 0, "miss": 0, "stored": 0, "evicted": 0, "errors": 0}


def enabled() -> bool:
    """The on/off switch. Off = behavior before this wave: everyone pays
    their own cold open."""
    return env.get("KIR_SCENE_CACHE", "1") != "0"


def cache_dir() -> pathlib.Path:
    raw = env.get("KIR_SCENE_CACHE_DIR", "")
    if raw:
        return pathlib.Path(raw)
    return pathlib.Path("/tmp/kir-scene-cache")


def _max_bytes() -> int:
    """The cap is in BYTES, not entries: the facade scene is 0.5 MB, the
    демо-v3 scene is 5.2 MB, and counting them the same is not counting at
    all."""
    try:
        return max(10_000_000, int(env.get(
            "KIR_SCENE_CACHE_BYTES", "") or 2_000_000_000))
    except (TypeError, ValueError):
        return 2_000_000_000


def key_for(run: str, run_dir: pathlib.Path, *,
            kind: str = "scene", extra: Sequence[str] = ()) -> str:
    """The key is over INPUTS and over whatever changes the content of the
    response.

    `kind` — the RESPONSE KIND, and it is mandatory in the key. The cache
    holds bytes; two consumers with the same key and different bodies would
    hand each other the wrong thing — a scene to whoever asked for a
    verdict. Measurement 20.08: adding `kind=` changes every existing key,
    meaning scenes will miss once and rebuild. This is named, not passed
    over in silence: one cold build is cheaper than one case of the panel
    getting the wrong blob.

    `extra` — whatever changes the response for THIS kind and is not
    visible from the catalog (e.g. the state of `KUKAI_CHECKER_V2` for a
    verdict). Strings, not objects: they go into `key_inputs` as a list and
    are readable at a glance.

    Computed over (name, size, mtime in NANOSECONDS) of the parse's files:
    0.1 ms for 17 files — 217 848x cheaper than a build. File contents are
    deliberately not hashed: L0 reaches 88 MB, and an honest hash would cost
    more than the cache. The price is named: swapping a file for one with
    THE SAME size AND THE SAME `st_mtime_ns` goes unnoticed by the cache,
    and the kernel issues a new timestamp once per tick (measured at
    4 ms). This is acceptable for an immutable archive; for a working
    directory it is not, and then the cache must be turned off with the
    flag.
    """
    inputs = key_inputs(run, run_dir, kind=kind, extra=extra)
    if inputs is None:
        # The directory can't be read — there is no key, and the cache must
        # miss, rather than hand back an entry justified by nothing in
        # particular.
        return ""
    digest = hashlib.sha256()
    for item in inputs:
        digest.update(b"|")
        digest.update(item.encode("utf-8"))
    return digest.hexdigest()


def key_inputs(run: str, run_dir: pathlib.Path, *,
               kind: str = "scene",
               extra: Sequence[str] = ()) -> Optional[list[str]]:
    """THE KEY INPUTS AS A LIST, not silently folded into a hash.

    THIS REQUIREMENT COMES FROM SOMEONE ELSE'S BURN. In the clash cache the
    key three times over failed to cover what changes the response: a
    raised ceiling kept returning the OLD refusal, because the ceiling
    wasn't in the key. A hash doesn't show such a hole — it looks equally
    convincing with a full set of inputs and with half of them. That's why
    the set is published as a list: a hole in it is visible to the eye and
    to a test.

    What goes in, and why each one:
      * `kind=` — the RESPONSE KIND (`scene` / `normcontrol` / …). The
        cache stores bytes, and without the kind, two consumers with
        identical inputs would get each other's body;
      * `version=` — the scene's FORMAT version. When the codec changes,
        everything goes stale;
      * `run=` — the name of the parse;
      * `graph=` — the `KUKAI_IR_BUILDING_GRAPH` flag. It changes the
        CONTENTS: with it, elements get `materialized`/`declared`; without
        it, `unknown`. A cache without it would hand a grey building to
        whoever turned the graph on;
      * one line per EACH parse file: `name:size:mtime_ns`. Nanoseconds,
        not whole seconds: rounding was throwing away the
        DISTINGUISHABILITY that the filesystem gives for free (F-269).

    WHAT IS NOT HERE, AND ITS PRICE. File contents are not hashed: L0
    reaches 88 MB, and an honest hash would cost more than the build
    itself. So swapping a file for one with THE SAME size AND THE SAME
    `st_mtime_ns` goes unnoticed by the cache, and this window is NOT a
    nanosecond: the kernel changes the timestamp once per tick (measured
    30.08 — 2 753 rewrites, 740 distinct timestamps, step 4.000 ms). This
    is acceptable for an immutable archive; for a working directory it is
    not, and then the cache is turned off with the flag. Named here, not
    implied.

    🔴 THE PRICE OF NANOSECONDS IS ALSO NAMED, ON BOTH SIDES. A copy of the
    archive made by a tool that only preserves time to the second (`cp -p`,
    some `rsync`) gives a DIFFERENT key — that is, a MISS and a cold
    build. A miss is safe, a false hit is not; trading the first for the
    second for convenience's sake would mean subordinating correctness to
    the cache.
    """
    out = [f"kind={kind}", f"version={CACHE_VERSION}", f"run={run}",
           f"graph={env.get('KIR_BUILDING_GRAPH', '')}"]
    out.extend(str(item) for item in extra)
    skip = _not_inputs()
    try:
        for path in sorted(p for p in run_dir.iterdir() if p.is_file()):
            if path.name in skip:
                continue
            st = path.stat()
            # 🔴 NANOSECONDS, NOT WHOLE SECONDS (F-269). `int(st.st_mtime)`
            # was discarding precision that EVERY real input HAS: a corpus
            # walk on 30.08.2026 — 93 of 93 directories walked, 1328 input
            # files, and 1328 (100 %) had a NON-ZERO fractional part of
            # mtime. The discriminator is TWO-SIDED, mtime was set by hand
            # (no race), the "before" subject is taken from git:
            #     mtime shift    HEAD      tree
            #     1 ns           BLIND     sees
            #     4 ms           BLIND     sees
            #     200 ms         BLIND     sees
            #     1 s            sees      sees
            # The filesystem had the precision; the key was the one
            # rounding it away.
            out.append(f"{path.name}:{st.st_size}:{st.st_mtime_ns}")
    except OSError:
        return None
    return out


def _not_inputs() -> frozenset:
    """Directory files that are NOT scene inputs.

    MEASUREMENT 11.08.2026, AND THIS MIRRORS SOMEONE ELSE'S BURN. In the
    clash cache the key did NOT COVER what changes the response, and a
    raised ceiling kept returning the old refusal. Here the error was the
    opposite, and so less visible: the key COVERED something that does NOT
    change the response.

    `.last_access` — the access mark that
    `decompile.snapshot_io.touch_last_access` sets on EVERY read of a parse
    file. Measurement: open the «план против объёма» panel (it calls
    `preview_snapshot`) — and the mark's `mtime` changes, and the scene key
    changes right along with it:

        key before the check   26243642fc0a722a9229
        key after               ebe15ccec14bdfd05399

    That is, the cache stopped hitting FOREVER for anyone who used the
    check, and it stopped silently: it looked like it was working, it was
    just rebuilding every single time. A key that covers too much breaks
    the cache; a key that covers too little breaks correctness. Both
    errors are about the same thing: the set of inputs must be EXACTLY the
    set of what changes the response.

    The name is taken from the owner, not written as a literal string: a
    home-grown copy would drift on rename and would return the defect
    silently.
    """
    names = {".last_access"}
    try:
        from kir.decompile.snapshot_io import LAST_ACCESS_MARKER
        names.add(str(LAST_ACCESS_MARKER))
    except Exception:  # noqa: BLE001 — a foreign module; the fallback name above
        pass
    return frozenset(names)


def _paths(key: str) -> tuple[pathlib.Path, pathlib.Path]:
    root = cache_dir()
    return root / f"{key}.bin", root / f"{key}.json"


def load(key: str) -> Optional[tuple[bytes, dict[str, Any]]]:
    """The scene bytes and info about the ENTRY. `None` — a miss, and that
    is not an error."""
    if not key or not enabled():
        return None
    blob_path, meta_path = _paths(key)
    try:
        if not blob_path.exists() or not meta_path.exists():
            _COUNTERS["miss"] += 1
            return None
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        blob = blob_path.read_bytes()
    except Exception:  # noqa: BLE001 — a corrupted entry is a miss, not a refusal
        _COUNTERS["errors"] += 1
        return None
    # ENTRY INTEGRITY IS CHECKED. A truncated file that still hands back an
    # internally consistent header is exactly the defect that the clash
    # snapshot catches with an exception, not a warning.
    if meta.get("bytes") != len(blob):
        _COUNTERS["errors"] += 1
        return None
    # 🔴 THE DIGEST IS MANDATORY, NOT OPTIONAL (F-268, 29.08.2026). The
    # comment above promised an INTEGRITY CHECK, but only LENGTH was being
    # checked: swapping a blob for another of the SAME length came back as
    # a HIT and was shown to the person as the building. Measurement: put
    # in b'good', swapped it for b'evil' — `load` returned b'evil',
    # `hit=True`, and `errors` stayed at ZERO. That is, the instrument did
    # not just get it wrong, it BELIEVED there were no errors.
    #
    # An entry laid down by the previous revision carries no digest — and
    # that is a MISS, not "nothing to check against." Silently accepting
    # an unverifiable entry is exactly the defect being fixed here. I did
    # not bump `CACHE_VERSION`: a version bump would devalue the ENTIRE
    # cache at once, while a miss devalues it gradually — every entry gets
    # rewritten on its next build, and the safety is the same.
    want = meta.get("sha256")
    if not want or want != hashlib.sha256(blob).hexdigest():
        _COUNTERS["errors"] += 1
        return None
    _COUNTERS["hit"] += 1
    age = max(0.0, time.time() - float(meta.get("built_at") or 0.0))
    note = {
        "hit": True,
        "built_at": meta.get("built_at"),
        "age_s": round(age, 1),
        "build_ms": meta.get("build_ms"),
        "version": meta.get("version"),
        # THE TIMINGS IN THE HEADER BELONG TO THE ORIGINAL BUILD.
        # Presenting them as its own would mean reporting "built in 20 s"
        # about a read that took a millisecond — lying via the instrument.
        "inputs": meta.get("inputs") or [],
        "ru": ("сцена взята из кэша; показания секундомера в заголовке "
               "принадлежат ИСХОДНОЙ постройке, а не этому ответу"),
    }
    return blob, note


def store(key: str, blob: bytes, *, build_ms: float,
          inputs: Optional[list[str]] = None) -> bool:
    if not key or not enabled():
        return False
    blob_path, meta_path = _paths(key)
    try:
        cache_dir().mkdir(parents=True, exist_ok=True)
        # We write through a temporary name: an interrupted write must not
        # leave behind a file that later gets read as whole.
        tmp = blob_path.with_suffix(".part")
        tmp.write_bytes(blob)
        tmp.replace(blob_path)
        meta_path.write_text(json.dumps({
            "version": CACHE_VERSION, "bytes": len(blob),
            # 🔴 A DIGEST OF THE BLOB, NOT JUST THE LENGTH (F-268). sha256
            # of the SCENE, not of the inputs: hashing an input is
            # expensive (L0 reaches 88 MB — the module header names
            # exactly that), while the scene is already in hand and costs
            # one extra pass at WRITE time. The price is measured on the
            # write side, which already costs 0.5–5 s; hashing five
            # megabytes is a few milliseconds.
            #
            # WHAT THIS DOES NOT FIX is stated so the change isn't mistaken
            # for a neighboring one: swapping an INPUT of the same length
            # and the same mtime stays unnoticed (`key_inputs`). The
            # window for this swap narrowed from a SECOND to a KERNEL TICK
            # (F-269, 30.08.2026) and did not close: narrowing is not the
            # same as closing, and only a hash of the content — which here
            # costs more than the cache — can close it.
            #
            # 🔴 THE REMAINDER IS NAMED AS A NUMBER, NOT AS THE WORD
            # "NANOSECOND". The kernel does not issue a new timestamp on
            # every write: a measurement on 30.08 on this box — 2 753
            # rewrites produced 740 DISTINCT `st_mtime_ns` values, the
            # step between neighboring timestamps being 4.000 ms (median).
            # That is, the key distinguishes 4 ms, not 1 ns, and the
            # margin is exactly 250x.
            "sha256": hashlib.sha256(blob).hexdigest(),
            "built_at": time.time(), "build_ms": round(float(build_ms), 1),
            # THE INPUTS ARE STORED ALONGSIDE THE ENTRY: they show what
            # this scene is grounded in, without running any code. A hash
            # does not show that.
            "inputs": list(inputs or ()),
        }, ensure_ascii=False), encoding="utf-8")
        _COUNTERS["stored"] += 1
        _evict()
        return True
    except Exception:  # noqa: BLE001 — the cache has no right to bring down the response
        _COUNTERS["errors"] += 1
        # 🔴 WE SWALLOW IT FOR THE RESPONSE, BUT NOT FOR THE JOURNAL. There
        # used to be only a counter here, and for nine days the only way
        # to learn about a store that never happened was to ask `stats()`.
        # The write-based check gets FORCIBLY re-verified: the first
        # `store` failure is exactly the event it exists for, and its past
        # green verdict is no longer valid.
        verdict = preflight(force=True)
        if not verdict.get("ok"):
            logger.error("склад кэша сцен отказал: %s", verdict.get("reason"))
        else:
            logger.exception("склад кэша сцен отказал, хотя каталог пишется")
        return False


def _evict() -> None:
    """Eviction by TOTAL size, oldest first. An unlimited cache is a leak
    with a good name."""
    root = cache_dir()
    try:
        blobs = sorted((p for p in root.glob("*.bin")),
                       key=lambda p: p.stat().st_mtime)
        total = sum(p.stat().st_size for p in blobs)
        cap = _max_bytes()
        while total > cap and blobs:
            victim = blobs.pop(0)
            total -= victim.stat().st_size
            victim.unlink(missing_ok=True)
            victim.with_suffix(".json").unlink(missing_ok=True)
            _COUNTERS["evicted"] += 1
    except OSError:
        _COUNTERS["errors"] += 1


def purge() -> int:
    root = cache_dir()
    removed = 0
    try:
        for path in list(root.glob("*.bin")) + list(root.glob("*.json")):
            path.unlink(missing_ok=True)
            removed += 1
    except OSError:
        _COUNTERS["errors"] += 1
    return removed


#: The directory's permissions, WHEN WE ARE THE ONES CREATING IT. `1777` —
#: like `/tmp`: everyone can write, everyone can only delete their own
#: (sticky bit). The owner's decision of 20.08.2026, made by hand after the
#: directory had belonged to `root` for nine days; here it is recorded IN
#: CODE, because `/tmp` does not survive every reboot, and without this
#: line the defect would come back silently.
#:
#: THE COST OF THIS IS NAMED: a shared writable directory in `/tmp` is an
#: attack surface for a local neighbor (planting a blob under someone
#: else's key). The sticky bit blocks deleting someone else's file and
#: does not block overwriting one's own name. The alternative, NOT chosen:
#: a per-user directory (`.../<uid>`) — then everyone has enough
#: permissions and there's nothing to swap, but the service and the waves
#: stop sharing the warm cache, and the owner just chose the shared one.
#: Changing that decision silently is not allowed.
_DIR_MODE = 0o1777

#: The verdict of the write-based check. `None` — never checked, not even
#: once.
_PREFLIGHT: dict[str, Any] | None = None


def preflight(*, force: bool = False) -> dict[str, Any]:
    """CAN WE WRITE HERE — VERIFIED BY WRITING, NOT BY PERMISSIONS.

    🔴 WHY THIS FUNCTION EXISTS, BY MEASUREMENT ON 20.08.2026.
    `/tmp/kir-scene-cache` belonged to `root` (mode 755, entries from
    11.08), the service runs as `kukai`, and `store` had been dropping a
    `PermissionError` into the `errors` counter for nine days. Two calls in
    a row gave `miss`/`miss` with `stored=0`: **the cache looked like it was
    working and cached nothing**, while its own docstring kept promising
    that "the cold open is paid by the first user, not by everyone." Form
    34 — fail-open turns a measurement of the failure into a measurement of
    the subject; the only way to learn about it was from a counter that
    nobody reads.

    WE DO NOT ASK PERMISSION — WE WRITE. `os.access` answers about bits,
    while writes go to the filesystem: a read-only mount, a full disk,
    someone else's ACL, exhausted inodes all give equally green bits and a
    red write. The owner fixed the directory by hand and checked it the
    same way — by writing.

    A REFUSAL CARRIES THE REPAIR COMMAND, not just the diagnosis: "couldn't"
    without "here's what fixes it" turns the log into a complaint.
    """
    global _PREFLIGHT
    if _PREFLIGHT is not None and not force:
        return _PREFLIGHT

    path = cache_dir()
    verdict: dict[str, Any] = {"dir": str(path), "enabled": enabled()}
    if not enabled():
        verdict["ok"] = True
        verdict["reason"] = "кэш выключен переключателем — писать и не должны"
        _PREFLIGHT = verdict
        return verdict

    probe = path / f".probe-{os.getpid()}"
    try:
        created = not path.exists()
        path.mkdir(parents=True, exist_ok=True)
        if created:
            # Only OUR OWN directory: chmod on someone else's would fail
            # anyway, and the attempt would look like a right we don't
            # have.
            try:
                os.chmod(path, _DIR_MODE)
            except OSError:
                logger.debug("cache dir chmod refused for %s", path,
                             exc_info=True)
        probe.write_bytes(b"kir")
        if probe.read_bytes() != b"kir":
            raise OSError("проба записалась и прочиталась иначе")
        verdict["ok"] = True
        verdict["reason"] = "проверено записью"
    except OSError as exc:
        st = None
        try:
            st = path.stat()
        except OSError:
            pass
        owner = mode = "?"
        if st is not None:
            mode = oct(st.st_mode & 0o7777)
            try:
                import pwd
                owner = pwd.getpwuid(st.st_uid).pw_name
            except Exception:  # noqa: BLE001 — there may be no name
                owner = str(st.st_uid)
        verdict["ok"] = False
        verdict["reason"] = (
            f"КЭШ СЦЕН НЕ ПИШЕТСЯ: {type(exc).__name__}: {exc}. Каталог "
            f"{path} принадлежит {owner}, права {mode}; этот процесс идёт под "
            f"{_whoami()}. Пока так — КАЖДЫЙ платит холодное открытие, а не "
            f"первый, и промах неотличим от попадания по времени. Лечится: "
            f"sudo chmod 1777 {path}  (либо KUKAI_KIR_SCENE_CACHE_DIR на "
            f"каталог, доступный службе)")
        # LOUDLY AND ONCE. Quietly is exactly the defect being fixed here.
        logger.error("%s", verdict["reason"])
    finally:
        try:
            probe.unlink()
        except OSError:
            pass
    _PREFLIGHT = verdict
    return verdict


def _whoami() -> str:
    try:
        import pwd
        return pwd.getpwuid(os.geteuid()).pw_name
    except Exception:  # noqa: BLE001
        return str(os.geteuid())


def stats() -> dict[str, Any]:
    out = dict(_COUNTERS)
    out["version"] = CACHE_VERSION
    out["enabled"] = enabled()
    out["dir"] = str(cache_dir())
    # THE WRITE VERDICT SITS ALONGSIDE THE COUNTERS: `stored=0` with
    # `errors=2` and `stored=0` on a cold start look the same but mean
    # different things.
    out["writable"] = preflight()
    try:
        blobs = list(cache_dir().glob("*.bin"))
        out["entries"] = len(blobs)
        out["bytes"] = sum(p.stat().st_size for p in blobs)
    except OSError:
        out["entries"] = 0
        out["bytes"] = 0
    out["max_bytes"] = _max_bytes()
    return out
