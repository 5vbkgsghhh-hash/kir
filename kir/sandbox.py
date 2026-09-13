"""KIR author-script sandbox — execution of PYTHON that writes the IR program.

The model writes python, the python executes here, before any compilation,
and NEVER touches Revit. Exactly one thing comes out: a list of IR
operations, which then goes through the usual proof pipeline (plan_program →
ground → emit → witness → acceptance → gate).

THE SECURITY BOUNDARY IS THE IR GATEWAY, NOT THIS SANDBOX.
Whatever the script does, its only output is the program's JSON, and that
JSON passes the compiler's typed check in full. So the sandbox protects the
BOX (process, memory, disk, network), not the proof model, and its threat
model is a CONFUSED NEURAL NETWORK, not an attacker: an infinite loop,
memory bloat, an accidental disk access, nondeterminism. What honestly
follows from this — in the §"WHAT THIS SANDBOX DOES NOT DO" section below.

ISOLATION LAYERS (bottom to top — from hard to instructive):

  L0  A SEPARATE PROCESS. The parent is not a hostage of foreign code: not
      a single exec() call in our own address space. The interpreter is
      fixed by path, argv is a vector (no shell at all), the environment
      is assembled by us from scratch.
  L1  NAMESPACES (unshare user+mount+net). The network is physically
      unreachable: the new netns has not a single route. This is checked
      by MEASUREMENT on every run (`probe_network`), and under the
      "required" policy network unreachability is a precondition for
      running: if the namespace was not created, the script does not
      execute.
  L2  EMPTY ROOT (chroot into an empty directory after all imports). Even
      code that escapes the restricted builtins to the real `open` will
      not find a single file: /etc/passwd does not exist in its root.
  L3  RLIMIT. RLIMIT_FSIZE=0 (nothing to write — only IR goes into the
      receipt), RLIMIT_AS (memory), RLIMIT_CPU (CPU time), RLIMIT_NPROC=0,
      RLIMIT_NOFILE, RLIMIT_CORE=0. NPROC itself has privileged
      exceptions: the ban on creating processes/threads is separately
      backed by a mandatory child-only libseccomp filter on
      fork/vfork/clone/clone3 with NNP and TSYNC.
  L4  THE WALL. A timeout on the subprocess itself + killing the entire
      process group.
  L5  IMPORT WHITELIST (not a blacklist: a blacklist is always
      incomplete). Exactly math / itertools / functools plus the DSL
      itself, which is handed to the script already imported. A hook on
      the script's __import__ plus a guard in sys.meta_path. Both
      frontiers read the SAME tuple (`policy.allowed_imports`), so they
      cannot drift apart. The operator flag
      KUKAI_IR_AUTHOR_GEOMETRY_LIBS (OFF by default) adds shapely and
      numpy to the list — and touches NOT A SINGLE isolation layer in
      doing so: the C extension is held by the kernel, not by the python
      name list (see `author_geometry_libs_enabled`).
  L6  RESTRICTED BUILTINS. Not "removed" but REPLACED with a stub that
      explains why the name is absent: NameError teaches nothing.
  L7  TYPED REFUSAL. A python exception NEVER surfaces as a raw
      traceback: a KIR-B* code, the exception kind, the message, THE LINE
      NUMBER IN THE MODEL'S SOURCE, and the line itself. Frames from our
      own pipeline never go into the refusal — the model must fix ITS OWN
      code.
  L8  THE EXIT SCREEN. A separate result channel (not stdout: print
      garbage cannot corrupt parsing), a JSON-representability check with
      the path reported, a ceiling on the number of operations and
      bytes, a nondeterminism screen (object address in the output), an
      optional REPLAY run with digest verification.

  L9  ENVIRONMENT SIGNATURE. `author_digest` signs the script's TEXT;
      next to it in the receipt goes `environment` — the interpreter and
      the versions of everything the script could have imported. Without
      it, the same `author_digest` would certify DIFFERENT
      `program_digest` values after a library update, and the reader
      would have no field at all to tell a script edit apart from
      environment drift (see §ENVIRONMENT SIGNATURE below).

WHY NONDETERMINISM IS BANNED OUTRIGHT, NOT BY TASTE: the script's source
is signed in the receipt (`author_digest` below). The signature of a
nondeterministic script signs nothing — on a repeat run it certifies a
different program. Hence: random/time/datetime/os/secrets/uuid are
banned, PYTHONHASHSEED=0 is fixed (traversal order of string sets), id()
is removed.

WHAT THIS SANDBOX DOES NOT DO (honestly, because the real boundary is the
gateway):
  * it is not protection against a deliberate escape from restricted
    builtins. The classic path `().__class__.__base__.__subclasses__()` →
    someone else's `__globals__` → the real `__import__` is closed by
    nothing in CPython except a separate interpreter. And it is not
    closed: escaped code ends up in an empty root, with no network, no
    write access, no fork, with a CPU and memory ceiling — and with its
    only way out through the IR gateway;
  * it does not stop the script from producing a SEMANTICALLY bad
    program: that is the job of plan_program/ground/acceptance, not of
    the sandbox;
  * it does not catch nondeterminism that leaves no trace in the output
    (for example, branching on an object's repr that gives the same
    answer anyway). The `replay_check` option catches only what changes
    the OUTPUT, and that is all that is observable at all;
  * RLIMIT_AS limits the address space, not RSS: the child's peak RSS is
    measured separately (`peak_rss_kb`) and goes into the report as a
    measurement.

CONTRACT WITH THE LANGUAGE (`kir/dsl.py`, written by another agent):
  «исполнить исходник — вернуть список операций либо типизированный
  отказ».
  The sandbox does NOT know the language's grammar. It:
    1. imports the language module BEFORE isolation and places its
       public names directly into the script's namespace (plus the `kir`
       alias), so the script does not need to import the language, and
       is forbidden to;
    2. after execution, assembles the program by the first method that
       fires: the language's drain function (`_DRAIN_CANDIDATES`, the
       live carrier is `dsl.take_ops()`) → the script's OWN variable
       (`ops`/`program`/…) → a call to `build()`. "Own" is checked by
       identity: `ops` from the language is always injected, and
       mistaking it for the author's variable would turn "the script
       collected nothing" into "the script returned a function";
    3. converts the operations to JSON and hands them up together with
       the envelope (`ir_version`/`intent`/`defaults`/`allow_destructive`).
  Modules (ModuleType) from the language's namespace are NEVER injected:
  if dsl.py does `import os`, the script does not get `os` through the
  back door.

COST (measured 03.08 on the prod box, python3.12): the happy path for 40
operations — 121 ms median, peak RSS 24 MB; a 104-operation program —
170 ms. Parallel runs cost linearly: N × (memory_mb + ~21 MB of
interpreter), and that is the only thing the caller must watch if it
decides to run the sandbox in batches.
"""
from __future__ import annotations

import copy
import difflib
import errno
import hashlib
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

# The kind of index and the ceilings live under ONE authority. A top-level
# import, not a lazy one: the module pulls in only `json` and `typing`,
# there is no cycle, and a second copy of the word "full" in this file
# would be exactly the defect the whole package exists against — a
# quantity declared in one place and read in another.
from kir import building_index as _building_index
from kir import env as _env

from kir.diag import (
    Diagnostic,
    KirRefusal,
    SANDBOX_BAD_RESULT,
    SANDBOX_CAPABILITY_ABSENT,
    SANDBOX_CRASH,
    SANDBOX_FORBIDDEN_BUILTIN,
    SANDBOX_FORBIDDEN_IMPORT,
    SANDBOX_MEMORY,
    SANDBOX_NONDETERMINISM,
    SANDBOX_NO_OPS,
    SANDBOX_OUTPUT_LIMIT,
    SANDBOX_PARAM,
    SANDBOX_UNREAD,
    SANDBOX_RECON,
    SANDBOX_RUNTIME,
    SANDBOX_SYNTAX,
    SANDBOX_TIMEOUT,
    SANDBOX_UNAVAILABLE,
)

# ─────────────────────────────────────────────────────────────────────────────
# Contract constants
# ─────────────────────────────────────────────────────────────────────────────

#: The name under which the model's source is visible to the interpreter.
#: Internal: it is used to pick out traceback frames belonging to the
#: MODEL and discard our own.
SCRIPT_FILENAME = "<kir-script>"


def author_frames(frame=None) -> list[int]:
    """Lines of the AUTHOR's script in the LIVE stack, outermost to
    innermost.

    ONE TRAVERSAL CARRIER FOR THREE CONSUMERS, and this is not tidying
    up. Before 27.08.2026 the frame traversal was written in this file
    TWICE — `_on_xcpu` (the live frame) and `script_frames` (the
    traceback) — and a third consumer became the operation's provenance
    (`dsl.Program._append`). A third copy of the selection rule would
    have drifted from the first two on the very first edit to
    `SCRIPT_FILENAME`: this tree's named defect — a quantity declared in
    one place and read in another.

    THE LIST'S SHAPE IS THE SAME AS `script_frames`'s: outermost to
    innermost, so `[-1]` is the innermost frame — the very line where it
    all happens. The shapes must match: both chains are printed by the
    same `SandboxRefusal.render()`, and a reversed order would give the
    reader two different meanings under one name.

    `f_back` goes from the inside out, so the reversal belongs here, not
    at the caller: a reversal repeated at every consumer is exactly the
    second carrier this function eliminates.

    Outside the sandbox it returns EMPTY — there is no author script
    there at all, and an empty chain is more honest than a substituted
    foreign line (form 44: a plausible value is more dangerous than an
    absence — nobody argues with it).
    """
    if frame is None:
        frame = sys._getframe(1)
    out: list[int] = []
    while frame is not None:
        if frame.f_code.co_filename == SCRIPT_FILENAME:
            out.append(frame.f_lineno)
        frame = frame.f_back
    out.reverse()
    return out

#: Exactly what is allowed to be imported. A whitelist, not a blacklist.
#:
#: 🔴 THE COMPOSITION IS A DECISION, NOT A MEASUREMENT, AND THIS IS
#: STATED HERE BECAUSE THERE WAS NO ONE TO ASK. On 20.08.2026 the refusal
#: corpus (`data/telemetry/kir_rejections.jsonl`, 2395 lines, window
#: 16.07 → 19.08) was checked against the question «какие импорты модель
#: пробовала и получила отказ»: lines from the sandbox there are **0 out
#: of 2395** — the feed is fed by COMPILER refusals (`coverage_feed`,
#: keys `reject_code`/`op_requested`), and `KIR-B004` does not land in it
#: at all. Zero here means «спрашивать не у кого», not "the model never
#: stumbled" (form 4: for every zero from the corpus, first ask whether
#: the corpus is reachable).
#:
#: Added on 20.08 — for the structure of INTENT, not for computation:
#: `collections` (namedtuple/deque/defaultdict — a dot with field names
#: instead of `p[0]`), `dataclasses`, and `typing`. This is exactly what
#: an LLM habitually uses to structure a description, and a refusal here
#: costs the model a turn retreating to tuples. Verified by EXECUTION
#: against the prod policy, not by reasoning, and `dataclasses` in the
#: process earned itself two fixes below (compilation and frame
#: registration) — on its own it failed with someone else's error.
#:
#: `__future__` is the fourth, and it is SPECIAL: it is not a library
#: but a compiler directive, it has no runtime surface at all. It is
#: here because `from __future__ import annotations` is the most common
#: first line of modern python, and a refusal on it reads to the model
#: as «питон тут обрезан». Measured 20.08: with it in the list, a script
#: under PEP 563 passes in full.
#:
#: What is not here and why: `statistics`/`hashlib`/`time` — the
#: NONDETERMINISM family in `_import_reason` (the script's signature in
#: the receipt), `os`/`sys` — the system family, `re`/`decimal`/`heapq`
#: — not refused, but NOT REQUESTED by anyone: extending the whitelist
#: by guesswork means paying for describing a capability nobody asked
#: for.
ALLOWED_IMPORTS: tuple[str, ...] = (
    "math", "itertools", "functools",
    "collections", "dataclasses", "typing", "__future__")

#: Geometry libraries that the OPERATOR FLAG adds to the whitelist. On
#: their own they open nothing — see `author_geometry_libs_enabled`.
GEOMETRY_IMPORTS: tuple[str, ...] = ("shapely", "numpy")

#: The name of the operator flag — HERE ONLY FOR READING FROM THE
#: OUTSIDE (tests, documentation). In the gate itself,
#: `author_geometry_libs_enabled`, it is written as a LITERAL, and this
#: is not an oversight-driven duplication: `tools/capability_map.py`
#: looks for flags by regex, `os.getenv("ИМЯ")`, over the text, and a
#: call through the constant the inventory WILL NOT SEE — the flag would
#: become invisible, that is, sitting in the store by construction. That
#: the names have not drifted apart is held by a test
#: (`test_author_geometry_libs`), not by an agreement.
AUTHOR_GEOMETRY_LIBS_FLAG = "KUKAI_IR_AUTHOR_GEOMETRY_LIBS"

#: OPERATOR SWITCHES that reach the child. A whitelist, not a blacklist,
#: and short on purpose: the child's environment is assembled by us from
#: scratch, not inherited, so "forgot to carry it over" here looks like
#: «оператор выключил» — a silent disagreement with the service that is
#: not observable in any way at all.
#: The script cannot see them: `os` is unreachable to it, neither by
#: import nor by injection. Determinism does not suffer — this is a
#: switch position, not time, not chance.
#:
#: TWO TELEMETRY ADDRESSES ARE HERE BY MEASUREMENT OF 14.08.2026, not
#: for completeness. The child also compiles (the course runs its
#: recipes through the real sandbox), and a compilation refusal writes a
#: line to the refusal feed. The child's environment is assembled from
#: scratch, so an address that was NOT CARRIED OVER is read by it as
#: «адрес установки» — that is, a LIVE corpus, even when the parent has
#: been moved to /tmp. The parent half is closed by the root-level
#: `conftest.py`; without these two lines the other half would remain
#: open, and an instrument that closes off half its range is more
#: dangerous than one that is absent. In prod neither variable is set —
#: so carrying them over changes nothing. What is carried over IS NAMED
#: BY ITS NEW NAME, and the old one arrives WITH IT AUTOMATICALLY.
#:
#: 🔴 WHY A DERIVATION, NOT A LIST (28.08.2026). A flat tuple used to
#: stand here, and it held `KUKAI_CHECKER_V2` and
#: `KUKAI_IR_DSL_OP_CEILING`. That day both names moved to `KIR_*`
#: (`kir/env.py`) — and the list stayed as it was. A parent that has the
#: NEW name set assembled the child's environment WITHOUT it: the flag
#: inside the sandbox read as «оператор выключил», and the verdict
#: would answer «включите то, что уже включено». Exactly the refusal
#: this tuple exists against.
#:
#: That is why the NEW names are the ones enumerated, and the old ones
#: are taken from the same table that relocated them: the two lists
#: about ONE subject have nothing left to drift apart on.
_CARRIED_NEW: tuple[str, ...] = (
    "KIR_CHECKER_V2", "KIR_REJECTIONS_PATH", "KIR_WITNESS_PATH",
    # 🔴 THE BUILDER'S OP CEILING. The script executes in a SEPARATE
    # process, and without carrying the variable over, the ceiling's
    # behavior is unverifiable: the test guarding the census in the
    # budget refusal would otherwise have to build 200,001 ops and die
    # on memory. Introduced 21.08.2026 together with the variable
    # itself.
    "KIR_DSL_OP_CEILING")

ENV_PASSTHROUGH: tuple[str, ...] = tuple(dict.fromkeys(
    name
    for new in _CARRIED_NEW
    for name in (new, _env.RENAMED.get(new))
    if name))
_ENV_PASSTHROUGH = ENV_PASSTHROUGH

#: The sandbox's transport ceiling. NOT to be confused with the
#: compiler's budgets (the author-facing `MAX_OPS_PER_PROGRAM` and the
#: post-macro `MAX_VALIDATED_OPS`): those are counted LATER and measure
#: the author's intent, while this one measures the pipe.
#:
#: 🔴 THE NUMBERS WERE REMOVED FROM HERE ON 20.08.2026, AND THIS IS NOT
#: LAZINESS. This used to say «MAX_OPS_PER_PROGRAM=20 /
#: MAX_VALIDATED_OPS=320», while the live values are 1000 and 22000
#: (asked from `compiler`, not recalled from memory). The difference is
#: one and a half orders of magnitude, and it would have read as a fact
#: about the product. There is no need to repeat the value next to its
#: name: the name itself is the address at which it is asked for. The
#: same grep BY NUMBER found 21 such spots in the tree, including the
#: canon itself.
# 🔴 RAISED ON 20.08.2026 together with the author-facing budget (1000
# -> 100 000): this limit is a TRANSPORT one and must stay ABOVE the
# author's, otherwise it substitutes itself for the compiler's budget
# and refuses before it does — that is, the author gets «песочница»
# where the fault lies with their design. Kept with headroom for macro
# expansion, same as `MAX_VALIDATED_OPS`.
MAX_SCRIPT_OPS = 400_000
MAX_RESULT_BYTES = 8 * 1024 * 1024
MAX_SOURCE_BYTES = 256 * 1024
MAX_STDOUT_CHARS = 4000
MAX_JSON_DEPTH = 32

#: Resource defaults. Chosen so the prod box does not notice the run:
#: 256 MB of address space is ~254 MB of worst-case peak RSS (measured:
#: string bloat runs right into the limit).
DEFAULT_CPU_SECONDS = 5.0
DEFAULT_WALL_SECONDS = 8.0
DEFAULT_MEMORY_MB = 256
DEFAULT_RECURSION_LIMIT = 500
DEFAULT_NOFILE = 64

#: NAMES THAT THE SANDBOX PUTS INTO THE SCRIPT'S NAMESPACE ITSELF — not
#: through `course.SANDBOX_NAMES` and not through `dsl`. The list is
#: CLOSED AND COMPLETE BY CONSTRUCTION: the injection below checks
#: against it and REFUSES on any discrepancy, so a third name cannot be
#: introduced silently.
#:
#: 🔴 WHY A CONSTANT, NOT TWO ASSIGNMENTS (measured 15.08.2026). The
#: guard `tests/test_sandbox_names_are_declared.py` declares that it
#: checks EVERY name in the script's namespace, and its scope is
#: `dsl.__all__ | SANDBOX_NAMES`. Names from here were not included in
#: that scope AT ALL: `model` lived unchecked from the moment the
#: catalog appeared, and `building` would have gone the same way. An
#: instrument that covers only part of its own range is this tree's
#: named defect, and here it was.
HOST_NAMES: tuple[str, ...] = ("model", "building", "param")

#: Limits on declaring sliders. ASSIGNED, and named so this is visible.
#: The lower bound is derived: zero parameters — a program without
#: sliders, which is legal and costs nothing. The upper one is a
#: decision: a set of a hundred knobs stops being a set of knobs and
#: becomes a second source file that nobody reads. Allowed to raise by
#: measurement, forbidden to raise silently.
#: 🔴 STDIN FRAME VERSION TAG. INTRODUCED AT THE COST OF A BROKEN PROD
#: ON 20.08.2026.
#:
#: A SHAPE WE HAD NOT WRITTEN DOWN: the rule "edits in the tree do not
#: affect the service before a restart" HAS A HOLE, EXACTLY IN THE
#: SANDBOX. The parent lives in the service's memory and waits for
#: deployment, while the CHILD is a fresh process that imports
#: `kir.sandbox` FROM DISK on every run. That is, the sandbox deploys
#: ITSELF, instantly and without anyone's decision.
#:
#: Measured: the service came up at 19:19, `sandbox.py` was edited at
#: 20:25 — the parent wrote a frame with two headers, the child parsed
#: it expecting three, and the live `program_py` path answered real
#: users with `KIR-B011 кадр повреждён`.
#:
#: WHY COMPATIBILITY, NOT JUST A VERSION. A version in the header turns
#: an unintelligible breakage into a named refusal — and leaves prod
#: down until a restart. The desync here is ONE-DIRECTIONAL by
#: construction: the child is always the freshest, the parent is always
#: the same version or older. So it is enough for a NEW child to read a
#: frame from an OLD parent, and then a format edit stops being an
#: event for prod at all. The version stays — but for the case we have
#: not seen yet: a frame from the future.
FRAME_MARKER = b"KIRFRAME2"

MAX_PARAMS = 64
MAX_PARAM_NAME = 48

#: The order in which the language is polled: the first function that
#: fires collects the accumulated ops.
_DRAIN_CANDIDATES = ("take_ops", "drain_ops", "drain", "collect_ops",
                     "collect", "pop_ops", "emitted_ops", "flush_ops")
#: Script variables that may hold a ready-made program.
_NS_CANDIDATES = ("ops", "OPS", "program", "PROGRAM", "result", "RESULT")
#: Script functions that will return the program if it is not in a
#: variable.
_BUILD_CANDIDATES = ("build", "build_program", "main")

#: Program envelope fields that the script is allowed to set itself.
#: They match the compiler's `known_top`: the envelope must arrive
#: whole, otherwise the caller reassembles it by eye and loses what the
#: author stated explicitly.
#:
#: `phases` is AN EXCEPTION TO THIS MATCH, and a deliberate one. The
#: phase table is placed by `course.take_ops` (the boundaries the
#: author drew via `phase()`); the compiler's `known_top` does NOT know
#: it YET, so a program with phases, submitted as ONE program, gets a
#: typed refusal, KIR-P003, instead of silently executing as one
#: transaction. Phase-by-phase execution is separate work
#: (`serving.py`); until it exists, fail-closed here is the correct
#: behavior: there is no checkpoint between phases yet, and pretending
#: silently that there is one is not allowed.
#: 🔴 `units` WAS ADDED ON 25.08.2026 — THE FOURTH BREAK IN ONE CHAIN.
#:
#: Three links of the intent chain (`course.unit()` -> the model's
#: receipt) were fixed the same day: the plan learned to CARRY the
#: table, `_units_of` learned to READ it, the receipt learned to COPY
#: it. And none of that gave ANYTHING on the path the model actually
#: walks: a script through the sandbox.
#:
#: Live run: `with unit("санузел"): create_wall(...)` gives the
#: envelope `{"ir_version": "1.0"}` — and nothing else. `course.take_ops()`
#: assembles the table CORRECTLY (keys `ir_version`, `ops`, `units`),
#: and this loop discarded it without a single word, because the name
#: was not in the list. The same script with `phase()` instead of
#: `unit()` did get its envelope.
#:
#: BOTH ENDS OF THE PIPE WERE BUILT AND WAITING: `compiler.known_top`
#: knows `units` and has accepted it from the very start. ONE NAME was
#: missing from the filter list — and that is exactly why a filter list
#: is dangerous: it stays silent about what it discarded.
# 2026-09-05: do not keep a second allow-list here. These are examples of
# program fields, not permission to silently drop the author's unknown keys.
# The compiler owns semantic acceptance; harvesting preserves the entire
# explicit envelope so an unsupported field can receive its named refusal.

#: 🔴 THE ENVELOPE IS OUR CONCERN, NOT THE AUTHOR'S (measured
#: 16.08.2026, a live owner turn). `SANDBOX_NO_OPS` above declares the
#: list in the `ops` variable a LEGITIMATE alternative to language
#: calls — and it worked up to the compiler, then died there: the
#: knobs path stamps `ir_version` in `Program.build()` (`dsl.py`), the
#: envelope-variable path has none at all, and the author got
#: `KIR-P004 ir_version обязателен` — about a field they never wrote
#: and do not know about from the tool's description.
#:
#: Measured on a live turn: the model got this refusal twice, went off
#: to fix the WRONG thing twice, and the turn ended having built
#: nothing.
#:
#: We ADVERTISE the path and do not finish building it — that is our
#: defect, not the author's mistake, so it is cured by finishing the
#: build, not by a better refusal. We stamp ONLY what is missing: an
#: envelope with an EXPLICITLY WRONG version must still get
#: `KIR-P004`, because there the author told an untruth about the
#: version rather than staying silent. Two different facts — two
#: different outcomes (`tests/test_envelope_is_ours.py`).
#:
#: We do NOT write the version as a literal: a second place obligated
#: to match the registry is exactly this tree's named defect. We ask
#: the authority, lazily — the import lives in the PARENT
#: (`_result_from_payload`), the child does not need the registry for
#: this.
def _ir_version() -> str:
    """The IR version from its SOLE owner — the registry."""
    from kir.spec import IR_VERSION
    return IR_VERSION

#: The trace of a default repr is an object's address. The only kind of
#: nondeterminism that is VISIBLE in the output, which is exactly why
#: it is caught by the screen, not by a sermon.
_ADDRESS_RE = re.compile(r"<[^<>]{0,120}?\bat 0x[0-9a-fA-F]{4,}>")

_CLONE_NEWNS = 0x00020000
_CLONE_NEWUSER = 0x10000000
_CLONE_NEWNET = 0x40000000

# Public libseccomp ABI constants, NOT architecture-specific syscall numbers.
# https://github.com/seccomp/libseccomp/blob/main/include/seccomp.h.in
_SCMP_ACT_ALLOW = 0x7FFF0000
_SCMP_ACT_ERRNO = 0x00050000
_SCMP_FLTATR_CTL_NNP = 3
_SCMP_FLTATR_CTL_TSYNC = 4
_PROCESS_CREATION_SYSCALLS = ("fork", "vfork", "clone", "clone3")


def _load_process_creation_guard():
    """Load the trusted OS library before chroot; never install in the parent."""
    import ctypes

    class Version(ctypes.Structure):
        _fields_ = [("major", ctypes.c_uint), ("minor", ctypes.c_uint), ("micro", ctypes.c_uint)]

    library = ctypes.CDLL("libseccomp.so.2", use_errno=True)
    signatures = {
        "seccomp_init": ([ctypes.c_uint32], ctypes.c_void_p),
        "seccomp_release": ([ctypes.c_void_p], None),
        "seccomp_attr_set": ([ctypes.c_void_p, ctypes.c_int, ctypes.c_uint32], ctypes.c_int),
        "seccomp_syscall_resolve_name": ([ctypes.c_char_p], ctypes.c_int),
        "seccomp_rule_add_array": ([ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int,
                                     ctypes.c_uint, ctypes.c_void_p], ctypes.c_int),
        "seccomp_load": ([ctypes.c_void_p], ctypes.c_int),
        "seccomp_arch_native": ([], ctypes.c_uint32),
        "seccomp_version": ([], ctypes.POINTER(Version)),
    }
    for name, (arguments, result) in signatures.items():
        function = getattr(library, name)
        function.argtypes, function.restype = arguments, result
    return library


def _install_process_creation_guard(library) -> dict:
    """Deny new processes/threads in THIS child, including prewarmed threads.

    RLIMIT_NPROC is not enough for a process retaining the root kernel identity
    after unshare. libseccomp resolves native syscall names and supplies its
    architecture guard; non-native ABIs keep the library's kill default. NNP
    and TSYNC are mandatory. No silent partial filter or broader syscall policy.
    https://libseccomp.readthedocs.io/en/latest/man/man3/seccomp_attr_set.3/
    https://libseccomp.readthedocs.io/en/latest/man/man3/seccomp_rule_add.3/
    """
    context = library.seccomp_init(_SCMP_ACT_ALLOW)
    if not context:
        raise RuntimeError("process guard allocation failed")
    try:
        for attribute in (_SCMP_FLTATR_CTL_NNP, _SCMP_FLTATR_CTL_TSYNC):
            if library.seccomp_attr_set(context, attribute, 1) != 0:
                raise RuntimeError("process guard synchronization/NNP unavailable")
        for name in _PROCESS_CREATION_SYSCALLS:
            number = library.seccomp_syscall_resolve_name(name.encode("ascii"))
            # -1 is __NR_SCMP_ERROR; other negative pseudo syscall IDs are
            # valid libseccomp values and must be handled by the library.
            if number == -1 or library.seccomp_rule_add_array(
                    context, _SCMP_ACT_ERRNO | errno.EAGAIN, number, 0, None) != 0:
                raise RuntimeError("process creation syscall filter unsupported: " + name)
        if library.seccomp_load(context) != 0:
            raise RuntimeError("process creation filter was not installed")
        version = library.seccomp_version().contents
        return {"state": "denied", "mechanism": "libseccomp", "library_version":
                [version.major, version.minor, version.micro], "syscalls": list(_PROCESS_CREATION_SYSCALLS),
                "errno": errno.EAGAIN, "thread_synchronization": True, "no_new_privileges": True,
                "native_architecture": library.seccomp_arch_native()}
    finally:
        # Frees userspace construction data; does NOT remove the kernel filter.
        library.seccomp_release(context)


# ─────────────────────────────────────────────────────────────────────────────
# Policy
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SandboxPolicy:
    """Exactly what this run is allowed to do. Everything numeric lives
    here, so a refusal can NAME the exhausted limit instead of saying
    «слишком много»."""

    cpu_seconds: float = DEFAULT_CPU_SECONDS
    wall_seconds: float = DEFAULT_WALL_SECONDS
    memory_mb: int = DEFAULT_MEMORY_MB
    max_ops: int = MAX_SCRIPT_OPS
    max_result_bytes: int = MAX_RESULT_BYTES
    max_source_bytes: int = MAX_SOURCE_BYTES
    max_stdout_chars: int = MAX_STDOUT_CHARS
    recursion_limit: int = DEFAULT_RECURSION_LIMIT
    nofile: int = DEFAULT_NOFILE
    allowed_imports: tuple[str, ...] = ALLOWED_IMPORTS

    #: "required"    — no network namespace ⇒ the run is cancelled
    #:                 (fail-closed: the promise of «ноль сети» is
    #:                 either proven, or it isn't);
    #: "best_effort" — we try, and on a kernel refusal we keep going and
    #:                 write that into `isolation` honestly;
    #: "off"         — leave the namespaces alone (for boxes without userns).
    network: str = "required"
    #: chroot into an empty directory after imports. Turned off if the
    #: language reports a LAZY import (see KIR-B012: the refusal will
    #: name this switch).
    filesystem_isolation: bool = True
    #: A network measurement on every run, instead of relying on intent.
    probe_network: bool = True
    #: Run the script twice and compare the program digest. Twice as
    #: expensive, but it turns "nondeterminism is forbidden" from a rule
    #: into a measurement.
    replay_check: bool = False

    #: The module whose public names are placed into the script's
    #: namespace.
    #:
    #: `course.language` is `dsl` PLUS the course's names
    #: (`course.SANDBOX_NAMES`), glued together with no semantics of its
    #: own. The language does not change from the gluing: a script
    #: written for `kir.dsl` works here without a single edit — the
    #: function objects are the same.
    #:
    #: **THE COMPOSITION IS NOT ENUMERATED HERE, AND THIS IS A DECISION,
    #: NOT LAZINESS.** The line lied twice: first it named four names
    #: out of six, then seven out of eight (`phase` was wired in and the
    #: line was not updated). A listing living as a copy next to the
    #: original always drifts from it — the only question is whether
    #: anyone notices. Ask `course.SANDBOX_NAMES` — there it exists once
    #: and is correct by definition; how many there are right now is
    #: printed by `tests/test_sandbox_names_are_declared.py`, which also
    #: requires that every name be either described to the model or
    #: declared dark with a reason.
    #:
    #: WHY A DEFAULT, NOT AN OPTION. A course behind a switch is a
    #: course that does not exist for the model; and what that ends in
    #: has now been measured: `create_group` was called ZERO times
    #: across 51,574 raised operations, and `sdk.py` lay excellent and
    #: unreachable for five weeks. A capability with no path to it from
    #: the real entry point does not exist (the law of reachability,
    #: `tests/capability_reachability`).
    #:
    #: The cost of a permanent presence has been measured and is small:
    #: the pointer is 176 tokens, a typical lesson request ~1,076, the
    #: whole course 10,808 — against 7,140 for `skill.py`, which is
    #: paid on EVERY request. (Measured 03.08; since then the pointer
    #: has gained a seventh name and stayed below its limit — held by
    #: `test_course.test_the_pointer_is_small_enough_to_hang_permanently`,
    #: not by this line.)
    dsl_module: str = "kir.course.language"
    extra_sys_path: tuple[str, ...] = ()
    python_exe: str = ""

    def __post_init__(self) -> None:
        """Reject misspelled/degraded policy before a child can be started.

        Explicit off/best_effort networking remains a caller choice. Requested
        filesystem isolation and OS limits, however, must actually be applied.
        This validates configuration, not hostile-code containment or portability.
        """
        for name in ("cpu_seconds", "wall_seconds"):
            value = getattr(self, name)
            try:
                valid = type(value) in (int, float) and math.isfinite(value) and value > 0
            except OverflowError:
                valid = False
            if not valid:
                raise ValueError(f"{name} must be a finite positive number")
        for name in ("memory_mb", "max_ops", "max_result_bytes", "max_source_bytes",
                     "max_stdout_chars", "recursion_limit", "nofile"):
            value = getattr(self, name)
            if type(value) is not int or not 0 < value <= sys.maxsize:
                raise ValueError(f"{name} must be a positive platform-sized integer")
        if type(self.network) is not str or self.network not in {"required", "best_effort", "off"}:
            raise ValueError("network must be required, best_effort or off")
        for name in ("filesystem_isolation", "probe_network", "replay_check"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be bool")
        module_pattern = r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*"
        if type(self.dsl_module) is not str or re.fullmatch(module_pattern, self.dsl_module) is None:
            raise ValueError("dsl_module must be a dotted module name")
        for name in ("allowed_imports", "extra_sys_path"):
            values = getattr(self, name)
            if type(values) is not tuple or any(type(value) is not str or not value.strip()
                                               or "\0" in value for value in values):
                raise ValueError(f"{name} must be a tuple of nonempty strings")
        if any(re.fullmatch(module_pattern, value) is None for value in self.allowed_imports):
            raise ValueError("allowed_imports must contain dotted module names")
        if type(self.python_exe) is not str or "\0" in self.python_exe:
            raise ValueError("python_exe must be a string without NUL")

    def child_config(self) -> dict:
        return {
            "cpu_seconds": self.cpu_seconds,
            "wall_seconds": self.wall_seconds,
            "memory_mb": self.memory_mb,
            "max_ops": self.max_ops,
            "max_result_bytes": self.max_result_bytes,
            "max_stdout_chars": self.max_stdout_chars,
            "recursion_limit": self.recursion_limit,
            "nofile": self.nofile,
            "allowed_imports": list(self.allowed_imports),
            "network": self.network,
            "filesystem_isolation": self.filesystem_isolation,
            "probe_network": self.probe_network,
            "dsl_module": self.dsl_module,
            "extra_sys_path": list(self.extra_sys_path),
        }


DEFAULT_POLICY = SandboxPolicy()


# ─────────────────────────────────────────────────────────────────────────────
# Refusal
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SandboxRefusal:
    """The sandbox's typed refusal.

    `message_ru` is exactly what the model will see. It never carries
    internal frames; the operator-level detail lives in `detail` and is
    not shown upward.
    """

    code: str
    message_ru: str
    kind: str                       # kind: the exception class name, or a mechanism
    #: whose fault this is. "author" — the model fixes it; "sandbox" —
    #: we fix it; "unknown" — the process died without saying.
    blame: str = "author"
    line: Optional[int] = None      # LINE NUMBER IN THE MODEL'S SOURCE
    line_text: Optional[str] = None
    #: the chain of script lines bottom to top (called from…), model
    #: frames only
    script_frames: list[int] = field(default_factory=list)
    detail: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        out = {
            "code": self.code,
            "message_ru": self.message_ru,
            "kind": self.kind,
            "blame": self.blame,
        }
        if self.line is not None:
            out["line"] = self.line
        if self.line_text is not None:
            out["line_text"] = self.line_text
        if self.script_frames:
            out["script_frames"] = list(self.script_frames)
        if self.detail:
            out["detail"] = dict(self.detail)
        return out

    def render(self) -> str:
        """The refusal text through the model's eyes: code, gist, location."""
        head = f"{self.code}: {self.message_ru}"
        if self.line is not None:
            text = (self.line_text or "").strip()
            head += f"\nстрока {self.line}"
            if text:
                head += f": {text}"
            if len(self.script_frames) > 1:
                chain = " ← ".join(str(n) for n in reversed(self.script_frames))
                head += f"\nцепочка строк скрипта: {chain}"
        return head

    def to_diagnostic(self) -> Diagnostic:
        """A projection onto the compiler's common diagnostics envelope."""
        return Diagnostic(code=self.code, message_ru=self.render())

    @classmethod
    def from_dict(cls, raw: dict) -> "SandboxRefusal":
        return cls(
            code=str(raw.get("code") or SANDBOX_UNAVAILABLE),
            message_ru=str(raw.get("message_ru") or ""),
            kind=str(raw.get("kind") or "unknown"),
            blame=str(raw.get("blame") or "unknown"),
            line=raw.get("line"),
            line_text=raw.get("line_text"),
            script_frames=list(raw.get("script_frames") or []),
            detail=dict(raw.get("detail") or {}),
        )


class SandboxResultContradiction(ValueError):
    """A receipt that contradicts itself. The refusal is TYPED and names both halves."""


@dataclass
class SandboxResult:
    """The result of execution: either operations, or a refusal. There
    is no third option.

    🔴 "THERE IS NO THIRD OPTION" WAS THE DOCSTRING'S PROMISE UNTIL
    02.09.2026, AND A THIRD ONE WAS BEING BUILT. Measured by execution:
    all three impossible shapes were being constructed silently —

        SandboxResult(ok=True, ops=[], refusal=<отказ>)   a green receipt
                                                           WITH A REFUSAL
                                                           INSIDE
        SandboxResult(ok=True, ops=[])                    "succeeded," having
                                                           built NOTHING
        SandboxResult(ok=False, ops=[оп])                 "failed," while
                                                           carrying a
                                                           program and NOT
                                                           NAMING the reason

    The first is a falsely-green receipt in pure form: the reader sees
    `ok`, while a refusal sits inside. This is the very kind marked in
    the registry on 31 of 75 open P0s ("a silently wrong result," "a
    falsely-green instrument").

    What is legal was MEASURED, not deduced: 15 real scripts (nine
    course recipes, an empty one, read-only, a forbidden import, broken
    syntax, a language refusal) produced EXACTLY TWO shapes —
    `(ok, без отказа, с операциями)` and `(не ok, с отказом, без
    операций)`. Neither an empty program nor an exploratory turn turned
    out to be an exception: they have their own NAMED refusals
    (`KIR-B007` «программа пуста», `KIR-B013` «разведочный ход»).
    """

    ok: bool
    ops: list[dict] = field(default_factory=list)
    refusal: Optional[SandboxRefusal] = None
    #: a signature of the EXACT source bytes — what goes into the receipt
    author_digest: str = ""
    #: THE SIGNATURE OF THE CATALOG handed to this run (empty — no
    #: catalog was supplied). A third signatory alongside `author_digest`
    #: and `environment`, and for the same reason: the same source over
    #: a DIFFERENT document gives a different program, and without this
    #: field the reader cannot tell a script edit apart from model
    #: drift.
    model_digest: str = ""
    #: a signature of the BUILDING INDEX — a fourth signatory of the
    #: same kind as the catalog and the environment. Without it, one
    #: `author_digest` would certify different programs after a
    #: BUILDING edit, and the reader would not be able to tell a script
    #: edit apart from model drift — exactly the argument recorded at
    #: `model_digest` above.
    building_digest: str = ""
    #: THE SIGNATURE OF THE SUPPLIED PARAMETERS — a fifth signatory of
    #: the same kind as the catalog, the building index, and the
    #: environment, and it was introduced FOR ONE DISTINCTION.
    #:
    #: 🔴 Before it, the receipt could not tell "the author rewrote the
    #: definition" apart from "the caller moved a slider": both
    #: produced a different `program_digest` under the same
    #: `author_digest`, and the only way to read that was as drift. Now
    #: it reads as a pair: same `author_digest` + a different
    #: `params_digest` — a knob was moved; a different `author_digest`
    #: — the definition was rewritten. Exactly the same argument
    #: recorded at `model_digest`, and this is no coincidence: a
    #: signatory is introduced every time one source legitimately gives
    #: rise to different programs.
    params_digest: str = ""
    #: THE SLIDER LEDGER: what the author declared, what the caller
    #: supplied, what came out. This is exactly why the slider exists as
    #: a separate capability rather than as `params.get(...)`: a set of
    #: declared knobs with bounds is what a slider is drawn from, and
    #: there is no way to obtain it other than by executing the script.
    params: list = field(default_factory=list)
    #: digest of the issued program: checked during replay_check
    program_digest: str = ""
    #: the envelope, if the script set it (intent/defaults/allow_destructive)
    envelope: dict = field(default_factory=dict)
    #: what the script printed. This is FEEDBACK for the model, not a
    #: result channel: the result travels over a separate descriptor and
    #: is not corrupted by print garbage.
    stdout: str = ""
    #: PROGRAMS THE AUTHOR LEFT BEHIND. The door builds the script's
    #: CURRENT program; `reset()` starts a new one, and nobody will ever
    #: build the previous one. Our own «жильё» recipe is written as two
    #: programs (`KIR-L002`: the staircase owns its own transactions) —
    #: and the staircase used to vanish SILENTLY. This does not change
    #: WHAT gets executed: it NAMES the LOSS.
    left_behind: list = field(default_factory=list)
    #: the MEASURED (not intended) isolation state of this run
    isolation: dict = field(default_factory=dict)
    #: WHAT the script was executed WITH: the interpreter and the
    #: versions of everything it could have imported
    #: (`environment_signature`). A separate field, not inside
    #: `isolation`: isolation answers "what the sandbox DID," environment
    #: answers "what this was computed on," and gluing two different
    #: questions into one dict means hiding the second one. Empty exactly
    #: when the child never ran.
    environment: dict = field(default_factory=dict)
    #: THE COURSE-READ LEDGER for this run: `course`/`recipe`/`spec`/
    #: `preview`/`design_check`/`score` — what the author asked and how
    #: many characters they were given back. Set up inside the sandbox
    #: (`kir.course._note_read`) and travels over THIS channel because
    #: the child has no other: network and filesystem are taken away
    #: from it by construction.
    #:
    #: Empty means "the course was never called." This is a LEGITIMATE
    #: and the most common outcome, not a gap: until 22.08.2026 there
    #: was nothing in any corpus to tell it apart from "it was called,
    #: but we did not record it" — see the argument at the ledger
    #: itself.
    course_reads: list = field(default_factory=list)
    #: THE PROVENANCE OF EACH OPERATION: `{id опа: [строки скрипта
    #: снаружи внутрь]}`.
    #:
    #: 🔴 WHY (27.08.2026). On a FAILING script the model has long
    #: gotten its own line — `SandboxRefusal.line`/`script_frames`. A
    #: SUCCESSFULLY assembled op had none, and the COMPILER's refusal
    #: arrives exactly then: python has already run, the program is
    #: assembled, and the 41st operation out of sixty fails. The model
    #: got an `op_id` and did not know which line of ITS OWN code
    #: produced this op — it fixed things by rereading itself and
    #: guessing.
    #:
    #: WHY A SIDECAR, NOT AN OPERATION FIELD. Verified by execution:
    #: `_src_line` inside the op and `_lineage` in the envelope both
    #: produce `KIR-P003` — the compiler fail-closes on an unfamiliar
    #: field in both forms. And that is correct: provenance MUST NOT
    #: change the program's identity, otherwise the same intent, written
    #: two different ways, would give different `plan_digest` values.
    #: The sidecar sits alongside, keyed by `id`, OUTSIDE the plan's
    #: signature.
    #:
    #: A CHAIN, NOT A SINGLE LINE: a call through the author's own
    #: function gives a line INSIDE the function, and the call site is
    #: outside it, and the author needs both. The shape is the same as
    #: `SandboxRefusal.script_frames` (outermost to innermost).
    #:
    #: Empty is a legitimate outcome: the script did not go through the
    #: sandbox, or the language was called directly. Empty is more
    #: honest than a substituted foreign line.
    lineage: dict = field(default_factory=dict)
    duration_s: float = 0.0
    #: peak RSS of EXACTLY THIS run (the child's `VmHWM`, KB). Zero
    #: means the child died without saying: it must not lie using the
    #: parent's watershed value, which depends on who ran earlier (see
    #: `_read_vm_hwm`).
    peak_rss_kb: int = 0

    def __post_init__(self) -> None:
        """THERE IS NO THIRD OPTION — NOW BY CONSTRUCTION, NOT BY THE
        DOCSTRING'S PROMISE.

        Three impossible shapes, each a falsely-green or a mute
        receipt. The refusal is typed and names BOTH halves of the
        contradiction: the reader does not need "wrong" — they need to
        know WHAT disagrees with WHAT.

        The check sits IN THE CONSTRUCTOR, not at the consumer: the
        receipt has many consumers (`serving`, `program_py`, tests,
        other doors), and a rule living at one of them does not help
        the other. It cannot be bypassed here without rewriting the
        class itself.
        """
        if self.ok and self.refusal is not None:
            raise SandboxResultContradiction(
                f"ok=True при отказе {self.refusal.code}: читатель видит "
                "зелёное, а внутри лежит отказ — ложно-зелёная квитанция")
        if not self.ok and self.refusal is None:
            raise SandboxResultContradiction(
                "ok=False без отказа: красная квитанция НЕ НАЗЫВАЕТ причины, "
                "и починить по ней нечего")
        if self.refusal is not None and self.ops:
            raise SandboxResultContradiction(
                f"отказ {self.refusal.code} и при этом {len(self.ops)} "
                "операций: отказавший ход не отдаёт программу — читатель "
                "принял бы её за построенную")
        if self.ok and not self.ops:
            raise SandboxResultContradiction(
                "ok=True при НУЛЕ операций: «получилось», построив ничего. "
                "У пустой программы и у разведочного хода есть СВОИ названные "
                "отказы (KIR-B007, KIR-B013) — молчаливое зелёное здесь их "
                "подменяет")


    @property
    def env_digest(self) -> str:
        """The environment signature in one line — what travels into
        the fixed evidence."""
        value = self.environment.get("digest") if self.environment else ""
        return value if isinstance(value, str) else ""

    def to_program(self) -> dict:
        """Return the complete detached authored IR, not a receipt or a plan.

        Defaults, intent, version, units and phase boundaries all remain as
        authored. Unknown fields also remain for the compiler to refuse; this
        method neither validates their semantics nor flattens execution phases.
        Digests/environment/lineage belong beside this program, never inside it.

        The result carrier remains mutable for replay/evidence stamping. If an
        already digested program has since changed, do not emit its old digest
        next to different bytes. A refused result has no executable program.
        """
        self.__post_init__()
        if not self.ok:
            raise SandboxResultContradiction("refused sandbox result has no program")
        if not isinstance(self.envelope, dict) or "ops" in self.envelope:
            raise SandboxResultContradiction(
                "envelope must be a dictionary without a second ops owner")
        if self.program_digest:
            try:
                actual = _program_digest(self.ops, self.envelope)
            except (TypeError, ValueError, UnicodeError) as exc:
                raise SandboxResultContradiction(
                    f"authored program is no longer canonical JSON: {exc}") from exc
            if actual != self.program_digest:
                raise SandboxResultContradiction(
                    "authored program changed after its program_digest was recorded")
        return copy.deepcopy({**self.envelope, "ops": self.ops})

    def as_dict(self) -> dict:
        out = {
            "ok": self.ok,
            "author_digest": self.author_digest,
            "program_digest": self.program_digest,
            # The ledger travels ALWAYS, even empty: "there are no
            # knobs" and "nobody asked about knobs" are different
            # statements, and the first must be visible.
            "params": list(self.params),
            "op_count": len(self.ops),
            "isolation": self.isolation,
            "duration_s": round(self.duration_s, 4),
            "peak_rss_kb": self.peak_rss_kb,
        }
        if self.course_reads:
            # Only if non-empty: "the course was never called" must
            # look like the absence of calls, not like an empty block
            # that reads "there were calls, but none of them."
            out["course_reads"] = list(self.course_reads)
        if self.params_digest:
            out["params_digest"] = self.params_digest
        if self.model_digest:
            out["model_digest"] = self.model_digest
        # 🔴 THE FIFTH SIGNATORY WOULD HAVE TRAVELLED SILENTLY (found
        # 27.08.2026). `author_digest`, `program_digest`,
        # `params_digest`, and `environment` were here, but
        # `building_digest` was not, even though it was introduced by
        # the same argument and was being stamped by the line right
        # next to it (`first.building_digest = …`). The same source
        # over a DIFFERENT building gives a different program, and
        # without the signature the receipt's reader cannot tell a
        # script edit apart from a catalog edit.
        #
        # THE HONEST BOUNDARY OF THIS FIX: it fixes the RECEIPT, not
        # the EVIDENCE. `serving` assembles `_AuthoredInput` from the
        # OBJECT, not from `as_dict` (historically `model_digest` also
        # only travelled through the object), and there nobody reads
        # `building_digest` — zero reads across the whole package. The
        # second half lives in `serving.py` and is NOT done here.
        if self.building_digest:
            out["building_digest"] = self.building_digest
        if self.environment:
            out["environment"] = self.environment
        if self.ok:
            out["ops"] = self.ops
            if self.envelope:
                out["envelope"] = self.envelope
            if self.lineage:
                # Only if non-empty: "there is no provenance" and "it
                # is empty" are different statements, and the first
                # must look like an absence.
                out["lineage"] = dict(self.lineage)
        elif self.refusal is not None:
            out["refusal"] = self.refusal.as_dict()
        if self.stdout:
            out["stdout"] = self.stdout
        if self.left_behind:
            out["left_behind"] = self.left_behind
        # Receipt consumers must not mutate the carrier's program, parameters
        # or evidence through nested dictionaries returned by serialization.
        return copy.deepcopy(out)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# ENVIRONMENT SIGNATURE
# ─────────────────────────────────────────────────────────────────────────────
#
# WHAT THIS FIXES. `author_digest` signs the script's TEXT and nothing
# else. As long as the script is only allowed stdlib, the hole is
# invisible; the moment even one external library lands in the
# whitelist, that same `author_digest` starts certifying DIFFERENT
# `program_digest` values — because between two audits shapely, or GEOS
# underneath it, got updated. The receipt would then have no field at
# all letting the reader tell "a script edit" apart from "a library
# update": one building, two signatures, and both look legitimate.
#
# `replay_check` does not catch this: it runs the script twice IN ONE
# PROCESS on ONE installation and measures nondeterminism, not drift
# over time.
#
# WHY WITHOUT A MANUAL LIST. Exactly what the script may import is
# signed — `policy.allowed_imports`. Add a module to the whitelist and
# it shows up in the signature by itself; a list that must not be
# forgotten to update would get forgotten precisely on the one
# occasion when it matters.

#: Attributes carrying the version of the NATIVE library underneath a
#: module (GEOS under shapely, etc.). Looked up by name, not by list: a
#: list would know about shapely and would not know about the next
#: library. Modules and private names are discarded.
_NATIVE_VERSION_RE = re.compile(r"version", re.I)
_MAX_NATIVE_FACTS = 8


def _module_version(name: str, module: Any) -> tuple[str, str]:
    """A module's version and WHAT it was obtained by. Order: from
    exact to weak."""
    if name in getattr(sys, "stdlib_module_names", frozenset()):
        # stdlib is versioned by the interpreter; it has no separate
        # version of its own. Asking for metadata is pointless and not
        # free (a miss costs ~0.6 ms walking sys.path), and the happy
        # path consists of exactly three such names.
        return "stdlib", "stdlib"
    try:
        import importlib.metadata as _md
        return _md.version(name), "importlib.metadata"
    except Exception:
        pass
    raw = getattr(module, "__version__", None)
    if isinstance(raw, str) and raw:
        return raw, "__version__"
    return "unknown", "none"


def _native_facts(module: Any) -> dict:
    """Versions of native libraries under a module — only for a LOADED
    module.

    Asking `shapely.geos_version` without importing shapely is
    impossible, so this block appears exactly for the modules the
    source named (and which are therefore warmed up). The condition is
    deterministic on the source: the same script in the same
    environment gives the same signature."""
    out: dict[str, str] = {}
    if module is None:
        return out
    for attr in sorted(dir(module)):
        # Private names are discarded together with `__version__`:
        # that version is already named by the `version` field, and
        # repeating it here would mean signing one fact twice.
        if attr.startswith("_"):
            continue
        if not _NATIVE_VERSION_RE.search(attr):
            continue
        try:
            value = getattr(module, attr)
        except Exception:
            continue
        if isinstance(value, str):
            out[attr] = value[:64]
        elif isinstance(value, tuple) and all(isinstance(x, int) for x in value):
            out[attr] = ".".join(str(x) for x in value)
        if len(out) >= _MAX_NATIVE_FACTS:
            break
    return out


def environment_signature(allowed: tuple[str, ...]) -> dict:
    """Exactly what the script was executed with: the interpreter + everything it could have imported.

    Computed IN THE CHILD and BEFORE chroot: `importlib.metadata` reads
    dist-info from disk, and there is no disk in the empty root.

    `digest` covers the block AS A WHOLE — interpreter, names,
    versions, and native facts. Compare two receipts of the same
    script and the digests diverge — the environment has drifted, and
    this is visible without reading it by eye.

    COST, MEASURED 09.08 ON THE PROD BOX (python3.12,
    `replay_check=True`, a turn = two runs): the default whitelist —
    ZERO (three stdlib names are answered from
    `sys.stdlib_module_names`, metadata is not read at all; median
    turn 341.6 ms against 357.9 ms on the code before the fix, i.e.
    within noise). With the geometry flag and WITHOUT mentioning
    shapely in the source — +64 ms and +2 MB per turn, and almost all
    of it is a one-time `import importlib.metadata` (59.8 ms); the
    version queries themselves are 3.1 ms for the first and ~0.6 ms
    for each subsequent one. With shapely mentioned, this gains the
    warm-up of the library itself (+16 MB peak, 40.8 against 25.0 MB).
    """
    modules = []
    for name in sorted(set(allowed)):
        module = sys.modules.get(name)
        version, via = _module_version(name, module)
        row: dict[str, Any] = {
            "name": name,
            "version": version,
            "via": via,
            # WHETHER a module is LOADED in this run is a fact, not
            # decoration: only for a loaded one can the version of the
            # native library underneath it be asked, and the reader
            # must be able to tell "there are no native facts" apart
            # from "they were not asked for."
            "loaded": module is not None,
        }
        native = _native_facts(module)
        if native:
            row["native"] = native
        modules.append(row)

    body = {
        "python": ".".join(str(p) for p in sys.version_info[:3]),
        # The full version string carries the build date and
        # compiler: a substitution of the interpreter itself under the
        # same "3.12.13" is visible from it, while it is not visible
        # from the short one.
        "python_build": sys.version.replace("\n", " "),
        "implementation": sys.implementation.name,
        "modules": modules,
    }
    payload = json.dumps(body, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"))
    body["digest"] = _digest(payload.encode("utf-8"))
    return body


def author_geometry_libs_enabled() -> bool:
    """A gate: whether to let shapely and numpy into the author
    script's whitelist.

    OFF BY DEFAULT. With the flag off, the whitelist is the previous
    one (`ALLOWED_IMPORTS`), the warm-up is the previous one, the cost
    is the previous one, and `import shapely` refuses with exactly the
    same typed KIR-B004, with the model's line number, as before this
    fix.

    WHAT HOLDS SECURITY WHEN THE FLAG IS ON. Not the whitelist — it
    was never the boundary anyway (see §"WHAT THIS SANDBOX DOES NOT
    DO"). The OS LAYERS hold it, and not one of them is weakened here:
    L0 a separate process (no exec at all in our address space), L1
    user+mount+net namespaces with a MEASUREMENT of network
    unreachability, L2 chroot into an empty directory AFTER warm-up,
    L3 RLIMIT_FSIZE=0 / RLIMIT_NPROC=0 / RLIMIT_AS / RLIMIT_CPU /
    RLIMIT_CORE=0, L4 a wall that kills the process group, L8 the exit
    screen. A C extension is arbitrary machine code in the child's
    address space, and the ONLY thing that can hold it is the kernel:
    no python whitelist has any effect on it. That is exactly why the
    flag touches EXACTLY ONE line of policy (`allowed_imports`) and
    does not touch a single isolation layer.

    The second half of the answer is the environment signature above:
    a library the script may call must be NAMED WITH ITS VERSION in
    the receipt. That is why step 1 (the signature) shipped to prod
    unconditionally, while this flag stays behind a switch.
    """
    return os.getenv("KUKAI_IR_AUTHOR_GEOMETRY_LIBS", "").strip().lower() in {
        "1", "true", "yes", "on",
    }


def allowed_imports_for_env() -> tuple[str, ...]:
    """The whitelist of THIS run: read live, not at module import
    time.

    Live — so that an edit on the service takes effect from the next
    turn, by the same rule as `checker.flags.checker_v2_enabled`. A
    cache here would be a silent disagreement with the operator."""
    if author_geometry_libs_enabled():
        return ALLOWED_IMPORTS + GEOMETRY_IMPORTS
    return ALLOWED_IMPORTS


def _program_digest(ops: list, envelope: dict) -> str:
    payload = json.dumps({"ops": ops, "envelope": envelope},
                         ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False)
    return _digest(payload.encode("utf-8"))


# ─────────────────────────────────────────────────────────────────────────────
# THE PARENT
# ─────────────────────────────────────────────────────────────────────────────

def _backend_root() -> str:
    """The directory CONTAINING the `kir` package — the child process
    gets it in PYTHONPATH.

    🔴 THERE USED TO BE THREE `dirname` CALLS WITH THE COMMENT
    «.../backend/kukai/ir/sandbox.py → .../backend», and that was
    correct EXACTLY for that layout. On 27.08.2026 KIR became a
    separate package (`/opt/kir/kir/sandbox.py`), and three steps up
    gave `/opt`, where `kir` is the REPOSITORY directory, not the
    package. The child process imported a half-package and crashed
    with `partially initialized module 'kir.spec'`; the author's
    script, in the process, got the refusal «язык KIR не загрузился» —
    that is, the language was blamed for a defect in ITS OWN
    packaging.

    We count not by steps upward, but from the place where the
    package ACTUALLY lives: the layout changes, this does not.
    """
    import kir
    return os.path.dirname(os.path.dirname(os.path.abspath(kir.__file__)))


def _refuse(code: str, message: str, *, kind: str, blame: str = "author",
            **detail: Any) -> SandboxRefusal:
    return SandboxRefusal(code=code, message_ru=message, kind=kind, blame=blame,
                          detail=detail)


# ─────────────────────────────────────────────────────────────────────────────
# THE OPEN DOCUMENT CATALOG — THE ONLY THING THE SCRIPT CAN READ
# ─────────────────────────────────────────────────────────────────────────────
#
# WHY. Until 14.08.2026 the script's namespace held 98 names, and NOT
# ONE OF THEM read the document the script writes into. Measured
# against the refusal corpus (314 authoring attempts, 16.07–14.08):
# "blindness to the catalog" — 29.9% of attempts, the largest class.
# The author must name a type, level, or grid BY NAME, and there was
# nowhere for them to get the names from: they were guessing them.
#
# WHAT THIS GIVES BEYOND "FEWER REFUSALS," and what it was actually
# built for: enumeration becomes a RULE. `for lvl in model.levels()`
# instead of twenty spelled-out floors; `model.grids()` — a typical
# floor by the grid, not by literal coordinates. This is exactly
# "pointing attention from the API to the geometry."
#
# WHAT IS NOT HERE AND WHY.
#
# * NO BUILDING GEOMETRY. The grounding snapshot carries CATALOGS
#   (levels, grids, type pools) and carries not a single wall and not
#   a single room — measured: `grep -c 'OfClass(typeof(Wall))|OST_Rooms'`
#   against `open_model.py` gives 0. So "find rooms without a window"
#   cannot be answered by this object, and it must not promise
#   anything of the sort, neither by a method name nor by a docstring.
#
# * NO `most_used` RULE. It lives in `ground._most_used` together with
#   its threshold `MOST_USED_MIN_RATIO`, and a second instance of the
#   rule would drift from the first on the very first edit — exactly
#   the defect this package exists to forbid. The `instances` counter
#   is visible in the rows; the decision is made by the author or by
#   the compiler, never by two different rules.
#
# * NO WRITING. The object is immutable and hands out tuples of
#   copies: a script that appended a row to the catalog would sign,
#   with its own signature, a document that does not exist.
#
# HONESTLY ABOUT FRESHNESS. The catalog is a snapshot AT THE MOMENT OF
# READING, not a live model. Grounding re-grounds the program against
# ITS OWN snapshot regardless and refuses if the assumption broke —
# which is why a stale catalog cannot build something wrong THROUGH A
# SELECTOR. But it can through a NUMBER: a script that branches on
# `len(model.levels())` will give rise to a different program, and
# grounding will calmly ground it. This is named here because the
# claim "a stale read is safe" has no second half.
def _промах_метода(объект: Any, имя: str, что: str) -> AttributeError:
    """A miss on a method name — WITH A LIST of the ones that exist.

    🔴 MEASURED 25.08.2026. `model.wall_types()` used to answer with a
    bare `AttributeError: 'ModelCatalog' object has no attribute
    'wall_types'`. The blame was named CORRECTLY — the method does not
    exist, it was made up — but the shape is unfit: not one existing
    name. The model has no way at all to enumerate them: `dir()` is
    closed inside the sandbox, the surface is closed, and the next
    turn goes to guessing.

    The project has long had a shape for this answer; it simply was
    not applied here. The argument is recorded in `course._resolve`
    verbatim: «Отказ без списка — это второй раунд: модель не угадает
    написание, она попробует синоним».

    THE BLAME STAYS THE AUTHOR'S. A made-up name is not our reading
    gap, and `ПробелЧтения` here would be lying in the other
    direction: saying "this is not on you" exactly where it is the
    author who must fix it. What gets fixed is the SHAPE, not the
    address of the fix.
    """
    доступные = sorted(
        н for н in dir(type(объект))
        if not н.startswith("_") and callable(getattr(type(объект), н, None)))
    близкие = difflib.get_close_matches(имя, доступные, n=4, cutoff=0.0)
    return AttributeError(
        f"у {что} нет «{имя}». БЛИЖАЙШИЕ ПО НАПИСАНИЮ: "
        f"{', '.join(близкие)}.\nВСЁ, ЧТО ЕСТЬ: {', '.join(доступные)}")


class ПробелЧтения(RuntimeError):
    """Something was asked about the model or the building that WE did
    not read for this turn.

    NOT THE AUTHOR'S ERROR, and this class exists precisely so a
    MACHINE can see that. Measured 25.08.2026: five such questions
    («индекс здания не подан», «каталог документа не подан») arrived
    as `KIR-B006` with `blame=author` — indistinguishable from `1/0` —
    even though the prose of those same refusals stated verbatim «это
    факт о НАШЕМ чтении, а не о здании». The blame field was lying
    about a correct script, and the model went off to rewrite it.

    A SUBCLASS OF `RuntimeError`, NOT `BaseException`, AND THIS IS A
    DECISION. Its neighbors (`_BadParam`, `_ForbiddenBuiltin`)
    deliberately subclass `BaseException` — so that an `except
    Exception` in the script does not swallow them and the program
    does not get assembled on defaults. The argument does not hold
    here: "no building was supplied" is a legitimate outcome of an
    offline run, and the author is ENTITLED to handle it (`try: …
    except RuntimeError: build without a building`). Changing the
    class would silently break such scripts in the name of an honesty
    they do not have anyway.

    A precedent for this shape stands in this same file: the branch
    `NameError and dsl is None` is declared ours with the same
    argument — "otherwise the model will go fix its own correct
    script." The shape was known and applied once out of six.
    """


class ModelCatalog:
    """The open document's catalog: levels, grids, and type pools. Read-only."""

    __slots__ = ("_pools", "_digest")

    def __init__(self, pools: Any = None, digest: str = "") -> None:
        # 🔴 AN EMPTY POOL STAYS IN THE CATALOG (15.08.2026). Before
        # this fix, `if kept:` stood here, and a pool that ARRIVED
        # empty was discarded on a par with a pool that was never sent
        # at all. Downstream, both produced the same refusal, «пула
        # нет в этом снимке» — that is, ONE CODE FOR TWO OUTCOMES, and
        # the difference between them decides what the author must do:
        #
        #   the pool is empty     — A FACT ABOUT THE DOCUMENT: there
        #                           are no types of that kind in it,
        #                           and the author must either create
        #                           a type or choose a different op.
        #                           The correct answer is an empty
        #                           tuple;
        #   the pool was not sent — A FACT ABOUT US: we did not ask.
        #                           The correct answer is a refusal,
        #                           because "none" would be untrue
        #                           here.
        #
        # Measured on this same fix: `model.types("wall_types")` with
        # the snapshot `{"wall_types": []}` used to answer «пула нет.
        # Пришли: (каталог не подан)» — both statements were false,
        # the catalog had been supplied and the pool was in it.
        clean: dict[str, tuple[dict, ...]] = {}
        if isinstance(pools, dict):
            for name, rows in pools.items():
                if not isinstance(name, str) or not isinstance(rows, list):
                    continue
                clean[name] = tuple(
                    dict(row) for row in rows if isinstance(row, dict))
        self._pools = clean
        self._digest = digest

    # ── what actually arrived ──────────────────────────────────────────
    @property
    def empty(self) -> bool:
        return not self._pools

    @property
    def digest(self) -> str:
        """The catalog's signature — the same one that travels into
        the receipt next to the script's signature."""
        return self._digest

    def pools(self) -> tuple[str, ...]:
        """Names of the pools that ARRIVED. An empty tuple means no
        catalog was supplied."""
        return tuple(sorted(self._pools))

    # ── contents ────────────────────────────────────────────────────────
    def levels(self) -> tuple[dict, ...]:
        """The document's levels: `id`, `name`, and `elevation_mm`, if
        it arrived."""
        return self._rows("levels")

    def grids(self) -> tuple[dict, ...]:
        """The document's grids — what a typical floor is built from
        by rule."""
        return self._rows("grids")

    def types(self, pool: str) -> tuple[dict, ...]:
        """Rows of one type pool; an unknown name — a REFUSAL with a
        list of the ones that arrived.

        A silent empty tuple for a typo would mean "there are no such
        types in the document," and that is a different statement, and
        it is false.
        """
        if not isinstance(pool, str):
            raise KeyError(
                f"каталог: имя пула обязано быть строкой, пришло {type(pool).__name__}")
        return self._rows(pool)

    # ── search by name ───────────────────────────────────────────────────
    #: The threshold at which two elevations count as
    #: INDISTINGUISHABLE. The same 1 mm as `resolved_refs` in the
    #: receipt (commit 9689a2a1), and the same rationale: Revit itself
    #: distinguishes elevations to the millimeter.
    NEIGHBOUR_MM = 1.0

    def find(self, pool: str, name: str) -> dict:
        """A pool row BY NAME — or a typed refusal with candidates.

        🔴 WHY A SEPARATE VERB, BY MEASUREMENT OF 19.08.2026. The
        catalog only handed out whole pools, and the author wrote the
        search themselves:

            next((r for r in model.levels() if r["name"] == n), None)

        A typo in the name gave `None`, the author appended `or
        <number>` — and a ZERO NOBODY HAD COMPUTED rode into the
        program. This is our named shape of the defect, and in one day
        it was bought three times over, on three different authors:
        540 beams at `z=0` when «Этаж 5» had been written; «Типовой -
        150мм» against «Типовой 150мм» on a control hand written in
        plain C#; and an elevation table recomputed by arithmetic
        instead of being read — twenty double-height columns, beams in
        the middle, no beams on the roof.

        The matching rule is THE SAME as grounding's (`ground.py`,
        `by=name`): an exact match, else the SINGLE case-insensitive
        one, else a refusal. These two places must not diverge: the
        script would find one thing, grounding would resolve another,
        and the author would have no field at all to notice it by.
        """
        rows = self._rows(pool)                      # the three outcomes are already named there
        if not isinstance(name, str):
            raise KeyError(
                f"каталог: имя обязано быть строкой, пришло {type(name).__name__}")
        exact = [r for r in rows if str(r.get("name", "")) == name]
        if len(exact) == 1:
            return dict(exact[0])
        if len(exact) > 1:
            raise KeyError(
                f"каталог: в пуле {pool!r} ИМЯ {name!r} носят {len(exact)} строк "
                f"(id {', '.join(str(r.get('id')) for r in exact)}) — выбор между "
                f"ними сделал бы не ты. Адресуй по id.")
        low = name.casefold()
        ci = [r for r in rows if str(r.get("name", "")).casefold() == low]
        if len(ci) == 1:
            return dict(ci[0])
        near = difflib.get_close_matches(
            name, [str(r.get("name", "")) for r in rows], n=5, cutoff=0.0)
        raise KeyError(
            f"каталог: в пуле {pool!r} нет имени {name!r}. Похожие: "
            f"{', '.join(repr(n) for n in near) if near else '(пул пуст)'}. "
            f"Всего строк {len(rows)}.")

    def level(self, name: str) -> dict:
        """A level by name: the catalog row plus a NAMED
        indistinguishable neighbor.

        🔴 EVIDENCE `KIR-A006`, the reason the neighbor is named at
        all: 35 columns went to the template «Уровень 1» instead of
        «Этаж 1», because BOTH sit at elevation 0. The reference
        resolved to the neighbor and looked legitimate. In the
        document where this was written, «Уровень 1»@0 and «Этаж
        1»@0 sit side by side right now.

        This is NOT turned into a refusal: two levels at the same
        elevation are a legitimate feature of a Revit document (a
        template one plus an authored one), and a refusal would break
        correct programs. So the value is returned, and the match is
        NAMED by the field `indistinguishable_on_elevation`. An empty
        list means "the neighbor was checked for and not found" — the
        absence of the key would mean "nobody looked," and that is a
        different statement.
        """
        row = self.find("levels", name)
        mine = row.get("elevation_mm")
        neighbours: list[str] = []
        if isinstance(mine, (int, float)):
            for other in self._rows("levels"):
                if other.get("id") == row.get("id"):
                    continue
                theirs = other.get("elevation_mm")
                if (isinstance(theirs, (int, float))
                        and abs(float(theirs) - float(mine)) <= self.NEIGHBOUR_MM):
                    neighbours.append(str(other.get("name", "")))
        row["indistinguishable_on_elevation"] = sorted(neighbours)
        return row

    def _rows(self, pool: str) -> tuple[dict, ...]:
        """Rows of a pool. THREE outcomes, and each is named
        separately.

        There used to be two outcomes for three cases: the absence of
        a catalog answered with a refusal, while the absence of a POOL
        in a supplied catalog answered with a silent empty tuple,
        indistinguishable from "there is none of this in the
        document." For `levels()` this is especially costly: there is
        no such thing as a Revit document without levels, and an empty
        answer there means OUR reading gap, not a fact about the
        building.
        """
        if not self._pools:
            raise ПробелЧтения(
                "каталог документа не подан этому запуску: спрашивать нечего. "
                "Так бывает у офлайн-прогонов и у ходов без живой модели — "
                "имена типов и уровней в таком запуске надо называть явно")
        if pool not in self._pools:
            raise KeyError(
                f"каталог: пула {pool!r} в этом снимке нет — его НЕ ПРИСЛАЛИ, "
                f"и это факт о нашем чтении, а не о документе. Пришли: "
                f"{', '.join(self.pools())}")
        return tuple(dict(row) for row in self._pools[pool])

    def __getattr__(self, имя: str) -> Any:
        # Called ONLY when the name is missing: the class has
        # `__slots__`, live methods are found earlier and never reach
        # here. Verified by a control.
        raise _промах_метода(self, имя, "каталога документа")

    def __repr__(self) -> str:                       # deterministic
        return (f"<каталог документа: {len(self._pools)} пулов, "
                f"{sum(len(v) for v in self._pools.values())} строк>")


class _Найдено(tuple):
    """The result of `find()` — a TUPLE that knows how much of it did
    not arrive.

    A subclass of `tuple`, not a new type: scripts are already
    written, and they do `len`, slicing, indexing, and looping.
    Changing the value's type would break them silently — and silently
    breaking the language the model writes in is not allowed for the
    sake of any honesty.

    It carries exactly two facts on top of the tuple: how many matched
    the criteria IN TOTAL, and whether the author chose the limit. The
    second is needed by `__repr__`, so it does not accuse the author
    of a truncation they themselves asked for.
    """

    # `__slots__` is IMPOSSIBLE here: python forbids non-empty slots
    # on a `tuple` subclass (`nonempty __slots__ not supported for
    # subtype of 'tuple'`) — a tuple has no room for them under its
    # fixed layout. The two fields live in `__dict__`, and that is the
    # cost of subclassing, not an oversight.

    def __new__(cls, ряды, *, всего: int, по_умолчанию: bool):
        это = super().__new__(cls, ряды)
        это.всего = int(всего)
        это.по_умолчанию = bool(по_умолчанию)
        return это

    def __repr__(self) -> str:                       # deterministic
        if len(self) >= self.всего:
            return super().__repr__()
        предел = ("потолок по умолчанию" if self.по_умолчанию
                  else "предел задан тобой")
        return (f"<найдено {self.всего}, отдано {len(self)} — СПИСОК УСЕЧЁН "
                f"({предел}); остальное: find(..., limit={self.всего})>")


class BuildingView:
    """THE EXISTING BUILDING IN THE SCRIPT'S HANDS — `ls`, `grep`, and
    `read` over the model.

    The catalog (`model`) answers "what can I build with"; this object
    answers "what is already standing here." Before it, nobody
    answered the second question: query-ops travel to Revit and come
    back into a RECEIPT, not into the script's hands, so the "found →
    looked → fixed" cycle broke apart into three turns.

    The mapping onto working with a repository — which is also the
    order the calls are given in:

        building.census()                 # ls   — what is in the building and how many
        building.levels()                 # ls   — the BUILDING's levels, not types
        building.find(cat="Стены", lvl="3")   # grep — with a bound and a total count
        building.get("7240696")           # read file:line — with every parameter
        building.observations()           # run the rules over what has BEEN BUILT

    THREE OUTCOMES FOR EVERY QUESTION, and not one of them stays
    silent — see the header of `kir.building_index`. An empty answer
    with a full index is a fact ABOUT THE BUILDING; with a census, it
    is a REFUSAL, because we did not look; without an index, it is a
    refusal of a third kind.
    """

    __slots__ = ("_tier", "_census", "_rows", "_params", "_by_id",
                 "_refused", "_observations", "_digest",
                 # Both fields are about OUR printing, not about the
                 # building: which truncations have already been
                 # named aloud, and how many have not been named.
                 "_названные_усечения", "_усечений_не_названо")

    def __init__(self, payload: Any = None, digest: str = "") -> None:
        data = payload if isinstance(payload, dict) else {}
        self._tier = data.get("tier") or ""
        self._census = data.get("census") if isinstance(
            data.get("census"), dict) else {}
        rows = data.get("elements")
        self._rows = tuple(dict(r) for r in rows
                           if isinstance(r, dict)) if isinstance(rows, list) else ()
        params = data.get("params")
        self._params = params if isinstance(params, dict) else {}
        self._refused = data.get("refused") or ""
        obs = data.get("observations")
        self._observations = tuple(obs) if isinstance(obs, list) else ()
        self._digest = digest
        self._by_id = {row.get("id"): row for row in self._rows}
        #: Which truncations have already been named aloud — BY THE
        #: QUERY'S SIGNATURE, not by a counter: `find(cat='Walls')`
        #: inside a loop over floors is ONE question asked ten times,
        #: and ten identical warnings say exactly as much as one,
        #: while eating up the channel tenfold.
        self._названные_усечения: set[tuple] = set()
        self._усечений_не_названо = 0

    # ── what actually arrived ──────────────────────────────────────────
    @property
    def empty(self) -> bool:
        """No index was supplied at all. NOT the same as "there is
        nothing in the building"."""
        return not self._tier

    @property
    def tier(self) -> str:
        """`full` — elements arrived; `census` — only the census; `` —
        not supplied."""
        return self._tier

    @property
    def digest(self) -> str:
        """The index's signature — a fourth signatory alongside the
        catalog and the environment."""
        return self._digest

    def _require_index(self, what: str) -> None:
        """THE ONE PLACE that decides the "no index at all" refusal.

        🔴 THE REASON MUST ARRIVE. Until 16.08.2026 the refusal was
        hardcoded as a literal in six different places, and `refused`
        from the payload was read by NOT ONE of them: something that
        supplied an index with an honest reason ("no decompile of this
        document in the corpus, 80 examined") got a generic "not
        supplied" instead of it. Three outcomes collapsed into one
        exactly where the distinction is needed — "we did not look"
        against "there was nothing to look at."
        """
        if self._tier:
            return
        if self._refused:
            raise ПробелЧтения(f"{what}: {self._refused}")
        raise ПробелЧтения(
            f"{what}: индекс здания не подан этому запуску. Так бывает у "
            f"офлайн-прогонов и у ходов без прочитанной модели — это факт "
            f"о НАШЕМ чтении, а не о здании")

    def _require_elements(self, what: str) -> None:
        """The one place that decides the right to answer element by
        element."""
        self._require_index(what)
        if self._tier != _building_index.TIER_FULL:
            raise ПробелЧтения(
                f"{what}: {self._refused or 'поэлементный слой индекса не приехал'}")

    # ── ls ──────────────────────────────────────────────────────────────
    def census(self) -> dict:
        """How much of what is in the building and on which levels.
        Present ALWAYS, if an index was supplied.

        The census weighs kilobytes and arrives even when the
        element-by-element layer did not fit — precisely so that "the
        building is too large" does not read as "nothing is known
        about the building."
        """
        self._require_index("перепись")
        return json.loads(json.dumps(self._census))     # a copy, not our own reference

    def top(self, n: int = 10) -> tuple[tuple[str, int], ...]:
        """The building's largest categories — AS PAIRS, in
        descending order.

        The order is decided HERE, not in the index, and this is not a
        matter of taste: the stdin frame is serialized with
        `sort_keys=True` (without this the index's signature is not
        reproducible), so any order declared on that side gets
        rewritten alphabetically, SILENTLY. The first version got
        caught on exactly this — the "top categories" used to hand
        back `OST_CableTray: 1` on a building with 695 walls. Pairs,
        not a dict: a dict would lose the order again at the very
        first serialization.
        """
        self._require_index("топ категорий")
        by_cat = self._census.get("by_category")
        if not isinstance(by_cat, dict):
            return ()
        ordered = sorted(by_cat.items(), key=lambda kv: (-kv[1], kv[0]))
        return tuple(ordered[:max(0, int(n))])

    def levels(self) -> tuple[str, ...]:
        """Levels that HAVE elements on them. This is a fact about the
        building, not about types."""
        self._require_index("уровни здания")
        by_level = self._census.get("by_level")
        return tuple(sorted(by_level)) if isinstance(by_level, dict) else ()

    def total(self) -> int:
        """How many elements are in the building IN TOTAL — known
        even from a census alone."""
        self._require_index("счёт элементов")
        value = self._census.get("total")
        return int(value) if isinstance(value, int) else 0

    def _проверить_признаки(self, criteria: dict, что: str) -> None:
        """A search criterion outside the closed set — a REFUSAL, not
        an empty answer.

        🔴 MEASURED 25.08.2026. `building.find(catt="Walls")` on a
        building of fifty walls used to return `()`. The reason is in
        `building_index.matches`: for an unknown key, `row.get("catt")`
        gives `None`, the comparison with "Walls" does not pass for a
        single row, and emptiness goes out the door.

        The model reads this as "there are no walls in the building" —
        A LIE ABOUT THE BUILDING, when the truth was about how the
        criterion was spelled. Worse than a refusal: on a refusal it
        would have asked differently, but here it keeps building on
        empty ground. This is the worst kind of outcome in this
        tree — a silently-wrong success.

        THE SET OF CRITERIA IS DERIVED FROM THE INDEX'S ROWS, not
        copied out by hand: the project's measurement of 15.08 says
        that ALL hand-written lists drifted and NOT ONE generated one
        did. A second list here would have been named "cat, lvl,
        type, id…" and would have drifted from the index at the very
        first new field.
        """
        if not criteria:
            return
        доступные = sorted({к for строка in self._rows for к in строка})
        чужие = [к for к in criteria if к not in доступные]
        if not чужие:
            return
        близкие = difflib.get_close_matches(чужие[0], доступные, n=3, cutoff=0.0)
        raise AttributeError(
            f"{что}: признака «{чужие[0]}» у элементов здания нет — поиск по "
            f"нему не нашёл бы НИЧЕГО и это читалось бы как «в здании такого "
            f"нет».\nБЛИЖАЙШИЕ ПО НАПИСАНИЮ: {', '.join(близкие)}.\n"
            f"ВСЁ, ЧТО ЕСТЬ: {', '.join(доступные)}. "
            f"Признаки cat, lvl, type ищутся ПОДСТРОКОЙ, остальные точно.")

    # ── grep ────────────────────────────────────────────────────────────
    def find(self, *, limit: int | None = None, **criteria) -> tuple[dict, ...]:
        """Elements by criteria: `cat`, `lvl`, `type` — by substring,
        the rest exactly.

        Truncation is DECLARED: if more than `limit` was found, the
        rest does not vanish silently — `found()` gives the full
        count, the list calls itself truncated in `__repr__`, and the
        DEFAULT ceiling speaks up about itself ALOUD.

        🔴 UNTIL 25.08.2026 THIS DOCSTRING PROMISED AND DID NOT
        DELIVER. A bare `tuple` was returned, with python's own
        `__repr__`. Measured by running on a building of 250 walls
        with a ceiling of 200: 200 came back, `repr` said nothing
        about truncation, `found()` knew 250. The model got 80% of the
        building and had no way to know it without asking a second
        question that nobody had told it was necessary. A loop over
        such a list looks complete — this is exactly the
        silently-wrong outcome the package was written to forbid. A
        promise in a docstring is not a mechanism: "declared in one
        place, not done in another" is this tree's named defect.

        THE TWO CASES ARE DISTINGUISHED ON PURPOSE. The model did not
        choose the default ceiling — it is announced in `stdout`, that
        is, in the channel it reads. An explicit `limit=` was named by
        the model itself — we do not shout about it aloud, `__repr__`
        stays honest regardless. Noise on a correctly written script
        turns off the guard faster than usefulness ever finds it.

        THE FULL COUNT IS TAKEN ONLY ON TRUNCATION. The traversal goes
        up to `cap + 1`: if nothing extra was found, there is no
        second pass and the cost is unchanged. We pay exactly in the
        one case this whole thing exists for.
        """
        self._require_elements("поиск по зданию")
        self._проверить_признаки(criteria, "поиск по зданию")
        cap = (_building_index.DEFAULT_FIND_LIMIT if limit is None
               else int(limit))
        out = []
        усечено = False
        for row in _building_index.iter_matching(self._rows, criteria):
            if len(out) >= cap:
                усечено = True
                break
            out.append(dict(row))
        if not усечено:
            return _Найдено(out, всего=len(out), по_умолчанию=limit is None)
        всего = sum(1 for _ in _building_index.iter_matching(self._rows,
                                                             criteria))
        if limit is None:
            self._сказать_об_усечении(criteria, len(out), всего)
        return _Найдено(out, всего=всего, по_умолчанию=limit is None)

    #: How many truncations to name individually. A script calling
    #: `find` in a loop would otherwise eat up the print channel with
    #: its own warnings — and the channel exists for the author's
    #: answer, not for our noise.
    _ПОТОЛОК_ИЗВЕЩЕНИЙ = 5

    def _сказать_об_усечении(self, criteria: dict, отдано: int,
                             всего: int) -> None:
        """Name the truncation INTO THE CHANNEL the model reads.

        `__repr__` alone will not do: it only arrives if something
        printed it, and a typical script writes `for эл in
        building.find(...)` and prints nothing. Silence here is
        indistinguishable from a complete answer.
        """
        подпись = tuple(sorted(criteria.items()))
        if подпись in self._названные_усечения:
            return
        if len(self._названные_усечения) >= self._ПОТОЛОК_ИЗВЕЩЕНИЙ:
            self._усечений_не_названо += 1
            return
        self._названные_усечения.add(подпись)
        зов = ", ".join(f"{k}={v!r}" for k, v in sorted(criteria.items()))
        print(f"⚠️  find({зов}) УСЕЧЁН: отдано {отдано} из {всего}. Потолок "
              f"{_building_index.DEFAULT_FIND_LIMIT} — УМОЛЧАНИЕ, ты его не "
              f"выбирал. Возьми остальное: find({зов}, limit={всего}) либо "
              f"спроси счёт: found({зов}).")

    def found(self, **criteria) -> int:
        """How many match the criteria IN TOTAL — without truncation.

        A counterpart to `find`: the list is bounded by the answer's
        ceiling, the count is bounded by nothing. Without this
        counterpart a truncated list would read as a complete result.
        """
        self._require_elements("счёт по зданию")
        self._проверить_признаки(criteria, "счёт по зданию")
        return sum(1 for _ in _building_index.iter_matching(self._rows, criteria))

    # ── read file:line ──────────────────────────────────────────────────
    def get(self, element_id: Any) -> dict:
        """One element with ALL its parameters. An unknown address — a
        REFUSAL.

        A silent `None` for an unknown id would mean "no such element
        exists," and that is a statement we are only entitled to make
        with a full index, and even then it must be SAID, not returned
        as emptiness.
        """
        self._require_elements("чтение элемента")
        key = str(element_id)
        row = self._by_id.get(key)
        if row is None:
            raise KeyError(
                f"элемента {key!r} в этом здании нет: индекс полный, "
                f"{self.total()} элементов, и такого адреса среди них не "
                f"встретилось")
        out = dict(row)
        detail = self._params.get(key)
        out["params"] = dict(detail) if isinstance(detail, dict) else {}
        return out

    # ── run the rules over what has BEEN BUILT ──────────────────────────
    def observations(self) -> tuple[dict, ...]:
        """Observations about the BUILT building — by the same rules
        as about the design intent.

        They are computed by the PARENT (`assembly_view.observe_l0`)
        and placed into the index: the child has five seconds of CPU
        time, and the building judge is not obliged to fit inside
        them. The script reads the finished result and branches.

        An empty tuple with a full index is a fact about the building:
        the rules found no violations among the ones they know how to
        see. This is NOT "the building is fine": six rules out of
        twenty are unconditionally excluded, and the list of what was
        excluded travels with the verdict, not from here.
        """
        self._require_index("наблюдения о здании")
        return tuple(dict(o) if isinstance(o, dict) else o
                     for o in self._observations)

    def __getattr__(self, имя: str) -> Any:
        raise _промах_метода(self, имя, "здания")

    def __repr__(self) -> str:                       # deterministic
        if not self._tier:
            return "<здание: индекс не подан>"
        if self._tier != _building_index.TIER_FULL:
            return (f"<здание: только перепись, {self.total()} элементов "
                    f"(поэлементный слой не поместился)>")
        return (f"<здание: {len(self._rows)} элементов, "
                f"{len(self._census.get('by_level') or ())} уровней>")


def _model_pools(model: Any) -> dict[str, list[dict]]:
    """The grounding snapshot -> only pools of rows `{id, name, …}`,
    nothing more.

    The snapshot's service keys (`__document_fingerprint`,
    `__revit_version`, `*__truncated`, `*__total`) do NOT land here ON
    PURPOSE: these are facts about READING, not about the document,
    and a script branching on them would be branching on our internal
    kitchen. The catalog must be about the building.
    """
    out: dict[str, list[dict]] = {}
    if not isinstance(model, dict):
        return out
    for name, rows in model.items():
        if not isinstance(name, str) or name.startswith("__"):
            continue
        if not isinstance(rows, list):
            continue
        # 🔴 `if kept:` REMOVED ON 15.08.2026 — the second half of the
        # same fix as in `ModelCatalog.__init__`. Here the filter
        # stood at the input and silently dropped a pool that ARRIVED
        # empty, before it ever reached the catalog; fixing one end
        # without the other would have given "an instrument covering
        # part of its range": the catalog would distinguish three
        # outcomes, and only two would ever reach it.
        #
        # An empty list means "the snapshot READ this pool and found
        # zero rows" — this is a fact about the DOCUMENT and it must
        # arrive. The absence of the key means "it was not read," and
        # the refusal in `_rows` answers for that.
        out[name] = [dict(row) for row in rows
                     if isinstance(row, dict) and row.get("id") is not None]
    return out


def model_catalog_digest(pools: Any) -> str:
    """The catalog's signature — THE SAME trick as the environment's
    signature.

    Without it, the same `author_digest` would certify DIFFERENT
    `program_digest` values after a document edit, and the reader
    would have no field at all to tell a SCRIPT edit apart from MODEL
    drift. This exact argument is already recorded in the module
    header about `environment`; here it is a third signatory of the
    same kind.
    """
    if not isinstance(pools, dict) or not pools:
        return ""
    blob = json.dumps(pools, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False)
    return _digest(blob.encode("utf-8", "surrogatepass"))


def building_catalog_digest(payload: Any) -> str:
    """The building index's signature — THE SAME trick as the
    catalog's signature.

    The argument is verbatim the same and is recorded at
    `model_catalog_digest`: without the signature, the same
    `author_digest` would certify DIFFERENT programs after a building
    edit, and the reader would have no field left to tell a SCRIPT
    edit apart from MODEL drift.
    """
    if not isinstance(payload, dict) or not payload:
        return ""
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False)
    return _digest(blob.encode("utf-8", "surrogatepass"))


def params_digest(payload: Any) -> str:
    """The signature of the SUPPLIED parameters — the same trick as
    the catalog's signature.

    What is signed is specifically the SUPPLIED values, not the
    effective ones. The difference matters: the author editing a
    default value changes the TEXT of the source, and `author_digest`
    already signs that; a second signature of the same event would
    create two carriers of one piece of knowledge, and they would
    drift apart silently.
    """
    if not isinstance(payload, dict) or not payload:
        return ""
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False)
    return _digest(blob.encode("utf-8", "surrogatepass"))


def execute_author_script(source: str,
                          *,
                          policy: SandboxPolicy = DEFAULT_POLICY,
                          model: Any = None,
                          building: Any = None,
                          params: Any = None) -> SandboxResult:
    """Execute the model's source and return IR operations, or a
    typed refusal.

    Input/setup errors and ordinary host errors are returned typed.
    The host's KeyboardInterrupt/SystemExit are not swallowed; a crash
    of the parent process itself is not covered by this contract.

    `model` is the CATALOG of the open document (the grounding
    snapshot as DATA: levels, grids, type pools). Optional: without it
    the name `model` is still present in the script, and it answers
    any question with the named reason "no catalog was supplied" —
    the absence of the name would read as "no such capability
    exists," and that is a different statement. It travels on the
    same stdin frame as the source: opening a second channel for data
    that already reaches the child would mean opening a second way to
    get it wrong. The catalog's signature is returned in
    `SandboxResult.model_digest` — see the argument at that field
    itself.
    """
    started = time.perf_counter()
    try:
        return _prepare_author_execution(source, policy=policy, model=model, building=building, params=params)
    except Exception as exc:
        # Infrastructure failure can occur before OR after a child starts. Do
        # not infer non-execution or grant replay from this local failure.
        author_digest = ""
        if type(source) is str:
            try:
                author_digest = _digest(source.encode("utf-8"))
            except Exception:
                pass
        return SandboxResult(ok=False, author_digest=author_digest,
            duration_s=time.perf_counter() - started,
            refusal=_refuse(SANDBOX_UNAVAILABLE,
                "песочница не завершила обработку; состояние запуска требует проверки, повтор не разрешён",
                kind="HostFailure", blame="sandbox", exception_type=type(exc).__name__))


def _prepare_author_execution(source, *, policy, model, building, params) -> SandboxResult:
    """Validate and detach caller inputs before allocating child resources."""
    try:
        if type(policy) is not SandboxPolicy:
            raise ValueError("exact SandboxPolicy required")
        policy.__post_init__()  # Recheck a tampered/deserialized policy as well.
    except (ValueError, TypeError, AttributeError, OverflowError):
        return SandboxResult(ok=False, refusal=_refuse(SANDBOX_UNAVAILABLE,
            "политика песочницы некорректна; дочерний процесс не запускался",
            kind="InvalidPolicy", blame="caller"))
    if type(source) is not str:
        return SandboxResult(ok=False, refusal=_refuse(SANDBOX_SYNTAX,
            "исходник должен быть строкой UTF-8; дочерний процесс не запускался",
            kind="InvalidSource", blame="caller"))
    try:
        source.encode("utf-8")
    except UnicodeError:
        return SandboxResult(ok=False, refusal=_refuse(SANDBOX_SYNTAX,
            "исходник содержит недопустимую последовательность Unicode",
            kind="UnicodeEncodeError", blame="caller"))
    inputs = {}
    for name, value in (("model", model), ("building", building), ("params", params)):
        try:
            if value is None:
                value = {}
            if type(value) is not dict:
                raise ValueError("input must be an object")
            if _check_jsonable(value, name, 0) is not None:
                raise ValueError("input must contain bounded JSON values")
            # Snapshot once without invoking arbitrary __str__; JSON-compatible
            # tuples still normalize to arrays, as in the existing wire format.
            blob = json.dumps(value, ensure_ascii=False, sort_keys=True,
                              separators=(",", ":"), allow_nan=False).encode("utf-8")
            inputs[name] = json.loads(blob)
        except (TypeError, ValueError, UnicodeError, RecursionError, OverflowError):
            return SandboxResult(ok=False, author_digest=_digest(source.encode("utf-8")),
                refusal=_refuse(SANDBOX_PARAM if name == "params" else SANDBOX_BAD_RESULT,
                    f"вход {name} должен быть объектом из конечных JSON-значений; процесс не запускался",
                    kind="InvalidInput", blame="caller", input=name))
    return _execute_author_script(source, policy=policy, **inputs)


def _execute_author_script(source: str, *, policy: SandboxPolicy,
                           model: dict, building: dict, params: dict) -> SandboxResult:
    """Execute validated detached inputs; public entry normalizes host failures."""
    started = time.perf_counter()
    digest = _digest(source.encode("utf-8", "surrogatepass"))
    pools = _model_pools(model)
    model_digest = model_catalog_digest(pools)
    model_blob = (json.dumps(pools, sort_keys=True, ensure_ascii=False,
                             separators=(",", ":"), allow_nan=False)
                  .encode("utf-8", "surrogatepass") if pools else b"")
    building_payload = building if isinstance(building, dict) else {}
    building_digest = building_catalog_digest(building_payload)
    building_blob = (json.dumps(building_payload, sort_keys=True,
                                ensure_ascii=False, separators=(",", ":"),
                                allow_nan=False)
                     .encode("utf-8", "surrogatepass")
                     if building_payload else b"")
    params_payload = params if isinstance(params, dict) else {}
    params_sig = params_digest(params_payload)
    params_blob = (json.dumps(params_payload, sort_keys=True,
                              ensure_ascii=False, separators=(",", ":"),
                              allow_nan=False)
                   .encode("utf-8", "surrogatepass")
                   if params_payload else b"")

    if not source.strip():
        return SandboxResult(
            ok=False, author_digest=digest,
            duration_s=time.perf_counter() - started,
            refusal=_refuse(
                SANDBOX_NO_OPS,
                "исходник пуст: скрипт обязан собрать хотя бы одну операцию IR",
                kind="EmptySource"),
        )

    raw = source.encode("utf-8", "surrogatepass")
    if len(raw) > policy.max_source_bytes:
        return SandboxResult(
            ok=False, author_digest=digest,
            duration_s=time.perf_counter() - started,
            refusal=_refuse(
                SANDBOX_OUTPUT_LIMIT,
                f"исходник {len(raw)} байт при пределе {policy.max_source_bytes}: "
                f"скрипт, который пишет программу, столько не весит — "
                f"вероятно, в него вклеены данные вместо кода",
                kind="SourceTooLarge",
                source_bytes=len(raw), limit=policy.max_source_bytes),
        )

    first = _run_once(raw, policy, model_blob, building_blob, params_blob)
    first.author_digest = digest
    first.model_digest = model_digest
    first.building_digest = building_digest
    first.params_digest = params_sig
    first.duration_s = time.perf_counter() - started

    if first.ok and policy.replay_check:
        # The repeat runs with the SAME catalog: what is checked is
        # the SCRIPT's determinism, and supplying a different document
        # the second time would mean measuring model drift and
        # calling it the author's nondeterminism.
        # The SAME parameters on the second run — by the same
        # argument as the catalog: supplying different ones would
        # mean measuring not the script's determinism but a
        # difference in knobs, and calling that the author's
        # nondeterminism.
        second = _run_once(raw, policy, model_blob, building_blob, params_blob)
        second.author_digest = digest
        second.model_digest = model_digest
        second.building_digest = building_digest
        second.params_digest = params_sig
        if not second.ok:
            second.duration_s = time.perf_counter() - started
            return second
        if second.program_digest != first.program_digest:
            first.ok = False
            first.refusal = _refuse(
                SANDBOX_NONDETERMINISM,
                "две прогонки одного исходника дали РАЗНЫЕ программы. "
                "Подпись исходника (author_digest) в этом случае не удостоверяет "
                "ничего. Ищите источник разброса: обход множества/словаря, "
                "сравнение объектов по адресу, попытку взять время или случайность",
                kind="ReplayMismatch", blame="author",
                digest_run1=first.program_digest, digest_run2=second.program_digest)
            first.ops = []
        first.isolation = dict(first.isolation)
        first.isolation["replay_checked"] = True
        # The repeat also checks the ENVIRONMENT, since it exists
        # anyway. It is almost impossible for two runs of one parent
        # process to diverge — but "almost" gets named in words, not
        # passed over in silence: a package update landing exactly
        # between the two runs would turn the first run's
        # `program_digest` into the signature of an environment that
        # no longer exists.
        first.isolation["environment_replay"] = (
            "same" if second.env_digest == first.env_digest else "CHANGED")
        first.duration_s = time.perf_counter() - started

    return first


def _run_once(raw_source: bytes, policy: SandboxPolicy,
              model_blob: bytes = b"",
              building_blob: bytes = b"",
              params_blob: bytes = b"") -> SandboxResult:
    """One child; public entry names failures after resources are cleaned up."""
    import resource  # locally: the parent needs it only for measurement

    exe = policy.python_exe or sys.executable
    read_fd = write_fd = -1
    jail = None

    env = {
        "PYTHONPATH": os.pathsep.join([_backend_root(), *policy.extra_sys_path]),
        # DETERMINISM: without this the traversal order of string
        # sets changes from run to run, and the source's signature
        # stops meaning anything.
        "PYTHONHASHSEED": "0",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "LC_ALL": "C.UTF-8",
        "TZ": "UTC",
        "PATH": "",
        "KIR_SANDBOX_CFG": json.dumps(policy.child_config()),
    }
    # Operator switches — see ENV_PASSTHROUGH. The child's environment
    # is assembled by us from scratch: a switch not carried over here
    # reads as "off."
    for name in ENV_PASSTHROUGH:
        value = os.environ.get(name)
        if value is not None:
            env[name] = value
    argv = [exe, "-s", "-B", "-c",
            "import kir.sandbox as _s; _s._child_main()"]

    rss_before = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    chunks: list[bytes] = []

    def _drain() -> None:
        try:
            while True:
                block = os.read(read_fd, 65536)
                if not block:
                    break
                chunks.append(block)
        except OSError:
            pass

    reader = threading.Thread(target=_drain, daemon=True)
    proc = None
    timed_out = False
    stderr_text = ""
    try:
        read_fd, write_fd = os.pipe()
        jail = tempfile.mkdtemp(prefix="kir_jail_")
        env["KIR_SANDBOX_RESULT_FD"] = str(write_fd)
        env["KIR_SANDBOX_JAIL"] = jail
        try:
            proc = subprocess.Popen(
                argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, env=env, cwd=jail,
                pass_fds=(write_fd,), start_new_session=True,
                close_fds=True,
            )
        except OSError as exc:
            return SandboxResult(ok=False, refusal=_refuse(
                SANDBOX_UNAVAILABLE,
                "песочница не запустилась: интерпретатор не стартовал",
                kind=type(exc).__name__, blame="sandbox", error=str(exc)))

        os.close(write_fd)
        write_fd = -1
        reader.start()

        try:
            # THE STDIN FRAME: the catalog's length as a decimal
            # string, a newline, the catalog itself, then the source
            # VERBATIM. The header is written ALWAYS — "a zero-length
            # catalog" and "there was no catalog" must be read by one
            # and the same parser, otherwise the child gets a branch
            # that nobody ever runs. The source's signature is taken
            # BEFORE framing and is not changed by the frame.
            frame = (FRAME_MARKER + b"\n"
                     + str(len(model_blob)).encode("ascii") + b"\n"
                     + str(len(building_blob)).encode("ascii") + b"\n"
                     + str(len(params_blob)).encode("ascii") + b"\n"
                     + model_blob + building_blob + params_blob + raw_source)
            _, err = proc.communicate(input=frame, timeout=policy.wall_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_group(proc)
            try:
                _, err = proc.communicate(timeout=5.0)
            except Exception:
                err = b""
        stderr_text = (err or b"").decode("utf-8", "replace")
        reader.join(timeout=5.0)
    finally:
        if proc is not None and proc.poll() is None:
            _kill_group(proc)
            try:
                proc.wait(timeout=5.0)
            except Exception:
                pass  # No confirmed process-tree termination is claimed.
        for fd in (read_fd, write_fd):
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
        # rmdir is not enough: RLIMIT_FSIZE=0 forbids CONTENT, but
        # does not stop an empty file from being created, and such a
        # file would leave the directory on prod forever.
        if jail is not None:
            shutil.rmtree(jail, ignore_errors=True)

    # THE PARENT'S NUMBER IS EVIDENCE, NOT A READING, and here is why.
    # `ru_maxrss` under RUSAGE_CHILDREN is the high-water mark across
    # all reaped children, and on top of that it is assembled from the
    # CHILDREN's own `ru_maxrss` values, each inherited from the
    # parent on fork (measured in `_read_vm_hwm`). So an increase only
    # proves "not less than," and only in a single-threaded caller at
    # that. The run's peak comes from the child itself, via VmHWM;
    # only a trace for operator-side analysis falls here, for when the
    # child died without saying anything.
    rss_after = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    children_growth = max(0, rss_after - rss_before)

    payload_bytes = b"".join(chunks)
    if len(payload_bytes) > policy.max_result_bytes:
        return SandboxResult(ok=False, refusal=_refuse(
            SANDBOX_OUTPUT_LIMIT,
            f"скрипт выдал больше {policy.max_result_bytes} байт — "
            f"это транспортный предел песочницы, а не бюджет компилятора",
            kind="ResultTooLarge", blame="author", bytes=len(payload_bytes)))

    payload = _parse_result_channel(payload_bytes)
    if payload is None:
        if payload_bytes:
            stderr_text += "\n[sandbox] result channel unparsable"
        return _classify_dead_child(proc, timed_out, policy, stderr_text,
                                    children_growth)

    # peak_rss_kb comes ONLY from the child (VmHWM). It must not be
    # substituted with the parent's evidence: that would produce a
    # number that depends on who ran in the suite BEFORE us.
    result = _result_from_payload(payload, policy)
    if children_growth:
        result.isolation.setdefault("children_rss_growth_kb", children_growth)
    return result


def _parse_result_channel(payload_bytes: bytes) -> Optional[dict]:
    """Parsing the result channel.

    The channel is separate from stdout precisely so that the
    script's print cannot corrupt it. But code that escaped could in
    theory write to the descriptor directly, so the second attempt is
    the last non-empty line."""
    if not payload_bytes:
        return None
    text = payload_bytes.decode("utf-8", "replace")
    for candidate in (text, *reversed(text.strip().splitlines())):
        try:
            got = json.loads(candidate)
        except Exception:
            continue
        if isinstance(got, dict) and "ok" in got:
            return got
    return None


def _kill_group(proc: "subprocess.Popen") -> None:
    """Terminate the child group, including startup before its syscall guard.

    This is cleanup, not a claim of complete process-tree termination.
    """
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except Exception:
            pass


def _classify_dead_child(proc, timed_out: bool, policy: SandboxPolicy,
                         stderr_text: str, children_growth: int) -> SandboxResult:
    """The child did not hand back a result. We classify by WHAT it
    died of.

    `peak_rss_kb` STAYS ZERO here, and that is honest: the peak comes
    from the child (VmHWM), and a dead child said nothing. The
    parent's increase is placed into the refusal's evidence, not into
    the reading field — otherwise the number would depend on who ran
    before us."""
    rc = proc.returncode if proc is not None else None
    tail = stderr_text.strip()[-1500:]
    trace = children_growth or None

    if timed_out:
        return SandboxResult(ok=False, refusal=_refuse(
            SANDBOX_TIMEOUT,
            f"скрипт не завершился за {policy.wall_seconds:g} с по стене и снят. "
            f"Вероятнее всего — цикл без выхода. Строку назвать не могу: процесс "
            f"снят снаружи, а не остановлен изнутри. "
            f"Пределы: процессорное время {policy.cpu_seconds:g} с, стена "
            f"{policy.wall_seconds:g} с",
            kind="WallTimeout", blame="author",
            wall_seconds=policy.wall_seconds, stderr_tail=tail,
            children_rss_growth_kb=trace))

    if rc is not None and rc < 0:
        signum = -rc
        name = signal.Signals(signum).name if signum in set(
            s.value for s in signal.Signals) else f"SIG{signum}"
        if signum == signal.SIGXCPU:
            return SandboxResult(ok=False, refusal=_refuse(
                SANDBOX_TIMEOUT,
                f"скрипт исчерпал жёсткий предел процессорного времени "
                f"({policy.cpu_seconds:g} с) и снят ядром. Так бывает, когда "
                f"цикл без выхода проглотил и мягкое предупреждение тоже "
                f"(перехватывать BaseException в скрипте не надо)",
                kind=name, blame="author", cpu_seconds=policy.cpu_seconds,
                children_rss_growth_kb=trace))
        if signum == signal.SIGSEGV:
            return SandboxResult(ok=False, refusal=_refuse(
                SANDBOX_CRASH,
                "интерпретатор упал на этом скрипте (SIGSEGV). Обычные причины — "
                "очень глубокая вложенность выражения, рекурсия без базового "
                "случая или обращение к памяти в обход языка. Программа не "
                "собрана; процесс был отдельным, поэтому падение никого не задело",
                kind=name, blame="author", stderr_tail=tail))
        if signum == signal.SIGKILL:
            return SandboxResult(ok=False, refusal=_refuse(
                SANDBOX_MEMORY,
                f"процесс скрипта снят ядром (SIGKILL) без сообщения. Обычно это "
                f"нехватка памяти: предел этого запуска — {policy.memory_mb} МБ",
                kind=name, blame="unknown", memory_mb=policy.memory_mb,
                stderr_tail=tail, children_rss_growth_kb=trace))
        return SandboxResult(ok=False, refusal=_refuse(
            SANDBOX_CRASH,
            f"процесс скрипта снят сигналом {name} и не отдал результата",
            kind=name, blame="unknown", stderr_tail=tail))

    return SandboxResult(ok=False, refusal=_refuse(
        SANDBOX_UNAVAILABLE,
        "песочница не отдала результата — это наш дефект, а не ошибка скрипта",
        kind="NoResult", blame="sandbox", returncode=rc, stderr_tail=tail))


def _result_from_payload(payload: dict, policy: SandboxPolicy) -> SandboxResult:
    isolation = dict(payload.get("isolation") or {})
    environment = dict(payload.get("environment") or {})
    stdout = str(payload.get("stdout") or "")
    peak = int(payload.get("peak_rss_kb") or 0)
    # The read ledger travels on BOTH outcomes. This is not symmetry
    # for symmetry's sake: a turn that only asked and built nothing is
    # declared a refusal by the sandbox, `KIR-B013` (exploration) —
    # and that is EXACTLY the turn where the course is read most
    # often. A ledger that only arrived on success would measure the
    # course's consumption everywhere except at the place it is
    # consumed most.
    reads = payload.get("course_reads")
    reads = list(reads) if isinstance(reads, list) else []

    if payload.get("ok"):
        ops = payload.get("ops") or []
        # 🔴 THE CHILD SAID "IT WORKED" WITHOUT ASSEMBLING A SINGLE
        # OPERATION. The parent must turn this into a NAMED refusal,
        # not a receipt. Until 02.09.2026 such a pair used to travel
        # outward as `ok=True, ops=[]` — "succeeded," having built
        # nothing; from that day the class does not construct it at
        # all (`SandboxResult.__post_init__`), and without this
        # branch a live turn would have crashed with an EXCEPTION
        # instead of an answer. A refusal to the author is cheaper
        # than a service crash, and cheaper than a silent green one —
        # both are worse than a named reason.
        if not ops:
            # 🔴 WITHOUT `author_digest` AND `duration_s`, AND THIS IS
            # NOT AN ECONOMY. They are simply NOT IN this scope:
            # `_result_from_payload` takes `payload` and `policy`, and
            # the signature and the clock live with the caller. The
            # first version of this called both names and would have
            # raised `NameError` the first time the child said "ok"
            # without operations — that is, in a branch no test ever
            # entered. Caught by the guard
            # `test_names_are_bound_where_they_are_called`, not by a
            # run: execution never reached here even once.
            return SandboxResult(
                ok=False, stdout=stdout,
                refusal=_refuse(
                    SANDBOX_NO_OPS,
                    "скрипт отработал без ошибки, но не собрал ни одной "
                    "операции IR: строить нечего. Если ход был разведочным — "
                    "это законно, и печать ответа уже у тебя; если строил — "
                    "проверь, что вызовы языка не остались внутри условия, "
                    "которое не выполнилось",
                    kind="NoOpsFromChild"),
            )
        envelope = dict(payload.get("envelope") or {})
        # We finish assembling the envelope BEFORE the digest —
        # otherwise the signature would describe a different program
        # from the one that travels onward. See the argument at
        # `_ir_version`: the `ops`-variable path is declared
        # legitimate, and it must arrive.
        envelope.setdefault("ir_version", _ir_version())
        # NARROWING BY THE TOP-LEVEL `ops` LIST IS NOT ALLOWED, AND
        # THIS WAS NOTICED BEFORE A RUN. An op that became a GROUP
        # MEMBER is taken out of `ops` (`Program.take`) and lives
        # inside `member_ops`. Filtering by the top level would
        # discard provenance exactly for the operations the author
        # wrote with a loop — that is, for the main case. An extra
        # key is harmless (a lookup by a foreign id simply finds
        # nothing), a lost one is not.
        raw_lineage = payload.get("lineage")
        lineage: dict = {}
        if isinstance(raw_lineage, dict):
            lineage = {str(k): [int(n) for n in v]
                       for k, v in raw_lineage.items() if isinstance(v, list)}
        return SandboxResult(
            ok=True, ops=list(ops), envelope=envelope, stdout=stdout,
            isolation=isolation, environment=environment, peak_rss_kb=peak,
            params=list(payload.get("params") or []),
            course_reads=reads, lineage=lineage,
            left_behind=[dict(item) for item
                         in (payload.get("left_behind") or ())
                         if isinstance(item, dict)],
            program_digest=_program_digest(list(ops), envelope))

    refusal = SandboxRefusal.from_dict(payload.get("refusal") or {})
    return SandboxResult(ok=False, refusal=refusal, stdout=stdout,
                         isolation=isolation, environment=environment,
                         course_reads=reads, peak_rss_kb=peak)


# ─────────────────────────────────────────────────────────────────────────────
# THE CHILD
# ─────────────────────────────────────────────────────────────────────────────

class _CpuExhausted(BaseException):
    """SIGXCPU, raised as an exception. A subclass of BaseException ON
    PURPOSE: an `except Exception` in the script must not swallow
    it."""

    def __init__(self, lineno: Optional[int]):
        super().__init__("cpu time exhausted")
        self.lineno = lineno


class _ForbiddenImport(BaseException):
    def __init__(self, module: str):
        super().__init__(module)
        self.module = module


class _ForbiddenBuiltin(BaseException):
    def __init__(self, name: str):
        super().__init__(name)
        self.name = name


class _BadParam(BaseException):
    """A slider was declared or supplied incorrectly.

    A subclass of BaseException and its own class — for the same two
    reasons as its neighbors above. First: an `except Exception` in
    the script must not swallow this refusal, otherwise the program
    would be assembled on default values and signed as if it had been
    ordered. Second: parsing goes through `fail_from_exception`, so
    the refusal arrives WITH THE LINE NUMBER of that very `param()`
    call.

    🔴 Calling `refuse()` here is NOT ALLOWED, and this was measured
    by reading the seam: `refuse()` does `sys.exit(0)`, and `exec` is
    wrapped in `except SystemExit`, which on code 0 goes ON — to
    assembling the program and a second `emit` into an
    already-closed descriptor. The very same seam that saves the
    script from its own `exit()` would silently swallow our refusal.
    """

    def __init__(self, message: str, *, kind: str, blame: str = "caller",
                 **detail: Any):
        super().__init__(message)
        self.message_ru = message
        self.kind = kind
        self.blame = blame
        self.detail = detail


class _CappedWriter:
    """The script's sys.stdout. Print garbage does not go into the
    result channel at all — it goes HERE, gets truncated to a
    ceiling, and is returned to the model as feedback."""

    def __init__(self, cap: int):
        self.cap = cap
        self.parts: list[str] = []
        self.size = 0
        self.dropped = 0

    def write(self, s) -> int:
        text = s if isinstance(s, str) else str(s)
        room = self.cap - self.size
        if room > 0:
            self.parts.append(text[:room])
            self.size += min(room, len(text))
        if len(text) > max(room, 0):
            self.dropped += len(text) - max(room, 0)
        return len(text)

    def flush(self) -> None:
        return None

    def isatty(self) -> bool:
        return False

    def getvalue(self) -> str:
        out = "".join(self.parts)
        if self.dropped:
            out += f"\n[обрезано ещё {self.dropped} символов]"
        return out


def _import_reason(module: str, allowed: tuple[str, ...]) -> tuple[str, str]:
    """Why a particular module is absent — by CODE and by prose,
    grouped by family.

    The refusal must TEACH: "the module is not allowed" will be read
    by the model as a whim and it will try a neighbor, while
    "nondeterminism breaks the signature" closes off the whole family
    at once.

    🔴 RETURNS A PAIR SINCE 02.09.2026 (E-85), AND THIS IS NOT A
    CONVENIENCE, IT IS A FAULT BEING FIXED. The prose here used to
    distinguish three COMPLETELY different states — "not allowed,"
    "allowed but not installed," "our own defect" — while the
    refusal code for all three was the same: `KIR-B004` with the
    blame on the AUTHOR. A distinction carried only in prose is
    invisible to a machine (the same argument that introduced
    `KIR-B015`), and the author of a correct program went off to edit
    a whitelist they had never touched, instead of installing the
    package. The code names the fix; the prose explains it.
    """
    root = module.split(".")[0]
    allow = ", ".join(allowed)

    # 🔴 FIRST — THE CASE WHEN THE ROOT IS IN THE LIST (fix
    # 29.08.2026, E-17).
    #
    # The refusal was SELF-CONTRADICTORY and pointed at the wrong
    # cause. Live on this machine: «импорт 'shapely.geometry'
    # запрещён. белый список импортов закрыт: разрешено ровно ...,
    # shapely, numpy» — that is, one and the same text called the
    # module both forbidden and allowed. The suggested move ("extend
    # the list") does not help: there is nothing to extend, it is
    # already there.
    #
    # The real cause is in `_import_permitted`: a submodule is let
    # through on the criterion `hasattr(sys.modules.get(root),
    # "__path__")`, and this criterion conflates TWO different
    # states. `sys.modules.get(root) is None` means "not loaded" — in
    # this environment the library simply DOES NOT EXIST — not "not a
    # package." The sandbox child runs with `-s` and
    # `PYTHONNOUSERSITE=1`, and a library sitting in user site is not
    # visible to it AT ALL.
    #
    # The difference is not cosmetic: the three states have three
    # DIFFERENT next moves — install the library, do not call the
    # submodule, do not call the module. A refusal that names the
    # wrong cause sends the reader to fix the wrong thing.
    if root in allowed:
        present = sys.modules.get(root)
        if present is None:
            # ENVIRONMENT, NOT THE AUTHOR: the whitelist has nothing
            # to do with it, there is nothing to fix.
            return (SANDBOX_CAPABILITY_ABSENT,
                    f"библиотека «{root}» РАЗРЕШЕНА, но в этой среде НЕ "
                    f"УСТАНОВЛЕНА (или не загрузилась): белый список тут ни "
                    f"при чём — расширять нечего, {root} уже в нём. Скрипт "
                    f"исполняется отдельным процессом с `-s`, поэтому "
                    f"библиотеки из пользовательского site ему не видны; "
                    f"нужна установка в то окружение, которым запущен "
                    f"родитель")
        if not hasattr(present, "__path__"):
            # The author called a submodule on a non-package — this
            # is their line and their fix to make.
            return (SANDBOX_FORBIDDEN_IMPORT,
                    f"«{root}» разрешён, но он НЕ ПАКЕТ, и подмодуля "
                    f"«{module}» у него не бывает вовсе. Зовите сам "
                    f"«{root}»")
        # The package is in place and loaded — we should not be able
        # to land here; if we did, the pass-through rule and the
        # refusal text have drifted apart, and that must be said
        # aloud, not answered with a generic phrase about the
        # whitelist.
        # 🔴 THIS BRANCH NAMES ITSELF AS OUR OWN DEFECT — AND NOW ITS
        # CODE DOES TOO. It is unreachable by construction (the
        # pass-through rule would have let the import through), but
        # unreachability must SPEAK UP, not stay silent under a
        # foreign code with the blame on the author: exactly this
        # lesson was bought on `KIR-B013` in `serving`.
        return (SANDBOX_UNAVAILABLE,
                f"«{module}» отклонён, хотя «{root}» разрешён, загружен и "
                f"является пакетом — правило пропуска и объяснение отказа "
                f"разошлись. Это дефект песочницы, а не скрипта")

    nondet = {"random", "secrets", "uuid", "time", "datetime", "calendar",
              "statistics", "hashlib", "hmac", "tempfile"}
    system = {"os", "sys", "subprocess", "shutil", "pathlib", "io", "glob",
              "ctypes", "signal", "resource", "multiprocessing", "threading",
              "importlib", "builtins", "gc", "inspect", "sysconfig", "pty"}
    net = {"socket", "urllib", "http", "requests", "ftplib", "smtplib",
           "asyncio", "ssl", "telnetlib", "xmlrpc", "webbrowser"}
    # THERE IS NO SEPARATE FAMILY FOR shapely/numpy HERE, ON PURPOSE.
    # It would fire EXACTLY when the flag is off (when it is on,
    # these names are allowed and never reach the refusal) — that is,
    # it would change the refusal text on a path that must stay
    # byte-for-byte the same. The generic phrase below is already
    # true: the whitelist is closed, and it is listed in full.
    # Below is the REAL prohibition: the root is outside the
    # whitelist. Here the fix is the author's (call something else),
    # and the code stays `KIR-B004`.
    if root in nondet:
        return (SANDBOX_FORBIDDEN_IMPORT,
                f"НЕДЕТЕРМИНИЗМ ЗАПРЕЩЁН: исходник скрипта подписывается в "
                f"квитанции, и подпись недетерминированного скрипта не "
                f"подписывает ничего. Нужен разброс — впишите числа явно. "
                f"Разрешено ровно: {allow}")
    if root in system:
        return (SANDBOX_FORBIDDEN_IMPORT,
                f"доступа к системе у скрипта нет: наружу выходит ровно одна "
                f"вещь — программа IR. Разрешено ровно: {allow}")
    if root in net:
        return (SANDBOX_FORBIDDEN_IMPORT,
                f"сети нет вовсе: скрипт исполняется в отдельном сетевом "
                f"пространстве имён без единого маршрута. Разрешено ровно: {allow}")
    return (SANDBOX_FORBIDDEN_IMPORT,
            f"белый список импортов закрыт: разрешено ровно {allow} "
            f"(и язык KIR, который уже доступен без импорта)")


_BUILTIN_REASONS = {
    "open": "файлов нет: скрипт исполняется в пустом корне и без права записи "
            "(RLIMIT_FSIZE=0). Всё, что нужно программе, пишется операциями IR",
    "eval": "исполнение сгенерированного текста запрещено: скрипт подписывается "
            "в квитанции, а подписать можно только то, что читается глазами",
    "exec": "исполнение сгенерированного текста запрещено: скрипт подписывается "
            "в квитанции, а подписать можно только то, что читается глазами",
    "compile": "исполнение сгенерированного текста запрещено: скрипт подписывается "
               "в квитанции, а подписать можно только то, что читается глазами",
    "input": "интерактивного ввода нет: скрипт исполняется без человека рядом",
    "id": "id() — это адрес объекта, то есть недетерминизм: он меняется от "
          "запуска к запуску и делает подпись исходника бессмысленной",
    "globals": "интроспекция пространства имён скрипту не нужна: программа "
               "собирается вызовами языка",
    "locals": "интроспекция пространства имён скрипту не нужна: программа "
              "собирается вызовами языка",
    "vars": "интроспекция пространства имён скрипту не нужна: программа "
            "собирается вызовами языка",
    "breakpoint": "отладчика здесь нет: процесс исполняется без терминала",
    # NAMES WHAT IS REACHABLE, NOT THE GENRE. Until 04.08 the refusal
    # pointed "to the hint" — true and useless: the hint arrives once
    # and does not answer "what slots does THIS op have." Measured
    # the same day: a weak model spent 13 of 27 refusals guessing
    # slots one at a time, one per turn. Every language function's
    # docstring is assembled from the registry (`dsl._docstring`:
    # slots, kinds, bounds, postcondition) and is read RIGHT IN THE
    # SCRIPT — that is, in the same turn, with no second round.
    # Verified by execution in the sandbox, not deduced.
    "help": "интерактивной справки нет, но форма опа читается в самом скрипте: "
            "print(create_wall.__doc__) печатает ВСЕ слоты с видами, границами "
            "и постусловием — в квитанцию ЭТОГО ЖЕ хода",
    "exit": "выходить не надо: программа считается собранной, когда скрипт "
            "дошёл до конца",
    "quit": "выходить не надо: программа считается собранной, когда скрипт "
            "дошёл до конца",
    "__import__": "импорт вызывается через инструкцию import и ограничен белым "
                  "списком",
}

_SAFE_BUILTIN_NAMES = (
    "abs", "all", "any", "ascii", "bin", "bool", "bytearray", "bytes",
    "callable", "chr", "complex", "dict", "dir", "divmod", "enumerate",
    "filter", "float", "format", "frozenset", "getattr", "hasattr", "hash",
    "hex", "int", "isinstance", "issubclass", "iter", "len", "list", "map",
    "max", "min", "next", "object", "oct", "ord", "pow", "print", "range",
    "repr", "reversed", "round", "set", "setattr", "delattr", "slice",
    "sorted", "staticmethod", "classmethod", "property", "str", "sum",
    "super", "tuple", "type", "zip", "True", "False", "None",
    "NotImplemented", "Ellipsis", "__build_class__",
    # exceptions — so the script can write a normal except
    "BaseException", "Exception", "ArithmeticError", "AssertionError",
    "AttributeError", "IndexError", "KeyError", "LookupError", "MemoryError",
    "NameError", "NotImplementedError", "OverflowError", "RecursionError",
    "RuntimeError", "StopIteration", "TypeError", "ValueError",
    "ZeroDivisionError", "UnicodeError", "FloatingPointError",
)


def _child_main() -> None:  # pragma: no cover — executes in another process
    """The child's entry point. Everything that fails here must exit
    as a refusal."""
    import builtins
    import ctypes
    import dataclasses
    import gc
    import resource
    import types

    result_fd = int(os.environ.get("KIR_SANDBOX_RESULT_FD", "-1"))
    jail = os.environ.get("KIR_SANDBOX_JAIL", "")
    try:
        cfg = json.loads(os.environ.get("KIR_SANDBOX_CFG") or "{}")
    except Exception:
        cfg = {}

    state: dict = {"isolation": {"process_creation": {"state": "not_applied"}}, "environment": {}, "stdout": "",
                   "source_lines": [], "hwm_fd": -1}

    def course_reads() -> list:
        """The course-read ledger — WITHOUT AN IMPORT and with no
        right to fail.

        Read from already-loaded modules, not imported: by the time
        `emit` runs, the import guard (`_MetaGuard`) may already be
        removed, or may not be, and introducing a dependency here on
        the order of removal would mean putting telemetry ahead of
        the result. The course was never called — the module is not
        in `sys.modules`, the ledger is empty, and that is a
        legitimate outcome.
        """
        try:
            module = sys.modules.get("kir.course")
            reader = getattr(module, "reads_ledger", None) if module else None
            return list(reader()) if callable(reader) else []
        except Exception:  # noqa: BLE001 — the ledger must not change the result
            return []

    def op_lineage() -> dict:
        """The operations' provenance — WITHOUT AN IMPORT and with no
        right to fail.

        By the same trick as `course_reads()` above, and for the same
        reason: the language is already loaded in THIS process, and
        importing it from here would mean depending on whether the
        import guard has already been removed.

        🔴 WE ASK `kir.dsl`, NOT `dsl_module`, AND THIS IS NOT A
        TRIFLE (caught by measurement on 27.08.2026, before the first
        run). The `dsl_module` default is the `kir.course.language`
        shim; it hands out `take_ops` BY NAME (deliberately absent
        from `dsl.__all__`), and does not hand out `take_lineage` at
        all. Had we asked the shim, `getattr` would have returned
        `None`, provenance would have silently turned out EMPTY, and
        every test on it would have gone green by construction —
        exactly the vacuous green this whole house was written
        against.

        The sidecar has exactly one carrier: `_append` lives in
        `kir.dsl`, and `course.take_ops()` calls `dsl.take_ops()`
        verbatim, so the store is always there, whichever front the
        author uses.

        A language front that accumulates ops ITSELF will not give
        provenance — and that is an honest absence: there is nowhere
        to take it from there.
        """
        try:
            module = sys.modules.get("kir.dsl")
            reader = getattr(module, "take_lineage", None) if module else None
            got = reader() if callable(reader) else None
            return dict(got) if isinstance(got, dict) else {}
        except Exception:  # noqa: BLE001 — provenance must not change the result
            return {}

    def emit(payload: dict) -> None:
        payload.setdefault("isolation", state["isolation"])
        payload.setdefault("environment", state["environment"])
        payload.setdefault("stdout", state["stdout"])
        # HERE, NOT AT EVERY CALLER: `emit` is the only door outward,
        # and both kinds of answer (success and refusal) pass through
        # it. Marking it at the call sites would give a ledger on
        # success and silence on exploration.
        payload.setdefault("course_reads", course_reads())
        # By the same argument as the read ledger: a program left
        # behind is left behind by the author on a refusal too, and
        # staying silent about it there would mean naming the loss
        # only where it is cheapest.
        payload.setdefault("left_behind", list(state.get("left_behind") or ()))
        payload.setdefault("peak_rss_kb", _read_vm_hwm(state["hwm_fd"]))
        try:
            data = json.dumps(payload, ensure_ascii=False,
                              allow_nan=False).encode("utf-8")
        except Exception as exc:
            data = json.dumps({
                "ok": False,
                "refusal": {"code": SANDBOX_UNAVAILABLE, "blame": "sandbox",
                            "kind": type(exc).__name__,
                            "message_ru": "результат не сериализуется"},
            }).encode("utf-8")
        cap = int(cfg.get("max_result_bytes") or MAX_RESULT_BYTES)
        if len(data) > cap:
            data = json.dumps({
                "ok": False,
                "refusal": {
                    "code": SANDBOX_OUTPUT_LIMIT, "blame": "author",
                    "kind": "ResultTooLarge",
                    "message_ru": (f"результат {len(data)} байт при транспортном "
                                   f"пределе песочницы {cap}"),
                },
            }, ensure_ascii=False).encode("utf-8")
        view = memoryview(data)
        while view:
            written = os.write(result_fd, view[:65536])
            view = view[written:]
        try:
            os.close(result_fd)
        except OSError:
            pass

    def refuse(code: str, message: str, *, kind: str, blame: str = "author",
               line: Optional[int] = None, frames: Optional[list] = None,
               **detail: Any) -> None:
        text = None
        if line is not None and 1 <= line <= len(state["source_lines"]):
            text = state["source_lines"][line - 1]
        payload = {
            "ok": False,
            "refusal": {
                "code": code, "message_ru": message, "kind": kind,
                "blame": blame, "line": line, "line_text": text,
                "script_frames": frames or ([line] if line else []),
                "detail": {k: v for k, v in detail.items() if v is not None},
            },
        }
        emit(payload)
        sys.exit(0)

    # ── 1. the source arrives over stdin, then stdin is taken away ──────────
    try:
        raw = sys.stdin.buffer.read()
    except Exception:
        raw = b""
    try:
        devnull = os.open(os.devnull, os.O_RDWR)
        os.dup2(devnull, 0)
    except OSError:
        pass
    # THE FRAME: the catalog's length, a newline, the catalog, the
    # source. The parent writes it ALWAYS (see `_run_once`), so there
    # is no "there is no frame" branch here: it would be a branch
    # that nobody ever runs.
    model_pools: dict = {}
    building_payload: dict = {}
    supplied_params: dict = {}
    # ── FRAME VERSION. Read FIRST, and tolerant of an old parent ─────────────
    #
    # The child is taken from DISK on every run, the parent lives in
    # the service's memory until a restart — so a desync here is not
    # an exception but the norm between an edit and a deployment. It
    # has ONE direction: the child is always the freshest, the parent
    # is the same version or older. So a frame without a tag is not
    # an error but a LEGITIMATE frame from a parent that does not
    # know about the tag yet; it has no parameters in it, by
    # construction, and that is the only thing we do not know about
    # it.
    frame_version = 1
    head, sep, rest = raw.partition(b"\n")
    if head == FRAME_MARKER:
        frame_version = 2
        head, sep, rest = rest.partition(b"\n")
    elif head.startswith(b"KIRFRAME"):
        # A frame FROM THE FUTURE: the parent is newer than the
        # child. By construction this cannot happen (the child comes
        # from disk), but if it did — this is OUR deployment
        # breakage, and it must be named, not arrive as "a corrupted
        # frame."
        refuse(SANDBOX_CRASH,
               f"кадр stdin версии {head.decode('ascii', 'replace')!r}, а этот "
               f"ребёнок понимает {FRAME_MARKER.decode()!r} и безметочный. "
               f"Родитель новее ребёнка — так бывает только при поломке "
               f"выкладки. Это дефект НАШЕЙ стороны",
               kind="FrameVersionAhead", blame="sandbox")
        return
    if not sep or not head.isdigit():
        refuse(SANDBOX_CRASH,
               "кадр stdin песочницы повреждён: заголовок длины каталога не "
               "прочитан. Это дефект НАШЕЙ стороны, а не скрипта",
               kind="FrameError", blame="sandbox")
        return
    head2, sep2, rest = rest.partition(b"\n")
    if not sep2 or not head2.isdigit():
        refuse(SANDBOX_CRASH,
               "кадр stdin песочницы повреждён: заголовок длины индекса здания "
               "не прочитан. Это дефект НАШЕЙ стороны, а не скрипта",
               kind="FrameError", blame="sandbox")
        return
    params_len = 0
    if frame_version >= 2:
        head3, sep3, rest = rest.partition(b"\n")
        if not sep3 or not head3.isdigit():
            refuse(SANDBOX_CRASH,
                   "кадр stdin песочницы повреждён: заголовок длины параметров "
                   "не прочитан. Это дефект НАШЕЙ стороны, а не скрипта",
                   kind="FrameError", blame="sandbox")
            return
        params_len = int(head3)
    model_bytes, rest = rest[:int(head)], rest[int(head):]
    building_bytes, rest = rest[:int(head2)], rest[int(head2):]
    params_bytes, raw = rest[:params_len], rest[params_len:]
    if params_bytes:
        # 🔴 HERE THE "CORRUPTED" BRANCH BEHAVES DIFFERENTLY FROM THE
        # CATALOG'S, AND THIS IS A DECISION. The catalog and the
        # index are a CONVENIENCE: corrupted, they silently become
        # empty, because the script is legitimate without them too.
        # Parameters are INPUT: an empty set instead of the one
        # supplied would mean building the program on default values
        # and signing it as if it had been ordered. This is exactly
        # the outcome the compiler forbids, which is why it is a
        # REFUSAL here.
        try:
            loaded_p = json.loads(params_bytes.decode("utf-8", "surrogatepass"))
        except Exception as exc:
            refuse(SANDBOX_CRASH,
                   f"параметры не разобраны как JSON: {exc}. Это дефект НАШЕЙ "
                   f"стороны — набор собирали мы",
                   kind="ParamsFrameError", blame="sandbox")
            return
        if not isinstance(loaded_p, dict):
            refuse(SANDBOX_PARAM,
                   "параметры обязаны быть объектом «имя -> значение»",
                   kind="ParamsNotAMapping", blame="caller")
            return
        supplied_params = loaded_p
    if building_bytes:
        try:
            loaded_b = json.loads(building_bytes.decode("utf-8", "surrogatepass"))
            if isinstance(loaded_b, dict):
                building_payload = loaded_b
        except Exception:
            # The index is a CONVENIENCE, not a condition for
            # execution: a corrupted index has no right to cancel the
            # turn. The script will see "no index was supplied" and
            # will say so in words if it tries to ask for it.
            building_payload = {}
    if model_bytes:
        try:
            loaded = json.loads(model_bytes.decode("utf-8", "surrogatepass"))
            if isinstance(loaded, dict):
                model_pools = loaded
        except Exception:
            # The catalog is a CONVENIENCE, not a condition for
            # execution: a corrupted catalog has no right to cancel
            # the turn. The script will see "no catalog was supplied"
            # and will say so in words if it tries to ask for it.
            model_pools = {}
    try:
        source = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        refuse(SANDBOX_SYNTAX,
               f"исходник не в UTF-8: {exc.reason} на байте {exc.start}",
               kind="UnicodeDecodeError")
        return
    state["source_lines"] = source.splitlines()
    state["isolation"]["model_pools"] = len(model_pools)
    state["isolation"]["building_elements"] = len(
        building_payload.get("elements") or ())

    # ── 2. warm-up: EVERYTHING that will be needed is imported BEFORE chroot ─
    for entry in reversed(cfg.get("extra_sys_path") or []):
        if entry and entry not in sys.path:
            sys.path.insert(0, entry)

    allowed = tuple(cfg.get("allowed_imports", ALLOWED_IMPORTS))
    warm: dict[str, Any] = {}
    import importlib
    # ONLY STDLIB WARMS UP HERE, AND THIS IS BEFORE `unshare` —
    # meaning not a single line of this list may raise a thread pool.
    # External modules from the whitelist (shapely/numpy) warm up
    # LOWER, in the window between the namespaces and the empty root,
    # and only if the source named them: numpy pulls in OpenBLAS, and
    # `unshare(CLONE_NEWUSER)` in a multithreaded process answers
    # EINVAL (measured 03.08 — warming up before `unshare` broke
    # EVERY such run).
    warm_names = [n for n in allowed
                  if n in getattr(sys, "stdlib_module_names", frozenset())] + [
        "collections", "collections.abc", "numbers", "decimal", "fractions",
        "copy", "reprlib", "operator", "keyword", "linecache", "encodings.idna",
        "codecs", "abc", "enum", "typing", "re", "string", "textwrap",
    ]
    for name in warm_names:
        try:
            warm[name] = importlib.import_module(name)
        except Exception:
            pass

    dsl_module = cfg.get("dsl_module") or "kir.dsl"
    dsl = None
    dsl_error = ""
    try:
        dsl = importlib.import_module(dsl_module)
    except Exception as exc:
        dsl_error = f"{type(exc).__name__}: {exc}"
    state["isolation"]["dsl_module"] = dsl_module if dsl else f"unavailable ({dsl_error})"

    # ── 3. isolation: namespaces → empty root → limits ───────────────────────
    # The descriptor on /proc/self/status is taken HERE, while /proc
    # is still visible: after chroot the path is unreachable, and the
    # open descriptor is re-read. This is the only honest source for
    # the peak of THIS process (see _read_vm_hwm).
    try:
        state["hwm_fd"] = os.open("/proc/self/status", os.O_RDONLY)
    except OSError:
        state["hwm_fd"] = -1
    state["isolation"]["peak_rss_source"] = (
        "VmHWM" if state["hwm_fd"] >= 0 else "unavailable")

    net_policy = str(cfg.get("network") or "required")
    ns_state = "off"
    if net_policy in ("required", "best_effort"):
        try:
            libc = ctypes.CDLL("libc.so.6", use_errno=True)
            rc = libc.unshare(_CLONE_NEWUSER | _CLONE_NEWNS | _CLONE_NEWNET)
            if rc == 0:
                ns_state = "user+mount+net"
            else:
                ns_state = f"unavailable (errno {ctypes.get_errno()})"
        except Exception as exc:
            ns_state = f"unavailable ({type(exc).__name__})"
    state["isolation"]["namespaces"] = ns_state
    state["isolation"]["uid"] = os.getuid()
    # The network namespace identifier — a measurement that can be
    # CHECKED against the parent's: a match ⇒ there is no network
    # isolation at all, whatever the policy promised. Taken before
    # chroot, while /proc is still visible.
    try:
        state["isolation"]["netns"] = os.readlink("/proc/self/ns/net")
    except OSError:
        state["isolation"]["netns"] = "unknown"

    if net_policy == "required" and not ns_state.startswith("user"):
        refuse(SANDBOX_UNAVAILABLE,
               f"сетевое пространство имён не создано ({ns_state}), а политика "
               f"требует НУЛЯ СЕТИ. Запуск отменён до исполнения скрипта. "
               f"Боксу без непривилегированных user namespaces нужно поставить "
               f"policy.network='best_effort'",
               kind="NamespaceUnavailable", blame="sandbox")
        return

    # A measurement instead of intent: network unreachability is
    # proven with a socket. But only when isolation is DECLARED: if
    # it was deliberately turned off, there is nothing to check, and
    # a stray outgoing packet from the prod box is none of our
    # business.
    state["isolation"]["network_probe"] = "not probed"
    if cfg.get("probe_network") and net_policy != "off":
        state["isolation"]["network_probe"] = _probe_network()
        if (net_policy == "required"
                and state["isolation"]["network_probe"] == "reachable"):
            refuse(SANDBOX_UNAVAILABLE,
                   "замер показал, что сеть достижима, хотя политика требует "
                   "нуля сети. Запуск отменён до исполнения скрипта",
                   kind="NetworkReachable", blame="sandbox")
            return

    # ── THE LANGUAGE WARMS UP WHATEVER THIS PARTICULAR SOURCE NEEDS ──────────
    #
    # THE WINDOW IS EXACTLY HERE, between the namespaces and the empty
    # root, and both of its edges are a MEASUREMENT, not caution.
    #
    # NOT EARLIER than `unshare`: the verdict module pulls in numpy,
    # and numpy raises an OpenBLAS thread pool — and
    # `unshare(CLONE_NEWUSER)` in a multithreaded process answers
    # EINVAL. Measured 03.08: warming up before `unshare` BROKE EVERY
    # run that called `design_check` — the `network="required"`
    # policy honestly cancelled the turn (KIR-B012) even before the
    # script executed.
    #
    # NOT LATER than chroot: shapely and numpy load their .so files
    # from disk, and there is no disk in the empty root. And
    # certainly not later than the import guard (`_MetaGuard`): it
    # would raise KIR-B004 with the MODEL's line number, sending the
    # author to fix a correct script.
    #
    # WHY CONDITIONAL. Measured: the verdict module costs +536 ms and
    # +43 MB, and the script executes TWICE (`replay_check`) on a
    # happy path of 121 ms. THE LANGUAGE DECIDES: the sandbox does not
    # know the grammar (see §CONTRACT) and must not know it. The hook
    # is optional; its exception does not surface here — a module
    # that did not warm up is an absent capability, not a broken
    # turn.
    warm_hook = getattr(dsl, "warm_for_source", None) if dsl is not None else None
    if callable(warm_hook):
        try:
            state["isolation"]["warmed"] = list(warm_hook(source) or ())
        except Exception as exc:
            state["isolation"]["warmed"] = f"failed ({type(exc).__name__}: {exc})"

    # ── THE SAME WINDOW, SECOND HALF: THE WHITELIST, NOT THE LANGUAGE'S NAMES ─
    #
    # The hook above decides about NAMES that the language placed
    # into the script's namespace (`preview`, `design_check`). Here it
    # decides about IMPORTS — and imports belong entirely to the
    # sandbox: the whitelist is its own field, and nobody but it
    # knows what is in it today. The same trick (the SOURCE decides),
    # the same reason (cost), the same window (after `unshare`,
    # before chroot).
    #
    # The text-based condition here is not a heuristic but an EXACT
    # CONDITION, and even more exact than the hook's: to import a
    # module, its name must be written out — `__import__`, `eval`,
    # `exec`, and `globals` are closed to the script.
    state["isolation"]["warmed_libs"] = _warm_allowed_third_party(source, allowed)

    # ── ENVIRONMENT SIGNATURE: THE LAST THING DONE WHILE THE DISK IS ALIVE ───
    # `importlib.metadata` reads dist-info FROM DISK, and one line
    # below the root becomes empty. Computed AFTER warm-up on
    # purpose: only for a loaded module can the version of the native
    # library underneath it be asked (GEOS under shapely).
    try:
        state["environment"] = environment_signature(allowed)
    except Exception as exc:                       # a signature must not be able to break the turn
        state["environment"] = {"error": f"{type(exc).__name__}: {exc}"}

    try:
        process_creation_guard = _load_process_creation_guard()
    except Exception as exc:
        state["isolation"]["process_creation"] = {"state": "unavailable", "failure": type(exc).__name__}
        refuse(SANDBOX_UNAVAILABLE,
               "библиотека запрета создания процессов недоступна; скрипт не исполнялся",
               kind="ProcessCreationGuardUnavailable", blame="sandbox")
        return

    # THE MEMORY BUDGET IS TAKEN AFTER ALL OF OUR OWN IMPORTS, AND
    # THIS IS NOT A TRIFLE.
    #
    # `memory_mb` promises the SCRIPT that many megabytes ON TOP OF
    # what is already used, so the limit = "how much is used right
    # now" + the budget. Measured 03.08 by exactly this rule being
    # broken: the snapshot was taken BEFORE warm-up, warmed-up
    # numpy/shapely (which reserve address space many times over what
    # they occupy in RSS) ate into the script's budget, and a
    # 298-operation program died on the way out with a MemoryError
    # INSIDE json.dumps — that is, a "the result cannot be
    # serialized" refusal instead of an honest "ran out of memory."
    # The whole turn was lost.
    #
    # Cannot be later: /proc is unreachable after chroot (see
    # `_read_vm_hwm`).
    try:
        vm_bytes = _self_vm_size()
    except Exception:
        vm_bytes = 64 * 1024 * 1024

    fs_state = "off"
    if cfg.get("filesystem_isolation") and jail:
        try:
            os.chroot(jail)
            os.chdir("/")
            fs_state = "chroot"
        except Exception as exc:
            fs_state = f"unavailable ({type(exc).__name__}: {exc})"
    state["isolation"]["filesystem"] = fs_state
    if cfg.get("filesystem_isolation") and fs_state != "chroot":
        refuse(SANDBOX_UNAVAILABLE,
               "запрошенная изоляция файловой системы недоступна; скрипт не исполнялся",
               kind="FilesystemIsolationUnavailable", blame="sandbox")
        return

    # SIGXFSZ by default KILLS the process. We ignore it so that a
    # write to a file becomes an ordinary OSError(EFBIG) — that is,
    # an instructive refusal, not silence.
    try:
        signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
    except Exception:
        pass

    def _on_xcpu(signum, frame):
        # The traversal is shared (`author_frames`), not its own: the
        # rule for selecting the author's frames lives in ONE place.
        # `[-1]` is the script's innermost frame, exactly what used
        # to be taken here by a `break` on the first match.
        frames = author_frames(frame)
        raise _CpuExhausted(frames[-1] if frames else None)

    try:
        signal.signal(signal.SIGXCPU, _on_xcpu)
    except Exception:
        pass

    mem_bytes = int(cfg.get("memory_mb") or DEFAULT_MEMORY_MB) * 1024 * 1024
    cpu_s = float(cfg.get("cpu_seconds") or DEFAULT_CPU_SECONDS)
    limits = {}
    for name, value in (
        ("RLIMIT_FSIZE", (0, 0)),                    # nothing to write
        ("RLIMIT_CORE", (0, 0)),                     # prod will not get a dump
        ("RLIMIT_NPROC", (0, 0)),                    # syscall guard below closes privileged exemptions
        ("RLIMIT_NOFILE", (int(cfg.get("nofile") or DEFAULT_NOFILE),) * 2),
        ("RLIMIT_AS", (vm_bytes + mem_bytes, vm_bytes + mem_bytes)),
        ("RLIMIT_CPU", (max(1, int(cpu_s)), max(1, int(cpu_s)) + 2)),
    ):
        try:
            resource.setrlimit(getattr(resource, name), value)
            limits[name] = value[0]
        except (ValueError, OSError, OverflowError) as exc:
            limits[name] = f"failed ({exc})"
    state["isolation"]["limits"] = limits
    state["isolation"]["memory_mb"] = int(cfg.get("memory_mb") or DEFAULT_MEMORY_MB)
    state["isolation"]["cpu_seconds"] = cpu_s
    if any(not isinstance(value, int) for value in limits.values()):
        refuse(SANDBOX_UNAVAILABLE,
               "операционная система не установила обязательные лимиты; скрипт не исполнялся",
               kind="ResourceLimitUnavailable", blame="sandbox")
        return

    try:
        sys.setrecursionlimit(int(cfg.get("recursion_limit") or DEFAULT_RECURSION_LIMIT))
    except (ValueError, RecursionError, OverflowError):
        refuse(SANDBOX_UNAVAILABLE,
               "предел рекурсии не установлен; скрипт не исполнялся",
               kind="ResourceLimitUnavailable", blame="sandbox")
        return
    try:
        state["isolation"]["process_creation"] = _install_process_creation_guard(process_creation_guard)
    except Exception as exc:
        state["isolation"]["process_creation"] = {"state": "unavailable", "failure": type(exc).__name__}
        refuse(SANDBOX_UNAVAILABLE,
               "запрет создания процессов/потоков не установлен; скрипт не исполнялся",
               kind="ProcessCreationGuardUnavailable", blame="sandbox")
        return
    # The environment is wiped entirely, EXCEPT for the operator
    # switches. A wiped switch is not "safer," it is a SILENT
    # DISAGREEMENT with the operator: code that reads the flag live
    # (`checker.flags.checker_v2_enabled` — designed that way so an
    # edit on the service takes effect from the next check) would
    # read "off" in this process while it is on on the service, and
    # would produce the refusal «включите то, что уже включено». It
    # makes no difference to the script: its `os` is unreachable
    # either way, and the list itself is a whitelist and a short one.
    kept = {name: os.environ[name] for name in _ENV_PASSTHROUGH
            if name in os.environ}
    os.environ.clear()
    os.environ.update(kept)

    # ── 4. compiling the source ───────────────────────────────────────────────
    #
    # 🔴 `dont_inherit=True` — THE SCRIPT IS COMPILED IN THE LANGUAGE
    # DIALECT IT WAS WRITTEN IN, NOT IN OURS. By default `compile()`
    # INHERITS the calling module's `__future__`, and this file has,
    # on line 103, `from __future__ import annotations` — written for
    # OUR code. Through it the author silently got PEP 563: all of
    # their annotations turned into STRINGS.
    #
    # Measured 20.08.2026, the same source, only the flag changed:
    #     inheriting (as it was)  ->  AttributeError: 'NoneType' has no '__dict__'
    #     dont_inherit=True       ->  ok
    # That is, `@dataclass class Pt: x: float` — three lines an LLM
    # writes out of habit — used to fail with a foreign error,
    # blaming the author for our own import. The far end is named
    # explicitly: /usr/lib/python3.12/dataclasses.py:749 (`_is_type`)
    # writes `sys.modules.get(cls.__module__).__dict__` WITHOUT a
    # guard, and this branch is reachable ONLY under a string
    # annotation.
    #
    # This is our named defect in pure form: a quantity (the
    # language's dialect) is DECLARED in one place (line 103, about
    # this file) and READ in another (the author's frame), and there
    # was nothing to reconcile them.
    try:
        code = compile(source, SCRIPT_FILENAME, "exec", dont_inherit=True)
    except SyntaxError as exc:
        refuse(SANDBOX_SYNTAX,
               f"скрипт не разобран Python: {exc.msg}",
               kind=type(exc).__name__, line=exc.lineno,
               offset=exc.offset)
        return
    except ValueError as exc:                     # null bytes and the like
        refuse(SANDBOX_SYNTAX, f"скрипт не разобран Python: {exc}",
               kind=type(exc).__name__)
        return
    except MemoryError:
        refuse(SANDBOX_MEMORY,
               f"разбор исходника не уложился в {cfg.get('memory_mb')} МБ",
               kind="MemoryError")
        return
    except RecursionError:
        refuse(SANDBOX_SYNTAX,
               "выражение слишком глубоко вложено — интерпретатор не смог его "
               "разобрать. Разбейте его на промежуточные переменные",
               kind="RecursionError")
        return

    # ── 5. the script's namespace ─────────────────────────────────────────────
    real_import = builtins.__import__

    def _import_permitted(name: str) -> bool:
        """ONE rule for BOTH frontiers — the `__import__` hook and
        the meta_path guard.

        One, not two, because two drift apart: until 09.08 the hook
        required an exact name, while the guard checked only the
        root, and the whitelist meant different things depending on
        which path the import came in by.

        A SUBMODULE RIDES ALONG WITH ITS PACKAGE, and this is decided
        by `__path__`, not a list of names: `shapely.geometry` is
        allowed because `shapely` is a package; `math.foo` is still a
        refusal because `math` is not a package and never has
        submodules at all. Under the default whitelist (three
        non-package stdlib modules) the rule is INDISTINGUISHABLE
        from the previous one — that is exactly the condition "the
        flag being off changes nothing."
        """
        if name in allowed:
            return True
        root = name.split(".")[0]
        if root not in allowed:
            return False
        return hasattr(sys.modules.get(root), "__path__")

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if level != 0:
            raise _ForbiddenImport(("." * level) + (name or ""))
        if _import_permitted(name or ""):
            return real_import(name, globals, locals, fromlist, level)
        raise _ForbiddenImport(name or "")

    class _MetaGuard:
        """The second frontier: catches an import that bypasses
        builtins.__import__."""

        def find_module(self, fullname, path=None):
            return self.find_spec(fullname, path)

        def find_spec(self, fullname, path=None, target=None):
            if _import_permitted(fullname):
                return None
            raise _ForbiddenImport(fullname)

    safe_builtins: dict[str, Any] = {}
    for bname in _SAFE_BUILTIN_NAMES:
        if hasattr(builtins, bname):
            safe_builtins[bname] = getattr(builtins, bname)
    safe_builtins["__import__"] = guarded_import

    def _make_stub(bname: str):
        def _stub(*_a, **_kw):
            raise _ForbiddenBuiltin(bname)
        _stub.__name__ = bname
        return _stub

    for bname in _BUILTIN_REASONS:
        if bname != "__import__":
            safe_builtins[bname] = _make_stub(bname)

    ns: dict[str, Any] = {
        "__name__": "kir_author_script",
        "__builtins__": safe_builtins,
        "__doc__": None,
    }
    if dsl is not None:
        exported = getattr(dsl, "__all__", None)
        names = list(exported) if exported else [
            n for n in vars(dsl) if not n.startswith("_")]
        for n in names:
            value = getattr(dsl, n, None)
            # WE NEVER INJECT MODULES: if dsl.py does `import os`,
            # the script must not get `os` through the injection's
            # back door.
            if isinstance(value, types.ModuleType):
                continue
            ns[n] = value
        ns["kir"] = dsl
    # THE CATALOG IS PLACED ALWAYS, even empty. A name that is
    # sometimes there and sometimes not forces the author to guess
    # whether the capability exists; an empty catalog answers any
    # question with a named reason. This is an OBJECT, not a module:
    # injecting modules is forbidden above by the same rule as `os`.
    # THE CATALOG AND THE INDEX ARE PLACED ALWAYS, even empty: a name
    # that is sometimes there and sometimes not forces the author to
    # guess whether the capability exists, and an empty object
    # answers any question with a named reason. The injection
    # travels as a LIST and is checked against `HOST_NAMES` —
    # otherwise a third name would be introduced silently and slip
    # past the docs guard again (see the argument at the constant
    # itself).
    # ── SLIDER: DECLARATION AND USE IN ONE PLACE ──────────────────────────────
    #
    # The shape was chosen out of three, and two were rejected with
    # an argument.
    #
    # REJECTED: a bare `params` dict in the script's namespace
    # (`params.get("width_mm", 6000)`). There is NO declaration here:
    # there is no way to enumerate the knobs without reading the
    # script by eye, and a typo by the caller ("widht_mm") silently
    # gives the default value — the wrong program gets built, and
    # gets signed as if it had been ordered. This is exactly the
    # outcome the compiler forbids.
    #
    # REJECTED: a module-level table `PARAMS = {...}`, read after the
    # run. The declaration drifts from the use (two carriers of one
    # piece of knowledge — this tree's named defect), and worse: the
    # script needs the value DURING the computation, while the table
    # is only read afterward.
    #
    # ACCEPTED: `param(name, default, min=, max=, choices=, doc=)`
    # returns the EFFECTIVE value. Declaration and use are one line,
    # so there is nothing to drift apart; the ledger of what was
    # declared assembles itself and travels into the receipt, and a
    # slider is drawn from it.
    _declared: dict = {}
    _order: list = []

    def _param_kind(value: Any) -> str:
        # bool FIRST: in python it is a subclass of int, and without
        # this line, a knob declared as a number would accept True as
        # one.
        if isinstance(value, bool):
            return "bool"
        if isinstance(value, int):
            return "int"
        if isinstance(value, float):
            return "float"
        if isinstance(value, str):
            return "str"
        return type(value).__name__

    def _check_range(name: str, kind: str, value: Any, spec: dict,
                     blame: str) -> None:
        lo, hi, choices = spec["min"], spec["max"], spec["choices"]
        if lo is not None and value < lo:
            raise _BadParam(
                f"параметр '{name}' = {value!r} меньше объявленного минимума "
                f"{lo!r}", kind="ParamBelowMin", blame=blame,
                param=name, value=value, min=lo)
        if hi is not None and value > hi:
            raise _BadParam(
                f"параметр '{name}' = {value!r} больше объявленного максимума "
                f"{hi!r}", kind="ParamAboveMax", blame=blame,
                param=name, value=value, max=hi)
        if choices is not None and value not in choices:
            raise _BadParam(
                f"параметр '{name}' = {value!r} не входит в объявленный набор "
                f"{list(choices)!r}", kind="ParamNotInChoices", blame=blame,
                param=name, value=value, choices=list(choices))

    def _param(name: Any, default: Any, *, min: Any = None, max: Any = None,
               choices: Any = None, doc: str = "") -> Any:
        """A named program parameter. Returns the EFFECTIVE value."""
        if not isinstance(name, str) or not name:
            raise _BadParam("имя параметра — непустая строка",
                            kind="ParamNameKind", blame="author")
        if len(name) > MAX_PARAM_NAME or not name.replace("_", "").isalnum():
            raise _BadParam(
                f"имя параметра '{name}' негодно: допустимы буквы, цифры и "
                f"подчёркивание, не длиннее {MAX_PARAM_NAME}. Имя ползунка "
                f"адресуют снаружи — оно обязано быть простым",
                kind="ParamNameShape", blame="author", param=name)
        kind = _param_kind(default)
        if kind not in ("bool", "int", "float", "str"):
            raise _BadParam(
                f"параметр '{name}': умолчание рода {kind} не годится. Ручка — "
                f"ЧИСЛО, СТРОКА или ФЛАГ; список и словарь ручкой не бывают, "
                f"это второй исходник, который никто не читает",
                kind="ParamValueKind", blame="author", param=name, got=kind)
        spec = {"name": name, "default": default, "kind": kind,
                "min": min, "max": max,
                "choices": list(choices) if choices is not None else None,
                "doc": str(doc or "")}
        previous = _declared.get(name)
        if previous is not None:
            # A repeat with the SAME conditions is legitimate: `param`
            # gets called inside a loop or a function. A repeat with
            # DIFFERENT ones is two carriers of one knob, and they
            # will drift apart silently.
            # What is compared is the DECLARATIONS, not the outcomes:
            # `value` and `used_default` are the result of resolving
            # the knob, and the existing record has them while the
            # new description does not yet. The first version
            # compared those too and rejected a LEGITIMATE repeat
            # inside a loop; caught by a narrowness control, not by
            # reading.
            _RESOLVED = ("value", "used_default")
            if {k: v for k, v in previous.items() if k not in _RESOLVED} != spec:
                raise _BadParam(
                    f"параметр '{name}' объявлен дважды по-разному. У одной "
                    f"ручки одно объявление: два разойдутся молча",
                    kind="ParamRedeclared", blame="author", param=name)
            return previous["value"]
        if len(_declared) >= MAX_PARAMS:
            raise _BadParam(
                f"объявлено {MAX_PARAMS} параметров — предел. Набор из сотни "
                f"ручек перестаёт быть набором ручек",
                kind="ParamTooMany", blame="author", limit=MAX_PARAMS)
        # The default must satisfy ITS OWN bounds: otherwise a
        # program without a single supplied parameter is already
        # illegitimate, and only whoever moves the knob would ever
        # find that out.
        if kind in ("int", "float"):
            _check_range(name, kind, default, spec, "author")
        elif spec["choices"] is not None and default not in spec["choices"]:
            _check_range(name, kind, default, spec, "author")

        value, used_default = default, True
        if name in supplied_params:
            given = supplied_params[name]
            given_kind = _param_kind(given)
            # Widening int -> float is legitimate (millimeters get
            # written both ways); the reverse, and everything else,
            # is not.
            if not (given_kind == kind
                    or (kind == "float" and given_kind == "int")):
                raise _BadParam(
                    f"параметр '{name}' объявлен как {kind}, а подан как "
                    f"{given_kind}",
                    kind="ParamKindMismatch", blame="caller",
                    param=name, expected=kind, got=given_kind)
            if kind == "float":
                given = float(given)
            if kind in ("int", "float") or spec["choices"] is not None:
                _check_range(name, kind, given, spec, "caller")
            value, used_default = given, False

        spec["value"] = value
        spec["used_default"] = used_default
        _declared[name] = spec
        _order.append(name)
        return value

    hosts = {
        "model": ModelCatalog(model_pools, model_catalog_digest(model_pools)),
        "building": BuildingView(building_payload,
                                 building_catalog_digest(building_payload)),
        "param": _param,
    }
    if set(hosts) != set(HOST_NAMES):
        refuse(SANDBOX_UNAVAILABLE,
               "песочница кладёт имена %s, а объявлены %s — это дефект НАШЕЙ "
               "стороны: имя, не названное в HOST_NAMES, не проверяет ни один "
               "сторож документации"
               % (sorted(hosts), sorted(HOST_NAMES)),
               kind="HostNamesDrift", blame="sandbox")
        return
    ns.update(hosts)

    stdout = _CappedWriter(int(cfg.get("max_stdout_chars") or MAX_STDOUT_CHARS))
    real_stdout, real_stderr = sys.stdout, sys.stderr
    sys.stdout = stdout
    sys.stderr = stdout
    sys.meta_path.insert(0, _MetaGuard())

    def script_frames(tb) -> list[int]:
        out = []
        while tb is not None:
            if tb.tb_frame.f_code.co_filename == SCRIPT_FILENAME:
                out.append(tb.tb_lineno)
            tb = tb.tb_next
        return out

    def restore() -> None:
        sys.stdout, sys.stderr = real_stdout, real_stderr
        state["stdout"] = stdout.getvalue()
        for finder in list(sys.meta_path):
            if isinstance(finder, _MetaGuard):
                sys.meta_path.remove(finder)

    def fail_from_exception(exc: BaseException, frames: list[int]) -> None:
        """ONE single point converting a python exception into a
        typed refusal.

        One, not two, because an exception from `build()` is the same
        model error as an exception from the script's body, and the
        refusal code must match."""
        line = frames[-1] if frames else None
        if isinstance(exc, _BadParam):
            refuse(SANDBOX_PARAM, exc.message_ru, kind=exc.kind,
                   blame=exc.blame, line=line, frames=frames, **exc.detail)
            return
        if isinstance(exc, _ForbiddenImport):
            module = exc.module
            # 🔴 ASK THE WARM-UP FIRST, THEN ASSIGN BLAME
            # (01.09.2026).
            #
            # The warm-up had already recorded ITS OWN failure in
            # `isolation.warmed` with the tag `НЕ ЗАГРУЖЕН:` (fix
            # 29.08, finding E-18) — but the refusal did not look at
            # that field, and so it printed "import forbidden, write
            # create_wall(...)" on the line where the author had
            # written a CALL and not a single import. The author was
            # blamed for something they never wrote, while the real
            # cause — "the module is unreachable from the child's
            # path" — sat right next to it, in the receipt.
            #
            # THIS IS THE SAME SHAPE AS E-17, AND IT WAS ONLY HALF
            # CLOSED: 29.08 taught the warm-up to SPEAK, but did not
            # teach the refusal to LISTEN. The channel existed, the
            # reader did not.
            #
            # THE MEASUREMENT THAT FORCED THE FIX: the course's
            # standard «жильё» recipe under `PYTHONPATH=/opt/kir
            # python3.12` refused with `KIR-B004` on the line
            # `design_check([stairs, build()])`, while `warmed` in
            # the same receipt carried `НЕ ЗАГРУЖЕН:kir.design_check
            # (ModuleNotFoundError)`. On the same tree under a venv
            # where the package is installed, everything passes —
            # that is, the refusal was about the ENVIRONMENT but was
            # printed as if it were about the SCRIPT.
            #
            # `blame` is taken from the closed list (`sandbox`)
            # rather than introducing a sixth value: a warm-up
            # failure is a capability the sandbox failed to provide,
            # and that is exactly what `sandbox` already means.
            warm_failure = _warm_failure_for(state, module)
            if warm_failure is not None:
                reason = (
                    f"это НЕ запрет и НЕ твоя строка: прогрев песочницы не "
                    f"смог загрузить модуль до изоляции ({warm_failure}). "
                    f"Способность отсутствует в ЭТОЙ среде — проверь, что "
                    f"пакет `kir` установлен в интерпретаторе, которым идёт "
                    f"запуск: дочерний процесс не наследует PYTHONPATH")
                # 🔴 OUR OWN CODE, NOT SOMEONE ELSE'S (02.09.2026,
                # E-85). The fix of 01.09 taught the refusal to
                # LISTEN to the warm-up and rewrote the prose — but
                # the code stayed `KIR-B004`, "import forbidden," with
                # the blame on the AUTHOR, while `blame="sandbox"`
                # (=`ours`) promised a fix ON OUR SIDE that does not
                # exist here. The reader of the tag was prose, while
                # the machine still saw an import ban on the line
                # where a CALL stands. `KIR-B016` names exactly what
                # happened: the capability is allowed, but is not
                # installed in this environment — the fix belongs to
                # the environment.
                refuse(SANDBOX_CAPABILITY_ABSENT,
                       f"'{module}' недоступен. {reason}",
                       kind="WarmFailed", blame="environment", line=line,
                       frames=frames, module=module, allowed=list(allowed),
                       warm_failure=warm_failure)
                return
            if module.split(".")[0] == (dsl_module or "").split(".")[0]:
                code = SANDBOX_FORBIDDEN_IMPORT
                reason = ("язык уже доступен без импорта: пишите "
                          "create_wall(...) или kir.create_wall(...)")
            else:
                code, reason = _import_reason(module, allowed)
            # THE HEADLINE FOLLOWS THE CODE, NOT THE OTHER WAY
            # AROUND. "Import forbidden" for a missing library is a
            # self-contradiction bought by E-17 and E-85: the
            # whitelist has nothing to do with it, there is nothing
            # to extend.
            head = ("импорт '%s' запрещён." % module
                    if code == SANDBOX_FORBIDDEN_IMPORT
                    else "'%s' недоступен." % module)
            refuse(code, f"{head} {reason}",
                   kind=("ForbiddenImport" if code == SANDBOX_FORBIDDEN_IMPORT
                         else "CapabilityAbsent"),
                   blame=_IMPORT_FAILURE_BLAME[code],
                   line=line, frames=frames,
                   module=module, allowed=list(allowed))
        elif isinstance(exc, _ForbiddenBuiltin):
            reason = _BUILTIN_REASONS.get(exc.name, "имя закрыто белым списком")
            refuse(SANDBOX_FORBIDDEN_BUILTIN,
                   f"'{exc.name}' в скрипте недоступен. {reason}",
                   kind="ForbiddenBuiltin", line=line, frames=frames,
                   name=exc.name)
        elif isinstance(exc, _CpuExhausted):
            refuse(SANDBOX_TIMEOUT,
                   f"скрипт не завершился за {cpu_s:g} с процессорного времени — "
                   f"вероятно, цикл без выхода. Пределы этого запуска: "
                   f"процессорное время {cpu_s:g} с, стена "
                   f"{cfg.get('wall_seconds')} с",
                   kind="CpuTimeout", line=exc.lineno or line,
                   cpu_seconds=cpu_s)
        elif isinstance(exc, MemoryError):
            refuse(SANDBOX_MEMORY,
                   f"скрипт превысил предел памяти {cfg.get('memory_mb')} МБ "
                   f"(адресное пространство). Не накапливайте данные в цикле: "
                   f"программа IR — это операции, а не массив",
                   kind="MemoryError", line=line, frames=frames,
                   memory_mb=cfg.get("memory_mb"))
        elif isinstance(exc, RecursionError):
            refuse(SANDBOX_RUNTIME,
                   f"рекурсия глубже {sys.getrecursionlimit()} кадров — "
                   f"вероятно, нет базового случая",
                   kind="RecursionError", line=line, frames=frames[-6:])
        elif isinstance(exc, KirRefusal):
            # 🔴 A TYPED REFUSAL FROM THE LANGUAGE IS NOT A SCRIPT
            # EXCEPTION. `DslRefusal` subclasses `KirRefusal` ON
            # PURPOSE, and its docstring names the callers
            # explicitly: «у вызывающего (ПЕСОЧНИЦА, скрипт, ремонтная
            # петля) одна ветка обработки на все типизированные
            # отказы KIR». There was no branch for it here, and the
            # refusal fell into the `else`:
            #
            #     code       = KIR-B006  "the script raised an exception"
            #     message_ru = "DslRefusal: KIR-P005: не задан слот …"
            #
            # That is, the real code lived in the TEXT, while the
            # blame shifted from the SLOT to the script. Branching by
            # code (`skill.REFUSAL_PLAYBOOK`, the repair loop) did
            # not work at this door, and the model fixed a correct
            # script on the hint about an exception.
            #
            # The repair fields travel TOO: a code without
            # `field_name`/`candidates` is half an answer — what must
            # be fixed is the NAMED slot.
            основная = (exc.diagnostics or [None])[0]
            if основная is None:
                message = str(exc).strip() or type(exc).__name__
                refuse(SANDBOX_RUNTIME, f"{type(exc).__name__}: {message}",
                       kind=type(exc).__name__, line=line, frames=frames)
                return
            детали = {
                поле: getattr(основная, поле)
                for поле in ("field_name", "expected", "got", "candidates",
                             "op_id", "op_index", "suggested_replacement")
                if getattr(основная, поле, None) not in (None, (), [])
            }
            refuse(основная.code, основная.message_ru,
                   kind=type(exc).__name__, blame="author",
                   line=line, frames=frames, **детали)
        elif isinstance(exc, NameError) and dsl is None:
            # The name is missing because the LANGUAGE FAILED TO
            # LOAD. This is our defect, and the refusal must say so
            # outright: otherwise the model will go fix its own
            # correct script on the hint "name is not defined."
            refuse(SANDBOX_UNAVAILABLE,
                   f"язык KIR не загрузился ({dsl_error}), поэтому имени из "
                   f"скрипта нет: {exc}. Это дефект песочницы, а не скрипта",
                   kind="NameError", blame="sandbox", line=line, frames=frames,
                   dsl_module=dsl_module, dsl_error=dsl_error)
        elif isinstance(exc, ПробелЧтения):
            # SOMETHING WAS ASKED THAT WE DID NOT READ. The blame is
            # not the author's: the index or the catalog were not
            # supplied to THIS TURN — this happens with an offline
            # run and with a turn where the plugin has not sent
            # context yet. `caller` (whoever assembled the call), not
            # `author`: the field's documentation states plainly
            # «author — чинит модель», and there is nothing to fix,
            # rewriting a correct script would burn a loop cycle for
            # nothing.
            refuse(SANDBOX_UNREAD, str(exc).strip() or "спрошено непрочитанное",
                   kind=type(exc).__name__, blame="caller",
                   line=line, frames=frames)
        elif (isinstance(exc, ModuleNotFoundError)
              and str(getattr(exc, "name", "") or "").split(".")[0] in allowed):
            # 🔴 A THIRD CARRIER OF THE SAME DEFECT, FOUND BY A RUN
            # (E-85, 02.09).
            #
            # The first two ("not installed" for a submodule, and a
            # warm-up failure) went through `_ForbiddenImport`,
            # because the guard does not let through a submodule of
            # an unloaded package. A ROOT import passes the guard
            # STRAIGHT THROUGH (`name in allowed` — the first line of
            # `_import_permitted`), the real `__import__` raises
            # `ModuleNotFoundError`, and it fell into the general
            # `else` as `KIR-B006`, "the script raised an exception,"
            # with the blame on the AUTHOR:
            #
            #     import shapely   ->  KIR-B006, blame=author, «No module named»
            #
            # The same fact, the same environment, a third foreign
            # code. The condition is narrow ON PURPOSE: what is asked
            # is the ROOT of the missing module against the
            # whitelist, so a `ModuleNotFoundError` from inside a
            # foreign library does not land here — its root does not
            # appear in the list.
            missing = str(getattr(exc, "name", "") or "")
            refuse(SANDBOX_CAPABILITY_ABSENT,
                   f"'{missing}' недоступен. Библиотека РАЗРЕШЕНА белым "
                   f"списком, но в этой среде НЕ УСТАНОВЛЕНА: скрипт "
                   f"исполняется отдельным процессом с `-s`, поэтому "
                   f"библиотеки из пользовательского site ему не видны. "
                   f"Правь не скрипт, а установку того окружения, которым "
                   f"идёт запуск",
                   kind="CapabilityAbsent", blame="environment",
                   line=line, frames=frames, module=missing,
                   allowed=list(allowed))
        elif isinstance(exc, NameError):
            # 🔴 A NAME THAT DOES NOT EXIST NAMES ITS NEIGHBORS (04.09.2026). The
            # refusal was `KIR-B006 NameError: name 'level' is not defined` — true,
            # and exactly useless: the author writes IN A LANGUAGE that has 82
            # operations sitting in its own namespace, and the one thing they do
            # not know is what it is called here. A measurement of a stranger's
            # path (04.09, clean venv, package from the network) named this
            # refusal among those that leave the run WITHOUT A TURN.
            #
            # Neighbors are drawn from the script's LIVE namespace, not from a list
            # kept alongside: such a list would drift from the registry at the very
            # first new operation, and drift silently. The search form is the same
            # `difflib.get_close_matches` that already appears three times in this
            # file.
            #
            # `ns` is created LATER than this function, yet the function is also
            # called from `build()` — that is, before the namespace exists.
            # Therefore the access is guarded: without a namespace the refusal
            # stays as before, without neighbors, but also without a second error
            # on top of the first.
            имя = str(getattr(exc, "name", "") or "")
            try:
                # FUNCTIONS, NOT EVERYTHING CALLABLE: `callable` lets CLASSES
                # through (`DslRefusal` and kin), and the first edition suggested
                # them on par with operations. The author is looking for an
                # OPERATION.
                доступные = sorted(k for k in ns
                                   if not k.startswith("_")
                                   and callable(ns[k])
                                   and not isinstance(ns[k], type))
            except NameError:
                доступные = []
            близкие = (difflib.get_close_matches(имя, доступные, n=4, cutoff=0.0)
                       if имя and доступные else [])
            хвост = ""
            if близкие:
                хвост = (f". Похожее в этом пространстве: "
                         f"{', '.join(близкие)}. Весь язык — `kir ops`")
            elif доступные:
                хвост = (f". В пространстве {len(доступные)} имён; "
                         f"весь язык — `kir ops`")
            message = str(exc).strip() or type(exc).__name__
            refuse(SANDBOX_RUNTIME, f"NameError: {message}{хвост}",
                   kind="NameError", line=line, frames=frames)
        else:
            message = str(exc).strip() or type(exc).__name__
            refuse(SANDBOX_RUNTIME, f"{type(exc).__name__}: {message}",
                   kind=type(exc).__name__, line=line, frames=frames)

    # ── 6. execution ────────────────────────────────────────────────────────
    #
    # 🔴 A SECOND CARRIER OF THE SAME DEFECT, AND IT WAS FOUND EXACTLY BECAUSE
    # IT WAS SOUGHT RIGHT HERE (the form "having fixed the shape, look for its
    # second carrier in the same file"). The `dont_inherit=True` above strips
    # OUR PEP 563 — but the `dataclasses.py:749` branch is reachable via A
    # STRING ANNOTATION in general, not only through `__future__`. The author
    # writes it in two ordinary ways:
    #
    #     x: 'float'                      quotes, a direct forward reference
    #     from __future__ import annotations   PEP 563 of the author's own will
    #
    # In both cases `_is_type` reads `sys.modules.get("kir_author_script")`
    # and gets `None`, because the author's frame is not in `sys.modules`.
    #
    # Measured 20.08.2026, `dont_inherit` is ALREADY on, only the registration
    # changed:
    #     quotes in the annotation, without registration  -> AttributeError @749
    #     quotes in the annotation, with registration      -> ok
    # A control on a third side: `make_dataclass` with the same input worked
    # ALWAYS — it does not pass through this branch, and this exact pair is
    # what tells "the library is broken" apart from "our frame is nameless".
    #
    # WHAT THIS DOES NOT OPEN UP. Importing `kir_author_script` from the
    # script is still a refusal: `guarded_import` checks the whitelist BEFORE
    # `sys.modules`, and the script's name is not on the list. The module
    # carries the SAME `ns` dict that the script already has at hand — zero
    # new surface. The child is single-use (one cfg frame, one result), so
    # there is nothing to remove either. `module.__dict__` cannot be
    # assigned — it is read-only, so we EXECUTE DIRECTLY INTO IT, and we
    # rebind `ns` to that same dict: `_harvest` and `ns.clear()` on
    # MemoryError both operate on it further down.
    _self_module = types.ModuleType(ns["__name__"])
    for _k in ("__loader__", "__spec__", "__package__"):
        _self_module.__dict__.pop(_k, None)      # we do not introduce names that were not there before
    _self_module.__dict__.update(ns)
    sys.modules[ns["__name__"]] = _self_module
    ns = _self_module.__dict__
    try:
        exec(code, ns)
    except SystemExit as exc:
        restore()
        if exc.code not in (None, 0):
            refuse(SANDBOX_RUNTIME,
                   f"скрипт завершился досрочно с кодом {exc.code}; программа "
                   f"считается собранной, только когда скрипт дошёл до конца",
                   kind="SystemExit")
            return
    except BaseException as exc:                  # noqa: BLE001 — this is the seam itself
        frames = script_frames(sys.exc_info()[2])
        if isinstance(exc, MemoryError):
            # We free (memory) BEFORE building the refusal: otherwise the text
            # formatting itself would hit the very same limit.
            ns.clear()
            gc.collect()
        restore()
        fail_from_exception(exc, frames)
        return

    # ── 6.5 ACCOUNTING FOR WHAT WAS LEFT BEHIND, AND RIGHT HERE ─────────────
    # It is taken BEFORE collection: collection itself goes through
    # `take_ops()`, and that starts a new program — meaning that after
    # collection the accounting would also hold the CURRENT program, the very
    # one the door is about to build. A measurement of the first edition: a
    # single-program script reported "left behind: 1". An instrument that
    # counts its own turn calls a loss what it never lost.
    #
    # The module is taken FROM THE OWNER and from `sys.modules`: this
    # function's `dsl` is `kir.course.language`, A WRAPPER (measured:
    # `isolation.dsl_module`), which has no accounting of its own; and there
    # is nowhere for import machinery to come from in an empty root.
    _язык = sys.modules.get("kir.dsl")
    try:
        _оставлено = _язык.left_behind() if _язык is not None else ()
    except Exception:                             # noqa: BLE001 — accounting is younger than the build
        _оставлено = ()
    if _оставлено:
        state["left_behind"] = [dict(item) for item in _оставлено]

    # ── 7. collecting the program ───────────────────────────────────────────
    try:
        harvested, how = _harvest(ns, dsl)
    except BaseException as exc:                  # noqa: BLE001
        frames = script_frames(sys.exc_info()[2])
        if isinstance(exc, MemoryError):
            ns.clear()
            gc.collect()
        restore()
        fail_from_exception(exc, frames)
        return
    restore()

    state["isolation"]["harvest"] = how

    envelope: dict = {}
    if isinstance(harvested, dict):
        if "ops" not in harvested:
            refuse(SANDBOX_BAD_RESULT,
                   "скрипт вернул словарь без ключа 'ops': программа — это "
                   "список операций либо конверт {'ops': [...]}",
                   kind="BadEnvelope", keys=sorted(harvested)[:12])
            return
        envelope = {key: value for key, value in harvested.items() if key != "ops"}
        harvested = harvested["ops"]

    if harvested is None:
        # 🔴 THE MOST FREQUENT CAUSE IS NAMED BY ITS NAME, NOT LEFT TO
        # GUESSWORK. A measurement on the overnight rig 17.08.2026: over a run
        # of the ladder, the door was reached 463 times, and `KIR-B007`
        # accounted for 176 of them — **38% of all calls**, the language's top
        # refusal by a huge margin (the runner-up: 36).
        #
        # One of its causes is THE MOST ORDINARY PYTHON IDIOM. A script of the
        # form
        #
        #     def build(): create_wall(...)
        #     if __name__ == "__main__": build()
        #
        # executes here WITHOUT errors and yields NOT A SINGLE operation: the
        # child executes the source through `compile(..., "exec")`, and
        # `__name__` in this namespace is not equal to `"__main__"`. Verified
        # by execution: the same script without the guard yields an
        # operation, with the guard — emptiness.
        #
        # The previous text named the CORRECT way and stayed silent about what
        # exactly ate the program for THIS author — and the tree's law
        # requires that a refusal carry both the cause AND the next turn.
        tail = ""
        try:
            if "__main__" in source and "__name__" in source:
                tail = (". ПРИЧИНА ЗДЕСЬ ВИДНА: скрипт прячет вызовы за "
                        "`if __name__ == \"__main__\"`, а этот блок тут НЕ "
                        "исполняется — имя пространства имён другое. "
                        "СЛЕДУЮЩИЙ ХОД: сними охрану и зови построение прямо, "
                        "верхним уровнем")
        except Exception:  # noqa: BLE001 — the hint has no right to bring down the refusal
            tail = ""
        # THE SAME FORK AS BELOW, BUT WITH ONE CAVEAT: when the structural
        # cause IS NAMED (`tail` — the `__main__` guard), it is more useful
        # than the "recon" label, because it says exactly what ate the
        # program. The label takes over only where there is nothing more to
        # say.
        if _answered(state) and not tail:
            refuse(SANDBOX_RECON,
                   "программы нет — и это РАЗВЕДОЧНЫЙ ХОД, а не отказ: скрипт "
                   "спросил и напечатал ответ, печать целиком приехала в "
                   "квитанции. Ход засчитан как вопрос. СЛЕДУЮЩИЙ ХОД: пришли "
                   "программу — те же имена языка, но с вызовом построения "
                   "(например create_wall(...))",
                   kind="Reconnaissance", blame="none",
                   stdout_chars=len(state.get("stdout") or ""))
            return
        refuse(SANDBOX_NO_OPS,
               "скрипт отработал без ошибок, но не выдал ни одной операции. "
               "Программа собирается вызовами языка (например create_wall(...)); "
               "альтернатива — присвоить список операций переменной ops" + tail,
               kind="NoOps",
               candidates=list(_NS_CANDIDATES[:4]))
        return

    if isinstance(harvested, (str, bytes)):
        refuse(SANDBOX_BAD_RESULT,
               f"программа пришла как {type(harvested).__name__}, а нужен "
               f"список операций. Строка — это не программа IR",
               kind="BadResultType", got=type(harvested).__name__)
        return
    if not isinstance(harvested, (list, tuple)):
        refuse(SANDBOX_BAD_RESULT,
               f"программа пришла как {type(harvested).__name__}, а нужен "
               f"список операций",
               kind="BadResultType", got=type(harvested).__name__)
        return

    ops_raw = list(harvested)
    if not ops_raw:
        # 🔴 A THIRD KIND OF ANSWER. A script that ASKED and printed an
        # answer is not a failure: it is exactly what is wanted from the
        # environment ("better to think ten times and act once", the owner's
        # amendment 17.08). The distinguisher is PRINTING, and it is checked
        # by BOTH halves in `tests/test_recon_is_not_a_refusal.py`: recon
        # prints, while true emptiness (`x = 1 + 1`, a bare comment) stays
        # silent at exactly zero characters.
        if _answered(state):
            refuse(SANDBOX_RECON,
                   "программы нет — и это РАЗВЕДОЧНЫЙ ХОД, а не отказ: скрипт "
                   "спросил и напечатал ответ, печать целиком приехала в "
                   "квитанции. Ход засчитан как вопрос. СЛЕДУЮЩИЙ ХОД: пришли "
                   "программу — те же имена языка, но с вызовом построения "
                   "(например create_wall(...))",
                   kind="Reconnaissance", blame="none",
                   stdout_chars=len(state.get("stdout") or ""))
            return
        refuse(SANDBOX_NO_OPS,
               "скрипт отработал, но программа пуста: ни одной операции, и "
               "напечатано тоже НИЧЕГО — то есть ход не построил и не спросил. "
               "Пустая программа ничего не доказывает и до Revit не доходит",
               kind="EmptyProgram")
        return

    max_ops = int(cfg.get("max_ops") or MAX_SCRIPT_OPS)
    if len(ops_raw) > max_ops:
        refuse(SANDBOX_OUTPUT_LIMIT,
               # 🔴 THE NUMBERS HERE NO LONGER LIVE AS A LITERAL. It used to
               # say "20 authored / 320 after macro expansion" against live
               # values of 1000 and 22000 — an error of 50x and 69x. And this
               # text is read not by a developer but by the author-model: it
               # cuts its own program by this text, by a factor of fifty. A
               # refusal that names the wrong limit does not inform — it
               # GOVERNS, and governs wrongly.
               #
               # Found 20.08.2026 by TWO independent waves in one evening.
               # There were three carriers: this text, the `sdk.py` docstring,
               # and a test that PINNED the wrong number. In the comment
               # twenty lines above, the numbers were already removed that
               # same morning — for exactly this reason — yet the refusal
               # text survived: the fix repaired one carrier out of three.
               f"скрипт выдал {len(ops_raw)} операций при транспортном пределе "
               f"песочницы {max_ops}. Это НЕ авторский бюджет компилятора "
               f"(его имена — compiler.MAX_OPS_PER_PROGRAM и MAX_VALIDATED_OPS, "
               f"он считается дальше по конвейеру и отказывает KIR-L001)",
               kind="TooManyOps", ops=len(ops_raw), limit=max_ops)
        return

    ops: list = []
    for i, op in enumerate(ops_raw):
        norm = _normalize_op(op, dataclasses)
        if norm is None:
            refuse(SANDBOX_BAD_RESULT,
                   f"ops[{i}] — это {type(op).__name__}, а операция должна быть "
                   f"объектом языка или словарём",
                   kind="BadOpType", index=i, got=type(op).__name__)
            return
        ops.append(norm)

    problem = _check_jsonable(ops, "ops", 0)
    if problem is not None:
        path, reason = problem
        refuse(SANDBOX_BAD_RESULT,
               f"{path}: {reason}. В программе IR живут только числа, строки, "
               f"булевы, null, списки и словари",
               kind="NotJsonable", path=path)
        return
    problem = _check_jsonable(envelope, "envelope", 0) if envelope else None
    if problem is not None:
        path, reason = problem
        refuse(SANDBOX_BAD_RESULT, f"{path}: {reason}",
               kind="NotJsonable", path=path)
        return

    try:
        serialized = json.dumps({"ops": ops, "envelope": envelope},
                                ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        refuse(SANDBOX_BAD_RESULT, f"программа не переводится в JSON: {exc}",
               kind=type(exc).__name__)
        return

    hit = _ADDRESS_RE.search(serialized)
    if hit is not None:
        refuse(SANDBOX_NONDETERMINISM,
               f"в программе оказался адрес объекта: {hit.group(0)}. Это repr "
               f"объекта, который меняется от запуска к запуску — программа "
               f"перестаёт быть воспроизводимой. Передавайте значения, а не "
               f"объекты",
               kind="ObjectAddressInOutput", sample=hit.group(0))
        return

    # ── SOMETHING SUPPLIED THAT NOBODY DECLARED IS A REFUSAL, NOT SILENCE ───
    # The check stands HERE, not in `param()`, by construction: the set of
    # declared handles is known only after the script has run to the end. A
    # silently swallowed extra name would mean "moved a handle, and the old
    # thing got built" — the caller is sure they ordered something else, and
    # the signature confirms it. The most expensive of all possible outcomes.
    unknown = sorted(set(supplied_params) - set(_declared))
    if unknown:
        known = sorted(_declared)
        refuse(SANDBOX_PARAM,
               f"подан параметр, которого программа не объявляла: "
               f"{', '.join(unknown)}. Объявлены: "
               f"{', '.join(known) if known else '(ни одного)'}. "
               f"СЛЕДУЮЩИЙ ХОД: возьми имя из объявленных либо добавь в скрипт "
               f"param('{unknown[0]}', <умолчание>)",
               kind="ParamUnknown", blame="caller",
               unknown=unknown, declared=known)
        return

    emit({"ok": True, "ops": ops, "envelope": envelope,
          "lineage": op_lineage(),
          "params": [dict(_declared[n]) for n in _order]})
    sys.exit(0)


def _dotted_mentions(source: str, root: str) -> list[str]:
    """All module paths with this root that are NAMED in the source, plus the root itself.

    Why not just the root. `import shapely` pulls in `shapely.geometry`, but
    NOT `shapely.ops` (measured on the prod box: 35 submodules in
    `sys.modules`, `ops` not among them). After chroot, an unfound submodule
    would become an ImportError inside an otherwise correct script — that is,
    a misattributed refusal.

    The list of paths is not stored anywhere: it is READ OUT OF THE SOURCE,
    so a new library on the whitelist requires no edit here.
    """
    pattern = re.compile(r"\b" + re.escape(root) + r"(?:\.[A-Za-z_]\w*)*")
    names = {root}
    for hit in pattern.findall(source):
        parts = hit.split(".")
        for i in range(1, len(parts) + 1):
            names.add(".".join(parts[:i]))
    # By length: the root comes before the submodule — otherwise importing
    # the submodule would pull in the root by itself, and the order in the
    # report would stop matching the load order.
    return sorted(names, key=lambda n: (n.count("."), n))


#: SUBMODULES THAT THE LIBRARY PULLS IN ITSELF, AND LATER — where "later"
#: here means "after chroot", when the files are already gone.
#:
#: 🔴 WHY, MEASURED 20.08.2026. The warm-up took ONLY modules NAMED in the
#: source. `np.median(a)` writes `numpy.ma` nowhere — yet numpy pulls it in
#: lazily, on first call. Result: the script crashed with `KIR-B006
#: ModuleNotFoundError: No module named 'numpy.ma'` MID-COMPUTATION, that is,
#: after the form was already computed, and the blame was written to the
#: author, though the author had done nothing.
#:
#: Dead were `np.median` and `np.quantile` — the most ordinary analysis
#: calls.
#:
#: THE COST IS MEASURED, NOT ESTIMATED: numpy itself imports in 80 ms, these
#: six submodules add 52 ms, three shapely submodules — 1 ms. It is paid only
#: by the turn that mentioned the library.
#:
#: THE LIST IS CLOSED AND NOT COMPLETE — like every such list in this tree.
#: An empty slot means "this lazy submodule has not killed anyone yet," not
#: "there are none." The next such refusal is caught by the same
#: `ModuleNotFoundError` text with a dot in the name, and is cured by adding
#: a line here.
LAZY_SUBMODULES: dict[str, tuple[str, ...]] = {
    "numpy": ("numpy.ma", "numpy.linalg", "numpy.fft",
              "numpy.random", "numpy.polynomial", "numpy.lib.stride_tricks"),
    "shapely": ("shapely.ops", "shapely.geometry", "shapely.affinity"),
}


#: A mark for a FAILED warm-up inside the list of what was warmed.
#:
#: 🔴 INTRODUCED 29.08.2026 (finding E-18). Both warm-ups swallowed failure
#: through `continue`, and the argument "do not throw" is correct: an
#: exception from here would have torn down a turn that could have been
#: built even without the library. What was wrong was something else — that
#: the failure went NOWHERE. `warmed` and `warmed_libs` ride in the receipt,
#: meaning the channel existed, but there was nothing to put into it, and
#: "the library is absent" came out on the other side as "import forbidden"
#: (E-17).
#:
#: A mark, not a separate field: the list of what was warmed is already
#: mixed (`lesson:...` next to module names), readers take it whole, and a
#: new field would have to be threaded through three places instead of zero.
WARM_FAILED_MARK = "НЕ ЗАГРУЖЕН:"

#: THE REPAIR FOR THE THREE OUTCOMES OF A FAILED IMPORT SHARES ONE PLACE,
#: NOT A TERNARY.
#:
#: A SANDBOX dictionary, not a registry one: the sandbox has its own closed
#: set of five values since 03.08 (`SandboxRefusal.blame`), and
#: `diag.SANDBOX_BLAME_TO_DIAG` TRANSLATES it. The values are written as
#: literals ON PURPOSE — the guard
#: `test_the_sandbox_vocabulary_is_translated_not_duplicated` reads this file
#: by walking the `ast` and sees only constants: hiding them behind a
#: computation would make the sixth value invisible to the guard.
_IMPORT_FAILURE_BLAME = {
    SANDBOX_FORBIDDEN_IMPORT: "author",       # fix the line: call something else
    SANDBOX_CAPABILITY_ABSENT: "environment", # fix the environment setup
    SANDBOX_UNAVAILABLE: "sandbox",           # ours to fix: the rule and the text have diverged
}


def _warm_failure_for(state: dict[str, Any], module: str) -> Optional[str]:
    """Did the warm-up report a failure for EXACTLY this module. `None` otherwise.

    🔴 A READER FOR A MARK THAT HAD NONE (01.09.2026). `WARM_FAILED_MARK` was
    introduced 29.08 so that a warm-up failure would SOUND — and it did sound
    — in the receipt. But the refusal printed to the author never looked at
    the receipt, and "the module is not in this environment" kept coming out
    on the other side as "import forbidden" with the blame on the author. A
    mark with no reader is a channel that speaks into emptiness.

    🔴 THE NAME IS MATCHED IN FULL, NOT BY PREFIX, AND THIS WAS BOUGHT BY ITS
    OWN GUARD. The first edition used `startswith(<mark><module>)` — and was
    caught by exactly that: `kir.design` is a prefix of `kir.design_check`,
    so a NEIGHBOR's failure was declared the asked-for module's failure and
    lifted the blame from where it belonged. Caught by
    `test_a_prefix_neighbour_is_not_mistaken_for_the_asked_module` before the
    first run for real. Now a BOUNDARY is required after the name: either a
    space (followed by the exception class in parentheses) or end of line.
    The tail is deliberately excluded from the match — it is free text and
    may change.

    Both warm-ups put their lines into DIFFERENT fields (`warmed` from the
    language, `warmed_libs` from the whitelist), so both are asked: a
    `shapely` failure and a `kir.design_check` failure are the same event as
    far as the author is concerned.
    """
    isolation = state.get("isolation") or {}
    head = WARM_FAILED_MARK + module
    for field in ("warmed", "warmed_libs"):
        entries = isolation.get(field)
        if not isinstance(entries, list):
            continue                # the `failed (...)` line, or the field does not exist yet
        for entry in entries:
            if not isinstance(entry, str) or not entry.startswith(head):
                continue
            tail = entry[len(head):]
            if tail == "" or tail.startswith(" "):
                return entry
    return None


def _warm_allowed_third_party(source: str, allowed: tuple[str, ...]) -> list:
    """Warm up external whitelist modules NAMED by the source.

    DOES NOT THROW, BUT DOES NOT STAY SILENT EITHER (fix 29.08.2026, finding
    E-18). The previous edition swallowed failure through `continue`, and the
    argument "do not throw" is correct: an exception from here would have
    torn down a turn that could have been built even without the library.
    What was wrong was something else — that the failure went NOWHERE. The
    list rides in the receipt as the `warmed_libs` field, meaning the channel
    existed, but there was nothing to put into it; from there "the library is
    absent" came out on the other side as "import forbidden" (E-17). Now a
    warm-up failure names ITSELF and its cause.
    """
    import importlib

    stdlib = getattr(sys, "stdlib_module_names", frozenset())
    loaded: list[str] = []

    def _warm(dotted: str) -> None:
        try:
            importlib.import_module(dotted)
        except Exception as exc:                  # noqa: BLE001 — we do not tear the turn
            loaded.append(f"{WARM_FAILED_MARK}{dotted} ({type(exc).__name__})")
            return
        loaded.append(dotted)

    for root in allowed:
        if root in stdlib or root in sys.builtin_module_names:
            continue
        if root not in source:
            continue
        for dotted in _dotted_mentions(source, root):
            _warm(dotted)
        for dotted in LAZY_SUBMODULES.get(root, ()):
            _warm(dotted)
    return loaded


def _read_vm_hwm(fd: int) -> int:
    """Peak RSS of THIS process (`VmHWM`, KB) via a descriptor opened ahead of time.

    WHY NOT `getrusage(RUSAGE_SELF).ru_maxrss`, as it was at first. Measured
    03.08: a child spawned by fork+exec INHERITS the parent's watershed and
    keeps it as its own. A lean parent (11.8 MB) → the child reports 11868 KB
    while the real VmHWM is 9844; a fat parent (403 MB) → the same child
    reports 403708 KB while the real VmHWM is 9804, and even after swelling
    by 120 MB the figure does not budge (the inherited maximum is higher).
    That is, this reading is NOT ABOUT THIS PROCESS. Our own suite caught
    two false failures this way: green alone, red in the suite — and a red
    test in the suite unlearns reading red at all.

    `VmHWM` lives in mm_struct and resets on exec, so it measures exactly
    this run. The descriptor is opened BEFORE chroot and re-read via
    lseek(0): after chroot the /proc path is unreachable (verified:
    FileNotFoundError), while an already-open descriptor still yields fresh
    values."""
    if fd < 0:
        return 0
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        blob = os.read(fd, 8192).decode("ascii", "replace")
    except OSError:
        return 0
    for line in blob.splitlines():
        if line.startswith("VmHWM:"):
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                return int(parts[1])
    return 0


def _self_vm_size() -> int:
    """The process's current address space (bytes).

    RLIMIT_AS counts the ENTIRE process, including the interpreter already
    loaded. So the script's limit = "how much is occupied right now" +
    budget, otherwise the budget would be silently eaten by our own
    imports."""
    with open("/proc/self/statm", "rb") as fh:
        pages = int(fh.read().split()[0])
    return pages * os.sysconf("SC_PAGE_SIZE")


def _probe_network() -> str:
    """A measurement, not an intention: we try to connect and report how it ended."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        try:
            s.connect(("1.1.1.1", 53))
            return "reachable"
        except OSError as exc:
            return f"unreachable ({exc.errno}: {exc.strerror})"
        finally:
            s.close()
    except Exception as exc:
        return f"unreachable ({type(exc).__name__})"


def _answered(state: dict) -> bool:
    """WHETHER THE SCRIPT ANSWERED — the only thing that tells recon apart from emptiness.

    Printing, and only that: `state["stdout"]` is already filled by
    `restore()` by the time of collection. Whitespace-only printing does NOT
    count as an answer — `"\n"` is not an answer but a trace; otherwise a
    lone `print()` would declare as recon a turn that said nothing.

    WHY NOT "the script touched `model`/`spec`". That was the first thought,
    and it is wrong by measurement: `model.levels()` with no catalog supplied
    raises an exception and goes into `KIR-B006` even BEFORE collection, that
    is, it never reaches here at all. The trait "asked" is unobservable here
    by construction; what is observed is the trait "answered", and it is
    also the only one that gives the MODEL anything: an answer that nobody
    printed does not exist for the next turn.
    """
    return bool((state.get("stdout") or "").strip())


def _harvest(ns: dict, dsl) -> tuple[Any, str]:
    """Take the program by the first contract-with-the-language method that worked.

    The language's names are injected directly into the script's namespace,
    so `ops` and `build` are ALWAYS there. Only a name that OVERRODE an
    injected name counts as the script's own variable — otherwise "the
    script collected nothing" would look like "the script returned a
    function," and the fix would go to the wrong place."""

    def is_own(name: str, value: Any) -> bool:
        return dsl is None or value is not getattr(dsl, name, None)

    if dsl is not None:
        for name in _DRAIN_CANDIDATES:
            fn = getattr(dsl, name, None)
            if callable(fn):
                got = fn()
                if got:
                    return got, f"dsl.{name}()"
    for name in _NS_CANDIDATES:
        value = ns.get(name)
        if (isinstance(value, (list, tuple, dict)) and value
                and is_own(name, value)):
            return value, f"ns.{name}"
    for name in _BUILD_CANDIDATES:
        fn = ns.get(name)
        if callable(fn):
            return fn(), (f"{name}()" if is_own(name, fn) else f"dsl.{name}()")
    for name in _NS_CANDIDATES:                   # empty, but declared
        if name in ns and is_own(name, ns[name]):
            return ns[name], f"ns.{name}"
    return None, "none"


def _normalize_op(op: Any, dataclasses_mod) -> Optional[dict]:
    """A language operation → a dict. We do not guess the object's shape: we ask."""
    if isinstance(op, dict):
        return dict(op)
    for method in ("to_dict", "as_dict", "asdict", "to_json", "dict",
                   "model_dump"):
        fn = getattr(op, method, None)
        if callable(fn):
            try:
                got = fn()
            except Exception:
                continue
            if isinstance(got, dict):
                return got
    if dataclasses_mod.is_dataclass(op) and not isinstance(op, type):
        try:
            return dataclasses_mod.asdict(op)
        except Exception:
            return None
    return None


def _check_jsonable(value: Any, path: str, depth: int):
    """A check for JSON representability WITH THE PATH NAMED.

    json.dumps reports "Object of type X is not JSON serializable" without a
    location; a refusal without a location is a second round of repair."""
    if depth > MAX_JSON_DEPTH:
        return (path, f"вложенность глубже {MAX_JSON_DEPTH}")
    if value is None or isinstance(value, (bool, str)):
        return None
    if isinstance(value, int):
        if abs(value) > 2 ** 63:
            return (path, "целое не помещается в 64 бита")
        return None
    if isinstance(value, float):
        if value != value:
            return (path, "NaN — числа NaN в JSON нет")
        if value in (float("inf"), float("-inf")):
            return (path, "бесконечность — её в JSON нет")
        return None
    if isinstance(value, dict):
        for k, v in value.items():
            if not isinstance(k, str):
                return (f"{path}.{k!r}",
                        f"ключ типа {type(k).__name__}, а нужен строковый")
            problem = _check_jsonable(v, f"{path}.{k}", depth + 1)
            if problem is not None:
                return problem
        return None
    if isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            problem = _check_jsonable(v, f"{path}[{i}]", depth + 1)
            if problem is not None:
                return problem
        return None
    return (path, f"значение типа {type(value).__name__}")


__all__ = [
    "SandboxPolicy",
    "SandboxRefusal",
    "SandboxResult",
    "DEFAULT_POLICY",
    "execute_author_script",
    "environment_signature",
    "author_geometry_libs_enabled",
    "allowed_imports_for_env",
    "AUTHOR_GEOMETRY_LIBS_FLAG",
    "GEOMETRY_IMPORTS",
    "SCRIPT_FILENAME",
    "ALLOWED_IMPORTS",
    "MAX_SCRIPT_OPS",
]
