"""Пожарная безопасность — эвакуация (СП 1.13130.2020). Curated leaves (Phase 5 data).

Priority per operator brief: the extractor (kukai.norm_control.MODEL_FACTS_CS) already
gives door/stair geometry, so evacuation exit width, stair march width and riser/tread
limits close as Ярус 1 (deterministic) leaves. Corridor width and path-length rules are
real, quantified requirements too, but the extractor has NO corridor-width or
path/distance fact yet — those stay Ярус 2 (grounded model-assist) until the extractor
grows a "path"/"corridor" fact (see module-level NOTE below).

Every anchor below is verified against data/norms.db by tests/test_norm_tree.py's
grounding invariant (kukai.norm_control.ground_citation) — a fabricated/mismatched
anchor fails the build.

NOTE — extractor extensions this discipline would benefit from:
  * corridor / path width (no "corridor" or "path" element_kind exists yet; a room
    modelled as a corridor only exposes area_m2/height_m, not its narrowest width) —
    would need a new fact, e.g. a min cross-section width computed from the room's
    boundary geometry (bounding-box-minus-recesses), exposed as `room.width_m` or a
    new `corridor` kind.
  * evacuation path length / distance-to-exit (door-to-stair, room-to-exit) — needs a
    routed-distance fact (shortest walkable path along the model's path network), not
    a straight-line measurement; currently nothing in MODEL_FACTS_CS computes this.
"""
from __future__ import annotations

from kukai.norm_tree import NormLeaf, Requirement

_SP1 = "СП 1.13130.2020"


LEAVES: list[NormLeaf] = [
    # ── Ярус 1 — deterministic (door/stair facts already extracted) ─────────

    NormLeaf(
        id="fire.evac.door.exit_width",
        title_ru="Ширина дверного проёма эвакуационного выхода",
        element_kind="door", categories=("OST_Doors",), norm_doc=_SP1,
        coarse_kw="эвакуационных",
        citation_anchor="Ширина эвакуационных выходов должна быть, как правило, не менее 0,8 м",
        topic_keywords=("эвакуация", "эвакуационный выход", "ширина двери", "ширина выхода", "дверь"),
        requirement=Requirement("width_m", "min", 0.8, "м", "0,8 м"),
        severity="review",
    ),
    NormLeaf(
        id="fire.evac.door.exit_height",
        title_ru="Высота дверного проёма эвакуационного выхода",
        element_kind="door", categories=("OST_Doors",), norm_doc=_SP1,
        coarse_kw="эвакуационных",
        citation_anchor="Высота эвакуационных выходов в свету должна быть, как правило, не менее 1,9 м",
        topic_keywords=("эвакуация", "эвакуационный выход", "высота двери", "высота выхода", "дверь"),
        requirement=Requirement("height_m", "min", 1.9, "м", "1,9 м"),
        severity="review",
    ),
    NormLeaf(
        id="fire.evac.stair.march_width_baseline",
        title_ru="Минимальная ширина марша эвакуационной лестницы (общий случай)",
        element_kind="stair", categories=("OST_Stairs",), norm_doc=_SP1,
        coarse_kw="остальных случаев",
        citation_anchor="е) 0,9 м - для всех остальных случаев",
        topic_keywords=("лестница", "марш", "ширина лестницы", "ширина марша", "эвакуация"),
        requirement=Requirement("width_m", "min", 0.9, "м", "0,9 м"),
        severity="review",
    ),
    NormLeaf(
        id="fire.evac.stair.riser_max",
        title_ru="Максимальная высота ступени эвакуационной лестницы",
        element_kind="stair", categories=("OST_Stairs",), norm_doc=_SP1,
        coarse_kw="ступени",
        citation_anchor="высота ступени - не более 22 см и не менее 5 см",
        topic_keywords=("лестница", "ступень", "подступенок", "высота ступени", "эвакуация"),
        requirement=Requirement("riser_m", "max", 0.22, "м", "22 см"),
        severity="review",
    ),
    NormLeaf(
        id="fire.evac.stair.tread_min",
        title_ru="Минимальная ширина проступи эвакуационной лестницы",
        element_kind="stair", categories=("OST_Stairs",), norm_doc=_SP1,
        coarse_kw="проступи",
        citation_anchor="ширина проступи - как правило, не менее 25 см",
        topic_keywords=("лестница", "проступь", "ступень", "ширина проступи", "эвакуация"),
        requirement=Requirement("tread_m", "min", 0.25, "м", "25 см"),
        severity="review",
    ),

    # ── Ярус 2 — grounded model-assist (fact not in the extractor yet) ──────

    NormLeaf(
        id="fire.evac.corridor.min_width",
        title_ru="Минимальная ширина пути эвакуации (коридора)",
        element_kind="room", categories=("OST_Rooms",), norm_doc=_SP1,
        coarse_kw="пандусов",
        citation_anchor="Ширина горизонтальных участков путей эвакуации и пандусов должна быть не менее",
        topic_keywords=("коридор", "ширина коридора", "путь эвакуации", "эвакуация"),
        check_question_ru=(
            "Ширина коридора/горизонтального участка пути эвакуации в модели — не менее "
            "1,0 м (не менее 1,2 м, если по этому пути могут эвакуироваться более 50 человек; "
            "не менее 0,7 м только для прохода к одиночному рабочему месту)?"
        ),
        severity="review",
    ),
    NormLeaf(
        id="fire.evac.path.residential_distance",
        title_ru="Расстояние от двери квартиры до лестничной клетки/выхода наружу",
        element_kind="door", categories=("OST_Doors",), norm_doc=_SP1,
        coarse_kw="квартир",
        citation_anchor="не должно превышать 12 м",
        topic_keywords=("расстояние", "путь эвакуации", "коридор", "квартира", "эвакуация"),
        check_question_ru=(
            "В секции жилого здания: расстояние от двери наиболее удалённой квартиры до "
            "выхода непосредственно наружу, вестибюля, лестничной клетки или тамбура — "
            "не более 12 м (если коридор/холл на этом пути не имеет оконного проёма площадью "
            "не менее 1,2 м2 в торце или системы противодымной вентиляции; иначе — по таблице 3 "
            "СП 1.13130.2020, как для тупикового коридора)?"
        ),
        severity="review",
    ),
]
