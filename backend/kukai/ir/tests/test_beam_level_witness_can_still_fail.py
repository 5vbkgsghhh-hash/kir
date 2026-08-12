"""Свидетель опорного уровня балки: он ослаблен ПРАВИЛЬНО — и всё ещё умеет
падать.

ИСТОРИЯ, БЕЗ КОТОРОЙ ЭТОТ ФАЙЛ ЧИНИТ УЖЕ ПОЧИНЕННОЕ. В корпусе
`data/telemetry/kir_witness.jsonl` двенадцать красных строк `create_beam`, все
27.07 (Revit 2023), все с одной подписью:

    13:05:17  KIR-X004  geometry_ok=true semantic_ok=true topology_ok=false
              ["BM3: level binding mismatch (topology)"]
    13:18:45  ["leg_sw: … leg_se: … leg_ne: … leg_nw: … f0a: … f0b: …
               f1a: … f1b: … f2a: … f2b: level binding mismatch (topology)"]
    13:22:47  ["base_test_tower: level binding mismatch (topology)"]

Последняя — 13:22:47. Коммит `158fadc9` «свидетель балки требовал того, чего
Revit не обещает» — 13:23:40, через 53 секунды; первая зелёная балка — 13:23:16
(прод импортирует рабочее дерево, поэтому правка живёт до коммита). То есть
дефект был настоящим и УЖЕ ЗАКРЫТ. Чинить эмиттер тут — чинить не то.

ЧТО ИМЕННО ГАРАНТИРУЕТ REVIT. Замер 27.07 живой пробой: передан L_01 @ 0 мм,
кривая положена на Z=3000 — привязка ушла к L_01ДОО1_+2.500, ближайшему снизу.
Аргумент `level` у `NewFamilyInstance(Line, …, StructuralType.Beam)` —
КОНТЕКСТ размещения, а не обещание. Поэтому равенства требовать нельзя;
инвариант, который Revit действительно держит, — опорный уровень СУЩЕСТВУЕТ.
Какой именно — читается в свидетель (`reference_level_id`/`reference_level`),
а не навязывается.

ЗАЧЕМ ТОГДА ЭТОТ ФАЙЛ. «Свидетель, переставший спрашивать» неотличим от
«свидетеля, который не умеет упасть», и существующие пины
(`test_struct.py::test_topology_reference_level_and_structuraltype_semantic`,
`test_hangs_and_lies.py::BeamLevelWitnessMustReadTheParameterABeamActuallyHas`)
проверяют НАЛИЧИЕ строки и ОТСУТСТВИЕ старой — но ни один не проверяет, что
уцелевшая проверка вообще способна сработать. Здесь закрыты обе дыры:

  1. проверку нельзя УДАЛИТЬ — сертификат перевода отказывается (мутация);
  2. проверку нельзя ВЫХОЛОСТИТЬ — эмитированное условие вычисляется на трёх
     ЗАМЕРЕННЫХ состояниях параметра и обязано сработать на двух плохих.

Состояния взяты не из головы, а из той же пробы 27.07:

    INSTANCE_REFERENCE_LEVEL_PARAM = 172458 («L_01_+0.000»)   -> молчит
    FAMILY_LEVEL_PARAM  HasValue=True  AsElementId=-1          -> ОБЯЗАН упасть
    LEVEL_PARAM         параметра нет (get_Parameter -> null)  -> ОБЯЗАН упасть

Именно второе состояние ломало СТАРУЮ цепочку: `HasValue` истинен и для
InvalidElementId, поэтому цепочка обрывалась на пустом звене и сравнивала «-1»
с ожидаемым id. Уцелевшая проверка обязана это состояние ловить — иначе
ослабление зашло дальше, чем позволяет замер.
"""
from __future__ import annotations

import copy
import os
import re
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_beam_queue.jsonl"))

from kukai.ir import ground as ground_mod  # noqa: E402
from kukai.ir import spec, struct_emit  # noqa: E402
from kukai.ir.compiler import _parse_and_check, compile_program  # noqa: E402
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT  # noqa: E402
from kukai.ir.translation_cert import certify_op  # noqa: E402

_BEAM = {"op": "create_beam", "id": "B",
         "p0_mm": [0, 0, 3000], "p1_mm": [6000, 0, 3000],
         "level": {"by": "element_id", "value": 42},
         "symbol": {"by": "element_id", "value": 1000}}


def _prog():
    return {"ir_version": "1.0", "intent": "балка", "ops": [copy.deepcopy(_BEAM)]}


def _beam_cs() -> str:
    out = compile_program(_prog(), revit_version="2023",
                          snapshot=GROUND_SNAPSHOT)
    assert out.ok, [d.as_dict() for d in out.diagnostics]
    return out.csharp


def _reference_level_condition(cs: str) -> str:
    """Достаёт ЭМИТИРОВАННОЕ условие сторожа — не переписывает его."""
    block = cs[cs.index("INSTANCE_REFERENCE_LEVEL_PARAM"):]
    m = re.search(r"if \((.*?)\)\n\s*__post\.Add", block, re.S)
    assert m, "сторож опорного уровня не найден в эмитированном C#"
    return " ".join(m.group(1).split())


# Словарь ЗАКРЫТ намеренно: новый терм в условии обязан привести автора сюда и
# заставить назвать, при каком замеренном состоянии он истинен. Иначе тест
# молча пропустит выхолощенного сторожа.
def _term(term: str, *, param_exists: bool, as_element_id: int) -> bool:
    term = term.strip()
    if term == "__rl == null":
        return not param_exists
    if term == "__rl.AsElementId() == null":
        # У существующего параметра AsElementId() возвращает -1, а не null —
        # ровно поэтому старая цепочка на `HasValue` и промахивалась.
        return False
    if term == "__rl.AsElementId() == ElementId.InvalidElementId":
        return as_element_id == -1
    raise AssertionError(
        f"незнакомый терм в стороже опорного уровня: {term!r} — допишите его "
        "в закрытый словарь и назовите замеренное состояние")


def _guard_fires(condition: str, *, param_exists: bool,
                 as_element_id: int) -> bool:
    """Вычисляет условие с коротким замыканием `||`, как это делает C#."""
    for term in condition.split("||"):
        if _term(term, param_exists=param_exists,
                 as_element_id=as_element_id):
            return True
    return False


class TheSurvivingBeamWitnessCanStillFail(unittest.TestCase):
    """Главное: ослабленный свидетель обязан уметь упасть."""

    def setUp(self):
        self.condition = _reference_level_condition(_beam_cs())

    def test_a_beam_with_a_real_reference_level_passes(self):
        """Иначе свидетель падал бы всегда — это второй способ быть бесполезным."""
        self.assertFalse(_guard_fires(self.condition, param_exists=True,
                                      as_element_id=172458))

    def test_an_empty_link_still_fails_the_witness(self):
        """Состояние, ломавшее СТАРУЮ цепочку (HasValue=True, AsElementId=-1),
        обязано остаться нарушением: балка без уровня — реальный дефект."""
        self.assertTrue(_guard_fires(self.condition, param_exists=True,
                                     as_element_id=-1))

    def test_a_missing_parameter_still_fails_the_witness(self):
        self.assertTrue(_guard_fires(self.condition, param_exists=False,
                                     as_element_id=-1))

    def test_the_guard_is_not_a_constant(self):
        """Прямая формулировка невакуумности: у сторожа есть и срабатывание,
        и молчание."""
        fires = {_guard_fires(self.condition, param_exists=p, as_element_id=e)
                 for p, e in ((True, 172458), (True, -1), (False, -1))}
        self.assertEqual(fires, {True, False})


class TheBeamWitnessCannotBeSilentlyDeleted(unittest.TestCase):
    """Мутация в стиле C5: снимаем проверку — сертификат обязан отказать."""

    def _certificate(self):
        grounded = ground_mod.ground(_parse_and_check(_prog()), GROUND_SNAPSHOT)
        return certify_op(grounded[0], "2023")

    def test_baseline_is_proven(self):
        cert = self._certificate()
        self.assertTrue(cert.proven, cert.gaps)

    def test_dropping_the_reference_level_check_breaks_the_certificate(self):
        original = struct_emit.emit_beam

        def hollowed(op, ver, stamp, isolation="atomic"):
            decl, create, checks, readback = original(op, ver, stamp, isolation)
            return decl, create, [c for c in checks
                                  if c.obligation_key != "reference_level"], readback

        struct_emit.emit_beam = hollowed
        try:
            cert = self._certificate()
        finally:
            struct_emit.emit_beam = original
        self.assertFalse(cert.proven)
        self.assertTrue(any("reference_level" in g for g in cert.gaps),
                        cert.gaps)


class TheBeamLevelIsNotASilentlyInjectedDefault(unittest.TestCase):
    """Второе жёсткое условие задачи, отвечено ЗАМЕРОМ, а не рассуждением.

    Правило `tests/test_silent_defaults.py`: свидетельствовать молча
    подставленный default нельзя — эмиттер не отличает «попросили ровно это»
    от «промолчали». У `create_beam` вопрос снят на уровне реестра: ни один
    его параметр default'а не несёт, а `level` вдобавок обязателен."""

    def test_create_beam_declares_no_defaults_at_all(self):
        defaulted = [p.name for p in spec.OPS["create_beam"].params
                     if getattr(p, "default", None) is not None]
        self.assertEqual(defaulted, [])

    def test_the_level_operand_is_required_so_silence_is_impossible(self):
        level = next(p for p in spec.OPS["create_beam"].params
                     if p.name == "level")
        self.assertTrue(level.required)


class TheOldEqualityDemandStaysGone(unittest.TestCase):
    """Регрессионный замок на возврат равенства, которого API не обещает."""

    def test_no_level_binding_equality_for_a_beam(self):
        cs = _beam_cs()
        self.assertNotIn("level binding mismatch", cs)
        self.assertIn("нет опорного уровня (topology)", cs)
        # Уровень ЧИТАЕТСЯ в результат — ослабление не потеряло наблюдаемость.
        self.assertIn('"reference_level_id"', cs)
        self.assertIn('"reference_level"', cs)


if __name__ == "__main__":
    unittest.main()
