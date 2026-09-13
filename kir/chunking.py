"""FORWARD-PATH CHUNKING — an author's program that does not fit into one bridge frame.

WHY THIS FILE APPEARED ON 20.08.2026. The owner raised the authoring budget
from 1000 to 100 000 operations, saying "so that this stops coming up
again." Raising the NUMBER did not grant the capability: the same day's
measurement showed that emission is linear while the websocket frame is
finite.

    ops     compile   C# MB   peak RSS MB
     1000       1.0 s      3.4          69
     5000       5.0 s     16.9         222
    20000      20.8 s     68.0         830
   100000     101   s    343         3723

That is, behind the 1000-operation limit stood not a budget but an UNNAMED
transport wall, and by raising the budget we merely moved the author from an
understandable refusal, `KIR-L001`, to a dropped connection. There is no size
guard on the bridge at all (verified: not a single length check in
`bridge_protocol`/`chat_ws`).

═══════════════════════════════════════════════════════════════════════════════
WHY THE FORWARD PATH CHUNKS MORE EASILY THAN THE REVERSE ONE — AND THIS IS NOT
LAZINESS, IT IS A LAW OF THE LANGUAGE
═══════════════════════════════════════════════════════════════════════════════

The reverse path (`decompile/materialize.py`, law D5a) has no right to tear a
`ref` apart, so its indivisible unit is a CONNECTED COMPONENT of the
reference graph. This law is useless on an author's program: twenty thousand
walls referencing a single `create_level` are one component, with nothing to
divide.

The forward path does NOT NEED this law, because in an author's program a
reference is ALWAYS BACKWARD. This is not a convention but a property by
construction, and it is recorded in three independent places in the tree:

    relate.py:1343            «an addressed op must be EARLIER than the one addressing it»
    ground.py:1029            «a forward reference is not found BY CONSTRUCTION»
    authoring_validation.py   «a backward reference passes, a forward reference is refused»

From this follows this file's law, one and short: **A CHUNK IS A CONTIGUOUS
SLICE IN AUTHORING ORDER.** Every reference is then either inside the chunk,
or backward — into a chunk that has ALREADY BEEN EXECUTED, meaning its
elements are known from the receipt's `element_map` and are substituted in
place of the `ref` (see :func:`bind_refs`).

This file has NO RIGHT to reorder operations. Order is part of the author's
intent: it is the author who decides what gets built first, and Revit is not
always indifferent to order (a room requires walls that already stand).
Topological sorting of the reverse path is legitimate where order was
produced by the parse; here it was written by a human.

═══════════════════════════════════════════════════════════════════════════════
🔴 ATOMICITY IS WEAKENED, AND THIS IS NAMED, NOT HIDDEN
═══════════════════════════════════════════════════════════════════════════════

Today the program is ONE transaction: the failure of any operation rolls
everything back. Split into N chunks, it becomes N transactions, and the
prior property CANNOT be preserved: a Revit transaction lives inside a
single C# execution and does not survive a round trip across the bridge.
`TransactionGroup` does not change this either — it lives in the same place.

So the choice was between staying silent and saying so, and it is said:
:class:`ChunkPlan` carries ``atomicity="per_chunk"`` and
``atomicity_note_ru``, which are obligated to reach the receipt. A failure on
chunk k means that chunks 1..k-1 are ALREADY IN THE MODEL; their elements are
listed, and based on them the author either continues or cleans up after
themselves. A silent "built halfway" is the worst outcome this compiler
allows, and here it is forbidden by the field's very name.

THIS IS WHY CHUNKING DOES NOT TURN ITSELF ON. A program that fits in the
frame runs exactly as before, as one transaction, byte for byte. A plan is
built only when one is NEEDED, and then the weakening of atomicity is a
deliberate price for something that would otherwise not get built at all.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from kir import spec

#: The live service's websocket frame: `uvicorn` without `--ws-max-size`
#: holds 16 MB. Verified 20.08.2026 by reading the unit
#: (`systemctl cat kukai-backend`): the flag is not there, so the default
#: applies.
FRAME_BYTES = 16 * 1024 * 1024

#: The share of the frame given to the USEFUL PAYLOAD. Not "just in case":
#: the body is encrypted and travels as base64, and base64 grows the volume
#: by exactly a third (4/3), with the envelope's headers on top. 0.5 leaves
#: headroom both for those and for the spread in the estimate below — the
#: estimated cost of an operation is APPROXIMATE, and a miss in it is
#: obligated to cost an extra chunk, not a dropped connection.
#:
#: THE ESTIMATE'S MISS IS MEASURED, NOT DECLARED "SMALL" (20.08.2026, the
#: plan checked against the actual compilation of EVERY chunk):
#:
#:     walls          budget 8.0 MB -> actual 8.2 MB   underestimate 2.5%
#:     surfaces       budget 8.0 MB -> actual 8.5 MB   underestimate 6.2%
#:
#: Both fit within the frame twice over. If some kind of operation ever
#: underestimates by a FACTOR OF TWO, the 0.5 share will stop saving it —
#: and the cure then is not "raise the share" but to MEASURE that kind and
#: add it to the table below.
FRAME_PAYLOAD_SHARE = 0.5

#: How many bytes of C# one operation gives birth to. MEASURED 20.08.2026 by
#: the difference between two compilations (10 ops versus 210), Revit 2026:
#:
#:     create_wall               3 492 B/op     4 803 ops per 16 MB
#:     create_floor_by_contour   6 977 B/op     2 404
#:     create_surface           11 005 B/op     1 524
#:
#: A THREEFOLD spread — this is exactly why chunking by the COUNT of
#: operations does not work: a chunk of 2000 walls fits, while one of 2000
#: surfaces exceeds the frame fourfold.
#:
#: 🔴 THE LIST IS CLOSED AND INCOMPLETE — like every such list in this tree.
#: An empty cell means "this kind is not measured," not "it is cheap," and so
#: an unmeasured kind is charged at the MOST EXPENSIVE of the known ones (see
#: `cost_of`). The error then always runs toward an extra chunk, not toward a
#: dropped connection.
MEASURED_BYTES_PER_OP: dict[str, int] = {
    "create_wall": 3_492,
    "create_floor_by_contour": 6_977,
    "create_surface": 11_005,
}

#: What an operation of an unknown kind is charged as. The maximum of what
#: was measured, not the average: the average errs in both directions, the
#: maximum only in the safe one.
UNKNOWN_OP_BYTES = max(MEASURED_BYTES_PER_OP.values())

#: 🔴 KINDS WHOSE COST IS SET BY CONTENT, NOT BY NAME (29.08.2026, audit
#: finding F-332). A flat price by name underestimated `create_directshape`
#: by a factor of 30.4: 38 legitimate ops with a mesh of maximum size yield
#: 12 710 386 bytes of C#, that is, 16 947 184 after base64 — 169 968 MORE
#: than the frame, against a plan estimate of 418 190 and ONE chunk. For a
#: human this is not "an extra chunk" but a DROPPED CONNECTION instead of a
#: named refusal.
#:
#: MEASURED BY THE SAME METHOD AS THE TABLE ABOVE — the difference between
#: two compilations (10 ops at rim=100 versus 10 ops at rim=4095), Revit
#: 2026:
#:
#:     verts+tris        C# per op     formula        miss
#:            21           9 048         8 735         -3.5%
#:           201          16 709        16 709          0.0%
#:          1001          51 565        52 152         +1.1%
#:          2001          95 091        96 456         +1.4%
#:          4001         184 199       185 064         +0.5%
#:          8191         370 698       370 698          0.0%
#:
#: That is, the cost is LINEAR in the number of vertices and triangles with a
#: miss of ≤3.5% over a 400-fold range — enough for the miss to cost an
#: extra chunk, not a drop (the `FRAME_PAYLOAD_SHARE` condition).
DIRECTSHAPE_BASE_BYTES = 7_804
DIRECTSHAPE_BYTES_PER_MESH_ITEM = 45   # rounded UP from the measured 44.30

#: 🔴 GROUP OVERHEAD ON TOP OF THE MEMBERS' SUM (29.08.2026, audit finding
#: F-322). `create_group` legitimately carries 1..1000 members
#: (`spec.GROUP_MEMBERS_MAX`), and `_emit_group` calls the emitter for EVERY
#: ONE of them. A flat price by name gave 11 005 bytes for a group that
#: actually prints 14 583 587 — an underestimate by a factor of 1325, and
#: chunking was declaring such a program "fitting in the frame."
#:
#: Measured by difference: a group of 10 surfaces prints 152 024 bytes of
#: C#, one of 200 prints 2 861 416. The same member OUTSIDE a group costs
#: 11 005 (table above), inside — 15 202 and 14 307 respectively. The
#: difference is the member's wrapper (`{oid}__m__{id}`, the read-back,
#: the witness), and it is LINEAR in the number of members, not constant.
#: The coefficient is rounded UP from the measured 1.38 — a ceiling, not an
#: average: the same discipline as with `UNKNOWN_OP_BYTES`.
GROUP_MEMBER_OVERHEAD = 1.4
#: The group's own constant part (NewGroup plus PlaceGroup for placement).
GROUP_BASE_BYTES = 11_005

#: Ops that live by their own program (KIR-L002: `StairsEditScope` owns its
#: own transactions). The list is taken from the registry, not
#: retranscribed: two tables that are obligated to match drift apart
#: silently.
SOLO_OPS = frozenset(spec.SOLO_OPS)

#: A single op that already does not fit. A separate code, because the cure
#: is different: there is nothing to split, the author is obligated to
#: simplify the operation itself.
CHUNK_OP_TOO_BIG = "KIR-K001"


class ChunkTooBig(Exception):
    """A single operation does not fit in the frame — there is nothing to split."""


@dataclass(frozen=True)
class Chunk:
    """A contiguous slice of the program plus everything known about it in advance."""

    index: int
    ops: tuple[dict, ...]
    est_bytes: int
    #: The op identifiers of THIS chunk — `bind_refs` uses them to
    #: distinguish an internal reference from a backward one.
    op_ids: frozenset[str]
    #: The op identifiers FROM PRIOR chunks that this one references. An
    #: empty set means "the chunk is self-sufficient," and this is a
    #: VERIFIABLE assertion, not a hope.
    needs: tuple[str, ...]
    #: Why the chunk ended here. Read by a human in the receipt.
    reason: str


@dataclass(frozen=True)
class ChunkPlan:
    chunks: tuple[Chunk, ...]
    atomicity: str
    atomicity_note_ru: str
    est_bytes_total: int
    budget_bytes: int

    @property
    def split(self) -> bool:
        """Whether splitting was needed. One chunk — the prior behavior, byte for byte."""
        return len(self.chunks) > 1


def cost_of(op: Mapping[str, Any]) -> int:
    """How many bytes of C# are expected from one operation.

    AN ESTIMATE, NOT A MEASUREMENT, and named so deliberately: only the
    emitter knows the exact cost, and calling it for every operation just
    for planning purposes would mean compiling the program twice. A miss in
    the estimate costs an extra chunk — a price chosen deliberately (see
    `FRAME_PAYLOAD_SHARE`).

    🔴 BUT THE OP'S NAME IS NOT ALWAYS ENOUGH, AND THIS IS MEASURED (F-332,
    F-322). For kinds that carry an ARRAY, the size is set by the content:
    one `create_directshape` costs anywhere from 9 048 to 370 698 bytes
    under the very same name, while a `create_group` of 1000 members prints
    14 583 587 at a flat price of 11 005. So such a kind is asked BY
    CONTENT, and the list of such kinds is CLOSED: not "guess from the
    dictionary's shape," but name them by name where the price has been
    MEASURED. Guessing by the dictionary's shape would set up a SECOND
    carrier of knowledge about the operations' shape, and it would drift
    apart from the registry on the very first op where a list of short
    flags has no effect on size.

    🔴 A COMPOSITE OPERATION IS CHARGED BY ITS COMPOSITION (F-322). Recursion
    over members is safe BY THE REGISTRY'S LAW, not by hope: a group inside
    a group is illegal (`authoring_validation` rejects `mop ==
    "create_group"` among members), so the depth is exactly 1. If this ban
    is ever lifted, the recursion will remain correct but will need a depth
    limiter.
    """
    name = str(op.get("op")) if isinstance(op, Mapping) else ""
    if name == "create_group":
        members = op.get("members")
        inner = 0
        if isinstance(members, (list, tuple)):
            for member in members:
                inner += (cost_of(member) if isinstance(member, Mapping)
                          else UNKNOWN_OP_BYTES)
        places = op.get("placements")
        n_place = len(places) if isinstance(places, (list, tuple)) else 1
        return (GROUP_BASE_BYTES
                + int(inner * GROUP_MEMBER_OVERHEAD)
                + GROUP_BASE_BYTES * max(0, n_place - 1))
    if name == "create_directshape":
        mesh = op.get("mesh")
        if isinstance(mesh, Mapping):
            verts = mesh.get("vertices_mm")
            tris = mesh.get("triangles")
            items = ((len(verts) if isinstance(verts, (list, tuple)) else 0)
                     + (len(tris) if isinstance(tris, (list, tuple)) else 0))
            return (DIRECTSHAPE_BASE_BYTES
                    + DIRECTSHAPE_BYTES_PER_MESH_ITEM * items)
        # A mesh in the wrong shape is the validator's concern, not the
        # planner's. Here such an op is charged as the MOST EXPENSIVE, like
        # any unmeasured one.
        return UNKNOWN_OP_BYTES
    return MEASURED_BYTES_PER_OP.get(name, UNKNOWN_OP_BYTES)


def _refs_of(value: Any, out: set) -> None:
    """Every `{"by": "ref", "value": ...}` inside the value, at any depth.

    The traversal is recursive because the selector lives both in a
    top-level field (`level`), inside a list (`members`), and inside a
    nested dictionary (`host`). Asking by field names would mean setting up
    a second carrier of knowledge about the selector's shape.
    """
    if isinstance(value, Mapping):
        if value.get("by") == "ref" and isinstance(value.get("value"), str):
            out.add(value["value"])
        for item in value.values():
            _refs_of(item, out)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _refs_of(item, out)


def refs_of_op(op: Mapping[str, Any]) -> frozenset[str]:
    out: set = set()
    _refs_of(op, out)
    return frozenset(out)


def plan_chunks(ops: Sequence[Mapping[str, Any]], *,
                frame_bytes: int = FRAME_BYTES,
                payload_share: float = FRAME_PAYLOAD_SHARE) -> ChunkPlan:
    """Split the program into contiguous slices that fit in the frame.

    The order of operations is PRESERVED EXACTLY — see the header. A chunk
    is closed when the next operation does not fit by estimate, or when a
    solo op is encountered.
    """
    budget = int(frame_bytes * payload_share)
    chunks: list[Chunk] = []
    current: list[dict] = []
    current_bytes = 0
    seen_ids: set = set()          # ops of ALL prior chunks
    total = 0

    def close(reason: str) -> None:
        nonlocal current, current_bytes
        if not current:
            return
        ids = frozenset(str(o.get("id")) for o in current if o.get("id") is not None)
        needs: set = set()
        for o in current:
            needs |= (refs_of_op(o) - ids)
        chunks.append(Chunk(
            index=len(chunks), ops=tuple(current), est_bytes=current_bytes,
            op_ids=ids, needs=tuple(sorted(needs)), reason=reason))
        seen_ids.update(ids)
        current = []
        current_bytes = 0

    for op in ops:
        size = cost_of(op)
        total += size
        if size > budget:
            # 🔴 THE ADVICE IS OBLIGATED TO FIT THE KIND (F-322). "Thin out
            # the mesh" means nothing for a group: its size is set by the
            # NUMBER OF MEMBERS, and the cure is to split the group, not to
            # simplify the geometry.
            members_here = (len(op.get("members") or ())
                            if str(op.get("op")) == "create_group" else 0)
            advice = (f"в группе {members_here} членов — раздели её на "
                      f"несколько групп поменьше"
                      if members_here else
                      "упрости саму операцию (реже сетка, меньше контрольных "
                      "точек, короче путь)")
            raise ChunkTooBig(
                f"{CHUNK_OP_TOO_BIG}: операция {op.get('op')!r} (id "
                f"{op.get('id')!r}) оценивается в {size} байт C# при бюджете "
                f"чанка {budget}. Делить нечего — {advice}")
        solo = str(op.get("op")) in SOLO_OPS
        if solo:
            close("следующая операция живёт своей программой")
            chunks_before = len(chunks)
            current = [dict(op)]
            current_bytes = size
            close(f"{op.get('op')} — соло-оп (KIR-L002: свои транзакции)")
            assert len(chunks) == chunks_before + 1
            continue
        if current and current_bytes + size > budget:
            close(f"следующая операция не влезала: {current_bytes} + {size} "
                  f"> {budget}")
        current.append(dict(op))
        current_bytes += size

    close("конец программы")

    note = (
        "программа разбита на несколько транзакций: отказ на чанке k означает, "
        "что чанки 1..k-1 УЖЕ В МОДЕЛИ. Прежней атомарности «всё или ничего» "
        "здесь нет и быть не может: транзакция Revit не переживает обмен с "
        "мостом. Элементы построенных чанков перечислены в квитанции — по ним "
        "продолжают либо убирают за собой"
        if len(chunks) > 1 else
        "программа влезла в один кадр: одна транзакция, поведение прежнее"
    )
    return ChunkPlan(
        chunks=tuple(chunks),
        atomicity="per_chunk" if len(chunks) > 1 else "whole_program",
        atomicity_note_ru=note,
        est_bytes_total=total,
        budget_bytes=budget,
    )


def bind_refs(chunk: Chunk, element_map: Mapping[str, Any]) -> list[dict]:
    """Replace BACKWARD references with the `element_id` from prior chunks' receipts.

    `element_map` is the same field the receipt already prints: an op's
    name -> the list of identifiers of the elements it built.

    🔴 AN OP THAT BUILT MORE THAN ONE ELEMENT CANNOT BE ADDRESSED BY A
    REFERENCE. A macro (`series`) expands into many elements, and "take the
    first one" would be making a choice on the author's behalf — exactly
    what this compiler forbids: a silent `.FirstOrDefault()`. Such a
    reference crossing a chunk boundary refuses, by name.
    """
    missing = [name for name in chunk.needs if name not in element_map]
    if missing:
        raise KeyError(
            f"чанк {chunk.index} ссылается на {missing}, но квитанции прошлых "
            f"чанков их не содержат — порядок исполнения нарушен")

    resolved: dict[str, str] = {}
    for name in chunk.needs:
        ids = element_map[name]
        ids = list(ids) if isinstance(ids, (list, tuple)) else [ids]
        if len(ids) != 1:
            raise ValueError(
                f"ссылка через границу чанка на {name!r}: оп построил "
                f"{len(ids)} элементов, а ссылка адресует один. Выбрать за "
                f"автора нельзя — держи такой оп и его читателей в ОДНОМ "
                f"чанке либо адресуй элемент явно по element_id")
        resolved[name] = str(ids[0])

    def rewrite(value: Any, *, frozen: bool = False) -> Any:
        if isinstance(value, Mapping):
            if (value.get("by") == "ref"
                    and value.get("value") in resolved):
                if frozen:
                    raise ValueError(
                        f"чанк {chunk.index}: ссылка на {value['value']!r} "
                        f"стоит внутри АДРЕСА ОТ ЭЛЕМЕНТА (`at_element`), а "
                        f"адресуемый оп остался в прошлом чанке. Переписать "
                        f"её в element_id нельзя: грамматика адреса "
                        f"(`relate`) принимает в `at_element` ТОЛЬКО "
                        f"{{\"by\": \"ref\"}} на оп ЭТОЙ ЖЕ программы, и "
                        f"переписанная ссылка получила бы KIR-T001 на "
                        f"зависимости, которая была верна. Дело не в "
                        f"придирчивости грамматики: адрес от элемента читает "
                        f"ЧИСЛА, написанные адресуемым опом (его точки и "
                        f"отметки), а не идентификатор построенного элемента — "
                        f"в другом чанке этих чисел нет вовсе, и дочитывать "
                        f"их из модели запрещено. СЛЕДУЮЩИЙ ХОД: держи "
                        f"адресуемый оп и его читателя в ОДНОМ чанке (они "
                        f"стоят рядом — раздели программу выше или ниже пары) "
                        f"либо задай точку литералом [x, y]")
                return {"by": "element_id",
                        "value": int(resolved[value["value"]])}
            # 🔴 THE CENSUS IS OBLIGATED TO KNOW WHICH NODES DO NOT BELONG TO
            # IT. `at_element` is, as of today, the only node with a CLOSED
            # selector shape (`relate._validate_element_address`:
            # `set(sel) == {"by","value"} and sel["by"] == "ref"`), and
            # "rewrite any {"by":"ref"} at any depth" was driving straight
            # into it silently. Measurement of 04.09.2026: the legitimate
            # address `{"at_element": {"by":"ref", "value":"W1"},
            # "point":"end"}` turned, after splitting, into
            # `{"at_element": {"by":"element_id","value":777}, ...}` and got
            # KIR-T001 — that is, chunking WAS ITSELF making a valid program
            # illegal. Here the node is flagged, and the refusal comes from
            # above, BY NAME.
            return {k: rewrite(v, frozen=(k == "at_element"))
                    for k, v in value.items()}
        if isinstance(value, list):
            return [rewrite(v, frozen=frozen) for v in value]
        return value

    return [rewrite(dict(op)) for op in chunk.ops]
