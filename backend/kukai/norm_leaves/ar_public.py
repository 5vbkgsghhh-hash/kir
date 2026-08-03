"""АР — Общественные здания (СП 118.13330.2022) — curated norm leaves.

Every leaf below is grounded against the real ``data/norms.db`` corpus (see
tests/test_norm_tree.py's load-bearing grounding invariant, and the self-check at
the bottom of this module): the ``citation_anchor`` is a REAL fragment of
СП 118.13330.2022, and — for Ярус 1 — the ``threshold_token`` is verified present
in the grounded window. A leaf that could not be grounded was dropped, not shipped.

Ярус 1 (deterministic — threshold maps onto an available extractor fact):
  - room.height_admin        — высота административных/служебных помещений ≥ 2,7 м
  - room.height_corridor     — высота коридоров/холлов для посетителей ≥ 2,4 м
  - room.vestibule_area      — площадь вестибюля ≥ 18 м²
  - room.ward_area           — площадь палаты (стационар/изолятор) ≥ 12 м²
  - room.medcabinet_area     — площадь медицинского кабинета ≥ 12 м²
  - room.religious_room_area — площадь помещения для религиозных обрядов ≥ 12 м²

Ярус 2 (grounded model-assist — the requirement is real but the current C# model-
facts extractor (kukai/norm_control.py: MODEL_FACTS_CS) has no matching fact; each
check_question_ru notes the exact extractor extension that would promote it to
Ярус 1):
  - room.corridor_width_edu  — needs room WIDTH (rooms currently expose only
                                area_m2/height_m, not width)
  - stair.landing_ge_march   — relational (landing width vs march width), plus needs
                                a separate landing_width_m fact (stair only exposes
                                the run's width_m)
  - stair.landing_length     — needs a landing_length_m fact (not extracted)
  - door.cabin_width         — needs the door's serving-room category/type (to tell
                                a restroom/shower-cabin door from any other door;
                                the extractor only exposes width_m/height_m/label)
  - stair.guard_height       — needs a guard/railing HEIGHT fact entirely (no
                                element_kind for railings exists yet; OST_Stairs*
                                Railing would need its own extractor branch)

4.27's height list carves out several categories (admin/service 2,7 м; occupied-but-
secondary 2,6 м; visitor corridors/halls 2,4 м; auxiliary corridors/rooms 2,2 м) as
permitted minima under 4.26's general 3 м baseline for newly-designed, permanently/
mass-occupied rooms. Only the two categories with an unambiguous, low-collision
`applies_when` room-label hook (кабинет → admin; коридор → corridor) are curated
here as Ярус 1; the 2,6 м / 2,2 м bands were deliberately left out — a plain
"коридор" or unlabelled-room substring match would misfire between the 2,4 м
(visitor) and 2,2 м (auxiliary) corridor bands, so shipping a leaf for those two
would trade a false-confidence "review" verdict for what should stay a documented
gap.
"""
from __future__ import annotations

from kukai.norm_tree import NormLeaf, Requirement

_SP118 = "СП 118.13330.2022"


LEAVES: list[NormLeaf] = [
    # ── Ярус 1 — deterministic ──────────────────────────────────────────────
    NormLeaf(
        id="ar.public.room.height_admin",
        title_ru="Высота административных и служебных помещений",
        element_kind="room", categories=("OST_Rooms",), norm_doc=_SP118,
        coarse_kw="административных и служебных",
        citation_anchor="2,7 - в административных и служебных помещениях",
        topic_keywords=("высота", "кабинет", "администрат", "офис", "служебн"),
        requirement=Requirement("height_m", "min", 2.7, "м", "2,7", applies_when="кабинет"),
        severity="review",
    ),
    NormLeaf(
        id="ar.public.room.height_corridor",
        title_ru="Высота коридоров и холлов для посетителей",
        element_kind="room", categories=("OST_Rooms",), norm_doc=_SP118,
        coarse_kw="в коридорах", citation_anchor="2,4 - в коридорах",
        topic_keywords=("высота", "коридор", "холл"),
        requirement=Requirement("height_m", "min", 2.4, "м", "2,4", applies_when="коридор"),
        severity="review",
    ),
    NormLeaf(
        id="ar.public.room.vestibule_area",
        title_ru="Площадь вестибюля",
        element_kind="room", categories=("OST_Rooms",), norm_doc=_SP118,
        coarse_kw="вестибюля", citation_anchor="не менее 18 м2 суммарной площади",
        topic_keywords=("вестибюль", "площадь вестибюля"),
        requirement=Requirement("area_m2", "min", 18.0, "м²", "18 м2", applies_when="вестибюл"),
        severity="review",
    ),
    NormLeaf(
        id="ar.public.room.ward_area",
        title_ru="Минимальная площадь палаты (стационар/изолятор)",
        element_kind="room", categories=("OST_Rooms",), norm_doc=_SP118,
        coarse_kw="палаты для взрослых",
        citation_anchor="палаты для взрослых в стационаре, изоляторе",
        topic_keywords=("палата", "стационар", "изолятор"),
        requirement=Requirement("area_m2", "min", 12.0, "м²", "12 м2", applies_when="палат"),
        severity="review",
    ),
    NormLeaf(
        id="ar.public.room.medcabinet_area",
        title_ru="Минимальная площадь медицинского кабинета",
        element_kind="room", categories=("OST_Rooms",), norm_doc=_SP118,
        coarse_kw="медицинского кабинета",
        citation_anchor="Минимальную площадь медицинского кабинета",
        topic_keywords=("медицинский кабинет", "медпункт"),
        requirement=Requirement("area_m2", "min", 12.0, "м²", "12 м2", applies_when="медицинск"),
        severity="review",
    ),
    NormLeaf(
        id="ar.public.room.religious_room_area",
        title_ru="Площадь помещения для религиозных обрядов",
        element_kind="room", categories=("OST_Rooms",), norm_doc=_SP118,
        coarse_kw="религиозных обрядов",
        citation_anchor="для проведения религиозных обрядов",
        topic_keywords=("религиозн", "молельная", "обряд"),
        requirement=Requirement("area_m2", "min", 12.0, "м²", "12 м2", applies_when="религиозн"),
        severity="review",
    ),

    # ── Ярус 2 — grounded model-assist (no matching extractor fact yet) ────
    NormLeaf(
        id="ar.public.room.corridor_width_edu",
        title_ru="Ширина коридора/рекреации у учебных помещений",
        element_kind="room", categories=("OST_Rooms",), norm_doc=_SP118,
        coarse_kw="коридора шириной", citation_anchor="коридора шириной не менее 4,0 м",
        topic_keywords=("коридор", "рекреация", "ширина коридора", "учебное помещение"),
        check_question_ru=(
            "Ширина рекреации или коридора у входа в учебное помещение вместимостью от 20 "
            "обучающихся (классно-урочная система) — не менее 4,0 м?"
        ),
        severity="review",
    ),
    NormLeaf(
        id="ar.public.stair.landing_ge_march",
        title_ru="Ширина лестничной площадки не менее ширины марша",
        element_kind="stair", categories=("OST_Stairs",), norm_doc=_SP118,
        coarse_kw="лестничных площадок",
        citation_anchor="Ширина лестничных площадок должна быть не менее ширины марша",
        topic_keywords=("лестница", "лестничная площадка", "марш"),
        check_question_ru="Ширина лестничной площадки не менее ширины марша лестницы?",
        severity="review",
    ),
    NormLeaf(
        id="ar.public.stair.landing_length",
        title_ru="Длина промежуточной лестничной площадки",
        element_kind="stair", categories=("OST_Stairs",), norm_doc=_SP118,
        coarse_kw="Промежуточная площадка",
        citation_anchor="марше лестницы должна иметь длину не менее 1 м",
        topic_keywords=("лестница", "промежуточная площадка", "марш"),
        check_question_ru="Длина промежуточной площадки в прямом марше лестницы — не менее 1 м?",
        severity="review",
    ),
    NormLeaf(
        id="ar.public.door.cabin_width",
        title_ru="Ширина двери кабины уборной/душевой",
        element_kind="door", categories=("OST_Doors",), norm_doc=_SP118,
        coarse_kw="кабин уборных и душевых",
        citation_anchor="Для кабин уборных и душевых минимальную ширину дверного полотна",
        topic_keywords=("уборная", "душевая", "кабина", "дверь кабины"),
        check_question_ru=(
            "Ширина полотна двери кабины уборной/душевой — не менее 0,8 м (ширина проёма в свету "
            "— не менее 0,75 м; допускается 0,7 м / 0,65 м при реконструкции, капремонте, смене "
            "функционального назначения помещения)?"
        ),
        severity="review",
    ),
    NormLeaf(
        id="ar.public.stair.guard_height",
        title_ru="Высота ограждений лестниц и пандусов внутри здания",
        element_kind="stair", categories=("OST_Stairs",), norm_doc=_SP118,
        coarse_kw="ограждений внутри здания",
        citation_anchor="ограждений внутри здания, в том числе лестниц и пандусов",
        topic_keywords=("ограждение", "поручень", "лестница", "пандус"),
        check_question_ru=(
            "Высота ограждения лестниц/пандусов внутри здания — не менее 0,9 м (не менее 1,2 м — "
            "при перепаде отметок пола более 1,0 м, просвете между маршами более 0,3 м, или в "
            "помещениях с возможным пребыванием детей)?"
        ),
        severity="review",
    ),
]


if __name__ == "__main__":
    # Self-check (also exercised by tests/test_norm_tree.py's grounding invariant
    # once this module is wired into norm_tree.ROOT): every leaf must ground, and
    # every Ярус-1 threshold token must appear in the grounded window.
    from kukai.norm_control import ground_citation

    ok = True
    for lf in LEAVES:
        cite = ground_citation(lf)
        if not cite:
            ok = False
            print(f"UNGROUNDED: {lf.id} — anchor {lf.citation_anchor!r} not found")
            continue
        if lf.requirement is not None and lf.requirement.threshold_token not in cite:
            ok = False
            print(f"TOKEN MISMATCH: {lf.id} — {lf.requirement.threshold_token!r} not in {cite!r}")
    print("ALL_GROUNDED", ok, len(LEAVES))
