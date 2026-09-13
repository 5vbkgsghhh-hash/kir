"""AN ENVIRONMENT VARIABLE'S NAME IS PART OF THE PACKAGE'S SURFACE, NOT ITS INTERNAL AFFAIR.

WHY THIS FILE, IN THE OWNER'S WORDS, 2026-08-27: the product is universal,
"anyone can download it and deploy it for themselves". Someone who installed
the `kir` package under the Apache-2.0 license and turns on a check inside it
reads `KUKAI_CHECKER_V2` — the name of SOMEONE ELSE'S product they have never
heard of. This is not cosmetics: **whoever fails to deploy builds ZERO
buildings**, and a name absent from the language's documentation gets in the
way of deployment exactly as much as a missing setting does.

🔴 AND WHY THIS IS NOT A RENAME BUT READING TWO NAMES. The tree `/opt/kir` is
installed EDITABLE in the live service's venv (`KIR_PLAN.md` §0.1): between
saving a file and the host's live service there is neither a build nor a
release. A plain rename would devalue EVERY environment line of the running
units the moment the file lands on disk. So the old name keeps being read, and
the service does not notice the edit at all.

    KIR_CHECKER_V2 is set      -> it is used
    only KUKAI_... is set      -> the old one is used, everything works as before
    both are set                -> the NEW one, even if it is empty: an
                                  explicitly set new name is a CHOICE, and
                                  silently yielding to the old one would make
                                  the name optional

WHAT IS NOT HERE, AND WHY. There is no "you are using the old name" warning:
it would have to be printed on every read in the live service, where the old
name is the norm, not a mistake. Whoever wants to know calls `legacy_in_use()`
and gets a list.

🔴 WHAT DID NOT MAKE IT IN HERE, AND THIS IS A BOUNDARY, NOT AN OVERSIGHT —
FOURTEEN NAMES:

    KUKAI_A5_CONFIRM_TOKEN   A5 lease
    KUKAI_ADMIN_DEVICES      the product's service devices
    KUKAI_DB_POOL_MIN        the product's database pool
    KUKAI_LLM_MODEL          which model the PRODUCT itself runs on
    KUKAI_FALLBACK_TIERS     its own fallback ladder
    nine more model names     THINKING/FALLBACK/LAST_RESORT/MODELING, CODEXPROXY_*,
                              AGY_MODEL, ANTIGRAVITY_MODEL

All fourteen are PRODUCT concepts, not the language's, and renaming them to
`KIR_*` would mean declaring someone else's subject as one's own. That KIR
reads them at all is a debt of the BOUNDARY, and it is fixed with a PORT, not
with letters in a name. Written down so the next wave does not "finish
cleaning up" this too; the list is CLOSED AND CHECKED BY A NUMBER —
`tests/test_the_environment_has_one_door.py::PRODUCT`, which also forbids
their appearing in the table below.

🔴 THE NUMBER "FOUR" STOOD HERE SINCE 08-28 AND WAS THREE TIMES TOO SMALL. It
was counted from places that were then PARSED BY HAND; ten LLM model names
lived in `schema_transport.py` as tuples (`_LEG_ENV`, `_OPENAI_PREFIXED_ENV`)
and were not counted. The prose was trusted because there was nothing to
check it with; now there is.
"""
# 🔴 PROVENANCE MOVED OUT OF THE DOCSTRING ON 2026-09-01 — A DOOR VERSUS A
# JOURNAL. The module docstring is a PUBLIC DOOR: `help()` prints it to a
# reader of the published package, and the address of our own machine tells
# them nothing. The knowledge is not erased — it is here, in the journal,
# where it belongs:
#     the host's live service is `kukai-backend.service`; it is exactly its
#     environment lines that a plain rename would devalue the moment the
#     file lands on disk
from __future__ import annotations

import os
from typing import Any

#: NEW NAME -> OLD NAME. The list is CLOSED: a new variable is set up right
#: away under the `KIR_*` name and does not land here — only those with a
#: past are here.
#:
#: Measured 2026-08-28: the package (excluding tests) read 12 `KUKAI_*` names
#: in 12 places; ten of them are about the LANGUAGE, and they are here. The
#: eleventh (`KUKAI_A5_CONFIRM_TOKEN`) is a product concept, see the header.
#: The twelfth (`KUKAI_X`) turned out to be a placeholder in a comment, not a
#: read — the instrument caught the string, not an actual access.
RENAMED: dict[str, str] = {
    # the checker
    "KIR_CHECKER_V2": "KUKAI_CHECKER_V2",
    # decompile store
    "KIR_DECOMPILE_DATA": "KUKAI_DECOMPILE_DATA",
    # the authoring python
    "KIR_DSL_OP_CEILING": "KUKAI_IR_DSL_OP_CEILING",
    # the reverse path
    "KIR_EXTRACT_BATCH": "KUKAI_IR_EXTRACT_BATCH",
    "KIR_EXTRACT_WINDOW_WAIT_S": "KUKAI_IR_EXTRACT_WINDOW_WAIT_S",
    # journal
    "KIR_JOURNAL_RESTORE": "KUKAI_JOURNAL_RESTORE",
    # the viewer
    "KIR_PUSH_QUEUE": "KUKAI_KIR_PUSH_QUEUE",
    "KIR_SCENE_CACHE": "KUKAI_KIR_SCENE_CACHE",
    "KIR_SCENE_CACHE_DIR": "KUKAI_KIR_SCENE_CACHE_DIR",
    # the HOST's root — named honestly: this is not "our backend", it is someone else's root
    "KIR_HOST_ROOT": "KUKAI_BACKEND_ROOT",

    # 🔴 A SECOND WAVE THE SAME DAY. The first edition of this table took 10
    # names — exactly the ones read as a LITERAL right in the access itself.
    # An extended guard (`tests/test_env_names_belong_to_the_language.py`)
    # showed that 52 accesses go THROUGH A MODULE-LEVEL CONSTANT
    # (`os.environ.get(_FLAG)`), and sixteen more `KUKAI_*` names turned up
    # there. The third correction of one number in a single shift: 43 -> 12
    # -> 28, and each time the instrument was at fault, not the subject.
    "KIR_DECOMPILE_OUT": "KUKAI_DECOMPILE_OUT",
    "KIR_DECOMPILE_CORPUS": "KUKAI_DECOMPILE_CORPUS",
    "KIR_ATOM_ESCROW": "KUKAI_IR_ATOM_ESCROW",
    "KIR_TOOL": "KUKAI_KIR_TOOL",
    "KIR_DECOMPILE": "KUKAI_KIR_DECOMPILE",
    "KIR_BUILT_VERDICT": "KUKAI_KIR_BUILT_VERDICT",
    "KIR_BUILDING_VERDICT": "KUKAI_KIR_BUILDING_VERDICT",
    "KIR_LIVE_PLAN": "KUKAI_KIR_LIVE_PLAN",
    "KIR_TRANSFER": "KUKAI_KIR_TRANSFER",
    "KIR_SCHEMA_DEDUP": "KUKAI_KIR_SCHEMA_DEDUP",
    "KIR_SCRIPT_FIRST": "KUKAI_KIR_SCRIPT_FIRST",
    "KIR_SCENE_PUSH": "KUKAI_KIR_SCENE_PUSH",

    # 🔴 A THIRD WAVE, 2026-09-01 — AND THIS NAME WAS FOUND NOT BY A GUARD BUT
    # BY A DISCREPANCY BETWEEN TWO TREES. Comparing the published
    # `kir-building` package against this tree by decompiling (not by text)
    # gave nine files diverging in EXECUTABLE code; two divergences were
    # behavioral, and one is here: the artifact read ONLY
    # `KIR_COMPILE_REQUIRED_VERSIONS`, the tree ONLY
    # `KUKAI_COMPILE_REQUIRED_VERSIONS`. One value, two names, two trees, and
    # neither read both: someone who narrowed the version matrix on their
    # side got a silent "narrowing rejected" on the other.
    #
    # 🔴 WHY THIS LINE IS NOT COSMETIC BUT A CONTROL: the ratchet
    # `test_no_module_of_the_package_reads_a_renamed_name_directly` treats a
    # direct read of ANY value from this table as a violation. Until today
    # the name was not in the table, and `compile_client.py` read it
    # directly — THE GUARD WAS BLIND BY CONSTRUCTION, because it takes its
    # list of violations from this very table. Which means adding the pair
    # was bound to TURN THE RATCHET RED and demand a fix from the reader; and
    # that is exactly what happened, proven by a run in both directions.
    "KIR_COMPILE_REQUIRED_VERSIONS": "KUKAI_COMPILE_REQUIRED_VERSIONS",

    # 🔴 A FOURTH WAVE, 2026-09-02 — AND THIS ENTIRE TABLE HAD, ALL THIS TIME,
    # BEEN GUARDED BY A GUARD THAT WAS BLIND BY CONSTRUCTION. The ratchet
    # `test_no_module_of_the_package_reads_a_renamed_name_directly` takes its
    # list of violations FROM THIS SAME TABLE: a name absent from the table
    # is not forbidden to read directly, and so the package quietly went on
    # hosting 42 more direct reads of the host's names. Measured by an `ast`
    # walk over production on 2026-09-02: 73 accesses to the environment in
    # 42 files outside the two doors.
    #
    # Of these, NOT PREVIOUSLY PARSED BY A HUMAN: 24 went THROUGH A HELPER
    # (`_int_env(name, …)`, `_env_float(name, …)`), where the name is an
    # ARGUMENT, not an access literal; the second wave's instrument saw them,
    # the eye did not.
    #
    # Everything below is about the LANGUAGE: graph limits, journal and
    # showroom ceilings, decompile opt-ins. Product concepts (see the header)
    # still do NOT LAND here, and there are four of them.
    "KIR_BUILDING_GRAPH": "KUKAI_IR_BUILDING_GRAPH",
    "KIR_CLASH": "KUKAI_IR_CLASH",
    "KIR_CLASH_MAX_BODIES": "KUKAI_IR_CLASH_MAX_BODIES",
    "KIR_CLASH_MAX_ELEMENTS": "KUKAI_IR_CLASH_MAX_ELEMENTS",
    "KIR_CLASH_MAX_OFFERS": "KUKAI_IR_CLASH_MAX_OFFERS",
    "KIR_CLASH_MAX_PAIRS": "KUKAI_IR_CLASH_MAX_PAIRS",
    "KIR_CLASH_PROPOSAL_MS": "KUKAI_IR_CLASH_PROPOSAL_MS",
    "KIR_COMPONENT": "KUKAI_IR_COMPONENT",
    "KIR_DECOMPILE_JOURNAL": "KUKAI_IR_JOURNAL",
    "KIR_EFFECTS": "KUKAI_IR_EFFECTS",
    "KIR_FACE_REF": "KUKAI_IR_FACE_REF",
    "KIR_MERGE3": "KUKAI_IR_MERGE3",
    "KIR_MERKLE": "KUKAI_IR_MERKLE",
    "KIR_NATIVE_GROUP": "KUKAI_IR_NATIVE_GROUP",
    "KIR_OPEN_MODEL_PREFLIGHT": "KUKAI_IR_OPEN_MODEL_PREFLIGHT",
    "KIR_PRIORS": "KUKAI_IR_PRIORS",
    "KIR_REBUILD": "KUKAI_IR_REBUILD",
    "KIR_SNAPSHOT_JANITOR_IDLE_HOURS": "KUKAI_IR_SNAPSHOT_JANITOR_IDLE_HOURS",
    "KIR_SNAPSHOT_JANITOR_INACTIVE_DELETE_DAYS":
        "KUKAI_IR_SNAPSHOT_JANITOR_INACTIVE_DELETE_DAYS",
    "KIR_SNAPSHOT_JANITOR_KEEP_REVISIONS":
        "KUKAI_IR_SNAPSHOT_JANITOR_KEEP_REVISIONS",
    "KIR_SNAPSHOT_JANITOR_MIN_AGE_HOURS":
        "KUKAI_IR_SNAPSHOT_JANITOR_MIN_AGE_HOURS",
    "KIR_SNAPSHOT_JANITOR_SILENT_DAYS_FOR_GZIP":
        "KUKAI_IR_SNAPSHOT_JANITOR_SILENT_DAYS_FOR_GZIP",
    "KIR_TRANSLATION_CERT": "KUKAI_IR_TRANSLATION_CERT",
    "KIR_TYPE_SHAPES": "KUKAI_IR_TYPE_SHAPES",
    "KIR_VERIFIED": "KUKAI_IR_VERIFIED",
    "KIR_WEAK_SANDBOX": "KUKAI_WEAK_SANDBOX",
    # ceilings of the live journal, the showroom, the plan stream and the
    # verdict — all six kinds were read by the helper under the old name
    "KIR_BUILDING_VERDICT_OPS": "KUKAI_KIR_BUILDING_VERDICT_OPS",
    "KIR_BUILDING_VERDICT_PROGRAMS": "KUKAI_KIR_BUILDING_VERDICT_PROGRAMS",
    "KIR_JOURNAL_DATUMS": "KUKAI_KIR_JOURNAL_DATUMS",
    "KIR_JOURNAL_OPS": "KUKAI_KIR_JOURNAL_OPS",
    "KIR_JOURNAL_PROGRAMS": "KUKAI_KIR_JOURNAL_PROGRAMS",
    "KIR_JOURNAL_SESSIONS": "KUKAI_KIR_JOURNAL_SESSIONS",
    "KIR_LIVE_PLAN_INDEX_BATCH": "KUKAI_KIR_LIVE_PLAN_INDEX_BATCH",
    "KIR_LIVE_PLAN_INTERVAL_MS": "KUKAI_KIR_LIVE_PLAN_INTERVAL_MS",
    "KIR_LIVE_PLAN_LEVELS": "KUKAI_KIR_LIVE_PLAN_LEVELS",
    "KIR_LIVE_PLAN_QUEUE": "KUKAI_KIR_LIVE_PLAN_QUEUE",
    "KIR_LIVE_PLAN_SEND_MS": "KUKAI_KIR_LIVE_PLAN_SEND_MS",
    "KIR_LIVE_PLAN_SLICE_OPS": "KUKAI_KIR_LIVE_PLAN_SLICE_OPS",
    "KIR_SCENE_CACHE_BYTES": "KUKAI_KIR_SCENE_CACHE_BYTES",
    "KIR_SHOWROOM_BYTES": "KUKAI_KIR_SHOWROOM_BYTES",
    "KIR_SHOWROOM_FRAMES": "KUKAI_KIR_SHOWROOM_FRAMES",
    "KIR_SHOWROOM_SESSIONS": "KUKAI_KIR_SHOWROOM_SESSIONS",
}

#: The reverse side of the same table — for guards and for the environment report.
LEGACY_NAMES: frozenset[str] = frozenset(RENAMED.values())


def get(name: str, default: Any = None) -> Any:
    """The value of environment variable `name`, with an eye on its old name.

    The order is load-bearing and is written in the header: the new name,
    then the old one, then `default`. The default is handed back AS IS and
    need not be a string: two call sites read the environment with a numeric
    default (`KIR_EXTRACT_BATCH`, `KIR_EXTRACT_WINDOW_WAIT_S`), and coercing
    it to a string for the sake of the signature would mean fitting the
    callers to the type, not the type to the callers.

    An empty string is a SET value, not an absence: otherwise
    `KIR_SCENE_CACHE_DIR=""` (a deliberate "write nowhere") would silently
    yield to the old name, and it would become impossible to turn the setting off.
    """
    value = os.environ.get(name)
    if value is not None:
        return value
    legacy = RENAMED.get(name)
    if legacy is not None:
        value = os.environ.get(legacy)
        if value is not None:
            return value
    return default


def legacy_in_use() -> tuple[str, ...]:
    """Old names the environment sets RIGHT NOW while the new ones are unset.

    A report, not a warning: in the live service the old name is the norm.
    Needed by whoever is migrating the environment and wants to see what
    still rests on the old names.
    """
    return tuple(sorted(
        legacy for new, legacy in RENAMED.items()
        if legacy in os.environ and new not in os.environ))


def describe() -> list[dict[str, object]]:
    """Describe aliases and currently present KIR names without exposing values.

    RENAMED is deliberately NOT a registry of every setting: new settings have
    no legacy alias. Include present KIR_* names separately and do not claim
    that their presence proves a consumer exists. Unset non-aliased settings
    and call-site defaults are outside this report's scope.
    """
    present = {name for name in os.environ
               if name.startswith("KIR_") and name.isascii()
               and all(character.isupper() or character.isdigit() or character == "_"
                       for character in name) and len(name) <= 128}
    rows = []
    for name in sorted(set(RENAMED) | present):
        former = RENAMED.get(name)
        if name in os.environ:
            source = "new"
            value = os.environ[name]
        elif former is not None and former in os.environ:
            source = "legacy"
            value = os.environ[former]
        else:
            source, value = "unset", None
        rows.append({"name": name, "former_name": former, "source": source,
                     "value_state": "unset" if value is None else "empty" if value == "" else "set",
                     "legacy_present": former is not None and former in os.environ,
                     "scope": "known_alias" if former is not None else "present_only"})
    return rows


def set_default(name: str, value: str) -> None:
    """Set `name`, ONLY IF neither it nor its old name is already set.

    🔴 WHY A WRITE DOOR, NOT A BARE ``os.environ.setdefault``. The bare
    version asks about ONE name. If `name` has a past and the operator set
    the OLD one, `setdefault` will not see it, will set its own default — and
    :func:`get` will return the default, because the new name is now set and
    wins by the order of authorities. That is, a setting the operator did set
    would silently disappear, and the write made somewhere during import
    would be to blame.

    The same PROPERTY is asked as on a read: "has the value already been
    named?" — under either of its two names.
    """
    if get(name) is None:
        os.environ[name] = value
