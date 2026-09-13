"""§18.3: a witness must read THE VERY AXIS it signs.

The violation's axis is not a message decoration but a machine fact:
`serving.py` splits the `geometry_ok/topology_ok/semantic_ok` triple exactly
along the substrings `(geometry)` / `(topology)` in the violation text. So a
check that reads back a PARAMETER it wrote itself, yet signs as
`(geometry)`, forces the consumer to read "geometry proven" where nobody
ever measured any geometry.

This is exactly what happened with `create_wall.location_line`: the emitter
set `WALL_KEY_REF_PARAM`, the witness read its ordinal back, and the result
went onto the geometry axis. A live measurement on 07.28
(`docs/2026-07-28-location-line-measurement.md`) showed that this parameter
does not move the wall's body AT ALL — neither for our walls nor for the
operator's 724 real walls — so the `(geometry)` signature was a signature on
the unproven.

The rule here is narrow, and hence checkable: a check signed `(geometry)`
whose reader consists ONLY of `get_Parameter(...)` does not discharge
geometry. Properties Revit computes itself (`Location`, `get_BoundingBox`,
`TextNote.Width`) do not fall under the rule — the emitter never wrote them.
"""

from __future__ import annotations

import os
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_axis_queue.jsonl"))

from kir import ground as ground_mod  # noqa: E402
from kir.authoring import _EMITTERS  # noqa: E402
from kir.compiler import _parse_and_check  # noqa: E402
from kir.emit_model import BarePost, WitnessCheck  # noqa: E402
from kir.tests.fixtures import GROUND_SNAPSHOT  # noqa: E402
from kir.tests.test_emitter_scope_contract import PROGRAMS  # noqa: E402

#: One version is enough: only ElementId literals diverge between versions,
#: not the set of witnesses or their messages.
VERSION = "2024"

LVL = {"by": "name", "value": "Этаж 1"}

#: Branches that are not in the scope-contract corpus but that set
#: parametric witnesses — otherwise the rule simply will not see them.
EXTRA_PROGRAMS = {
    "wall_location_line": {
        "ir_version": "1.0", "intent": "линия привязки", "ops": [
            {"op": "create_wall", "id": "WL", "p0_mm": [0, 0],
             "p1_mm": [6000, 0], "level": LVL,
             "location_line": "finish_face_exterior"},
        ]},
    "wall_top_offset": {
        "ir_version": "1.0", "intent": "верх с офсетом", "ops": [
            {"op": "create_level", "id": "LT", "elev_mm": 6000, "name": "КИР-В"},
            {"op": "create_wall", "id": "WT", "p0_mm": [0, 0],
             "p1_mm": [6000, 0], "level": LVL, "height_mm": 5500,
             "top_level": {"by": "ref", "value": "LT"},
             "top_offset_mm": -500},
        ]},
}

#: Properties that Revit itself computes from the model: the emitter never
#: wrote them, so reading them is genuine external evidence.
_MODEL_COMPUTED = (
    "Location", "get_BoundingBox", "GetEndPoint", ".Point", "Origin",
    "FacingOrientation", "HandOrientation", ".Elevation", ".Curve",
    ".Center", ".Radius", ".Width", "ComputeCentroid", "GetTotalTransform",
)

#: (op, obligation key) -> justification. A list of EXPLICIT discrepancies:
#: every entry is a statement of fact, not a way to silence the rule.
_ALLOWED_PARAMETER_GEOMETRY = {
    ("create_wall", "base_offset"):
        "WALL_BASE_OFFSET — это САМА вертикальная посадка: положение тела есть "
        "чистая функция значения параметра, другого источника истины у отметки "
        "нет. Отличие от location_line качественное: там параметр от положения "
        "тела развязан (замер 28.07, п. c). Строгая форма §18.3 требует и "
        "здесь читать геометрию — разбирается в MINOR-пакете §18.7(6).",
    ("create_wall", "top_offset"):
        "WALL_TOP_OFFSET — то же самое для верха привязки.",
    ("create_ceiling", "height_offset"):
        "CEILING_HEIGHTABOVELEVEL_PARAM — тот же случай, что WALL_BASE_OFFSET "
        "выше, и внесён по тому же уже принятому разбору, а не по новому "
        "поводу: отметка потолка есть ЧИСТАЯ ФУНКЦИЯ этого параметра, другого "
        "источника истины у неё нет. Прочитать её «настоящей геометрией» "
        "нечем: габарит потолка включает толщину типа, поэтому bbox.Min.Z "
        "отличается от плоскости эскиза на величину, которой мы на этапе "
        "эмиссии не знаем, и сверка по нему обвиняла бы правильный потолок. "
        "Строгая форма §18.3 требует и здесь читать геометрию — тот же "
        "MINOR-пакет §18.7(6), что и у стены. ОТДЕЛЬНО: create_floor несёт "
        "ровно такой же свидетель на FLOOR_HEIGHTABOVELEVEL_PARAM и в этом "
        "списке не значится только потому, что ни одна программа корпуса не "
        "задаёт полу смещение — то есть там дыра не закрыта, а не проверена.",
    # ── 08.03: THE PREDICTION ABOVE CAME TRUE ───────────────────────────
    # The scope-contract corpus was extended with branches it never built
    # (the tolerance-provenance wave), and precisely the four witnesses the
    # caveat on create_ceiling called "the hole is not closed, only not
    # checked" became VISIBLE to this rule. This is not a new defect and not
    # a relaxation: the case is identical to the already-handled
    # WALL_BASE_OFFSET — the mark is a PURE FUNCTION of the parameter, it
    # has no other source of truth, while the body's dimension includes the
    # type's thickness, which we do not know at emission time. The correct
    # reading of geometry here is the same MINOR package §18.7(6); the
    # entry is made so the fact is NAMED, not so the rule falls silent.
    ("create_floor", "height_offset"):
        "FLOOR_HEIGHTABOVELEVEL_PARAM — тот самый случай, который оговорка "
        "к create_ceiling назвала непроверенным: с 03.08 корпус его строит "
        "(программа offsets_and_diameters), и он предъявлен явно. §18.7(6).",
    ("create_floor_by_contour", "height_offset"):
        "FLOOR_HEIGHTABOVELEVEL_PARAM у плиты по контуру — тот же свидетель "
        "и тот же разбор, что у create_floor выше. §18.7(6).",
    ("create_column", "base_offset"):
        "FAMILY_BASE_LEVEL_OFFSET_PARAM — вертикальная посадка колонны есть "
        "чистая функция этого параметра (аналог WALL_BASE_OFFSET). Настоящей "
        "геометрией это читается только габаритом, который у колонны несёт "
        "сечение типа, — сверка по нему обвиняла бы верную колонну. §18.7(6).",
    ("create_column", "top_offset"):
        "FAMILY_TOP_LEVEL_OFFSET_PARAM — то же самое для верха. §18.7(6).",
    # ── 08.26: AN EIGHTH OF THE SAME KIND, AND THE KIND IS ESTABLISHED,
    # NOT ASSUMED ──
    ("create_room", "upper_offset"):
        "ROOM_UPPER_OFFSET — верхний предел помещения есть ЧИСТАЯ ФУНКЦИЯ "
        "этого параметра, другого авторского источника у него нет (заведён "
        "25.08 живой находкой HAB022: NewRoom ставит предел из умолчания "
        "документа, 8 футов = 2438мм, ниже нормы 2500мм, и язык не мог "
        "задать его вовсе). ДВА КАНДИДАТА НА «НАСТОЯЩУЮ ГЕОМЕТРИЮ» "
        "РАССМОТРЕНЫ И ОТВЕРГНУТЫ ПОИМЁННО, оба есть 6/6 по api_surface: "
        "(1) `Room.UnboundedHeight` — это ВТОРАЯ ДВЕРЬ К ТЕМ ЖЕ ЧИСЛАМ "
        "(верхний предел минус база), то есть чтение того же параметра "
        "другим именем: букву §18.3 оно бы удовлетворило, смысл — нет; "
        "(2) `Room.Volume` / `ClosedShell` — обрезаны ОГРАНИЧИВАЮЩИМИ "
        "элементами и включены только при включённом расчёте объёмов в "
        "документе, поэтому у помещения с потолком ниже предела сверка "
        "обвиняла бы ВЕРНОЕ помещение — ровно довод create_ceiling выше. "
        "Строгая форма §18.3 требует и здесь читать геометрию — тот же "
        "MINOR-пакет §18.7(6), что у стены, потолка, пола и колонны. "
        "Запись сделана, чтобы факт был НАЗВАН, а не чтобы правило "
        "замолчало.",
}


def _checks_of(program: dict) -> list[tuple[str, WitnessCheck]]:
    """[(op name, WitnessCheck)] for all ops in the program.

    A program whose ops give a typed REFUSAL on VERSION yields no witnesses
    on that version at all — and this is not a gap but the operation's
    correct answer. Before 08.09 the corpus knew only a version's lower
    bound (`__min_ver__`, a ceiling since 2022); the loads wave brought an
    upper one (`__max_ver__`: the free load was removed from the API by
    Autodesk in 2024), and without accounting for it, the refusal would land
    here as an exception, that is, it would look like a break in the
    axis-honesty rule.
    """

    if program.get("__min_ver__", "0000") > VERSION:
        return []
    if program.get("__max_ver__", "9999") < VERSION:
        return []
    prog = {k: v for k, v in program.items() if not k.startswith("__")}
    grounded = ground_mod.ground(_parse_and_check(prog), GROUND_SNAPSHOT)
    out: list[tuple[str, WitnessCheck]] = []
    for op in grounded:
        emitter = _EMITTERS.get(op["op"])
        if emitter is None:      # create_stairs: its own program template
            continue
        _decl, _create, post, _readback = emitter(op, VERSION, "kir:axis")
        if isinstance(post, BarePost):
            post = list(post.checks)
        if not isinstance(post, (list, tuple)):
            continue             # a string post that has not migrated yet
        for check in post:
            out.append((op["op"], check))
    return out


class GeometryClaimsMustReadGeometry(unittest.TestCase):
    def test_no_geometry_verdict_rests_on_a_parameter_readback(self) -> None:
        corpus = dict(PROGRAMS)
        corpus.update(EXTRA_PROGRAMS)

        offenders = set()
        for name in sorted(corpus):
            for op_name, check in _checks_of(corpus[name]):
                if "(geometry)" not in check.message:
                    continue
                blob = check.reader_cs + check.verdict_cs
                if any(token in blob for token in _MODEL_COMPUTED):
                    continue
                if "get_Parameter" not in blob:
                    continue
                if (op_name, check.obligation_key) in _ALLOWED_PARAMETER_GEOMETRY:
                    continue
                offenders.add((op_name, check.obligation_key, check.message))

        self.assertEqual(
            sorted(offenders), [],
            "свидетель подписывается геометрией, а читает назад параметр, "
            "который сам же записал (§18.3): " + repr(sorted(offenders)))

    def test_the_allowlist_names_only_live_checks(self) -> None:
        # An exception that has outlived its own check is a permit for
        # something that no longer exists: the list must shrink together
        # with the code.
        corpus = dict(PROGRAMS)
        corpus.update(EXTRA_PROGRAMS)
        live = {(op_name, check.obligation_key)
                for name in corpus
                for op_name, check in _checks_of(corpus[name])}

        for entry in _ALLOWED_PARAMETER_GEOMETRY:
            with self.subTest(entry=entry):
                self.assertIn(entry, live)


if __name__ == "__main__":
    unittest.main()
