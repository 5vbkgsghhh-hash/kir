"""Продуктовый слой отчёта: контракт `clash-review/1`.

Слой ВЫВОДИМ из `clash-report/2` чистой функцией и версионируется отдельно —
доказательство и представление живут разными чередами. Тесты держат ровно эту
границу: канон не смеет зависеть от статуса, а представление не смеет обещать
больше, чем доказал детектор.
"""
from __future__ import annotations

import pytest

from kukai.clash import detect as D
from kukai.clash import review as R
from kukai.clash import snapshot as S


def _rep(els):
    return D.detect(S.build_from_elements(els, origin={"run_dir": "t"}),
                    pair_filter=D.any_physical_pair_filter)


TWO_WALLS = [{"element_id": "1", "category": "OST_Walls",
              "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [5000, 200, 3000]},
             {"element_id": "2", "category": "OST_Walls",
              "bbox_min_mm": [100, 0, 0], "bbox_max_mm": [5000, 200, 3000]}]


def test_review_is_derived_and_does_not_touch_the_canon():
    """Канон обязан остаться байт-в-байт тем же после построения обзора."""
    rep = _rep(TWO_WALLS)
    before = D.dumps(rep)
    R.build_review(rep)
    assert D.dumps(rep) == before, "обзор изменил доказательство"


def test_status_is_reserved_but_empty():
    """Цикл «обсудили → закрыли» ещё не приехал, но схема его ЖДЁТ."""
    v = R.build_review(_rep(TWO_WALLS))
    st = v["top_findings"][0]["status"]
    assert st["state"] == "open"
    assert st["changed_by"] is None and st["changed_at"] is None
    assert v["status_vocabulary"] == ["open", "discussed", "dismissed", "fixed"]


def test_a_coarse_pair_never_gets_the_top_severity():
    """Грубая пара НЕ доказывает проникания тел. Обещать проектировщику
    «критично» на недоказанном — тот же Гудхарт, что `exact` у капсулы."""
    els = [{"element_id": "1", "category": "OST_Walls",
            "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [5000, 200, 3000]},
           {"element_id": "2", "category": "OST_Walls",
            "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [5000, 199, 3000]}]
    v = R.build_review(_rep(els))
    for row in v["top_findings"]:
        if row["hull_grade"] == "coarse" and row["pair_kind"] == "interference":
            assert row["severity"] in ("средняя", "низкая"), row


def test_a_proven_duplicate_is_critical_and_says_how_to_fix():
    """Совпали ОСИ и сечения — совпадение доказано геометрией, и совет
    «удалить одну» законен."""
    els = [{"element_id": "1", "category": "OST_PipeCurves",
            "p0_mm": [0, 0, 0], "p1_mm": [5000, 0, 0],
            "section_radius_mm": 100.0, "section_round": True,
            "bbox_min_mm": [-100, -100, -100], "bbox_max_mm": [5100, 100, 100]},
           {"element_id": "2", "category": "OST_PipeCurves",
            "p0_mm": [0, 0, 0], "p1_mm": [5000, 0, 0],
            "section_radius_mm": 100.0, "section_round": True,
            "bbox_min_mm": [-100, -100, -100], "bbox_max_mm": [5100, 100, 100]}]
    v = R.build_review(_rep(els))
    row = v["top_findings"][0]
    assert row["pair_kind"] == "coincident_duplicate"
    assert row["severity"] == "критично"
    assert "удалением" in row["text"]
    assert v["summary"]["duplicates"] == 1


def test_a_bbox_only_duplicate_never_tells_you_to_delete():
    """Стене ось запрещена (ревью №2), оболочка — габаритный бокс. Совпавшие
    боксы остаются лучшей догадкой о дубликате, но ДОКАЗАТЕЛЬСТВА совпадения
    тел у нас нет: две диагонали квадрата дают ровно такой же бокс. Значит
    строка не смеет содержать разрушительного указания.
    """
    els = [{"element_id": "1", "category": "OST_Walls",
            "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [5000, 200, 3000]},
           {"element_id": "2", "category": "OST_Walls",
            "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [5000, 200, 3000]}]
    v = R.build_review(_rep(els))
    row = v["top_findings"][0]
    assert row["pair_kind"] == "coincident_duplicate"
    assert row["severity"] == "критично", "находка не пропала и не подешевела"
    assert v["summary"]["duplicates"] == 1
    assert "удал" not in row["text"].lower(), row["text"]
    assert "габарит" in row["text"].lower(), row["text"]
    assert "сверить" in row["text"].lower(), row["text"]


def test_the_summary_hint_does_not_promise_deletion_for_every_duplicate():
    """Тот же закон на уровне сводки: «дубликаты — чинится удалением» стояло
    над счётчиком, в который попадают и недоказанные пары."""
    els = [{"element_id": "1", "category": "OST_Walls",
            "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [5000, 200, 3000]},
           {"element_id": "2", "category": "OST_Walls",
            "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [5000, 200, 3000]}]
    hint = R.build_review(_rep(els))["summary"]["duplicates_hint"]
    assert "габарит" in hint.lower() and "сверить" in hint.lower(), hint


def test_no_row_ever_orders_a_deletion_without_the_proof():
    """Закон, а не пример: разрушительное указание допустимо ТОЛЬКО там, где
    детектор доказал совпадение тел. Сцена нарочно смешанная — доказанные
    дубликаты, недоказанные, диагонали и обычные пересечения разом."""
    def pipe(eid, p0, p1, r=100.0):
        xs, ys, zs = (p0[0], p1[0]), (p0[1], p1[1]), (p0[2], p1[2])
        return {"element_id": eid, "category": "OST_PipeCurves",
                "p0_mm": list(p0), "p1_mm": list(p1),
                "section_radius_mm": r, "section_round": True,
                "bbox_min_mm": [min(xs) - r, min(ys) - r, min(zs) - r],
                "bbox_max_mm": [max(xs) + r, max(ys) + r, max(zs) + r]}

    els = [pipe("1", (0, 0, 0), (5000, 0, 0)),          # доказанный дубликат…
           pipe("2", (0, 0, 0), (5000, 0, 0)),          # …вторая половина пары
           pipe("3", (0, 8000, 0), (4000, 12000, 0), 200.0),   # диагонали
           pipe("4", (4000, 8000, 0), (0, 12000, 0), 200.0),
           {"element_id": "5", "category": "OST_Walls",
            "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [5000, 200, 3000]},
           {"element_id": "6", "category": "OST_Walls",   # дубликат по боксу
            "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [5000, 200, 3000]},
           {"element_id": "7", "category": "OST_Walls",   # обычное пересечение
            "bbox_min_mm": [100, 0, 0], "bbox_max_mm": [5000, 200, 3000]}]
    rep = _rep(els)
    by_id = {f["finding_id"]: f for f in rep["findings"]}
    v = R.build_review(rep)
    assert len(v["top_findings"]) == len(by_id) > 5, "сцена обеднела"
    for row in v["top_findings"]:
        if "удал" in row["text"].lower():
            assert D.duplicate_claim_is_proven(by_id[row["finding_id"]]), row
    assert any("удалением" in r["text"] for r in v["top_findings"]), (
        "доказанный дубликат перестал говорить, что с ним делать")


def test_every_row_carries_both_element_ids_for_the_frontend():
    els = [{"element_id": "10", "category": "OST_CableTray",
            "p0_mm": [0, 0, 0], "p1_mm": [1000, 0, 0],
            "params": {"RBS_CABLETRAY_WIDTH_PARAM": 200.0,
                       "RBS_CABLETRAY_HEIGHT_PARAM": 100.0},
            "bbox_min_mm": [-10, -110, -60], "bbox_max_mm": [1010, 110, 60]},
           {"element_id": "20", "category": "OST_Walls",
            "bbox_min_mm": [400, -200, -200], "bbox_max_mm": [600, 200, 200]}]
    v = R.build_review(_rep(els))
    assert v["top_findings"], "лоток сквозь стену не найден"
    for row in v["top_findings"]:
        assert row["a_element_id"] and row["b_element_id"]
    assert "Лоток 10" in v["top_findings"][0]["text"]


def test_grouping_is_by_element_because_that_is_what_is_worked_on():
    """У проектировщика в работе ЭЛЕМЕНТ, а не пара: элемент несёт список
    СВОИХ конфликтов, и обе стороны пары попадают в группировку."""
    els = TWO_WALLS + [{"element_id": "3", "category": "OST_Walls",
                        "bbox_min_mm": [200, 0, 0],
                        "bbox_max_mm": [5000, 200, 3000]}]
    v = R.build_review(_rep(els))
    by_id = {e["element_id"]: e for e in v["elements"]}
    assert set(by_id) == {"1", "2", "3"}
    assert by_id["1"]["conflict_total"] == 2
    assert all(c["with_element_id"] != "1" for c in by_id["1"]["conflicts"])


def test_incomplete_search_is_shouted_not_whispered():
    """Отчёт с невидимыми элементами не смеет выглядеть исчерпывающим."""
    els = [{"element_id": "w", "category": "OST_Walls",
            "p0_mm": [0, 0, 0], "p1_mm": [5000, 0, 0], "params": {}},
           {"element_id": "p", "category": "OST_PipeCurves",
            "p0_mm": [0, 0, 0], "p1_mm": [1000, 0, 0],
            "params": {"RBS_PIPE_OUTER_DIAMETER": 114.3},
            "bbox_min_mm": [-58, -58, -58], "bbox_max_mm": [1058, 58, 58]}]
    v = R.build_review(_rep(els))
    assert v["summary"]["search_complete"] is False
    assert "неполон" in v["summary"]["search_incomplete_note"]
    assert "ВНИМАНИЕ" in R.to_markdown(v)


def test_labels_are_class_names_not_family_names():
    """Словарь закрыт классами `KIND_TABLE`. Имён типов и семейств в нём нет
    и быть не может — это запрет оператора, а не стилистика."""
    from kukai.clash import hulls as H
    labels = {v.label for v in H.KIND_TABLE.values() if v.eligible and v.label}
    missing = sorted(l for l in labels if l not in R.LABEL_RU)
    assert not missing, f"пригодные классы без русского имени: {missing}"
    assert not any("НР_" in v or "_ВТ_" in v for v in R.LABEL_RU.values()), (
        "в словаре имя типа/семейства — это хардкод под одну модель")
