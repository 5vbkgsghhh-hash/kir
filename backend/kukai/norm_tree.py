"""Норм-дерево — the spine of comprehensive normcontrol (Phase 5 architecture).

A NORM DECISION TREE is the shared spine: a hierarchy of domains (discipline →
subtopic) whose leaves are checkable requirements. ONE traversal serves all three
operations — route(query)→docs (smart-inject / Path B), leaves_for_category(cat)→
checks (deterministic audit / Path A), coverage()→honest "не покрыто" map.

Design: small FIXED engine (this module's functions) + growing DATA (the ROOT tree).
Closing a new norm = adding a LEAF (data), not code. Two tiers live on the same tree:
  * Ярус 1 — a leaf WITH a Requirement: deterministic quantified check (no model).
  * Ярус 2 — a leaf with only an anchor + check_question: grounded model-assist (the
    model checks REAL scoped clause vs REAL extracted facts; citation shown; candidate).

Every leaf's citation_anchor is verified against norms.db by a build-time test
(tests/test_norm_tree.py) — a fabricated anchor / mismatched number fails the test, so
coverage can grow (incl. via Sonnet curation) without ever shipping a fabricated norm.

Reuses kukai/norm_control.py: ground_citation (tight verified-anchor window),
evaluate_rule (deterministic eval), MODEL_FACTS_CS (comprehensive extractor). Full
spec: /root/kukai-normcontrol-tree-design.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ── data model (all DATA — grows by curation, not code) ──────────────────────

@dataclass(frozen=True)
class Requirement:
    """Present on a leaf ⇒ Ярус 1 (deterministic quantified rule)."""
    param: str                          # facts key: "area_m2" | "height_m" | "width_m" | ...
    predicate: str                      # "min" | "max"
    threshold: float
    unit: str                           # "м²" | "м"
    threshold_token: str                # the number as it appears in the clause ("8 м2")
    applies_when: Optional[str] = None   # label substring filter ("кухн", "гостин")


@dataclass(frozen=True)
class NormLeaf:
    """A single checkable requirement bound to a norm clause. The `norm_doc`,
    `coarse_kw`, `citation_anchor` fields are the exact contract of
    norm_control.ground_citation, so a leaf grounds itself with the built helper."""
    id: str
    title_ru: str
    element_kind: str                    # facts key from the extractor: "room"|"door"|...
    categories: tuple[str, ...]          # Revit categories, e.g. ("OST_Rooms",)
    norm_doc: str                        # "СП 54.13330.2016" — a doc present in norms.db
    coarse_kw: str                       # for ground_citation
    citation_anchor: str                 # verified clause fragment (normalized whitespace)
    topic_keywords: tuple[str, ...]      # for routing: ("кухня","кухни","kitchen")
    requirement: Optional[Requirement] = None   # set ⇒ Ярус 1; None ⇒ Ярус 2
    check_question_ru: str = ""          # Ярус 2: what the model verifies against the clause
    severity: str = "review"

    @property
    def tier(self) -> int:
        return 1 if self.requirement is not None else 2


@dataclass(frozen=True)
class NormNode:
    """A domain node (discipline / subtopic)."""
    id: str
    title_ru: str
    keywords: tuple[str, ...]            # routing keywords
    norm_docs: tuple[str, ...] = ()
    children: tuple["NormNode", ...] = ()
    leaves: tuple[NormLeaf, ...] = ()


# ── the tree v0 — all disciplines are NODES; leaves grow by curation ─────────
# Only corpus-VERIFIED leaves are included (the 3 СП 54 rules, migrated to Ярус 1).
# Other disciplines are nodes (doc + keywords) with no leaves yet — coverage() shows
# them as gaps; the Sonnet fleet curates their leaves against this locked schema.

_SP54 = "СП 54.13330.2016"

_AR_RESIDENTIAL = NormNode(
    id="ar.residential", title_ru="Жилые здания (СП 54)",
    keywords=("жилой", "жилые", "квартир", "жилищ"),
    norm_docs=(_SP54,),
    leaves=(
        NormLeaf(
            id="ar.residential.room.height", title_ru="Высота жилых помещений",
            element_kind="room", categories=("OST_Rooms",), norm_doc=_SP54,
            coarse_kw="высот", citation_anchor="не менее 2,5 м",
            topic_keywords=("высота", "потолок", "height"),
            requirement=Requirement("height_m", "min", 2.5, "м", "2,5 м"),
            severity="review",
        ),
        NormLeaf(
            id="ar.residential.room.kitchen_area", title_ru="Площадь кухни",
            element_kind="room", categories=("OST_Rooms",), norm_doc=_SP54,
            coarse_kw="кухни", citation_anchor="кухни — 8 м2",
            topic_keywords=("кухня", "кухни", "kitchen"),
            requirement=Requirement("area_m2", "min", 8.0, "м²", "8 м2", applies_when="кухн"),
            severity="review",
        ),
        NormLeaf(
            id="ar.residential.room.living_area", title_ru="Площадь общей жилой комнаты",
            element_kind="room", categories=("OST_Rooms",), norm_doc=_SP54,
            coarse_kw="жилой комнаты", citation_anchor="жилой комнаты в однокомнатной квартире — 14 м2",
            topic_keywords=("гостиная", "жилая комната", "общая комната"),
            requirement=Requirement("area_m2", "min", 14.0, "м²", "14 м2", applies_when="гостин"),
            severity="review",
        ),
    ),
)

_SKELETON = NormNode(
    id="root", title_ru="Нормы", keywords=(),
    children=(
        NormNode(id="ar", title_ru="Архитектура (АР)", keywords=("архитектур", "ар"),
                 children=(
                     _AR_RESIDENTIAL,
                     NormNode(id="ar.public", title_ru="Общественные здания (СП 118)",
                              keywords=("общественн", "административн", "офис"),
                              norm_docs=("СП 118.13330.2022",)),
                 )),
        NormNode(id="kr", title_ru="Конструкции (КР)", keywords=("конструкц", "кр", "несущ"),
                 children=(
                     NormNode(id="kr.monolith", title_ru="Монолитные ЖБ (СП 63)",
                              keywords=("монолит", "железобетон", "жб", "армирован", "защитный слой"),
                              norm_docs=("СП 63.13330.2018",)),
                     NormNode(id="kr.steel", title_ru="Стальные конструкции (СП 16)",
                              keywords=("металл", "сталь", "профиль", "балка"),
                              norm_docs=("СП 16.13330.2017",)),
                     NormNode(id="kr.loads", title_ru="Нагрузки (СП 20)",
                              keywords=("нагрузк", "снег", "ветров"),
                              norm_docs=("СП 20.13330.2016",)),
                 )),
        NormNode(id="ov", title_ru="Отопление-вентиляция (СП 60)",
                 keywords=("отоплен", "вентиляц", "овик", "ов"),
                 norm_docs=("СП 60.13330.2020",)),
        NormNode(id="vk", title_ru="Водоснабжение-канализация (СП 30/32)",
                 keywords=("водоснабж", "канализац", "вк"),
                 norm_docs=("СП 30.13330.2020", "СП 32.13330.2018")),
        NormNode(id="eom", title_ru="Электрика (ПУЭ, СП 256)",
                 keywords=("электр", "кабель", "розетк", "пуэ", "эом"),
                 norm_docs=("ПУЭ-7", "СП 256.1325800.2016")),
        NormNode(id="fire", title_ru="Пожарная безопасность (СП 1.13130)",
                 keywords=("пожар", "эвакуац", "огнестойк", "дым"),
                 norm_docs=("СП 1.13130.2020",)),
        NormNode(id="thermal", title_ru="Теплотехника (СП 50)",
                 keywords=("теплов", "теплопередач", "теплозащит"),
                 norm_docs=("СП 50.13330.2012",)),
        NormNode(id="bim", title_ru="BIM/ТИМ (СП 333)",
                 keywords=("bim", "бим", "тим", "информационн модел"),
                 norm_docs=("СП 333.1325800.2020",)),
    ),
)


# ── assembly — attach curated per-discipline leaf modules to the skeleton ────
from dataclasses import replace as _replace  # noqa: E402
import importlib as _il  # noqa: E402
import pkgutil as _pk  # noqa: E402


def _skeleton_node_ids(node: NormNode) -> set:
    ids = {node.id}
    for c in node.children:
        ids |= _skeleton_node_ids(c)
    return ids


def _curated_leaves() -> list:
    out: list = []
    try:
        from kukai import norm_leaves as _pkg
        for _m in _pk.iter_modules(_pkg.__path__):
            try:
                _mod = _il.import_module(f"kukai.norm_leaves.{_m.name}")
                _lv = getattr(_mod, "LEAVES", None)
                if isinstance(_lv, list):
                    out.extend(_lv)
            except Exception:  # noqa: BLE001 - one bad leaf module must not break the tree
                pass
    except Exception:  # noqa: BLE001
        pass
    return out


def _attach(node: NormNode, by_node: dict) -> NormNode:
    return _replace(
        node,
        children=tuple(_attach(c, by_node) for c in node.children),
        leaves=node.leaves + tuple(by_node.get(node.id, ())),
    )


def _assemble(skeleton: NormNode) -> NormNode:
    ids = _skeleton_node_ids(skeleton)
    by_node: dict = {}
    for lf in _curated_leaves():
        parts = lf.id.split(".")
        target = next((".".join(parts[:i]) for i in range(len(parts), 0, -1)
                       if ".".join(parts[:i]) in ids), None)
        if target:
            by_node.setdefault(target, []).append(lf)
    return _attach(skeleton, by_node)


ROOT: NormNode = _assemble(_SKELETON)


# ── engine — small, fixed, pure (one traversal serves all three operations) ──

def all_nodes(node: NormNode = ROOT) -> list[NormNode]:
    out = [node]
    for c in node.children:
        out.extend(all_nodes(c))
    return out


def all_leaves(node: NormNode = ROOT) -> list[NormLeaf]:
    out = list(node.leaves)
    for c in node.children:
        out.extend(all_leaves(c))
    return out


def route(query: str, node: NormNode = ROOT) -> list[NormNode]:
    """Nodes whose keywords appear in the query (deterministic router, Path B).
    Returns the deepest matching nodes across all branches (an element/query can
    activate several)."""
    q = (query or "").lower()
    hits: list[NormNode] = []
    for n in all_nodes(node):
        node_hit = bool(n.keywords) and any(kw in q for kw in n.keywords)
        leaf_hit = any(kw.lower() in q for lf in n.leaves for kw in lf.topic_keywords)
        if node_hit or leaf_hit:
            hits.append(n)
    return hits


def _ancestor_docs(target: NormNode, node: NormNode = ROOT, trail: tuple = ()) -> tuple[str, ...]:
    trail = trail + tuple(node.norm_docs)
    if node.id == target.id:
        return trail
    for c in node.children:
        r = _ancestor_docs(target, c, trail)
        if r is not None:
            return r
    return None  # type: ignore[return-value]


def docs_for_query(query: str) -> list[str]:
    """norm_docs of the routed nodes (+ their ancestors), de-duplicated, order-preserving.
    This is the SCOPE for smart-inject: retrieve ONLY from these docs, not the whole base."""
    seen: dict[str, None] = {}
    for n in route(query):
        for d in (_ancestor_docs(n) or ()) + n.norm_docs:
            if d and d not in seen:
                seen[d] = None
    # a routed node already includes its own docs via trail; keep leaf-node docs too
    for n in route(query):
        for d in n.norm_docs:
            seen.setdefault(d, None)
    return list(seen.keys())


def leaves_for_category(category: str, node: NormNode = ROOT) -> list[NormLeaf]:
    """All leaves whose Revit categories include `category` (Path A audit)."""
    return [lf for lf in all_leaves(node) if category in lf.categories]


def leaves_for_query(query: str) -> list[NormLeaf]:
    """Leaves under the routed subtrees (Path B, when checking a specific topic)."""
    out: list[NormLeaf] = []
    for n in route(query):
        out.extend(all_leaves(n))
    return out


def coverage(node: NormNode = ROOT) -> dict:
    """Honest coverage map: per top-level discipline, how many Ярус-1 / Ярус-2 leaves
    and which element kinds are covered. Nodes with zero leaves are visible gaps."""
    out: dict[str, dict] = {}
    for disc in node.children:
        leaves = all_leaves(disc)
        out[disc.id] = {
            "title": disc.title_ru,
            "tier1": sum(1 for lf in leaves if lf.tier == 1),
            "tier2": sum(1 for lf in leaves if lf.tier == 2),
            "kinds": sorted({lf.element_kind for lf in leaves}),
            "docs": sorted({d for n in all_nodes(disc) for d in n.norm_docs}),
        }
    return out


# ── Path A — deterministic audit over the tree (Ярус 1) + honest coverage ────

def _eval_leaf(leaf: NormLeaf, elements: list, ground_citation, Finding) -> list:
    """Deterministic Ярус-1 check of one leaf against extracted elements. A
    missing value ⇒ not_evaluated (never a silent pass)."""
    req = leaf.requirement
    out: list = []
    citation = None
    for el in elements:
        label = str(el.get("label", el.get("name", "")))
        if req.applies_when and req.applies_when.lower() not in label.lower():
            continue
        raw = el.get(req.param)
        try:
            obs = float(raw) if raw is not None else None
        except (TypeError, ValueError):
            obs = None
        if obs is None:
            verdict, reason = "not_evaluated", f"нет значения '{req.param}'"
        elif (obs >= req.threshold if req.predicate == "min" else obs <= req.threshold):
            verdict, reason = "pass", ""
        else:
            op = "≥" if req.predicate == "min" else "≤"
            verdict = "violation"
            reason = f"{obs:g} {req.unit} — требование {op} {req.threshold:g} {req.unit}"
        if verdict == "violation" and citation is None:
            citation = ground_citation(leaf)
        out.append(Finding(
            rule_id=leaf.id, norm_doc=leaf.norm_doc, name_ru=leaf.title_ru,
            element_id=el.get("id"), element_label=label, observed=obs,
            threshold=req.threshold, unit=req.unit, verdict=verdict, reason=reason,
            citation=citation or "",
        ))
    return out


def _tree_coverage_footer(facts: dict) -> str:
    cov = coverage()
    ya1 = sum(c["tier1"] for c in cov.values())
    ya2 = sum(c["tier2"] for c in cov.values())
    kinds = ", ".join(f"{k}:{len(v)}" for k, v in facts.items() if isinstance(v, list)) or "нет"
    gaps = [c["title"] for c in cov.values() if c["tier1"] == 0 and c["tier2"] == 0]
    tail = (f"\n\n— Покрытие: {ya1} правил проверено детерминированно (Ярус 1); "
            f"{ya2} требований Ярус 2 (нужна экспертная сверка / расширение модели данных). "
            f"Элементы модели: {kinds}.")
    if gaps:
        tail += f" Не покрыто вовсе: {', '.join(gaps)}."
    return tail


async def run_tree_audit(bridge_call) -> str:
    """Path A — DETERMINISTIC audit over the tree. Extract PER CATEGORY (isolated
    compilations, so one version-incompatible category can't zero out the rest),
    evaluate every Ярус-1 leaf, append the honest coverage footer + any categories
    that failed to extract. No model in the loop."""
    from kukai.norm_control import (
        _CAT_EXTRACTORS, _element_list, ground_citation, Finding,
        format_normcontrol_report,
    )
    kinds = sorted({lf.element_kind for lf in all_leaves() if lf.requirement is not None})
    facts: dict = {}
    failed: list = []
    for kind in kinds:
        code = _CAT_EXTRACTORS.get(kind)
        if not code:
            continue
        try:
            res = await bridge_call("execute", {"code": code})
        except Exception:  # noqa: BLE001 — a failed extraction must not crash the turn
            res = None
        els, ok = _element_list(res)
        facts[kind] = els
        if not ok:
            failed.append(kind)

    findings: list = []
    for leaf in all_leaves():
        if leaf.requirement is None:      # Ярус 2 — staged (grounded model-assist next)
            continue
        findings.extend(_eval_leaf(leaf, facts.get(leaf.element_kind, []), ground_citation, Finding))
    report = format_normcontrol_report(findings) + _tree_coverage_footer(facts)
    if failed:
        report += (f"\n⚠️ Не удалось извлечь категории: {', '.join(failed)} "
                   f"(несовместимость версии Revit — сообщите разработчику).")
    return report
