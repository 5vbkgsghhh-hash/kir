"""HOST PORTS: KIR states what it needs, not where to get it from.

    from kir import ports
    tc = ports.need(ports.TURN_CONTEXT)      # no provider -> PortMissing
    rv = ports.ask(ports.DESIGN_REVIEW)      # no provider -> None

WHY. The owner's word of 27.08.2026: "Kuki is just one of the environments
where KIR runs." KIR must stand on its own, and KUKAI must be ONE of its
hosts. Before this file, KIR called the product by name:
`from kukai.llm.turn_context import ...` right inside a function body. Such
a call does not break loading — it breaks the RUNTIME for someone else, in
someone else's environment, on whatever branch they reached. Static analysis
does not see this; the instrument
`test_kir_boundary_to_the_product_is_a_closed_list.py` does.

🔴 WHY A REGISTRY, NOT A STRING IMPORT FROM CONFIG. A string import is the
same hard call, just written down late and unchecked: a typo in the name
turns into a refusal for the user. Here the host REGISTERS what it has, and
the list of what is supplied can be printed (`supplied()`), meaning the
environment can be asked what it can do BEFORE anything breaks.

🔴 WHY A FACTORY, NOT A READY-MADE OBJECT. Today's calls are lazy ON
PURPOSE: `kukai.llm` and `kukai.api` are heavy and in places locked onto
each other, and an early import would change the product's load order. The
host hands over `() -> object`, the registry calls it ONCE on first request
and remembers it. Laziness is preserved byte for byte.

🔴 WHY `need` RAISES INSTEAD OF RETURNING `None`. The call sites in
`serving.py` are already wrapped in `try/except Exception` and treat failure
as "was not asked" (mode not set, screen unavailable, review not recorded).
`PortMissing` is a subclass of `Exception`, so substituting a port in place
of an import DOES NOT CHANGE BEHAVIOR ON ANY branch: the absence of a
provider looks exactly like a failed import. This is a precondition for the
cut, not a convenience: a cut that changes behavior is no longer a cut.

WHAT THIS FILE DOES NOT DO. It does not substitute stubs and does not "work
without a host somehow." No provider means a NAMED refusal carrying the
port's name. An emptiness that cannot be enumerated is a named refusal, not
an emptiness.
"""

from __future__ import annotations

from typing import Any, Callable, Protocol, runtime_checkable

#: TURN context: who is asking and in what mode. Everything is optional —
#: an unset field means "not this mode", not a refusal.
TURN_CONTEXT = "llm.turn_context"

#: A live report to the screen. The screen has no right to crash a turn.
TURN_PROGRESS = "llm.turn_progress"

#: The pipeline that executes C# in Revit. The ONE port without which
#: writing is impossible: KIR prints C#, but does not send it.
EXECUTION = "llm.revit_execution_pipeline"

#: Open window sessions and the socket registry — for the document header.
SESSION_CONTEXTS = "api.chat_ws"
WS_REGISTRY = "api.ws_registry"

#: Program review and build consistency — the PRODUCT's judgments about
#: the program.
DESIGN_REVIEW = "design.review"
DESIGN_COHERENCE = "design.coherence"

#: 🔴 ROOM FUNCTION FROM ITS NAME — for when our lexicon did not recognize
#: the name.
#:
#: WHY, IN THE OWNER'S WORDS OF 28.08.2026: the product is universal, "anyone
#: can download and deploy it themselves." That means names will come in any
#: language, with any abbreviations, and with typos. The same day's
#: measurement: 81 names in eight languages, the lexicon recognizes 6/81
#: under v1 and 23/81 under v2; six of the eight languages score ZERO.
#:
#: 🔴 AND THAT IS NOT A REASON TO GROW THE DICTIONARY — the owner's decision,
#: same place: "you cannot foresee every word, and if you decide to try, it's
#: a pile of garbage in the code." Seven of the eight Russian misses are not
#: typos but declensions, abbreviations, and punctuation: misses grow with
#: the ways of WRITING, and cannot in principle be closed by a word list. So
#: the lexicon is DECLARED incomplete (see the header of
#: `checker/classify.py`), and the OWNER names what is missing — whether with
#: their country's dictionary, an LLM, or their own template's parameter.
#: KIR does not choose which.
#:
#: 🔴 WHY THIS DOES NOT BREAK THE JUDGE'S DETERMINISM. The port is called
#: ONCE, when the model is built, and the answer is RECORDED into
#: `Room.function` together with the kind
#: `Room.function_source = "host_classifier"`. The judge reads what was
#: RECORDED and never goes to a live guess: the same model gives the same
#: verdict. The kind is `derived` (`function_provenance.DERIVED`) — it was
#: not the author who named it, so this function CANNOT cast a veto on the
#: verdict.
#:
#: THE ABSENCE OF A PROVIDER IS THE STANDARD ANSWER, not a refusal: it is
#: asked with `ask()`. An unrecognized name remains unrecognized, and this
#: does not turn into silence — HAB062 and the coverage section name such
#: rooms explicitly (`checker/tests/
#: test_a_foreign_name_is_unverifiable_not_exempt.py`).
ROOM_CLASSIFIER = "design.room_classifier"

#: Application state (the A5 tenancy base).
APP_STATE = "app_state"

#: The bridge protocol: outcome envelopes that the PRODUCT builds.
BRIDGE_PROTOCOL = "api.bridge_protocol"

#: Collapsing a tool result for the chat is also the HOST's business.
CHAT_HELPERS = "api.chat_helpers"

#: KIR's service door into the product (an admin endpoint). The language
#: does not have one.
ADMIN_KIR = "api.admin_kir"

#: The host's viewer route: the socket through which it serves the scene.
VIEWER_ROUTE = "api.viewer"

#: THIS INSTALLATION'S DATA DIRECTORIES — the OWNER names them, the package
#: does not derive them.
#:
#: WHY, BY THE MEASUREMENT OF 28.08.2026. After the cut, `install_paths`
#: climbs up from the package's location to the `backend/kukai` marker; above
#: `/opt/kir` no such directory exists, and `install_root()` answers `None`
#: ALWAYS. The answer is honest — the package has every right not to know a
#: stranger's layout — but the OWNER does have the data, and eight of the
#: viewer's fourteen routes stand on it. Live: `list_runs()` -> 0 while 81
#: decompiles with an L0 stream sit on disk; the live service's environment
#: (pid 2951264, started 27.08 12:17) carries not a single `KIR_*` variable.
#:
#: 🔴 AND WHY THIS IS NOT FIXED BY A SINGLE ROOT VARIABLE. Directories of
#: different KINDS sit under DIFFERENT roots for the owner — measured the
#: same day, by a run:
#:
#:     KIR_INSTALL_ROOT=<backend>   corpus  backend/backend/data/decompile  YES
#:                                  feeds   backend/backend/data/telemetry  NO
#:     KIR_INSTALL_ROOT=<repository>  the other way around
#:
#: The reason is not the owner's layout, but that
#: `serving._DECOMPILE_OUT_ROOT` is a RELATIVE path, resolved against the
#: service's working directory. There is no single root covering both
#: kinds; so the root cannot be derived arithmetically by anyone, and it
#: must be asked FOR, BY KIND, from whoever laid the installation out.
#:
#: WHAT TO RETURN: the directory for the kind (`str` or `Path`). A kind the
#: owner does not keep is simply NOT NAMED — `None` is legitimate and means
#: exactly the same thing as an unsupplied port: the consumer falls back to
#: its existing `None` policy (feeds stay silent, acceptance refuses
#: pre-effect). Making up a plausible path instead of admitting absence is
#: not allowed: a stranger's directory being written into is worse than
#: silence.
INSTALL_DATA = "data.install_paths"

#: ── TOOLS, NOT RUNTIME ───────────────────────────────────────────────────
#: These two ports are needed by KIR's GATES, not by program execution:
#: closing service references and offline-document loaders. Today they are
#: supplied by the product's `tools/`; they are KIR's by subject, but they
#: themselves pull in the product, so moving them inside would ADD crossings
#: rather than remove them. The port names the dependency instead of hiding
#: it: a standalone KIR will say "instrument not supplied" instead of
#: `ImportError`, and the gate will count it as a REFUSAL, not a skip — a
#: silently skipped check reads as a passed one.
REFERENCE_CLOSURE = "tools.closure_probe"
OFFLINE_GATE = "tools.compile_gate_offline"

#: 🔴 THE OWNER'S ENTRY POINTS. Introduced 01.09.2026 by the owner's law, not
#: by convenience: "KIR is the language of buildings, environment-agnostic;
#: the product is just ONE of the environments." Before this,
#: `instruments/capability_graph.py` held the product's deployment map as
#: LITERALS — four module names and systemd unit names — and the package,
#: shipped to PyPI under Apache-2.0, printed them to EVERY reader.
#:
#: WHAT TO RETURN: a mapping of MODULE NAME -> what launches it, as a
#: string. An unsupplied port is legitimate and means "no entry points
#: declared": the traversal remains COMPLETE, and the reachability share is
#: not printed at all — printing it from an empty set would produce a zero
#: indistinguishable from a dead tree.
ENTRY_POINTS = "tools.entry_points"

#: 🔴 THE TRANSPORT FOR THE MCP DOOR IS NARROWER THAN `EXECUTION`, AND ON
#: PURPOSE (02.09.2026).
#:
#: `EXECUTION` declares the PRODUCT's pipeline: `RevitExecutionPipeline`,
#: assembled from `llm_client` and `bridge_callback`. The MCP door has
#: neither one nor the other — it does not even have the notion of a "turn".
#: Forcing it to speak in the product's shape would mean writing the product
#: into the language exactly where we cut it out.
#:
#: WHAT TO RETURN: an object with two methods (see `McpRevitPort`). Reading
#: is enough for `kir_open`; writing is asked for separately, so that a host
#: offering ONLY reading can be expressed — "you may look, you may not
#: write" is a legitimate environment, and it must not look like a
#: breakage.
#:
#: THE ABSENCE OF A PROVIDER IS THE STANDARD STATE, not a refusal of the
#: environment: the offline doors (`kir_author`, `kir_compile`,
#: `kir_rehearse`, `kir_preview`, `kir_spec`) work without it and never ask
#: for it once.
MCP_REVIT = "mcp.revit"

ALL_PORTS: tuple[str, ...] = (
    TURN_CONTEXT, TURN_PROGRESS, EXECUTION, SESSION_CONTEXTS,
    WS_REGISTRY, DESIGN_REVIEW, DESIGN_COHERENCE, ROOM_CLASSIFIER, APP_STATE,
    REFERENCE_CLOSURE, OFFLINE_GATE, BRIDGE_PROTOCOL, CHAT_HELPERS,
    ADMIN_KIR, VIEWER_ROUTE, INSTALL_DATA, ENTRY_POINTS, MCP_REVIT,
)


class PortMissing(Exception):
    """The host did not supply this capability. The port's name is in the
    text."""


@runtime_checkable
class TurnContextPort(Protocol):
    """Attributes of the current turn. Each one may be absent."""

    def kir_mode_active(self) -> bool: ...
    def kir_hold_active(self) -> bool: ...
    def turn_document_title(self) -> str: ...


@runtime_checkable
class TurnProgressPort(Protocol):
    """A report to the screen. Asynchronous, and its failure does not crash
    the turn."""

    async def report_failure(self, text: str) -> None: ...
    async def report_write(self, created: int, dur_ms: int, note: str) -> None: ...


@runtime_checkable
class RoomClassifierPort(Protocol):
    """The owner names room functions whose NAMES our lexicon did not
    recognize.

    IN A BATCH, NOT ONE AT A TIME, AND THIS IS LOAD-BEARING. The decompile
    store holds 44 684 room names with 8453 DISTINCT ones (measured
    18.08.2026): calling per room would mean 44 684 calls to the LLM
    provider instead of one. The batch also makes the answer recordable as
    a whole — and a recorded answer is exactly what keeps the judge
    deterministic.

    WHAT TO RETURN: a mapping of NAME -> a `RoomFunction` value (as a
    string, e.g. `"жилая"`). A name the owner does not know, it simply DOES
    NOT PUT into the answer — and that is not a loss: the unrecognized
    stays unrecognized and is voiced through HAB062. Making up `"прочее"`
    instead of absence is NOT ALLOWED: `прочее` is a claim of
    "non-residential", it lifts the fitness-for-use rules, and it differs
    from the unknown by exactly the reason this port exists.

    A value not present in `RoomFunction` is DISCARDED by the caller: a
    stranger's typo in a kind name has no right to become a room function.
    What is discarded stays unclassified, that is, loud — there is no way
    to lose it silently.
    """

    def classify_room_names(self, names: tuple[str, ...]) -> dict[str, str]: ...


@runtime_checkable
class InstallDataPort(Protocol):
    """The installation's data directory, BY KIND. An address only — no
    reading, no writing.

    The kinds the package asks for today (the list is open, on purpose: a
    new consumer introduces its own kind rather than re-training the
    owner):

        "decompile"   the decompile store — the viewer, the course, and the
                       axis census stand on it
        "telemetry"   witness, refusal, and shadow feeds, the program journal
        "evidence"    acceptance evidence

    WHAT THIS PORT DOES NOT DO. It does not create directories and does
    not check permissions: both are the CONSUMER's policy, and each
    consumer has its own (feeds fail-open, acceptance refuses pre-effect).
    The port answers one question — "where does THIS live for YOU" — and
    `None` is a legitimate answer.
    """

    def data_path(self, kind: str) -> Any: ...


@runtime_checkable
class ExecutionPort(Protocol):
    """Sending printed C# to Revit and receiving the execution record."""

    def wrap_user_code(self, csharp: str) -> str: ...


@runtime_checkable
class McpRevitPort(Protocol):
    """Transport to Revit for the MCP door. Two methods, both asynchronous.

    `read` executes ONLY read-only C# and returns the parsed bridge
    response. `write` executes writing C# and returns the execution
    receipt.

    SPLIT NOT FOR ELEGANCE: a host offering only reading must be able to be
    expressed. A single method with a "now write" flag would make "you may
    look, you may not write" indistinguishable from breakage, and such an
    environment is legitimate and probably the first one in which the door
    will end up in a stranger's hands.

    WHAT THE HOST MUST GUARANTEE: `write` either applied the program whole,
    or applied nothing at all. The language cannot fix a partial
    application — it has no carrier through which to learn about one.

    🔴 OPERATION IDENTITY (06.09.2026, finding from audit E6). Before this,
    retrying a write after a LOST RESPONSE created a second element: the
    door had no way to say "this is the same operation," and the owner had
    no way to answer "I already executed it." The contract was extended
    BACKWARD-COMPATIBLY, with two optional capabilities; a host that
    supplies neither works exactly as before, and the door learns this by
    CHECKING THE SIGNATURE, not by catching an exception (an exception is
    indistinguishable from the write itself failing — and these are two
    different things).

      * `write(..., operation_id=...)` — THE SUBMISSION'S NAME. A host that
        accepts it must execute the operation with the given
        `operation_id` NO MORE THAN ONCE: a repeated `write` with the same
        name does not apply the program a second time, but returns the
        first receipt. This is deduplication on the side that alone can
        provide it — the language cannot provide it.
      * `lookup(operation_id)` — HOW IT ENDED. Returns that operation's
        receipt or `None`, and `None` is allowed to be returned ONLY when
        the runtime CAN PROVE the operation never started. A host that
        "simply doesn't know" must return a receipt with an unknown
        status, or raise: the door reads both a raise and unknown-ness as
        "the outcome is still unknown" and blocks a second submission.
        Lying here with `None` means allowing a double write — this is the
        ONE place in the contract where an error by the host costs an
        element in the model.

    Both capabilities are optional and checked separately: a host may
    support `operation_id` without supporting `lookup` (in which case the
    door asks a human), and vice versa.
    """

    async def read(self, csharp: str, *, timeout_ms: int) -> Any: ...
    async def write(self, csharp: str, *, timeout_ms: int,
                    operation_id: str | None = None) -> Any: ...


@runtime_checkable
class McpRevitLookupPort(Protocol):
    """The OPTIONAL second half of `McpRevitPort` — "how it ended".

    A separate protocol, not a line inside the first one, ON PURPOSE:
    `runtime_checkable` checks for the PRESENCE of names, and declaring an
    optional method inside the shared protocol would make every host
    without it formally non-conforming. Here the capability is asked about
    separately and on its own.

    The `lookup` contract lives in `McpRevitPort`'s header: an operation's
    receipt or `None`, and `None` only when "never started" is PROVEN.
    """

    async def lookup(self, operation_id: str) -> Any: ...


@runtime_checkable
class LlmProviderPort(Protocol):
    """A language-model provider. ONE turn: request -> response, and
    nothing else.

    🔴 WHAT THIS PROTOCOL DOES NOT HAVE, AND THIS IS THE MAIN POINT. No
    `store`, no path, no revision, no task. The provider has no right to
    either read the project or write it: it receives MESSAGES and returns
    TEXT. Everything that happens to the text afterward — the sandbox, the
    program, the proposal, CAS — is done by the caller, through doors that
    already exist. Give the provider access to storage, and "the model
    wrote the program" would stop being a checkable claim: there would be
    no way to tell what was composed from what was peeked at.

    There is NO real implementation in the tree, and there cannot be one
    this shift: it needs access and an agreed spending limit (the owner's
    word). There is a cassette stand-in and the NAMED refusal
    `RealProviderUnavailable`.
    """

    def complete(self, request: Any) -> Any:
        """`CompletionRequest -> CompletionResponse`. There are no further
        turns."""


@runtime_checkable
class ReviewPort(Protocol):
    def record(self, program: Any) -> None: ...


@runtime_checkable
class CoherencePort(Protocol):
    def flatten(self, programs: Any) -> Any: ...
    def check(self, elements: Any) -> Any: ...


_factories: dict[str, Callable[[], Any]] = {}
_resolved: dict[str, Any] = {}


def register(name: str, factory: Callable[[], Any]) -> None:
    """The host declares a capability. `factory` is called LAZILY, once.

    Re-registration is allowed and replaces the previous one along with
    any already-resolved object: the test suite has every right to swap
    the host, and a silent "first one wins" would hide the swap.
    """
    if name not in ALL_PORTS:
        raise ValueError(
            f"порт «{name}» не объявлен в ALL_PORTS: имя, которого никто не "
            f"спрашивает, — опечатка, а не расширение")
    _factories[name] = factory
    _resolved.pop(name, None)


def unregister(name: str) -> None:
    """Remove a provider. Needed by the test suite: without removal, a
    REFUSAL cannot be checked."""
    _factories.pop(name, None)
    _resolved.pop(name, None)


def supplied() -> tuple[str, ...]:
    """What the host has supplied. The environment can be asked BEFORE
    anything breaks."""
    return tuple(sorted(_factories))


def missing() -> tuple[str, ...]:
    return tuple(p for p in ALL_PORTS if p not in _factories)


def ask(name: str) -> Any | None:
    """A provider or `None`. For places where absence is the standard
    answer."""
    try:
        return need(name)
    except PortMissing:
        return None


def need(name: str) -> Any:
    """A provider, or `PortMissing`.

    Substituted IN PLACE of a product import: `PortMissing` is a subclass
    of `Exception`, so existing `try/except Exception` blocks catch it
    exactly as they caught `ImportError`. Behavior does not change.
    """
    if name in _resolved:
        return _resolved[name]
    factory = _factories.get(name)
    if factory is None:
        raise PortMissing(
            f"порт «{name}» не поставлен этой средой; поставлено: "
            f"{', '.join(supplied()) or '—'}")
    obj = factory()
    if obj is None:
        raise PortMissing(f"поставщик порта «{name}» вернул None")
    _resolved[name] = obj
    return obj
