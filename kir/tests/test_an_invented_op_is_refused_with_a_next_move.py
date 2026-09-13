"""An op the registry does not have refuses BY NAME, not by bare AttributeError.

🔴 BOUGHT BY A MEASUREMENT (13.09.2026, RQ7 preparation, refusal corpus case
`m17`). A model that invents `create_balcony` used to get python's own
`AttributeError` — **50 characters, no next move, no hint that a registry
exists**. In the planned experiment the model has three rounds; a refusal
without a next move spends a round and buys nothing. Inventing a plausible op
name is also the FIRST thing a model does when it does not know the surface.

The corpus is `.work/prod-20260913/rq7-prep/refusals/corpus.py`; after this fix
it reports 19 refusals of 20 naming a next move, against 16 before.
"""
import pytest

from kir import dsl, spec


def test_an_invented_op_names_the_registry_and_the_next_move():
    with pytest.raises(AttributeError) as caught:
        dsl.create_balcony(p0_mm=[0.0, 0.0])
    text = str(caught.value)
    assert "нет операции «create_balcony»" in text
    assert "СЛЕДУЮЩИЙ ХОД" in text
    assert "dsl.op_names()" in text
    assert str(len(dsl.op_names())) in text, "число операций реестра названо"


def test_a_typo_is_offered_the_nearest_real_names():
    with pytest.raises(AttributeError) as caught:
        dsl.creat_wall()
    text = str(caught.value)
    assert "Похожие имена:" in text and "create_wall" in text


def test_a_name_with_no_neighbour_still_gets_the_next_move():
    """The hint is a courtesy; the next move is the contract."""
    with pytest.raises(AttributeError) as caught:
        dsl.zzzzz_нечто()
    text = str(caught.value)
    assert "Похожие имена" not in text
    assert "СЛЕДУЮЩИЙ ХОД" in text


def test_control_the_registry_ops_are_untouched():
    """The refusal must not shadow the REAL names — however many there are.

    🔴 ЧИСЛО 83 СТОЯЛО ЗДЕСЬ ЛИТЕРАЛОМ И ПОКРАСНЕЛО ОТ ЧУЖОЙ РАБОТЫ
    (13.09.2026): соседний исполнитель добавил в реестр `query_level_plan`,
    опов стало 84, и контроль упал — хотя проверяет он НЕ РАЗМЕР РЕЕСТРА, а
    что отказ по выдуманному имени не заслонил настоящие. Размер реестра —
    свойство ЧУЖОГО надела, и пинить его здесь значит ломать этот тест каждым
    честным пополнением языка.

    Проверяется то, что действительно принадлежит этому тесту: поверхность
    `dsl` СОВПАДАЕТ с реестром (ни одно имя не потеряно и ни одно не
    придумано), и настоящие имена по-прежнему вызываемы. Нижняя граница
    оставлена названной — она стережёт обратный случай, пустой реестр, на
    котором тест был бы зелен по построению.
    """
    names = dsl.op_names()
    assert set(names) == set(spec.OPS), (
        "поверхность dsl разошлась с реестром: "
        f"лишние {sorted(set(names) - set(spec.OPS))}, "
        f"потерянные {sorted(set(spec.OPS) - set(names))}")
    assert len(names) >= 80, f"реестр съёжился до {len(names)} опов"
    for name in ("create_wall", "create_level", "set_param", "delete"):
        assert callable(getattr(dsl, name))
    assert set(names) <= set(dsl.__all__)


def test_control_dunder_lookups_are_not_turned_into_product_refusals():
    """`copy`, `pickle` and inspect probe for dunders; they must get the plain error."""
    with pytest.raises(AttributeError) as caught:
        dsl.__wrapped__  # noqa: B018 — the probe itself is the subject
    assert "СЛЕДУЮЩИЙ ХОД" not in str(caught.value)
