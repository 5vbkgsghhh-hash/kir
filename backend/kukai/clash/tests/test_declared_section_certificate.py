"""ПОЧЕМУ КЛЕШ НЕ МОЖЕТ СКАЗАТЬ «ЧИНИТЬ»: ДВЕ СТЕНЫ, А НЕ ОДНА.

Замер 11.08.2026. В проде верхняя ступень недостижима: `_rung` даёт `fix`
только при `proven is True`, `_physical_overlap_proof` требует
`verdict == "confirmed"` плюс сертифицированное ВНУТРЕННЕЕ перекрытие, и две
пересекающиеся в воздухе трубы выходят как `look`. Этот файл держит на виду
ОБЕ причины — вторая нашлась при попытке снять первую, и без неё план
«зарегистрировать издателя от объявления» выглядит выполнимым, а он не
выполним.

СТЕНА ПЕРВАЯ — НЕТ ПРОИЗВОДСТВЕННОГО ИЗДАТЕЛЯ. Реестр доверия содержит ровно
одно имя, и оно называет себя: `certify_analytic_inner_for_test`, издатель
`kir.clash.analytic-test-body/v1`, происхождение `explicit-analytic-body/v1`.
Издатель требует ИСТИННОЕ ТЕЛО на вход, а его докстрока называет условие снятия
запрета: «until a Revit body extractor can provide equivalent source evidence».
`record.inner` в проде не заполняется НИГДЕ.

    Эта стена НЕ является общей. Для `bbox` запрет верен (габарит телом не
    является) и для `profile` верен (контур огрубляет наружу). Но у КРУГЛОГО
    объявленного сечения капсула не приближает тело, она И ЕСТЬ тело: программа
    сказала 400 мм, эмиттер ставит ровно 400 мм, и извлекатель из Revit не
    нужен, чтобы знать то, что мы сами собираемся построить.

СТЕНА ВТОРАЯ, ГЛУБЖЕ ПЕРВОЙ — ЯДРО ДОКАЗАТЕЛЬСТВА ПРИНИМАЕТ ТОЛЬКО
МНОГОГРАННИКИ. `_analytic_vertices` канонизирует `Aabb` и `Prism` и отвергает
`Capsule` и `PrismSet`. Это не пробел, а решение ядра, записанное в нём же:
«No Capsule is silently promoted to an inner hull merely because its outer
approximation has a radius». ВСЯКАЯ трасса MEP — капсула. Значит даже при живом
издателе от объявления сертификат для того самого класса, ради которого всё
затевалось, не выдаётся: тело круглой трубы этому ядру нечем выразить.

ПОЧЕМУ ЭТО ЗАПИСАНО ТЕСТОМ, А НЕ КОММЕНТАРИЕМ. Обе стены — утверждения о
СЕГОДНЯШНЕМ коде, и обе обязаны покраснеть, когда их снимут: первая — когда
появится второй издатель, вторая — когда ядро научится телу вращения. Красный
здесь означает «стена снята, перечитай план», а не поломку. Комментарий такого
не умеет: в этом файле уже есть история про то, как запись пережила свою правду.

ЧЕГО ЭТОТ ФАЙЛ НЕ ПОКРЫВАЕТ: он не утверждает, что сертификат от объявления —
правильный следующий ход. Он утверждает лишь, ЧТО именно мешает, и что мешают
две разные вещи, а не одна.
"""
from __future__ import annotations

from kukai.clash import detect as D
from kukai.clash import geom as G
from kukai.clash import hulls as H


def _duct(source_id: str, *, y_mm: float = 0.0, across: bool = False,
          params: dict | None = None, category: str = "OST_DuctCurves"):
    el = {"element_id": source_id, "category": category,
          "params": params or {"RBS_CURVE_DIAMETER_PARAM": 400.0}}
    if across:
        el |= {"p0_mm": [2500.0, -2000.0, 2700.0],
               "p1_mm": [2500.0, 2000.0, 2700.0]}
    else:
        el |= {"p0_mm": [0.0, y_mm, 2700.0], "p1_mm": [5000.0, y_mm, 2700.0]}
    rec, refusal = H.build_hull(el)
    assert rec is not None, refusal
    return rec


# ── СТЕНА ПЕРВАЯ ──────────────────────────────────────────────────────────

def test_the_trust_registry_has_exactly_one_issuer_and_it_is_a_fixture():
    """Единственный зарегистрированный издатель называет себя тестовым — и
    именем, и происхождением. Красный здесь = появился второй издатель."""
    assert set(H.INNER_CERTIFICATE_ISSUER_REGISTRY) == {
        H.ANALYTIC_TEST_INNER_ISSUER}
    assert "test" in H.ANALYTIC_TEST_INNER_ISSUER
    assert H.INNER_CERTIFICATE_PROVENANCE == frozenset(
        {H.ANALYTIC_BODY_PROVENANCE})
    assert hasattr(H, "certify_analytic_inner_for_test")


def test_no_production_hull_carries_inner_evidence():
    """`record.inner` не заполняется ни для одного источника оболочки."""
    for rec in (_duct("d1"),
                _duct("d2", params={"RBS_CURVE_WIDTH_PARAM": 400.0,
                                    "RBS_CURVE_HEIGHT_PARAM": 200.0})):
        assert rec.inner is None, rec.hull_source
    wall, _ = H.build_hull({"element_id": "w", "category": "OST_Walls",
                            "bbox_min_mm": [0, 0, 0],
                            "bbox_max_mm": [1000, 200, 3000]})
    assert wall.inner is None and wall.hull_source == "bbox"


def test_two_crossing_declared_ducts_stay_possible_for_a_NAMED_reason():
    """Две трассы, пересекающиеся в воздухе, — коллизия по любому прочтению, и
    вердикт «possible» с причиной, названной поимённо."""
    finding, why = D.evaluate_with_reason(_duct("d1"), _duct("d2", across=True))
    assert finding is not None, why
    proof = finding.as_dict()["physical_overlap_proof"]
    assert proof["status"] == "not_proven"
    assert proof["reason"] == "a:inner_evidence_absent;b:inner_evidence_absent"


def test_the_declared_capsule_IS_the_body_for_a_round_section():
    """ПОЧЕМУ ПЕРВАЯ СТЕНА НЕ ОБЩАЯ: у круглого сечения радиус капсулы РАВЕН
    половине объявленного диаметра — ни на волос больше. Огрубления нет, и
    доказывать тут нечего сверх того, что уже сказала программа."""
    rec = _duct("d1")
    assert rec.hull_source == "axis_section"
    assert isinstance(rec.hull, G.Capsule)
    assert rec.hull.radius == 200.0            # ровно 400/2, а не описанная
    rect = _duct("d2", params={"RBS_CURVE_WIDTH_PARAM": 400.0,
                               "RBS_CURVE_HEIGHT_PARAM": 200.0})
    # А у прямоугольного — ОПИСАННАЯ окружность, то есть огрубление наружу,
    # и для него запрет остаётся верным.
    assert rect.hull.radius > 200.0


# ── СТЕНА ВТОРАЯ ──────────────────────────────────────────────────────────

def test_the_proof_kernel_accepts_only_polytopes():
    """Ядро канонизирует `Aabb` и `Prism` и отвергает `Capsule`/`PrismSet`.

    Красный здесь = ядро научилось телу вращения, и план снятия первой стены
    снова выполним.
    """
    box = G.Aabb((0, 0, 0), (100, 200, 300))
    prism = G.Prism(((0, 0), (100, 0), (100, 100), (0, 100)), 0.0, 100.0)
    capsule = G.Capsule(((0, 0, 0), (1000, 0, 0)), 200.0)
    prism_set = G.PrismSet(((((0, 0), (100, 0), (100, 100), (0, 100))),),
                           0.0, 100.0)
    assert H._analytic_vertices(box) is not None
    assert H._analytic_vertices(prism) is not None
    assert H._analytic_vertices(capsule) is None, (
        "ядро приняло капсулу — вторая стена снята, перечитайте план")
    assert H._analytic_vertices(prism_set) is None


def test_every_mep_run_is_a_capsule_so_the_second_wall_binds_exactly_here():
    """Смычка двух стен: класс, ради которого стоило снимать первую, целиком
    состоит из тел, которые отвергает вторая."""
    for params in ({"RBS_CURVE_DIAMETER_PARAM": 400.0},
                   {"RBS_CURVE_WIDTH_PARAM": 400.0,
                    "RBS_CURVE_HEIGHT_PARAM": 200.0}):
        rec = _duct("d", params=params)
        assert isinstance(rec.hull, G.Capsule)
        assert H._analytic_vertices(rec.hull) is None
