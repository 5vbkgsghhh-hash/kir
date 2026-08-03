"""ПРОВЕНАНС ДОПУСКА — обещанное число обязано иметь адрес в реестре.

``translation_cert`` доказывает, что на каждую обещанную клаузулу СУЩЕСТВУЕТ
свидетель; о том, ОТКУДА взято число, с которым этот свидетель сравнивает, он
не говорит ничего.  До 03.08 все 35 пишущих опов были `PROVEN`, при этом
одиннадцать из них обещали в `post` миллиметры, которых реестр назвать не мог.

Образец дефекта (`create_type`, 27.07): проверка заявляла
``tol_key="param_mm"``, а C# сравнивала с захардкоженным ``0.5``.  Ссылка в
пустоту, которую не видел ни один тест: ключ был просто строкой, и никто
никогда не спрашивал, разрешается ли она.

ТРИ ЗАКОНА (формулировка — в ``emit_model.py``, там же и первые два стоят ПО
ПОСТРОЕНИЮ; здесь они проверяются, а третий живёт только тут):

  1. ЧЕКАНКА — допуск попадает в эмиссию только объектом :class:`Tolerance`,
     отчеканенным из ``spec.OPS[op].tolerances[key]``;
  2. ПРОЧТЕНО, А НЕ ЗАЯВЛЕНО — витнес, объявивший допуск, обязан содержать в
     своей C# строку, которую этот объект сам отрендерил;
  3. ОБЕЩАНИЕ ↔ РЕЕСТР ↔ ЭМИССИЯ — каждое ``±<число>`` из ``OpSpec.post``
     адресуемо в реестре, и каждая запись реестра доходит до эмитируемой C#.

Классы ниже — по одному на закон/сторону:

  * L0 — конструктор: три формы дефекта неконструируемы;
  * L1 — реестр: обещанное число адресуемо;
  * L2 — эмиссия: объявленный ключ разрешается;
  * L3 — эмиссия: объявленный провенанс НАСТОЯЩИЙ (возмущающий оракул);
  * L4 — реестр: мёртвых чисел нет;
  * L5 — корпус: сертифицирующий корпус строит КАЖДУЮ ветку допуска;
  * L6 — сертификат: каждый эмитируемый свидетель кем-то проверяется.

L3 и L4 не украшение: они делают невозможной ПОЛОВИНЧАТУЮ починку.  Внести
недостающие числа в реестр, не научив эмиттеры их читать, красит L1/L2 в
зелёный и L3/L4 в красный (замерено симуляцией 03.08).  Зелено только
реестр+эмиттер вместе.

Запускать точечно (полный набор — 5 ГБ RSS):

    venv/bin/python3.12 -m pytest kukai/ir/tests/test_tolerance_provenance.py -q
"""
from __future__ import annotations

import os
import re
import tempfile
import unittest

os.environ.setdefault(
    "KIR_REJECTIONS_PATH",
    os.path.join(tempfile.gettempdir(), "kir_tolprov_queue.jsonl"))

from kukai.ir import ground as ground_mod                      # noqa: E402
from kukai.ir import spec                                      # noqa: E402
from kukai.ir.authoring import _EMITTERS, emit_stairs_program  # noqa: E402
from kukai.ir.compiler import _parse_and_check                 # noqa: E402
from kukai.ir.emit_model import (                              # noqa: E402
    BarePost,
    EmitModelError,
    WitnessCheck,
    post_to_string,
    tolerance,
)
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT            # noqa: E402
from kukai.ir.tests.test_emitter_scope_contract import (       # noqa: E402
    PROGRAMS,
    VERSIONS,
)

WRITE_OPS = sorted(
    name for name, op_spec in spec.OPS.items()
    if op_spec.family in spec.WRITE_FAMILIES)

# ---------------------------------------------------------------------------
# Корпус
# ---------------------------------------------------------------------------

# create_stairs владеет своим шаблоном программы и не лежит в _EMITTERS.
_STAIRS_OP = {
    "op": "create_stairs", "id": "ST1", "p0_mm": [0, 0], "p1_mm": [3000, 0],
    "base_level": {"__grounded__": {"via": "id", "id": 42}},
    "top_level": {"__grounded__": {"via": "id", "id": 43}},
    "width_mm": 1200,
}

# Условные поля, открывающие ветку с допуском.
_FORCE = {"base_offset_mm": 150, "top_offset_mm": -250,
          "diameter_mm": 200, "height_offset_mm": 2700}


def _shipped_instances():
    """(op_name, grounded_op, version) для корпуса, который несёт репозиторий."""

    out = []
    for _pname, prog in PROGRAMS.items():
        min_ver = prog.get("__min_ver__", "2021")
        prog = {k: v for k, v in prog.items() if k != "__min_ver__"}
        grounded = ground_mod.ground(_parse_and_check(prog), GROUND_SNAPSHOT)
        for ver in [v for v in VERSIONS if v >= min_ver]:
            for op in grounded:
                out.append((op["op"], op, ver))
    for ver in VERSIONS:
        out.append(("create_stairs", _STAIRS_OP, ver))
    return out


def _full_instances():
    """Корпус плюс ветки, которых он мог бы не достигать."""

    out = list(_shipped_instances())
    for name, op, ver in list(out):
        if name == "create_stairs":
            continue
        forced = dict(op)
        for field, value in _FORCE.items():
            forced.setdefault(field, value)
        out.append((name, forced, ver))
    return out


SHIPPED = _shipped_instances()
FULL = _full_instances()


def _checks(name, op, ver):
    """Объекты WitnessCheck, которые оп эмитирует ([] у строкового жанра)."""

    if name == "create_stairs":
        return []
    _decl, _create, post, _rb = _EMITTERS[name](op, ver, "kir:tolprov")
    if isinstance(post, BarePost):
        post = list(post.checks)
    return list(post) if isinstance(post, (list, tuple)) else []


def _rendered(name, op, ver):
    """Всё, что оп эмитирует, одной строкой (для диффа возмущений)."""

    if name == "create_stairs":
        return emit_stairs_program(op, ver)
    decl, create, post, rb = _EMITTERS[name](op, ver, "kir:tolprov")
    if isinstance(post, BarePost):
        post = list(post.checks)
    return post_to_string(op["id"], post) + (decl or "") + (create or "") + (rb or "")


# ---------------------------------------------------------------------------
# L0 — КОНСТРУКТОР: три формы дефекта неконструируемы
# ---------------------------------------------------------------------------

class L0_TheDefectIsUnconstructible(unittest.TestCase):
    """Приём этого дома: ``WitnessCheck`` нельзя построить без ``__post.Add``,
    и класс дефектов F3 умер ПО ПОСТРОЕНИЮ.  То же самое сделано с допуском —
    ниже три формы, каждая из которых раньше жила молча."""

    def test_a_key_the_registry_cannot_answer_refuses_at_minting(self) -> None:
        """Ключ в пустоту (дефект create_type) — отказ на чеканке."""

        with self.assertRaises(EmitModelError):
            tolerance("create_wall", "нет_такого_ключа_mm")
        with self.assertRaises(EmitModelError):
            tolerance("нет_такого_опа", "endpoint_mm")

    def test_a_bare_key_string_is_not_a_provenance(self) -> None:
        """Голой строкой провенанс больше не объявляется: поля нет, а
        подсунутая строка/число — типизированный отказ."""

        with self.assertRaises(TypeError):
            WitnessCheck(
                obligation_key="k", reader_cs="",
                verdict_cs='    if (x > 5.0) __post.Add("m");\n',
                message="m", tol_key="endpoint_mm")      # type: ignore[call-arg]
        with self.assertRaises(EmitModelError):
            WitnessCheck(
                obligation_key="k", reader_cs="",
                verdict_cs='    if (x > 5.0) __post.Add("m");\n',
                message="m", tol="endpoint_mm")          # type: ignore[arg-type]

    def test_a_declared_but_unread_tolerance_is_unconstructible(self) -> None:
        """Заявленный допуск при числе, набранном рядом руками, — ровно дефект
        create_type; теперь такую проверку нельзя ПОСТРОИТЬ."""

        tol = tolerance("create_wall", "endpoint_mm")
        with self.assertRaises(EmitModelError):
            WitnessCheck(
                obligation_key="endpoints", reader_cs="",
                # число то же самое, но пришло не от объекта
                verdict_cs='    if (d > 5.0) __post.Add("m");\n',
                message="m", tol=tol)
        # а через объект — строится
        ok = WitnessCheck(
            obligation_key="endpoints", reader_cs="",
            verdict_cs=f'    if (d > {tol}) __post.Add("m");\n',
            message="m", tol=tol)
        self.assertEqual(ok.tol_key, "endpoint_mm")

    def test_the_registry_number_is_the_one_emitted(self) -> None:
        """Чеканка отдаёт РЕЕСТРОВОЕ значение, а не своё."""

        self.assertEqual(
            tolerance("create_wall", "endpoint_mm").value,
            float(spec.OPS["create_wall"].tolerances["endpoint_mm"]))


# ---------------------------------------------------------------------------
# L1 — РЕЕСТР: обещанное число адресуемо
# ---------------------------------------------------------------------------

# `±5mm`, `±0.1deg`, `±50` ... и неколичественное `±tol`.
_PROMISED = re.compile(r"±\s*(?:(\d+(?:\.\d+)?)|(tol)\b)")


class L1_PromisedNumberIsAddressable(unittest.TestCase):
    """Если ``OpSpec.post`` обещает ``±<n>`` (или ``±tol``), это число обязано
    лежать в ``OpSpec.tolerances``.  Обещание, которое реестр назвать не может,
    не проверит ни рецензент, ни приёмка, ни декомпилятор."""

    def test_every_prose_tolerance_has_a_registry_home(self) -> None:
        offenders = []
        for name in WRITE_OPS:
            op_spec = spec.OPS[name]
            promises = _PROMISED.findall(op_spec.post)
            if not promises:
                continue
            values = {float(v) for v in op_spec.tolerances.values()}
            if not op_spec.tolerances:
                offenders.append(
                    f"{name}: post promises "
                    f"{[a or b for a, b in promises]} but tolerances == {{}}")
                continue
            for number, _unquantified in promises:
                if number and float(number) not in values:
                    offenders.append(
                        f"{name}: post promises ±{number} but the registry "
                        f"holds {sorted(values)}")
        self.assertEqual(
            [], offenders,
            "\nопы, обещающие допуск, которого реестр назвать не может:\n  "
            + "\n  ".join(offenders))

    def test_tolerances_are_positive_finite_numbers(self) -> None:
        """Нулевой/отрицательный допуск делает проверку либо невыполнимой,
        либо бессмысленной (перенесено из прежней редакции модуля)."""

        for op_name, op_spec in sorted(spec.OPS.items()):
            for key, value in (getattr(op_spec, "tolerances", None)
                               or {}).items():
                with self.subTest(op=op_name, key=key):
                    self.assertIsInstance(value, (int, float))
                    self.assertNotIsInstance(value, bool)
                    self.assertGreater(float(value), 0.0)


# ---------------------------------------------------------------------------
# L2 — ЭМИССИЯ: объявленный ключ разрешается
# ---------------------------------------------------------------------------

class L2_TolKeyResolves(unittest.TestCase):
    """``WitnessCheck.tol_key`` — заявление о происхождении числа.  Ключ,
    которого нет в ``tolerances`` СВОЕГО опа, — дефект create_type."""

    def test_no_tol_key_points_into_the_void(self) -> None:
        offenders = set()
        for name, op, ver in FULL:
            for chk in _checks(name, op, ver):
                if chk.tol_key is None:
                    continue
                if chk.tol_key not in spec.OPS[name].tolerances:
                    offenders.add(
                        f"{name}.{chk.obligation_key}: tol_key="
                        f"{chk.tol_key!r} not in tolerances="
                        f"{spec.OPS[name].tolerances}")
        self.assertEqual(
            set(), offenders,
            "\nсвидетели, чей заявленный провенанс не разрешается:\n  "
            + "\n  ".join(sorted(offenders)))


# ---------------------------------------------------------------------------
# L3 — ЭМИССИЯ: объявленный провенанс НАСТОЯЩИЙ (возмущающий оракул)
# ---------------------------------------------------------------------------

class L3_DeclaredProvenanceIsReal(unittest.TestCase):
    """Тронь число в реестре — C# каждого свидетеля, который заявил, что его
    читает, ОБЯЗАНА поехать.  Свидетель с разрешимым ключом, который его не
    читает, — та же ложь, только с валидным ключом."""

    def test_poking_the_registry_moves_the_witness(self) -> None:
        offenders = []
        for name in WRITE_OPS:
            tolerances = spec.OPS[name].tolerances
            instances = [(n, o, v) for n, o, v in FULL if n == name]
            for key, value in list(tolerances.items()):
                claimants = [
                    (n, o, v, c) for n, o, v in instances
                    for c in _checks(n, o, v) if c.tol_key == key]
                if not claimants:
                    continue
                tolerances[key] = float(value) * 1000.0 + 7.77
                try:
                    moved = any(
                        next((x for x in _checks(n, o, v)
                              if x.obligation_key == c.obligation_key),
                             None) != c
                        for n, o, v, c in claimants)
                finally:
                    tolerances[key] = value
                if not moved:
                    offenders.append(
                        f"{name}.{key}: witnesses declare tol_key={key!r} but "
                        "their C# does not change when the registry does")
        self.assertEqual(
            [], offenders,
            "\nдекоративный tol_key (объявлен, но не прочитан):\n  "
            + "\n  ".join(offenders))


# ---------------------------------------------------------------------------
# L4 — РЕЕСТР: мёртвых чисел нет
# ---------------------------------------------------------------------------

class L4_NoDeadRegistryNumber(unittest.TestCase):
    """Каждая запись ``tolerances`` обязана доходить до эмитируемой C#.
    Число в реестре, которого никто не читает, — зеркальный дефект: выглядит
    как централизованный допуск, а настоящая калитка стоит в другом месте."""

    def test_every_tolerance_key_reaches_the_emission(self) -> None:
        baseline = {i: _rendered(*inst) for i, inst in enumerate(FULL)}
        offenders = []
        for name in WRITE_OPS:
            tolerances = spec.OPS[name].tolerances
            for key, value in list(tolerances.items()):
                tolerances[key] = float(value) * 1000.0 + 7.77
                try:
                    moved = any(
                        _rendered(*FULL[i]) != baseline[i]
                        for i in range(len(FULL)) if FULL[i][0] == name)
                finally:
                    tolerances[key] = value
                if not moved:
                    offenders.append(
                        f"{name}.tolerances[{key!r}] = {value} — ничего из "
                        f"того, что эмитирует {name}, его не читает")
        self.assertEqual(
            [], offenders,
            "\nмёртвые числа реестра:\n  " + "\n  ".join(offenders))


# ---------------------------------------------------------------------------
# L5 — КОРПУС: сертифицирующий корпус строит КАЖДУЮ ветку допуска
# ---------------------------------------------------------------------------

class L5_CorpusReachesEveryTolerance(unittest.TestCase):
    """Сертификат доказывает ровно то, что корпус собирает: ветка допуска, в
    которую корпус не заходит, заверена только в ОТРИЦАНИИ («свидетель
    правильно отсутствует»), и захардкоженное число внутри неё невидимо.
    Корпус — часть доказательства, поэтому он обязан быть полным."""

    def test_shipped_corpus_exercises_every_tolerance_key(self) -> None:
        baseline = {i: _rendered(*inst) for i, inst in enumerate(SHIPPED)}
        unreached = []
        for name in WRITE_OPS:
            tolerances = spec.OPS[name].tolerances
            for key, value in list(tolerances.items()):
                tolerances[key] = float(value) * 1000.0 + 7.77
                try:
                    moved = any(
                        _rendered(*SHIPPED[i]) != baseline[i]
                        for i in range(len(SHIPPED)) if SHIPPED[i][0] == name)
                finally:
                    tolerances[key] = value
                if not moved:
                    unreached.append(f"{name}.{key}")
        self.assertEqual(
            [], unreached,
            "\nветки допусков, которых сертифицирующий корпус не строит "
            "(сертификат не увидит в них хардкода):\n  "
            + "\n  ".join(unreached))


# ---------------------------------------------------------------------------
# L6 — СЕРТИФИКАТ: каждый эмитируемый свидетель кем-то проверяется
# ---------------------------------------------------------------------------

# Свидетели, которые есть защита в глубину, а не клаузула `OpSpec.post`.
# Формат: (оп, ключ) -> почему он законно вне биекции REFINEMENT.
_UNPROMISED_WITNESSES = {
    ("create_group", "placed"):
        "extra: post обещает экземпляры, а не отдельную пробу размещения",
    ("create_group", "member_0"):
        "перепроверка участника; его собственный post это уже обещает",
    ("create_group", "member_1"):
        "перепроверка участника; его собственный post это уже обещает",
}


class L6_EveryWitnessIsCertified(unittest.TestCase):
    """``audit_registry_coverage()`` сопоставляет прозаическую клаузулу с
    обязательством по ОБЩЕМУ СЛОВУ — то есть подстрокой в другой одежде.
    Замер 03.08: клаузула уклона route_* (KIR-X004) не имела своего
    обязательства и проходила аудит, потому что слово «segment» есть и у
    диаметра, и у связности; свидетель ПРИ ЭТОМ эмитировался, и его удаление
    оставляло сертификат PROVEN.

    Форма — мутация, ровно как дисциплина C5 этого репозитория: вырезание
    настоящего свидетеля ОБЯЗАНО уронить `proven`."""

    _SLOPED = [
        {"op": "route_pipe_system", "id": "RS1",
         "level": {"by": "element_id", "value": 42},
         "nodes": [{"id": "N1", "xyz_mm": [0, 0, 3000]},
                   {"id": "N2", "xyz_mm": [6000, 0, 2900]}],
         "segments": [{"from": "N1", "to": "N2",
                       "diameter_mm": 100, "slope_min_pct": 1.0}]},
        {"op": "route_duct_system", "id": "DS1",
         "level": {"by": "element_id", "value": 42},
         "nodes": [{"id": "N1", "xyz_mm": [0, 0, 3000]},
                   {"id": "N2", "xyz_mm": [6000, 0, 2900]}],
         "segments": [{"from": "N1", "to": "N2",
                       "diameter_mm": 200, "slope_min_pct": 1.0}]},
    ]

    def _corpus(self):
        for name, op, ver in FULL:
            if name != "create_stairs":
                yield name, op, ver
        for raw in self._SLOPED:
            grounded = ground_mod.ground(
                _parse_and_check({"ir_version": "1.0", "intent": "x",
                                  "ops": [raw]}), GROUND_SNAPSHOT)[0]
            for ver in VERSIONS:
                yield raw["op"], grounded, ver

    def test_excising_a_witness_flips_the_certificate(self) -> None:
        from kukai.ir import translation_cert as cert_mod

        uncertified = set()
        seen = set()
        for name, op, ver in self._corpus():
            for chk in _checks(name, op, ver):
                key = chk.obligation_key
                if (name, key) in _UNPROMISED_WITNESSES or (name, key) in seen:
                    continue
                seen.add((name, key))
                real = _EMITTERS[name]

                def excised(o, v, stamp, isolation="atomic", _r=real, _k=key):
                    d, c, post, rb = _r(o, v, stamp, isolation)
                    bare = isinstance(post, BarePost)
                    checks = list(post.checks) if bare else list(post)
                    kept = [x for x in checks if x.obligation_key != _k]
                    if not kept:
                        # Пустой post неконструируем (render_post отказывает),
                        # поэтому подставляется инертная заглушка: блок
                        # остаётся правильной формы, а КЛЮЧ под тестом исчез.
                        kept = [WitnessCheck(
                            obligation_key="__excised__", reader_cs="",
                            verdict_cs='    if (false) __post.Add("");\n',
                            message="excised", style="guard")]
                    return d, c, (BarePost(tuple(kept)) if bare else kept), rb

                _EMITTERS[name] = excised
                try:
                    still = cert_mod.certify_op(op, ver).proven
                finally:
                    _EMITTERS[name] = real
                if still:
                    uncertified.add(f"{name}.{key}")
        self.assertEqual(
            set(), uncertified,
            "\nсвидетели, которых сертификат не проверяет (их удаление "
            "оставляет PROVEN) и которые не объявлены необещанными:\n  "
            + "\n  ".join(sorted(uncertified)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
