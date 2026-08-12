"""§18.3: свидетель обязан читать ТУ ОСЬ, которую подписывает.

Ось нарушения — не украшение сообщения, а машинный факт: `serving.py`
раскладывает тройку `geometry_ok/topology_ok/semantic_ok` ровно по подстрокам
`(geometry)` / `(topology)` в тексте нарушения. Значит проверка, которая
читает НАЗАД ПАРАМЕТР, который сама же и записала, но подписывается
`(geometry)`, заставляет потребителя прочитать «геометрия доказана» там, где
никакой геометрии никто не мерил.

Ровно это и было у `create_wall.location_line`: эмиттер ставил
`WALL_KEY_REF_PARAM`, свидетель читал его ординал обратно, а результат уходил
на ось геометрии. Живой замер 28.07
(`docs/2026-07-28-location-line-measurement.md`) показал, что этот параметр
телом стены не двигает ВООБЩЕ — ни у наших стен, ни у 724 настоящих стен
оператора, — так что подпись «(geometry)» была подписью под непроверенным.

Правило здесь узкое и потому проверяемое: проверка, подписанная `(geometry)`,
чей читатель состоит ТОЛЬКО из `get_Parameter(...)`, геометрию не разряжает.
Свойства, которые Revit считает сам (`Location`, `get_BoundingBox`,
`TextNote.Width`), под правило не попадают — их эмиттер не записывал.
"""

from __future__ import annotations

import os
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_axis_queue.jsonl"))

from kukai.ir import ground as ground_mod  # noqa: E402
from kukai.ir.authoring import _EMITTERS  # noqa: E402
from kukai.ir.compiler import _parse_and_check  # noqa: E402
from kukai.ir.emit_model import BarePost, WitnessCheck  # noqa: E402
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT  # noqa: E402
from kukai.ir.tests.test_emitter_scope_contract import PROGRAMS  # noqa: E402

#: Одной версии достаточно: между версиями расходятся только литералы
#: ElementId, а состав свидетелей и их сообщения — нет.
VERSION = "2024"

LVL = {"by": "name", "value": "Этаж 1"}

#: Ветки, которых нет в корпусе scope-контракта, но которые ставят
#: параметрических свидетелей — иначе правило их просто не увидит.
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

#: Свойства, которые Revit вычисляет из модели сам: эмиттер их не записывал,
#: поэтому чтение их — настоящее внешнее свидетельство.
_MODEL_COMPUTED = (
    "Location", "get_BoundingBox", "GetEndPoint", ".Point", "Origin",
    "FacingOrientation", "HandOrientation", ".Elevation", ".Curve",
    ".Center", ".Radius", ".Width", "ComputeCentroid", "GetTotalTransform",
)

#: (оп, ключ обязательства) -> обоснование. Список ЯВНЫХ расхождений: каждая
#: запись — утверждение о факте, а не способ заглушить правило.
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
    # ── 03.08: ПРЕДСКАЗАНИЕ ВЫШЕ СБЫЛОСЬ ────────────────────────────────
    # Корпус scope-контракта расширен ветками, которых он не строил (волна
    # провенанса допусков), и ровно те четыре свидетеля, о которых оговорка
    # к create_ceiling говорила «дыра не закрыта, а не проверена», стали
    # ВИДНЫ этому правилу. Это не новый дефект и не послабление: случай
    # тождественен уже разобранному WALL_BASE_OFFSET — отметка есть ЧИСТАЯ
    # ФУНКЦИЯ параметра, другого источника истины у неё нет, а габарит тела
    # включает толщину типа, которой на этапе эмиссии мы не знаем.
    # Правильное чтение геометрии здесь — тот же MINOR-пакет §18.7(6);
    # запись сделана, чтобы факт был НАЗВАН, а не чтобы правило замолчало.
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
}


def _checks_of(program: dict) -> list[tuple[str, WitnessCheck]]:
    """[(имя опа, WitnessCheck)] для всех опов программы.

    Программа, чьи опы на VERSION типизированно ОТКАЗЫВАЮТ, свидетелей на этой
    версии не даёт вовсе — и это не пробел, а правильный ответ операции. До
    09.08 корпус знал только нижнюю границу версии (`__min_ver__`, потолок с
    2022); волна нагрузок принесла верхнюю (`__max_ver__`: свободная нагрузка
    убрана Autodesk из API в 2024), и без её учёта отказ прилетал бы сюда
    исключением, то есть выглядел бы как поломка правила честности осей.
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
        if emitter is None:      # create_stairs: свой шаблон программы
            continue
        _decl, _create, post, _readback = emitter(op, VERSION, "kir:axis")
        if isinstance(post, BarePost):
            post = list(post.checks)
        if not isinstance(post, (list, tuple)):
            continue             # ещё не мигрировавший строковый post
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
        # Исключение, пережившее свою проверку, — это разрешение на то, чего
        # больше нет: список обязан ссыхаться вместе с кодом.
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
