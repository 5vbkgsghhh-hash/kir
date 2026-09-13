"""A ROUND TRIP OF PRINTING ON REAL BUILDINGS, not on a fixture.

🔴 WHY A SEPARATE FILE. The synthetic round trip
(`test_program_source.py`) stands on six operations that I made up myself.
It proves that printing is reversible on what I imagined, and says
NOTHING about a real building: a hundred-vertex contour, an arc with
`bulge`, a curtain wall, a level with a hundred-character name, an
apartment with a reference inside — all of this only comes from the
corpus. This is exactly how the `NameError` regression was found (a
variable hidden inside a unit function's body): on `k2_ar_rd_v7` it is not
visible at all, on `sob62_fas_r23_v19` it was crashing two of four
levels.

THE WINDOW IS NAMED (form 28): every run reads the CORPUS ON DISK RIGHT
NOW and remembers nothing between runs.

IF THE CORPUS IS ABSENT — THIS IS A SKIP WITH A NAMED ADDRESS, not a
green test. The corpus is machine-local: `backend/data/decompile` is an
artifact of this particular workstation, and its absence is not a defect.
But "the instrument did not run" and "the instrument showed zero" are
different facts, and the reader must tell them apart.
"""
from __future__ import annotations

import json
import os

import pytest

from kir.decompile import program_source as ps
from kir.decompile.materialize import leaves_to_program

#: The machine-local store of parses. The path is named in full precisely
#: so that a skip is a work order, not an excuse.
CORPUS = os.environ.get(
    "KIR_DECOMPILE_CORPUS",
    "/opt/kukai-rebuild1/backend/backend/data/decompile")

#: The buildings were chosen DELIBERATELY DIVERSE, and each one was
#: bought for its own property:
#:
#: * `sob62_fas_r23_v19` — a facade building, where a reference ENTERS a
#:   semantic unit. Without it the whole "the function hid the variable"
#:   defect class is invisible;
#: * `sklnk_eom_r26_v8` — electrical: a different set of ops, different
#:   levels;
#: * `snowdon_plumb_v3` — plumbing: a level with not a single wall (the
#:   first version of the control looked for `create_wall` and on such a
#:   building found NOTHING, reporting "matched").
#:
#: The list is CLOSED, BUT NOT COMPLETE: this is a sample, not a census of
#: the corpus. A building whose property is not named here guards
#: nothing.
BUILDINGS = ("sob62_fas_r23_v19", "sklnk_eom_r26_v8", "snowdon_plumb_v3")

#: How many of the most populated levels to take from each building. More
#: means slower, and a full corpus run lives in the instrument, not in
#: the test suite.
FLOORS_PER_BUILDING = 2

#: The sample's power, without which this file guards nothing (canon: a
#: control on a degenerate input is green by construction). The numbers
#: come from a measurement on 17.08.2026 on these three buildings: 6
#: levels, 2874 operations, and at least one level where a reference
#: enters a unit.
MIN_FLOORS = 4
MIN_OPS = 1000


def _require_corpus() -> None:
    if not os.path.isdir(CORPUS):
        pytest.skip("КОРПУСА РАЗБОРОВ НЕТ: %s — прибор НЕ ЗАПУСКАЛСЯ, это не "
                    "«ноль расхождений». Переопределяется "
                    "KIR_DECOMPILE_CORPUS." % CORPUS)


def _tree(run: str) -> dict:
    from kir.decompile.snapshot_io import (
        open_snapshot, snapshot_file_exists)
    path = os.path.join(CORPUS, run, "tree.json")
    if not snapshot_file_exists(path):
        pytest.skip("разбора %s нет на этой машине (%s)" % (run, path))
    with open_snapshot(path, "rt", encoding="utf-8", touch=False) as handle:
        return json.load(handle)


def _type_names(run: str) -> dict:
    """Type names from the parse profile. No profile — EMPTY, and this is
    visible.

    An empty map does not break printing: the selector stays the source
    one, and the constant is marked «?? имени в профиле нет». Silently
    substituting a name would be worse than having no name.
    """

    # THE VARIABLE NAME IS DELIBERATELY KEPT SEPARATE. The profile is NOT
    # a compressible artifact, but earlier in this file `path` held
    # `tree.json`, and the guard `test_snapshot_existence_is_asked`
    # (tracking a variable without accounting for reassignment) was
    # blaming this line for checking the tree. The false alarm is not
    # cured by an exemption tag but by not letting two different things be
    # called by one name.
    profile_path = os.path.join(CORPUS, run, "open_model.profile.json")
    if not os.path.exists(profile_path):
        return {}
    with open(profile_path, encoding="utf-8") as handle:
        profile = json.load(handle)
    out: dict[int, str] = {}
    for pool in (profile.get("pools") or ()):
        for row in (pool.get("entries") or ()):
            eid = row.get("element_id")
            if eid is None:
                continue
            label = row.get("name") or row.get("type_name")
            family = row.get("family_name")
            if family and label and family != label:
                label = "%s / %s" % (family, label)
            if label:
                out[int(eid)] = str(label)
    return out


def _floors(tree: dict) -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []

    def walk(node: object) -> None:
        if not isinstance(node, dict):
            return
        macro = node.get("macro")
        if isinstance(macro, dict) and macro.get("type") == "floor":
            out.append((str(macro.get("level_name")), node))
        for child in (node.get("children") or ()):
            walk(child)

    walk(tree)
    return out


def _richest_floors(tree: dict, count: int) -> list[tuple[str, dict]]:
    scored = [(len(ps.floor_leaves(node)), level, node)
              for level, node in _floors(tree)]
    scored.sort(key=lambda row: (-row[0], row[1]))
    return [(level, node) for size, level, node in scored[:count] if size]


def _render(run: str, level: str, node: dict):
    leaves = ps.floor_leaves(node)
    units = ps.floor_units(node)
    result = leaves_to_program(leaves)
    rendering = ps.source_from_materialized(
        result, level=level, run=run, type_names=_type_names(run), units=units)
    source_ops = [op for program in result.programs
                  for op in (program.get("ops") or ())]
    return rendering, source_ops


def test_round_trip_converges_on_real_buildings() -> None:
    """A printed level, once EXECUTED, produces the SAME operations."""

    _require_corpus()
    floors = 0
    ops = 0
    linked_out_floors = 0
    empty = 0
    for run in BUILDINGS:
        tree = _tree(run)
        for level, node in _richest_floors(tree, FLOORS_PER_BUILDING):
            rendering, source_ops = _render(run, level, node)
            if rendering.empty:
                # The materializer produced not a single program. A round
                # trip over zero operations is green by construction and
                # does NOT count.
                empty += 1
                continue
            assert rendering.ok, "%s/%s: %s" % (run, level,
                                                rendering.report_ru())
            verdict = ps.round_trip(rendering, source_ops)
            assert verdict.ok, "%s/%s: %s" % (run, level, verdict.report_ru())
            floors += 1
            ops += rendering.ops_printed
            if any(part.units_linked_out for part in rendering.parts):
                linked_out_floors += 1

    assert floors >= MIN_FLOORS, (
        "выборка выродилась: этажей %d при пороге %d (пусто: %d). Зелёный на "
        "такой выборке ничего не доказывает" % (floors, MIN_FLOORS, empty))
    assert ops >= MIN_OPS, "операций %d при пороге %d" % (ops, MIN_OPS)
    assert linked_out_floors >= 1, (
        "ни на одном этаже ссылка не входит в семантическую единицу — значит "
        "класс дефекта «функция спрятала переменную» этой выборкой НЕ "
        "СТОРОЖИТСЯ, и зелёный тут ничего о нём не говорит")


def test_control_fail_on_a_real_floor_reddens_exactly_one_op() -> None:
    """One corrupted value on a REAL level — one red operation.

    A probe must be able to fail: if there is nothing to corrupt, that is
    a FAILURE of the probe, not a "match". This is exactly what burned
    the first version of the control in the bench — it looked for
    `create_wall` and on the plumbing building (zero walls) silently
    reported success.
    """

    _require_corpus()
    run = BUILDINGS[0]
    tree = _tree(run)
    picked = _richest_floors(tree, 1)
    assert picked, "у %s нет ни одного наполненного этажа" % run
    level, node = picked[0]
    rendering, source_ops = _render(run, level, node)
    assert rendering.ok and not rendering.empty, rendering.report_ru()

    # 🔴 ALL OF A LEVEL'S PROGRAMS ARE EXECUTED, NOT JUST ONE. The first
    # version of this probe corrupted the text of the first program and
    # checked the result of ONE program against the operations of THE
    # WHOLE level — and got "974 lost" on a printer that was actually
    # correct. The broad reddening looked like the instrument's
    # sensitivity, but it was a denominator miss.
    texts = [part.text for part in rendering.parts]

    # The victim is found BY THE LINE'S SHAPE, not by the op's name:
    # `id="..."` exists on every operation, whatever the building, while
    # `create_wall` does not (the plumbing building has zero walls).
    victim_part = victim_line = None
    for part_index, text in enumerate(texts):
        for index, line in enumerate(text.splitlines()):
            body = line.lstrip()
            if body.startswith(("create_", "place_family(", "route_")) \
                    and 'id="' in body and body.rstrip().endswith(")") \
                    and _has_number(body):
                victim_part, victim_line = part_index, index
                break
        if victim_part is not None:
            break
    assert victim_part is not None, (
        "🔴 КОНТРОЛЬ НЕ СОСТОЯЛСЯ: не нашлось строки-операции с числом, "
        "которое можно испортить. Это ОТКАЗ пробы, а не «сошлось»")

    lines = texts[victim_part].splitlines()
    original = lines[victim_line]
    lines[victim_line] = _bend_one_number(original)
    assert lines[victim_line] != original, "проба ничего не изменила"
    texts[victim_part] = "\n".join(lines) + "\n"

    executed: list = []
    for text in texts:
        one = ps.execute_source(text)
        assert not isinstance(one, str), one
        executed.extend(one.get("ops") or ())
    verdict = ps.compare_ops(source_ops, executed)

    assert not verdict.ok, "испорченная величина обязана покраснеть"
    assert verdict.source_ops == verdict.executed_ops, \
        "операция не должна была ПРОПАСТЬ — испорчена одна величина"
    assert sum(count for _key, count in verdict.lost) == 1, (
        "покраснеть обязана ОДНА операция, а не пачка: %s"
        % verdict.report_ru())
    assert sum(count for _key, count in verdict.extra) == 1, verdict.report_ru()
    assert verdict.lost[0][0].split("|")[0] == verdict.extra[0][0].split("|")[0], \
        "потеря и лишнее обязаны быть ОДНИМ и тем же опом"


def test_the_printed_source_survives_the_real_sandbox() -> None:
    """🔴 A BOUNDARY THAT TESTS USUALLY WALK AROUND IS CROSSED HERE IN
    FULL.

    The NAKAZ's canon, clause 5: "every boundary that tests walk around is
    a boundary where two greens diverge". `execute_source` puts the
    course's names straight into a dict and runs `exec` in this very
    process; the MODEL, however, receives text through
    `sandbox.execute_author_script` — a fork, an RLIMIT, an import guard,
    ceilings on source size and operation count. The unit-of-intent
    predicate had already been green across 229 tests and was completely
    broken through the real door for the simple reason that the tests
    never went through the sandbox.

    Measurement on 17.08.2026 (`sob62_fas_r23_v19`, the largest level,
    1224 operations in 5 programs): the sandbox took ALL five, returned
    1224 operations, 0 discrepancies, 1.1 s for all five. Texts of 51–64
    KB against a `MAX_SOURCE_BYTES` ceiling of 262 144 B and
    `MAX_SCRIPT_OPS` of 5000 — a fourfold margin by size and a
    sixteenfold margin by operations.

    Here ONE program is run: a proof of the same kind as the five, while
    a fork per program costs dialing time.
    """

    _require_corpus()
    from kir import sandbox

    run = BUILDINGS[0]
    picked = _richest_floors(_tree(run), 1)
    assert picked, "у %s нет ни одного наполненного этажа" % run
    level, node = picked[0]
    rendering, _source_ops = _render(run, level, node)
    assert rendering.ok and not rendering.empty, rendering.report_ru()

    part = rendering.parts[0]
    assert len(part.text.encode("utf-8")) < sandbox.MAX_SOURCE_BYTES, (
        "исходник %d Б при потолке песочницы %d — печать перестала пролезать "
        "в настоящую дверь" % (len(part.text.encode("utf-8")),
                               sandbox.MAX_SOURCE_BYTES))

    result = sandbox.execute_author_script(part.text,
                                           policy=sandbox.SandboxPolicy())
    assert result.ok, "песочница отказала: %s" % (result.refusal,)
    assert len(result.ops or ()) == part.ops, (
        "песочница вернула %d операций против %d напечатанных"
        % (len(result.ops or ()), part.ops))

    program_ops = [op for program in leaves_to_program(
        ps.floor_leaves(node)).programs
        for op in (program.get("ops") or ())]
    subset = [op for op in program_ops
              if op["id"] in {o["id"] for o in (result.ops or ())}]
    verdict = ps.compare_ops(subset, result.ops or ())
    assert verdict.ok, verdict.report_ru()


def test_the_rounding_the_round_trip_cannot_see_is_bounded_and_measured() -> None:
    """🔴 WHAT THE ROUND TRIP DOES NOT PROVE — AND THIS IS PINNED
    SEPARATELY.

    The check canonicalizes BOTH sides with the same `_round_by_kind`
    that printing uses. So a wrong rounding rule CANCELS ITSELF OUT in
    the round trip: corrupt it, and all 26 tests stay green (checked by
    mutation on 17.08.2026: swapping the authority for the name's suffix
    reddened NOTHING). The round trip proves "the same operations UP TO
    rounding by the registry's kind", and this has to be said out loud,
    not implied.

    So the tolerance is measured DIRECTLY and bounded: rounding to a
    millimeter has no right to move a value by more than 0.5 mm. Widen
    the grain to a centimeter — it will go red here, while the round trip
    will never notice.

    And the probe has a named POWER: if not a single value moved at all,
    there was nothing to measure and green means nothing.
    """

    _require_corpus()
    kinds = ps.param_kinds()
    moved = 0
    worst = 0.0
    checked = 0
    for run in BUILDINGS:
        tree = _tree(run)
        for level, node in _richest_floors(tree, 1):
            result = leaves_to_program(ps.floor_leaves(node))
            for program in result.programs:
                for op in (program.get("ops") or ()):
                    name = op.get("op")
                    for key, value in op.items():
                        if key in ("op", "id"):
                            continue
                        if kinds.get((name, key)) not in ps.MM_KINDS:
                            continue
                        for before, after in _pairs(
                                value, ps._round_by_kind(name, key, value,
                                                         kinds)):
                            checked += 1
                            delta = abs(before - after)
                            worst = max(worst, delta)
                            if delta:
                                moved += 1

    assert checked > 0, "миллиметровых величин не нашлось — проба вырождена"
    assert moved > 0, (
        "округление не сдвинуло НИ ОДНОЙ величины из %d: допуск не измерен, "
        "зелёный по построению" % checked)
    assert worst <= 0.5, (
        "округление сдвинуло величину на %.4f мм — это больше половины "
        "миллиметра, то есть зерно уже не миллиметровое" % worst)


def _pairs(before: object, after: object):
    """"Before/after" pairs matched by the same shape. Shapes diverge — we stay silent."""

    if isinstance(before, bool) or isinstance(after, bool):
        return
    if isinstance(before, (int, float)) and isinstance(after, (int, float)):
        yield float(before), float(after)
    elif isinstance(before, list) and isinstance(after, list) \
            and len(before) == len(after):
        for one, two in zip(before, after):
            yield from _pairs(one, two)
    elif isinstance(before, dict) and isinstance(after, dict):
        for key in before:
            if key in after and key not in ps.FREE_KEYS:
                yield from _pairs(before[key], after[key])


#: A numeric value in a printed line: `p0_mm=[123, …`, `offset_mm=900)`.
#: Numbers inside `by_element_id(…)` are deliberately NOT touched — this
#: is a type address, and swapping the address also changes the reference
#: to it, meaning it would go red beyond a single line.
_NUMBER = __import__("re").compile(r"[=\[,]\s*(-?\d+)(?=[,)\]])")


def _has_number(line: str) -> bool:
    return _NUMBER.search(line.split("id=")[0]) is not None


def _bend_one_number(line: str) -> str:
    """Shift EXACTLY one number of a line by 7 mm. None found — the probe fails."""

    head = line.split("id=")[0]
    match = _NUMBER.search(head)
    assert match, "🔴 в строке-жертве нет ни одного числа: %s" % line[:120]
    bent = str(int(match.group(1)) + 7)
    return line[:match.start(1)] + bent + line[match.end(1):]
