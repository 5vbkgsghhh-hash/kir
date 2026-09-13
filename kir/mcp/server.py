"""THE MCP SERVER OVER KIR: the language of buildings as a tool for any
host.

    python -m kir.mcp                      # stdio (Claude Desktop, Claude Code)
    python -m kir.mcp --http --port 8765   # Streamable HTTP

The target protocol revision is **2026-07-28**: no sessions, no
`initialize`, every request is self-contained. This stage STANDS WITHOUT
REVIT and without the product: it writes programs, compiles them to C#
for every shipped version, rehearses, and draws a floor plan. It writes
NOTHING to a live model and never asks for a write port — the hand
appears at stage 4 of the plan.

🔴 WHY THE SDK'S LOWER LEVEL, RATHER THAN THE ERGONOMIC ONE. The full
argument is in `surface.py`'s header: the ergonomic layer derives
`inputSchema` from python annotations, and that is a second carrier of
truth about the language. Here the schema is delivered VERBATIM from the
registry's generator.

🔴 A KIR REFUSAL IS A NORMAL RESULT, NOT `isError`. The rule is carried
over from `serving.py` verbatim, and it is load-bearing: a typed refusal
carries a `handoff` and TEACHES the next move, while `isError` says "the
tool broke" and cuts reasoning off. `is_error=True` is reserved for
exactly one case — the SERVER ITSELF crashed.

🔴 NOTHING IS TRUNCATED. A receipt cut in half is a lie, not an economy,
and this tree has already paid for exactly this defect once: gate 6/6
green, the golden green, 798 tests green, and only 300 characters out of
~520 reached the reader
(`emission-green-does-not-mean-delivered`, 26.08.2026). A response that is
too large gets a NAMED refusal with the limit's name and a next move
(`out_dir`), not an ellipsis.
"""
from __future__ import annotations

import functools
import hashlib
import inspect
import json
import logging
import os
import pathlib
import sys
from typing import Any

from kir.mcp import app as _app
from kir.mcp import live as _live
from kir.mcp import surface
from kir import wire_json

logger = logging.getLogger("kir.mcp")

#: 🔴 THE CEILING FOR INLINE C# IS A HOST CONVENTION, NOT THE LETTER OF
#: THE SPEC, and so it is named here as a number, rather than hidden. The
#: tower from `examples/tower_numpy.py` weighs 3,902,141 characters of
#: C# — embedding that into a response means bringing down the client's
#: window. Exceeding it is a refusal with the limit's name; the full text
#: can be obtained via `out_dir`.
INLINE_MAX_CHARS = 40_000

#: The freshness of the tool list (SEP-2549). The list is derived from
#: the package's registry: it is the same for everyone and changes only
#: with the package's version, that is, with a process restart. An hour
#: is an honest upper estimate, `public` is also a fact, not a
#: convenience: nothing in the list depends on who is asking.
TOOLS_TTL_MS = 3_600_000


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


def _refusal(code: str, message_ru: str, **extra: Any) -> dict:
    """A typed refusal of THIS server. One shape for every door.

    `next_ru` is mandatory: a refusal that does not name the next move
    forces the model to guess — and guessing costs a round trip.
    """
    body = {"ok": False, "kir": True, "err": {"code": code,
                                              "message_ru": message_ru}}
    body.update(extra)
    return body


# ─────────────────────────────────────────────────────────────────────────────
# Doors
# ─────────────────────────────────────────────────────────────────────────────

def _author(args: dict) -> dict:
    """`kir_author` — the author's python turns into IR operations."""
    from kir.mcp import policy as _policy
    from kir.sandbox import execute_author_script

    source = args.get("program_py")
    if not isinstance(source, str) or not source.strip():
        return _refusal("form", "поле `program_py` обязано быть непустой строкой",
                        next_ru="передай исходник питона, собирающий программу")
    params = args.get("params")
    # 🔴 THE DOOR'S POLICY, NOT THE PRODUCT'S (the owner's word,
    # 02.09.2026: «give MCP more assumptions»). What exactly is wider and
    # what is NOT weakened in the process — in the header of
    # `kir/mcp/policy.py`; in short: the name whitelist and the time and
    # memory budgets are wider, and not one OS isolation layer is
    # touched.
    result = execute_author_script(
        source, policy=_policy.author_policy(),
        params=params if isinstance(params, dict) else None)

    # The existing sandbox receipt owns authoring evidence. Keep it detached
    # beside the IR, including the exact source that this caller supplied;
    # neither compiler schema nor program digest contains receipt metadata.
    authorship = result.as_dict()
    authorship.pop("ops", None)
    authorship.pop("envelope", None)
    authorship["program_py"] = source

    if not result.ok:
        r = result.refusal
        # The sandbox's refusal arrives AS IS: it is already typed,
        # already carries the line number in the MODEL's own source, and
        # already contains none of our frames.
        # 🔴 THE CODE IS TAKEN FROM THE REFUSAL, AND THERE IS NO FALLBACK
        # (02.09.2026, found by a neighboring session). `getattr(r, "code",
        # "KIR-B000")` used to stand here, and it was a DOUBLE defect:
        # `KIR-B000` is not registered with the dispatcher (`diag.spec_of`
        # answers None) — meaning a code outside the closed list could
        # have ridden out to the model; and the `code` field on
        # `SandboxRefusal` is MANDATORY, meaning the fallback was
        # unreachable and existed only to lie. A made-up code is worse
        # than a missing one: it looks like a code.
        code = getattr(r, "code", None)
        return {
            "ok": False, "kir": True, "wrote_nothing": True,
            "err": {"code": code if isinstance(code, str) and code else "sandbox",
                    "message_ru": getattr(r, "message_ru", str(r))},
            "line": getattr(r, "line", None),
            "source_line": getattr(r, "line_text", None),
            "author_digest": result.author_digest,
            "authorship": authorship,
        }

    program = result.to_program()
    return {
        "ok": True, "kir": True, "wrote_nothing": True,
        "program": program,
        "ops": len(result.ops),
        "author_digest": result.author_digest,
        "params_digest": result.params_digest,
        "duration_s": round(result.duration_s, 3),
        "authorship": authorship,
        "next_ru": ("программа собрана и НИЧЕГО не построено: дальше "
                    "`kir_rehearse` (что не будет проверено), `kir_preview` "
                    "(как это выглядит) или `kir_compile` (C# по версиям)"),
    }


def _spec(args: dict) -> dict:
    """`kir_spec` — an op's contract. The text is taken from the same
    function that prints it to the author INSIDE the sandbox: two copies of
    the reference would drift apart, and the model would read something no
    longer in the registry."""
    import contextlib
    import io

    from kir import course

    op = args.get("op")
    if op is not None and not isinstance(op, str):
        return _refusal("form", "поле `op` обязано быть строкой",
                        next_ru="передай имя операции либо не передавай ничего")
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            course.spec(op)
    except Exception as exc:  # noqa: BLE001 — an unknown name also answers with text
        return _refusal("spec", f"{type(exc).__name__}: {exc}",
                        next_ru="позови `kir_spec` без аргумента — вернётся "
                                "оглавление реестра")
    answer = {"ok": True, "kir": True, "wrote_nothing": True,
              "op": op, "contract": buf.getvalue()}
    answer.update(_capability_fields(op))
    return answer


def _capability_fields(op: object) -> dict:
    """`limits` (axis -> reason) and `capabilities` — NEXT TO the contract,
    not inside it.

    WHY THIS EXISTS AT ALL. The contract answers what an op MEANS, and
    stays silent about what the tree around it can do with it: whether it
    is drawn on the plan, whether it is recovered back out of the model,
    whether it gives a solid to clash detection. Silence reads as "can do
    everything" — the same class of defect as the clash blind spot with no
    named reason (`clash_bundle.OP_NO_BODY`, header). The terminal has
    printed this since 07.09.2026 (`kir ops <name>`, the "WHAT THIS OP
    CANNOT DO" block), while the model, through the door, saw NOTHING at
    all — and it is exactly the model that authors programs.

    🔴 WHY NEXT TO IT, RATHER THAN INSIDE THE TEXT. THIS IS A MEASUREMENT,
    NOT TASTE (07.09.2026). The contract's text is cut by the SANDBOX
    ceiling (`course.LESSON_CAP` = 3300 = a 4000 channel minus a 700
    reserve for the model's own printing): it is printed by the same
    function that prints it to the author inside the sandbox, and the
    ceiling rides here together with the text. A census across all 83 ops
    of the registry — how many characters an op still has room for WITHOUT
    LOSING the contract's tail (binary search on the live trimmer):

        create_solid_blend     text 3538   MARGIN 18
        create_ceiling         text 3159   MARGIN 571
        create_stairs_landing  text 3188   MARGIN 1168
        the other 80                       MARGIN > 1900

    The limits block in prose weighs 321 characters at the median and 696
    at the maximum; even a form made of NOTHING BUT axis codes is 28. It
    does not fit into the text, and would not fit SILENTLY: for
    `create_solid_blend` the addition would push the contract from the
    "trim the prose" branch into the "cut the tail" branch, and the op
    would lose its parameter bounds (`height_mm 1..500000`, six values of
    `category`) — exactly the numbers a model would miss on. The ratchet
    `tests/test_an_overflowing_contract_keeps_its_tail.py` did not catch
    this: it skipped such an op with a `continue` line (removed the same
    day).

    THE DOOR HAS NO SUCH CEILING AT ALL: it answers JSON-RPC, not the
    sandbox's 4000-character pipe. The field stands next to it at zero
    channel cost and arrives MACHINE-READABLE — axis -> reason, rather than
    a paragraph the model has to parse.

    THERE IS ONE CARRIER — `kir.capability`, a projection of the five live
    axes; not one op name is hand-typed here, and the door cannot drift
    apart from the terminal.
    """
    from kir import capability, spec

    # The registry's table of contents (`op is None`) and a MACRO
    # (`spec("stack")`) are legitimate answers from `course.spec`, but they
    # have no axes: `capability` answers about OPS. Staying silent here is
    # more honest than returning an empty `limits`, which reads as "no
    # limits."
    if not isinstance(op, str) or op not in spec.OPS:
        return {}
    return {
        # The closed list of axes rides along with the answer ON
        # PURPOSE: without it, an empty `limits` is indistinguishable from
        # "we did not look." With it, it reads exactly as
        # `capability.limits` promises — "can do all five."
        "axes": list(capability.AXES),
        "limits": capability.limits(op),
        "capabilities": sorted(capability.capabilities(op)),
    }


class _LocalOutput:
    """stdio file output: an ordinary directory and overwriting writes, no confinement.

    The HTTP door supplies `http_security.OutputRoot` instead. Both answer
    `directory()`/`write()`, so `_compile` has ONE write path and the
    difference between the two contracts is a named object, not a `None`.
    """
    reports_effects = False

    @staticmethod
    def directory(value: str) -> pathlib.Path:
        target = pathlib.Path(value).expanduser()
        target.mkdir(parents=True, exist_ok=True)
        return target

    @staticmethod
    def write(directory: pathlib.Path, name: str, source: str) -> pathlib.Path:
        path = directory / name
        path.write_text(source, "utf-8")
        return path


_LOCAL_OUTPUT = _LocalOutput()


def _compile(args: dict, *, output_policy=_LOCAL_OUTPUT) -> dict:
    """`kir_compile` — C# by version. Not one call outward."""
    from kir.compiler import compile_program
    from kir.registry_base import REVIT_VERSIONS

    program = args.get("program")
    if not isinstance(program, dict):
        return _refusal("form", "поле `program` обязано быть объектом программы",
                        next_ru="возьми программу у `kir_author` или напиши "
                                "операции по схеме этого инструмента")
    versions = args.get("versions") or list(REVIT_VERSIONS)
    unknown = [v for v in versions if v not in REVIT_VERSIONS]
    if unknown:
        return _refusal(
            "version",
            f"версии не поставлены этим пакетом: {', '.join(map(str, unknown))}",
            supplied=list(REVIT_VERSIONS),
            next_ru="назови версии из перечня `supplied` или не передавай поле")

    out_dir = args.get("out_dir")
    target: pathlib.Path | None = None
    if isinstance(out_dir, str) and out_dir.strip():
        try:
            target = output_policy.directory(out_dir)
        except (OSError, ValueError) as exc:
            return _refusal("out_dir", f"каталог не создан: {exc}",
                            next_ru="назови каталог внутри --out-root HTTP-сервера "
                                    "либо используй существующий stdio-контракт")

    per: dict[str, Any] = {}
    green: list[str] = []
    created_outputs: list[str] = []
    output_error_seen = False
    for version in versions:
        try:
            out = compile_program(program, revit_version=version)
        except Exception as exc:  # noqa: BLE001 — a compiler refusal is not a crash of the door
            per[version] = {"ok": False,
                            "err": f"{type(exc).__name__}: {exc}"}
            continue
        csharp = out.csharp or ""
        row: dict[str, Any] = {
            "ok": bool(out.ok),
            "chars": len(csharp),
            "sha256": _sha256(csharp) if csharp else None,
            "diagnostics": [str(d) for d in (out.diagnostics or [])][:50],
        }
        if out.handoff:
            row["handoff"] = out.handoff
        if out.ok:
            if target is not None:
                try:
                    path = output_policy.write(target, f"kir_{version}.cs", csharp)
                except ValueError as failure:
                    output_error_seen = True
                    row.update(ok=False, file_error=str(failure),
                               file_effect="not_established", retry_safe=False)
                    per[version] = row
                    continue
                row["path"] = str(path)
                if output_policy.reports_effects:
                    row["file_effect"] = "created"
                    created_outputs.append(str(path))
            elif len(csharp) <= INLINE_MAX_CHARS:
                row["csharp"] = csharp
            else:
                # WE DO NOT TRUNCATE. We name the limit and the next move.
                row["csharp_withheld"] = {
                    "reason_ru": (f"C# длиной {len(csharp)} знаков не вложен: "
                                  f"предел встроенного ответа "
                                  f"{INLINE_MAX_CHARS} знаков"),
                    "next_ru": "передай `out_dir` — текст ляжет файлами по версиям",
                }
            green.append(version)
        per[version] = row

    result = {
        "ok": len(green) == len(versions),
        "kir": True, "wrote_nothing": True,
        "versions": {"asked": list(versions), "green": green,
                     "score": f"{len(green)}/{len(versions)}"},
        "per_version": per,
    }
    if output_policy.reports_effects:
        result.update(native_model_effect="none", filesystem_effect=(
            "partial_or_unknown" if output_error_seen else "created" if created_outputs else "none"),
            files_created=created_outputs, wrote_nothing=not (output_error_seen or created_outputs))
    return result


def _rehearse(args: dict) -> dict:
    """`kir_rehearse` — what will NOT be checked. No round trip, no transaction."""
    from kir.rehearsal import rehearse

    program = args.get("program")
    if not isinstance(program, dict):
        return _refusal("form", "поле `program` обязано быть объектом программы",
                        next_ru="возьми программу у `kir_author`")
    block = rehearse(program)
    return {"ok": True, "kir": True, "wrote_nothing": True,
            "rehearsal": block}


def _preview(args: dict) -> dict:
    """`kir_preview` — an SVG floor plan plus a census of the UNKNOWN."""
    from kir.preview import build_program_preview, render_svg

    program = args.get("program")
    if not isinstance(program, dict):
        return _refusal("form", "поле `program` обязано быть объектом программы",
                        next_ru="возьми программу у `kir_author`")
    levels = args.get("levels")
    building = build_program_preview(
        program, levels=levels if isinstance(levels, list) else None)
    sheets = []
    for plan in getattr(building, "plans", []) or []:
        # MCP answers the MODEL, not a human: it needs the full sheet.
        svg = render_svg(plan, audience="instrument")
        sheets.append({
            "level": getattr(plan, "level_name", None) or getattr(plan, "name", None),
            "chars": len(svg),
            "svg": svg if len(svg) <= INLINE_MAX_CHARS else None,
            "svg_withheld_ru": (None if len(svg) <= INLINE_MAX_CHARS else
                                f"SVG длиной {len(svg)} знаков не вложен: предел "
                                f"{INLINE_MAX_CHARS}"),
            # 🔴 THE CENSUS RIDES AS A SEPARATE FIELD, NOT ONLY INSIDE THE
            # SVG'S `<metadata>`. Before 02.09.2026 it lived only there —
            # and a client WITHOUT the app (that is, any text-only one) got
            # a huge string of drawing and NOT ONE word about what is not
            # on it. Law #4 ("412 of 480 drawn, 68 not drawn for named
            # reasons") is a statement of the same force as the drawing
            # itself, and it must reach through both channels.
            "census": plan.census.to_dict(),
        })
    return {"ok": True, "kir": True, "wrote_nothing": True,
            "doc_name": getattr(building, "doc_name", None),
            "assertion": getattr(getattr(building, "assertion", None), "value", None),
            "census": building.census.to_dict(),
            "sheets": sheets, "sheet_count": len(sheets)}


def served_resources() -> tuple[dict[str, Any], ...]:
    """What the door returns for `resources/list` — as ordinary
    dictionaries, without the SDK.

    🔴 WHY A SEPARATE FUNCTION, RATHER THAN A LITERAL INSIDE
    `build_server`. The tool REFERENCES `ui://` (the surface), the server
    IS THE ONE THAT SERVES that `ui://` (the wire). As long as both sides
    read one constant, an instrument that "cross-checks" them compares the
    constant against itself — that is, it guards nothing. Pulling it out
    makes the two sides two different paths: the surface assembles `meta`,
    the wire assembles the list, and now there IS something for them to
    drift apart by — meaning there is something to check
    (`test_the_app_is_wired`).
    """
    return ({
        "uri": _app.APP_URI,
        "name": "План этажа KIR",
        "description": ("Интерактивный лист: масштаб, выбор этажа и перепись "
                        "того, чего на чертеже НЕТ."),
        "mime_type": _app.APP_MIME_TYPE,
        "text": _app.HTML,
    },)


#: The dispatcher. A dictionary, not an `if`-ladder: a door's name exists
#: in EXACTLY ONE place, and it has nothing to drift apart from the
#: surface with — the gate cross-checks both sets.
_DOORS = {
    "kir_author": _author,
    "kir_spec": _spec,
    "kir_compile": _compile,
    "kir_rehearse": _rehearse,
    "kir_preview": _preview,
    "kir_open": _live.open_building,
    "kir_write": _live.write_program,
}

#: The name of the slot the request to the human and their answer ride
#: on. ONE for both directions: drifting apart, they would turn "the
#: human agreed" into "no answer" — and the door would silently go down
#: the refusal branch.
_HUMAN_SLOT = "confirm"

#: Doors that have a second move (MRTR). Enumerated, not guessed from
#: the signature: "accepts `confirmed`" is a property of the
#: implementation, while "asks the human" is a property of the CONTRACT,
#: and they must be free to change independently.
_ASKS_HUMAN = frozenset({"kir_write"})


async def dispatch(name: str, args: dict, *, doors: dict | None = None, **kw: Any) -> tuple[dict, bool]:
    """(the response body, whether the SERVER ITSELF crashed).

    The second member is not "did it succeed": a KIR refusal is obtained
    in the ordinary course of things and arrives with `is_error=False`.
    `True` here means exactly "the door failed in a way that was not
    provided for," and this is the one case of `isError` in this server.
    """
    door = (_DOORS if doors is None else doors).get(name)
    if door is None:
        return _refusal("unknown_tool", f"инструмента «{name}» этот сервер не несёт",
                        supplied=list(_DOORS), effect="none", wrote_nothing=True), False
    try:
        wire_json.encode({"arguments": args, "continuation": kw})
    except (ValueError, TypeError, UnicodeError, RecursionError):
        return _refusal("invalid_json_input", "аргументы должны быть JSON без NaN/Infinity",
                        wrote_nothing=True, effect="none",
                        next_ru="исправь аргументы; инструмент ещё не вызывался"), False
    try:
        payload = args if isinstance(args, dict) else {}
        # Doors of two kinds live behind one dispatcher: the offline
        # ones are synchronous (the sandbox is a subprocess, it needs no
        # event loop), the live ones are asynchronous (they make a round
        # trip outward). We tell them apart by EXECUTION, not by a list of
        # names: a list would fall behind on the very first new door.
        result = door(payload, **kw) if kw else door(payload)
        if inspect.isawaitable(result):
            result = await result
        try:
            if not isinstance(result, dict):
                raise TypeError("tool result must be an object")
            wire_json.encode(result)
        except (ValueError, TypeError, UnicodeError, RecursionError):
            context = wire_json.identity_context(payload)
            context.update(wire_json.identity_context(result))
            failed = wire_json.failure(result, known_effect="unknown", context=context)
            failed.update(kir=True, err={"code": "response_schema_failure",
                                        "message_ru": "инструмент уже вызван, но ответ нельзя "
                                                      "передать как JSON; это не откат"},
                          next_ru="не повторяй запись: проверь квитанцию исходной операции "
                                  "по context и прочитай сохранённое состояние")
            return failed, True
        return result, False
    except Exception as exc:  # noqa: BLE001
        # Arbitrary exception text can itself be unencodable, invoke custom
        # __str__, or contain credentials. Keep the cause's class, not its repr.
        kind = wire_json.exception_name(exc)
        logger.error("дверь %s подняла исключение %s", name, kind)
        return _refusal("server", f"{kind}: исключение после вызова инструмента",
                        effect="unknown", retry_safe=False, wrote_nothing=False,
                        context=wire_json.identity_context(args),
                        next_ru="это дефект сервера, а не программы; не повторяй запись "
                                "без проверки исходной операции и сохранённого состояния"), True


# ─────────────────────────────────────────────────────────────────────────────
# Wire
# ─────────────────────────────────────────────────────────────────────────────

def build_server(*, compile_output_policy=None) -> Any:
    """Assemble the SDK server. The `mcp` import is HERE, not in the
    module's header.

    The reason: the surface's determinism gate must judge it for whoever
    installed KIR WITHOUT the `[mcp]` extra. Importing at the top would
    turn the extra's absence into an import failure for the whole module,
    and the instrument would stop running exactly where it is needed most.
    """
    # 🔴 THE NAME `mcp` COLLIDED WITH OUR OWN DIRECTORY, AND THIS WAS
    # FOUND BY A FULL RUN ON 03.09.2026, NOT BY REASONING. Our package is
    # called `kir/mcp`, and the moment the `kir/` directory ITSELF lands on
    # `sys.path` (and pytest puts the rootdir there), `import mcp` resolves
    # TO US, not to the SDK. The failure looked like this:
    #
    #     ImportError: cannot import name 'CacheHint' from 'mcp.server'
    #                  (…/tree/kir/mcp/server.py)
    #
    # that is, it pointed at OUR file and read as our own defect. Worse
    # still: `pytest.importorskip("mcp")` PASSED at the same moment — it
    # honestly imported a module named `mcp`, just not that one. The guard
    # for the SDK's presence was fooled by our own package.
    #
    # So the shadowing is NAMED here, before the first reference to the
    # SDK.
    import mcp as _mcp

    _here = str(pathlib.Path(__file__).resolve().parent)
    _found = str(pathlib.Path(getattr(_mcp, "__file__", "") or "").resolve().parent)
    if _found == _here:
        raise RuntimeError(
            "имя `mcp` разрешилось в ЭТОТ пакет, а не в SDK протокола: "
            f"{_found}. Так бывает, когда на sys.path попал сам каталог "
            "`kir/` (это делает pytest от rootdir). Импортируй дверь как "
            "`kir.mcp`, а каталог `kir/` на путь не клади")

    import mcp_types as types
    from mcp.server import CacheHint
    from mcp.server.lowlevel import Server

    # The HTTP door confines file output by handing `kir_compile` a policy;
    # the dispatcher stays blind to tool names, as its own comment demands.
    doors = _DOORS if compile_output_policy is None else {
        **_DOORS, "kir_compile": functools.partial(_compile, output_policy=compile_output_policy)}

    def _tool_result(body: dict, *, crashed: bool = False) -> Any:
        text = wire_json.encode(body).decode("utf-8")
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=text)],
            structuredContent=json.loads(text), isError=crashed)

    def _refused(code: str, message_ru: str, next_ru: str) -> Any:
        return _tool_result(_refusal(code, message_ru, wrote_nothing=True, effect="none",
                                     next_ru=next_ru))

    async def on_list_tools(ctx: Any, params: Any) -> Any:
        return types.ListToolsResult(
            tools=[types.Tool(name=t["name"], description=t["description"],
                              inputSchema=t["input_schema"],
                              _meta=t.get("meta"))
                   for t in surface.tools()],
        )

    # ── DOOR RESOURCES. The list lives at `served_resources()`, not here. ─────
    async def on_list_resources(ctx: Any, params: Any) -> Any:
        return types.ListResourcesResult(resources=[
            types.Resource(uri=r["uri"], name=r["name"],
                           description=r["description"], mimeType=r["mime_type"])
            for r in served_resources()])

    async def on_read_resource(ctx: Any, params: Any) -> Any:
        wanted = str(params.uri)
        for r in served_resources():
            if r["uri"] == wanted:
                return types.ReadResourceResult(contents=[
                    types.TextResourceContents(uri=r["uri"],
                                               mimeType=r["mime_type"],
                                               text=r["text"])])
        raise ValueError(f"ресурса «{wanted}» этот сервер не несёт; есть: "
                         f"{[r['uri'] for r in served_resources()]}")

    async def on_call_tool(ctx: Any, params: Any) -> Any:
        # 🔴 THE SECOND MOVE (MRTR, SEP-2322). The sessionless core of
        # 2026-07-28 stores nothing between requests, so human consent
        # rides BACK AND FORTH through `requestState`, rather than sitting
        # with this SDK handler. The live door checks the program/building
        # binding and durable operation identity separately. This protocol
        # exchange does not authenticate a human or make arbitrary client
        # assertions of consent trustworthy.
        try:
            wire_json.encode(params.model_dump(mode="json", by_alias=True))
        except (TypeError, ValueError, UnicodeError, RecursionError):
            return _refused("invalid_json_input", "вход должен быть JSON без NaN/Infinity",
                            "исправь аргументы; инструмент ещё не вызывался")
        extra: dict[str, Any] = {}
        answers = params.input_responses or {}
        if params.name in _ASKS_HUMAN and answers:
            answer = answers.get(_HUMAN_SLOT)
            action = getattr(answer, "action", None)
            content = getattr(answer, "content", None) or {}
            # `decline`/`cancel` — NOT an error and not "yes." The three
            # outcomes are distinguished because "the human declined" and
            # "the human did not answer" call for different next moves.
            # ElicitResult.content permits strings and numbers for other forms;
            # the SDK does not enforce this question's boolean schema for us.
            # In particular, bool("false") would authorize a write.
            if action not in ("accept", "decline", "cancel") or (
                    action == "accept" and type(content.get("confirm")) is not bool):
                return _refused("confirmation_type",
                                "ответ на подтверждение должен содержать boolean true или false",
                                "повторите ответ формы с правильным типом; запись ещё не вызывалась")
            extra["confirmed"] = content["confirm"] if action == "accept" else False
            try:
                extra["state"] = json.loads(params.request_state or "{}",
                                             parse_constant=wire_json.reject_constant,
                                             parse_float=wire_json.finite_float)
            except (TypeError, ValueError, UnicodeError, RecursionError):
                return _refused("invalid_json_input",
                                "состояние продолжения должно быть JSON без NaN/Infinity",
                                "исправь состояние; инструмент ещё не вызывался")

        body, crashed = await dispatch(params.name, params.arguments or {}, doors=doors, **extra)

        ask = body.get(_live.INPUT_REQUIRED) if isinstance(body, dict) else None
        if ask:
            return types.InputRequiredResult(
                inputRequests={_HUMAN_SLOT: types.ElicitRequest(
                    method="elicitation/create",
                    params=types.ElicitRequestFormParams(
                        mode="form",
                        message=ask["message"],
                        requestedSchema=ask["schema"]))},
                requestState=wire_json.encode(ask["state"]).decode("utf-8"))

        return _tool_result(body, crashed=crashed)

    server = Server(
        "kir",
        title="KIR — building graph",
        version=_version(),
        instructions=surface.instructions(),
        # The list's freshness: the argument is at TOOLS_TTL_MS.
        cache_hints={"tools/list": CacheHint(ttl_ms=TOOLS_TTL_MS,
                                             scope="public")},
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
        on_list_resources=on_list_resources,
        on_read_resource=on_read_resource,
    )
    # 🔴 THE EXTENSION IS DECLARED, NOT ASSUMED (SEP-2133): it is opt-in
    # on BOTH sides, and a host that has not seen it among the
    # capabilities will not request the document — while the tool keeps
    # working as text regardless.
    server.extensions = {_app.UI_EXTENSION_ID: {}}
    # 🔴 MRTR FIELDS ARE CHECKED AT BUILD TIME, NOT GUESSED AT CALL TIME
    # (review 02.09.2026). A lenient `getattr(params, "input_responses",
    # None)` used to stand here, and its leniency bought exactly one
    # thing: if the field were renamed in the SDK, the human's answers
    # would stop being READ, the door would return a new confirmation
    # request on every repeat, and the human would keep agreeing forever,
    # writing nothing and getting not one refusal. The absence of a
    # mechanism must be loud and happen ONCE, not quiet and on every
    # single turn.
    missing = [f for f in ("input_responses", "request_state")
               if f not in types.CallToolRequestParams.model_fields]
    if missing:
        raise RuntimeError(
            f"SDK протокола не несёт полей MRTR {missing}: подтверждение записи "
            f"человеком не сможет доехать. Проверь версию пакета `mcp`")
    return server


def build_http_app(*, token: bytes, out_root, public_origin=None):
    """Keep SDK Host/Origin/body limits and add explicit HTTP capabilities."""
    from kir.mcp.http_security import BearerTokenMiddleware, OutputRoot
    from mcp.server.transport_security import TransportSecuritySettings

    BearerTokenMiddleware.check(token)  # validate before startup, not on the first request
    server = build_server(compile_output_policy=OutputRoot(out_root))
    security = None
    if public_origin:
        from urllib.parse import urlsplit
        security = TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[urlsplit(public_origin).netloc], allowed_origins=[public_origin])
    app = server.streamable_http_app(json_response=True, transport_security=security)
    app.add_middleware(BearerTokenMiddleware, token=token, require_https=bool(public_origin))
    return app


def _version() -> str:
    try:
        from importlib.metadata import version
        return version("kir-building")
    except Exception:  # noqa: BLE001
        return "0.0.0+unknown"


async def run_stdio() -> None:
    from mcp.server.stdio import stdio_server

    server = build_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream,
                         server.create_initialization_options())


#: THE "DID NOT HAPPEN" RETURN CODE — the shape of `kir/__main__.py`,
#: word for word: 0 answered · 1 refusal ON THE MERITS · 2 did not happen.
#: Reducing the extra's absence to "1" would mean saying "the door read
#: the request and rejected it" in a case where the door never came up at
#: all.
NOT_DONE = 2

#: What the wire needs beyond the core. IMPORT names, not distribution
#: ones — and they differ: `kir-building[mcp]` is installed,
#: `mcp`/`mcp_types` is imported. A refusal naming the wrong library
#: instead of our extra sends a human off to install the wrong thing.
SDK_MODULES = ("mcp", "mcp_types")
INSTALL_EXTRA = 'pip install "kir-building[mcp]"'


def _protocol_sdk_absent(*, http: bool) -> str | None:
    """What the wire is missing — BY NAME and BEFORE the first INFO line.

    🔴 MEASURED 04.09.2026, a clean venv from the wheel, an install
    WITHOUT `[mcp]`. `python -m kir.mcp` printed two INFO lines — a list of
    seven tools and a note about the schema, that is, exactly what reads
    as a successful start — followed by a raw `ModuleNotFoundError: No
    module named 'mcp'` with sixteen frames of a foreign stack. The words
    `kir-building[mcp]` were NOT in the output ONCE; of the sixteen
    frames, thirteen belonged to anyio and asyncio, that is, they pointed
    at libraries that had nothing to do with it.

    Worse than the raw stack is the order here: the surface's list was
    printed BEFORE the crash. The door announced seven tools, not one of
    which this run would have — and on the stdio transport, the model's
    client has nothing but these lines and the return code.

    THE RETURN CODE WAS HONEST THROUGHOUT — 1, not 0: the raw stack exits
    from `sys.exit(main())` before the call, and Python exits with one.
    "Zero" in the report only appeared for a measurement THROUGH A PIPE
    (`… 2>&1 | tail`), where `$?` is the tail's code; `PIPESTATUS[0]` in
    the same run gives 1. Here it is changed to 2 not because 1 is wrong,
    but because in this tree 1 is already taken by a refusal ON THE
    MERITS.

    What is checked is PRESENCE, not import: bringing up the SDK just to
    ask "is it there" is expensive and unnecessary. Shadowing by the name
    of our own package (`kir/` landing on `sys.path` — pytest does this
    from the rootdir) is named separately: without this, a module that IS
    present would be declared missing, and a human would install what is
    already installed. The full argument is in `build_server`'s header.
    """
    import importlib.util

    здесь = pathlib.Path(__file__).resolve().parent
    # `uvicorn` arrives transitively with the same extra, but is needed
    # ONLY for `--http`: asking for it on stdio would mean refusing over
    # the absence of something this run does not use.
    нужны = SDK_MODULES + (("uvicorn",) if http else ())
    нет: list[str] = []
    for имя in нужны:
        try:
            found = importlib.util.find_spec(имя)
        except (ImportError, ValueError):
            found = None
        if found is None:
            нет.append(имя)
            continue
        origin = found.origin or ""
        if origin and pathlib.Path(origin).resolve().parent == здесь:
            return (
                f"🔴 ОТКАЗ: имя `{имя}` разрешилось в ЭТОТ пакет ({здесь}), а "
                f"не в SDK протокола. Так бывает, когда на sys.path попал сам "
                f"каталог `kir/`.\n"
                f"   СЛЕДУЮЩИЙ ХОД: убери каталог `kir/` с sys.path и "
                f"импортируй дверь как `kir.mcp`")
    if not нет:
        return None
    return (
        f"🔴 ОТКАЗ: дверь MCP не поднята — дополнение `[mcp]` не поставлено "
        f"(нет модулей: {', '.join(нет)}). Ядро KIR при этом работает: "
        f"`kir demo`, `kir build`, `kir ops`, `kir course` дополнения не "
        f"требуют.\n"
        f"   СЛЕДУЮЩИЙ ХОД: {INSTALL_EXTRA}")


def main(argv: list[str] | None = None) -> int:
    """The entry point. Logs go TO STDERR, and on the stdio transport this
    is not a matter of taste: stdout is occupied by the wire, any line of
    ours in it corrupts a JSON-RPC frame."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m kir.mcp",
        description="MCP-сервер KIR (офлайн: без Ревита и без продукта)")
    parser.add_argument("--http", action="store_true",
                        help="Streamable HTTP вместо stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--token-file", help="файл приватного HTTP-токена (либо KIR_MCP_TOKEN)")
    parser.add_argument("--allow-remote", action="store_true", help="явно разрешить сетевой HTTP bind")
    parser.add_argument("--public-origin", help="точный https origin доверенного TLS-прокси")
    parser.add_argument("--out-root", help="корень HTTP out_dir; по умолчанию текущий каталог")
    args = parser.parse_args(argv)

    logging.basicConfig(stream=sys.stderr, level=args.log_level.upper(),
                        format="%(levelname)s %(name)s: %(message)s")

    # 🔴 FIRST "WILL WE COME UP AT ALL," THEN "WHAT DO WE CARRY." The
    # surface's list is a promise, and printing it before checking the
    # wire means promising seven tools to a run that will not have one of
    # them.
    absent = _protocol_sdk_absent(http=args.http)
    if absent is not None:
        # BY PRINTING, NOT BY LOGGING: `--log-level ERROR` is a
        # legitimate choice for a client, and a refusal that can be
        # muted by a log level stops being a refusal. The stream is the
        # same (stderr): stdout is occupied by the JSON-RPC wire.
        print(absent, file=sys.stderr)
        return NOT_DONE

    http_config = None
    if args.http:
        from kir.mcp.http_security import configured_token, remote_origin, HTTPConfigurationError
        try:
            origin = remote_origin(args.host, allow_remote=args.allow_remote, public_origin=args.public_origin)
            token = configured_token(args.token_file)
            http_config = build_http_app(token=token, out_root=args.out_root or pathlib.Path.cwd(),
                                         public_origin=origin)
        except HTTPConfigurationError as failure:
            print(f"ОТКАЗ HTTP: {failure}", file=sys.stderr)
            return NOT_DONE

    logger.info("поверхность: %s", ", ".join(surface.names()))
    logger.info("схема: %s", surface.schema_note())

    if args.http:
        import uvicorn
        uvicorn.run(http_config, host=args.host,
                    port=args.port, log_level=args.log_level.lower())
        return 0

    import anyio
    anyio.run(run_stdio)
    return 0
