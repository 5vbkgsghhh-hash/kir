"""КЛЕШ КАК ЗАПРОС С ОБЛАСТЬЮ, а не как слой хранимых рёбер.

Этот модуль НЕ детектор. Он — граница, за которой клеш входит в граф здания, и
устроен он так, чтобы хранить клеш-рёбра было НЕВОЗМОЖНО, а не просто не
принято. Запрет объявлен структурой (`ClashQuery` отдаёт итератор и не
складывает), а не комментарием: комментарий не переживёт того, кто захочет
«просто закэшировать».

═══════════════════════════════════════════════════════════════════════════
ПОЧЕМУ ЗАПРОС, А НЕ СЛОЙ — ПОРОГ НАЗВАН ЗАРАНЕЕ И ЗАМЕРЕН
═══════════════════════════════════════════════════════════════════════════

`демо-v3`, область `all_physical_diagnostic` (замер команды CLASH, 10.08.2026):

| величина | число |
|---|---|
| узлов (оболочек) | 84 120 |
| рёбер-кандидатов широкой фазы | 770 234 |
| рёбер-находок | 769 630 |
| отчёт о них, ОДИН файл JSON | **666 МБ** |
| пиковая RSS процесса | **2.66 ГБ** |
| время узкой фазы | 38.1 с |
| время самой сетки | **0.81 с** |

Отношение рёбер к узлам — **9.15**. Узкая фаза дороже сетки в **47 раз**.
Предел здесь не поиск соседей, а СПИСОК РЁБЕР: удвоение здания (~170 000 узлов)
требует порядка 10 ГБ только на находки. Граф, который попробует держать
клеш-рёбра рядом с узлами, упрётся в ту же стену — но уже на уровне всего
приложения, а не одного модуля.

═══════════════════════════════════════════════════════════════════════════
РЕБРО КЛЕША ТИПИЗИРОВАНО ДВАЖДЫ — И ЭТО ГЛАВНОЕ ИСПРАВЛЕНИЕ
═══════════════════════════════════════════════════════════════════════════

Сегодняшняя «находка» склеивает ТРИ разных отношения:

**(а) КАСАНИЕ** — общая граница, нулевое проникание. Способ, которым здание
СОБРАНО, а не дефект. Замер: `sob62_fas_r23_v19` — 7 804 касания против 19 523
перекрытий; `snowdon_plumb_v5` — 8 559 против 18 030. На треть всех отношений
пары касаются. Касание — ребро СБОРКИ, его место рядом с узлами навсегда, и
показывать его как находку нельзя.

**(б) ПРОНИКАНИЕ ТЕЛ** — пересечение положительного объёма. Физический
конфликт. Production builders пока outer-only (`exact` = 0 на историческом
корпусе), но dual geometry умеет доказать его пересечением двух
сертифицированных `Inner ⊆ Body`. Поэтому `PROVEN/OVERLAP` существует, но
строится только из opaque verified proof, а не из слова `confirmed`.

**(в) ПЕРЕСЕЧЕНИЕ ОБОЛОЧЕК** — то, что модуль РЕАЛЬНО считает: пересечение двух
КОНСЕРВАТИВНЫХ НАДМНОЖЕСТВ. Это факт о нашем ОПИСАНИИ постройки, не о постройке.

`modality` сегодня размазана по двум модулям и трём полям (`verdict`,
`hull_grade`, `slack`), и ровно на её склейке с `relation` сломались оба
дефекта, чинившиеся 10.08: вакуумный `plate_z_doubling` и ложный
`profile_convexified`.

**ОПРОВЕРЖЕНИЕ — ЭТО РЕБРО, А НЕ ОТСУТСТВИЕ РЕБРА.** Ребро, снятое правилом,
обязано остаться в ответе с ИМЕНЕМ правила; иначе «не нашли» неотличимо от
«не искали», и обе болезни возвращаются. Здесь это условие конструкции:
`ClashRelationEdge` с `REFUTED` без `refuted_by` не строится.

═══════════════════════════════════════════════════════════════════════════
ЧТО ЗАПРОС БЕРЁТ У ГРАФА ВМЕСТО ДОГАДКИ
═══════════════════════════════════════════════════════════════════════════

`resolve.ASSEMBLY_PAIRS` угадывает отношение сборки ПО ПАРЕ ЯРЛЫКОВ
(дверь~стена, импост~панель). Замер: **467 перекрытий из 3 348 (14.0 %)** на
`sob62_r23_v5` отнесены к сборке этой догадкой.

Догадку заменяет ребро `hosted_in`, и данные для него в разборе ЕСТЬ — замер
10.08 по `L0Element.host_id`:

    `sob62_r23_v5`      двери 153/153 (100 %) хозяин `OST_Walls`;
                        окна   31/31  (100 %) хозяин `OST_Walls`
    `sob62_fas_r23_v17` импосты 1 452/1 452 (100 %) хозяин `OST_Walls`;
                        панели    594/1 215 (48.9 %)
    `snowdon_plumb_v5`  двери 143/143, окна 114/114 (100 %)

НО ДОГАДКА ПРОМАХИВАЕТСЯ И В ТУ СТОРОНУ, КОТОРУЮ ЯРЛЫКИ НЕ ОПИСЫВАЮТ, и это
видно только по `host_id`:

* `sob62_fas_r23_v17`: **9 из 14** дверей имеют хозяином `OST_CurtainWallPanels`,
  а не стену;
* `snowdon_plumb_v5`: **89 из 1 425** импостов имеют хозяином панель, а
  **23 из 640** панелей — другую панель;
* `snowdon_plumb_v5`: **21** `OST_GenericModel` и **4** `OST_PlumbingFixtures`
  имеют хозяином `OST_Levels` — ОТМЕТКУ, а не тело. Пары ярлыков такого
  отношения не описывают вовсе, и в графе оно едет отдельным `PLACED_ON_DATUM`.

**И ГЛАВНОЕ ОГРАНИЧЕНИЕ, КОТОРОЕ НЕЛЬЗЯ ЗАМЕСТИ:** `host_id` несёт ответ не
везде. По корпусу висячих ссылок 1 263 из 213 811 (0.59 %), но они СОСРЕДОТОЧЕНЫ:
`snowdon_elec_v1` — **959 из 1 001 (95.8 %)**, четыре снимка Snowdon Plumbing —
**100 %**. Хозяин лежит в СВЯЗАННОМ файле. Поэтому запрос обязан различать
«хозяина нет» и «хозяин вне извлечения», и второй ответ — это ровно тот сигнал,
который делает межраздельную область непустой.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, Iterable, Iterator, Mapping, Sequence

from kukai.clash import detect as clash_detect
from kukai.ir.decompile.building_graph import (
    BuildingGraph,
    GraphBuildError,
    Modality,
    Relation,
)

__all__ = [
    "ClashQuery",
    "ClashRelation",
    "ClashRelationEdge",
    "ClashProofKind",
    "ConstraintVerdict",
    "ClashScope",
    "ScopeCensus",
    "VerifiedClashProof",
    "assembly_relation_of",
    "edge_from_finding",
]


class ClashRelation(str, Enum):
    """ГЕОМЕТРИЧЕСКОЕ отношение оболочек. Ортогонально `Modality`.

    Три значения вместо одного слова «находка» — см. шапку модуля.
    """

    #: Общая граница, нулевое проникание. Способ сборки, не дефект.
    CONTACT = "contact"
    #: Пересечение положительного объёма (или его консервативной надоценки).
    OVERLAP = "overlap"
    #: Разведены. Ответ, который тоже надо уметь произносить.
    SEPARATED = "separated"


class ClashProofKind(str, Enum):
    """The exact theorem a trusted detector proved for one pair."""

    CERTIFIED_INNER_OVERLAP = "certified_inner_overlap"
    CONSERVATIVE_OUTER_SEPARATION = "conservative_outer_separation"
    EXACT_BODY_CONTACT = "exact_body_contact"


class ConstraintVerdict(str, Enum):
    """Whether the requested clearance/interference rule was violated."""

    NOT_EVALUATED = "not_evaluated"
    SATISFIED = "satisfied"
    POSSIBLE_VIOLATION = "possible_violation"
    PROVEN_VIOLATION = "proven_violation"


_VERIFIED_CLASH_PROOF_AUTHORITY = object()


def _freeze_evidence(value: Any, *, path: str = "clash evidence") -> Any:
    """Deep immutable snapshot of JSON-like classifier evidence."""

    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise GraphBuildError(f"{path} contains a non-finite number")
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key, item in sorted(value.items(), key=lambda pair: str(pair[0])):
            if not isinstance(key, str):
                raise GraphBuildError(f"{path} keys must be strings")
            frozen[key] = _freeze_evidence(item, path=f"{path}.{key}")
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(
            _freeze_evidence(item, path=f"{path}[{index}]")
            for index, item in enumerate(value))
    raise GraphBuildError(
        f"{path} contains unsupported {type(value).__name__}")


@dataclass(frozen=True, init=False, slots=True)
class VerifiedClashProof:
    """Opaque in-process capability for a proven geometric relation.

    Public finding fields are audit data and can be edited after JSON
    serialization.  A caller therefore cannot construct this token from a
    plausible ``verdict`` string.  ``edge_from_finding`` mints it only while
    consuming a typed detector result and, for overlap, after validating the
    detector's complete sealed inner-proof chain.

    This is a trust boundary for serialized data, not a Python sandbox: code
    already executing inside this process is trusted.
    """

    kind: ClashProofKind
    relation: ClashRelation
    subject_a: str
    subject_b: str
    evidence_digest: str
    _authority: object = field(repr=False, compare=False)

    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        raise TypeError(
            "VerifiedClashProof is opaque; consume a typed detector finding")

    def valid_for(self, a: str, b: str, relation: ClashRelation) -> bool:
        return (
            self._authority is _VERIFIED_CLASH_PROOF_AUTHORITY
            and self.relation is relation
            and self.subject_a == a
            and self.subject_b == b
            and isinstance(self.evidence_digest, str)
            and len(self.evidence_digest) == 64
            and all(char in "0123456789abcdef"
                    for char in self.evidence_digest)
        )


def _mint_verified_clash_proof(
    *, kind: ClashProofKind, relation: ClashRelation,
    subject_a: str, subject_b: str, evidence_digest: str,
) -> VerifiedClashProof:
    proof = object.__new__(VerifiedClashProof)
    object.__setattr__(proof, "kind", kind)
    object.__setattr__(proof, "relation", relation)
    object.__setattr__(proof, "subject_a", subject_a)
    object.__setattr__(proof, "subject_b", subject_b)
    object.__setattr__(proof, "evidence_digest", evidence_digest)
    object.__setattr__(proof, "_authority", _VERIFIED_CLASH_PROOF_AUTHORITY)
    return proof


@dataclass(frozen=True, slots=True)
class ClashRelationEdge:
    """Клеш-ребро. Живёт ТОЛЬКО внутри ответа на запрос и никогда не хранится."""

    a: str
    b: str
    relation: ClashRelation
    modality: Modality
    #: Relation truth and rule truth are independent.  In particular,
    #: conservative outers can prove SEPARATED while only suggesting that the
    #: true-body clearance is too small.
    constraint_verdict: ConstraintVerdict = ConstraintVerdict.NOT_EVALUATED
    #: Имя ОГРУБЛЕНИЯ либо правила, снявшего ребро. Обязательно при REFUTED.
    refuted_by: str | None = None
    #: Источник оболочки A и B, глубина, нижняя ли это оценка.
    evidence: Mapping[str, Any] = field(default_factory=dict)
    #: In-process proof capability.  It is deliberately not reconstructed
    #: from ``evidence`` and never serialized as authority.
    verified_proof: VerifiedClashProof | None = field(
        default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        for name, subject in (("a", self.a), ("b", self.b)):
            if not isinstance(subject, str) or not subject.strip():
                raise GraphBuildError(
                    f"clash edge {name} must be a non-empty subject key")
        if self.a == self.b:
            raise GraphBuildError("clash edge requires two distinct subjects")
        if not isinstance(self.relation, ClashRelation):
            raise GraphBuildError("clash edge relation must be typed")
        if not isinstance(self.modality, Modality):
            raise GraphBuildError("clash edge modality must be typed")
        if not isinstance(self.constraint_verdict, ConstraintVerdict):
            raise GraphBuildError("constraint_verdict must be typed")
        if self.modality is Modality.REFUTED:
            if (not isinstance(self.refuted_by, str)
                    or not self.refuted_by.strip()):
                raise GraphBuildError(
                    "клеш-ребро REFUTED без имени огрубления неотличимо от "
                    "«не искали» — правило обязано назваться")
        if self.modality is not Modality.REFUTED and self.refuted_by:
            raise GraphBuildError(
                "`refuted_by` при неопровергнутом ребре — ложный след")
        if not isinstance(self.evidence, Mapping):
            raise GraphBuildError("clash edge evidence must be a mapping")
        object.__setattr__(
            self, "evidence", _freeze_evidence(self.evidence))
        if self.modality is Modality.PROVEN:
            if (not isinstance(self.verified_proof, VerifiedClashProof)
                    or not self.verified_proof.valid_for(
                        self.a, self.b, self.relation)):
                raise GraphBuildError(
                    "PROVEN геометрическое ребро требует opaque verified proof")
            if (self.relation is ClashRelation.OVERLAP
                    and self.verified_proof.kind
                    is not ClashProofKind.CERTIFIED_INNER_OVERLAP):
                raise GraphBuildError(
                    "PROVEN overlap требует certified inner overlap")
            if (self.relation is ClashRelation.CONTACT
                    and self.verified_proof.kind
                    is not ClashProofKind.EXACT_BODY_CONTACT):
                raise GraphBuildError(
                    "PROVEN contact требует exact-body contact proof")
            if (self.relation is ClashRelation.SEPARATED
                    and self.verified_proof.kind
                    is not ClashProofKind.CONSERVATIVE_OUTER_SEPARATION):
                raise GraphBuildError(
                    "PROVEN separation требует conservative outer proof")
        elif self.verified_proof is not None:
            raise GraphBuildError(
                "verified proof запрещён у ребра без PROVEN modality")


def _finding_digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def edge_from_finding(
        finding: clash_detect.Finding) -> ClashRelationEdge:
    """Adapt a typed detector result without promoting its JSON strings.

    Relation and proof modality are different axes:

    * certified inner positive-volume overlap -> ``PROVEN/OVERLAP``;
    * outer-only overlap or contact -> ``POSSIBLE``;
    * separation of conservative outer supersets -> ``PROVEN/SEPARATED``.

    The last implication is safe because ``Body ⊆ Outer`` on both sides: if
    the outers are disjoint, the bodies are disjoint.  It says nothing about
    a clearance violation being proven; that remains explicit in evidence.
    """

    if not isinstance(finding, clash_detect.Finding):
        raise GraphBuildError("clash edge adapter requires detector Finding")
    wire = finding.as_dict()
    side_a = wire.get("a")
    side_b = wire.get("b")
    if not isinstance(side_a, Mapping) or not isinstance(side_b, Mapping):
        raise GraphBuildError("detector finding has malformed subjects")
    a = side_a.get("source_element_id")
    b = side_b.get("source_element_id")
    if not isinstance(a, str) or not a or not isinstance(b, str) or not b:
        raise GraphBuildError("detector finding subjects must be non-empty")
    try:
        relation = ClashRelation(str(wire.get("hull_relation")))
    except ValueError as exc:
        raise GraphBuildError("detector finding relation is unsupported") from exc

    proof: VerifiedClashProof | None = None
    modality = Modality.POSSIBLE
    if relation is ClashRelation.OVERLAP and wire.get("verdict") == "confirmed":
        serialized = wire.get("physical_overlap_proof")
        if (isinstance(serialized, Mapping)
                and clash_detect.verify_serialized_physical_overlap_proof(
                    serialized, subject_a=a, subject_b=b)):
            proof_digest = serialized.get("proof_digest")
            if not isinstance(proof_digest, str):
                raise GraphBuildError("confirmed overlap proof lacks digest")
            proof = _mint_verified_clash_proof(
                kind=ClashProofKind.CERTIFIED_INNER_OVERLAP,
                relation=relation, subject_a=a, subject_b=b,
                evidence_digest=proof_digest,
            )
            modality = Modality.PROVEN
    elif relation is ClashRelation.SEPARATED:
        # This capability is minted from the live typed detector object, not
        # from a deserialized mapping.  The digest is an audit address only.
        proof = _mint_verified_clash_proof(
            kind=ClashProofKind.CONSERVATIVE_OUTER_SEPARATION,
            relation=relation, subject_a=a, subject_b=b,
            evidence_digest=_finding_digest({
                "finding_id": wire.get("finding_id"),
                "a": side_a,
                "b": side_b,
                "signed_distance_mm": wire.get("signed_distance_mm"),
                "hull_relation": wire.get("hull_relation"),
            }),
        )
        modality = Modality.PROVEN

    deficit = wire.get("clearance_deficit_mm")
    has_deficit = (
        not isinstance(deficit, bool)
        and isinstance(deficit, (int, float))
        and float(deficit) > 0.0
    )
    if relation is ClashRelation.OVERLAP:
        constraint_verdict = (
            ConstraintVerdict.PROVEN_VIOLATION
            if modality is Modality.PROVEN
            else ConstraintVerdict.POSSIBLE_VIOLATION)
    elif has_deficit:
        # A conservative outer gap is a lower bound on the true-body gap: it
        # proves separation, but not that the bodies fail the clearance.
        constraint_verdict = ConstraintVerdict.POSSIBLE_VIOLATION
    else:
        constraint_verdict = ConstraintVerdict.SATISFIED

    return ClashRelationEdge(
        a=a,
        b=b,
        relation=relation,
        modality=modality,
        constraint_verdict=constraint_verdict,
        evidence={
            "finding_id": wire.get("finding_id"),
            "geometry_verdict": wire.get("verdict"),
            "pair_kind": wire.get("pair_kind"),
            "signed_distance_mm": wire.get("signed_distance_mm"),
            "hull_overlap_depth_mm": wire.get("hull_overlap_depth_mm"),
            "clearance_mm": wire.get("clearance_mm"),
            "clearance_deficit_mm": wire.get("clearance_deficit_mm"),
            "proof_digest": (
                proof.evidence_digest if proof is not None else None),
        },
        verified_proof=proof,
    )


@dataclass(frozen=True, slots=True)
class ScopeCensus:
    """ЗНАМЕНАТЕЛЬ запроса. Без него ответ «клешей нет» не значит ничего.

    Закон переписи CLASH (`eligible = hulled + unsupported + missing_geometry`)
    сходится сегодня по каждой категории каждого из 65 разборов — 0 молчаливых
    выпадений на ~1.03 млн элементов. Здесь тот же закон на узлах ГРАФА.
    """

    nodes_in_scope: int
    nodes_with_hull: int
    refusals: Mapping[str, int]

    def __post_init__(self) -> None:
        for name, value in (
            ("nodes_in_scope", self.nodes_in_scope),
            ("nodes_with_hull", self.nodes_with_hull),
        ):
            if (isinstance(value, bool) or not isinstance(value, int)
                    or value < 0):
                raise GraphBuildError(
                    f"ScopeCensus.{name} must be a non-negative int")
        if not isinstance(self.refusals, Mapping):
            raise GraphBuildError("ScopeCensus.refusals must be a mapping")
        normalized: dict[str, int] = {}
        for reason, count in self.refusals.items():
            if not isinstance(reason, str) or not reason.strip():
                raise GraphBuildError(
                    "ScopeCensus refusal keys must be non-empty strings")
            if (isinstance(count, bool) or not isinstance(count, int)
                    or count < 0):
                raise GraphBuildError(
                    "ScopeCensus refusal counts must be non-negative ints")
            normalized[reason] = count
        object.__setattr__(
            self, "refusals",
            MappingProxyType(dict(sorted(normalized.items()))))
        self.assert_balanced()

    @property
    def refused(self) -> int:
        return sum(self.refusals.values())

    def assert_balanced(self) -> None:
        if self.nodes_with_hull + self.refused != self.nodes_in_scope:
            raise GraphBuildError(
                f"перепись области не сходится: узлов {self.nodes_in_scope}, "
                f"с оболочкой {self.nodes_with_hull}, названных отказов "
                f"{self.refused}")


@dataclass(frozen=True, slots=True)
class ClashScope:
    """ОБЛАСТЬ запроса. Клеш без области — это 770 234 ребра и 666 МБ.

    `scope_id` уже существует в модуле клешей; здесь он ОБЯЗАТЕЛЕН, потому что
    именно он отделяет запрос от слоя.
    """

    scope_id: str
    node_ids: frozenset[str]

    def __post_init__(self) -> None:
        if not isinstance(self.scope_id, str) or not self.scope_id.strip():
            raise GraphBuildError(
                "запрос без `scope_id` есть слой рёбер под другим именем")
        if not isinstance(self.node_ids, frozenset):
            raise GraphBuildError(
                "ClashScope.node_ids must be an immutable frozenset")
        if any(not isinstance(node_id, str) or not node_id.strip()
               for node_id in self.node_ids):
            raise GraphBuildError(
                "ClashScope node keys must be non-empty strings")
        if not self.node_ids:
            raise GraphBuildError(
                "empty ClashScope cannot support a non-vacuous clash verdict")


#: Отношения графа, при которых пересечение оболочек есть СБОРКА, а не конфликт.
#: Это СВИДЕТЕЛЬСТВО (прочитанное `host_id`), а не догадка по паре ярлыков.
_ASSEMBLY_RELATIONS: frozenset[Relation] = frozenset({
    Relation.HOSTED_IN,
    Relation.PLACED_ON_DATUM,
})


def assembly_relation_of(graph: BuildingGraph, a: str, b: str) -> str | None:
    """Объявлено ли между парой отношение СБОРКИ — по графу, а не по ярлыкам.

    Возвращает имя только точного ``PROVEN src↔dst`` отношения либо None.
    Неразрешённая ссылка на внешнего хозяина остаётся неопределённостью, но
    никогда не является доказательством, что произвольный второй кандидат и
    есть этот хозяин.

    Заменяет `resolve.ASSEMBLY_PAIRS`: 467 из 3 348 перекрытий (14.0 %) на
    `sob62_r23_v5` классифицировались догадкой по паре меток.
    """
    if not isinstance(graph, BuildingGraph):
        raise GraphBuildError("assembly lookup requires BuildingGraph")
    for name, value in (("a", a), ("b", b)):
        if not isinstance(value, str) or not value.strip():
            raise GraphBuildError(
                f"assembly lookup {name} must be a non-empty node key")
        if value not in graph:
            raise GraphBuildError(
                f"assembly lookup {name} is not a graph node: {value!r}")
    if a == b:
        raise GraphBuildError("assembly lookup requires two distinct nodes")
    for src, dst in ((a, b), (b, a)):
        for edge in graph.out_edges(src):
            if edge.relation not in _ASSEMBLY_RELATIONS:
                continue
            if edge.dst == dst and edge.modality is Modality.PROVEN:
                return edge.relation.value
    return None


def _assembly_uncertainty(
        graph: BuildingGraph, a: str, b: str) -> tuple[dict[str, Any], ...]:
    """Retain external-host blindness without turning it into pair truth."""

    unresolved: list[dict[str, Any]] = []
    for src in sorted((a, b)):
        for edge in graph.out_edges(src):
            if (edge.relation is Relation.HOSTED_IN
                    and edge.modality is Modality.UNRESOLVED_TARGET):
                unresolved.append({
                    "kind": "unresolved_external_host",
                    "source_node_id": src,
                    "declared_local_target": edge.dst,
                    "relation": edge.relation.value,
                    "modality": edge.modality.value,
                    "source_evidence": dict(edge.evidence),
                })
    return tuple(unresolved)


class ClashQuery:
    """Клеш как ЗАПРОС. Отдаёт итератор и НИЧЕГО не накапливает.

    Отсутствие метода, возвращающего список, — не забывчивость: это и есть
    запрет. Замер называет цену списка заранее (770 234 ребра, 666 МБ, 2.66 ГБ
    RSS на `демо-v3`), поэтому список не предлагается вовсе.
    """

    __slots__ = ("graph", "scope", "_pairs", "_classify", "census")

    def __init__(
        self,
        graph: BuildingGraph,
        scope: ClashScope,
        *,
        candidate_pairs: Callable[[], Iterable[tuple[str, str]]],
        classify: Callable[[str, str], ClashRelationEdge | None],
        census: ScopeCensus,
    ) -> None:
        if not isinstance(graph, BuildingGraph):
            raise GraphBuildError(
                "ClashQuery is local-only and requires BuildingGraph; an "
                "occurrence-keyed federated graph needs a federated adapter")
        if not isinstance(scope, ClashScope):
            raise GraphBuildError("ClashQuery scope must be ClashScope")
        if not isinstance(census, ScopeCensus):
            raise GraphBuildError("ClashQuery census must be ScopeCensus")
        if not callable(candidate_pairs) or not callable(classify):
            raise GraphBuildError(
                "ClashQuery candidate_pairs and classify must be callable")
        unknown = scope.node_ids - set(graph.nodes)
        if unknown:
            raise GraphBuildError(
                f"область называет {len(unknown)} узлов, которых в графе нет; "
                f"первый — {sorted(unknown)[0]!r}")
        if census.nodes_in_scope != len(scope.node_ids):
            raise GraphBuildError(
                "ScopeCensus.nodes_in_scope must equal the exact declared "
                "ClashScope node-key set")
        self.graph = graph
        self.scope = scope
        self._pairs = candidate_pairs
        self._classify = classify
        self.census = census

    def __iter__(self) -> Iterator[ClashRelationEdge]:
        """Единственный способ получить клеш-рёбра — пройти по ним ОДИН раз."""
        previous_pair: tuple[str, str] | None = None
        for candidate in self._pairs():
            if (not isinstance(candidate, (tuple, list))
                    or len(candidate) != 2):
                raise GraphBuildError(
                    "candidate stream must yield exact two-key pairs")
            a, b = candidate
            for name, node_id in (("a", a), ("b", b)):
                if not isinstance(node_id, str) or not node_id.strip():
                    raise GraphBuildError(
                        f"candidate {name} must be a non-empty node key")
            if a == b:
                raise GraphBuildError(
                    "candidate pair cannot address one node twice")
            pair = (a, b)
            if pair != tuple(sorted(pair)):
                raise GraphBuildError(
                    "candidate pair must use canonical subject order; A/B swap "
                    "would detach side-specific evidence")
            if previous_pair is not None and pair <= previous_pair:
                raise GraphBuildError(
                    "candidate stream must be strictly ordered and duplicate-free")
            previous_pair = pair
            if a not in self.scope.node_ids or b not in self.scope.node_ids:
                raise GraphBuildError(
                    "candidate pair escapes the exact declared ClashScope")
            assembly = assembly_relation_of(self.graph, a, b)
            uncertainty = _assembly_uncertainty(self.graph, a, b)
            edge = self._classify(a, b)
            if edge is None:
                raise GraphBuildError(
                    "classifier silently dropped a candidate; return an exact "
                    "SEPARATED, REFUTED, or uncertainty edge")
            if not isinstance(edge, ClashRelationEdge):
                raise GraphBuildError(
                    "classifier must return ClashRelationEdge")
            if (edge.a, edge.b) != (a, b):
                raise GraphBuildError(
                    "classifier returned swapped evidence or evidence for "
                    "another candidate pair")
            if assembly is not None and edge.modality is not Modality.REFUTED:
                reserved = {
                    "assembly_from", "was_modality",
                    "assembly_semantic_verdict",
                }
                if reserved.intersection(edge.evidence):
                    raise GraphBuildError(
                        "classifier evidence uses reserved assembly keys")
                # Отношение сборки СНИМАЕТ находку — и ребро ОСТАЁТСЯ, с
                # именем правила. `resolve` здесь угадывал по ярлыкам.
                edge = ClashRelationEdge(
                    a=edge.a, b=edge.b, relation=edge.relation,
                    modality=Modality.REFUTED,
                    constraint_verdict=ConstraintVerdict.SATISFIED,
                    refuted_by=f"assembly_relation:{assembly}",
                    evidence={**dict(edge.evidence),
                              "assembly_from": "building_graph",
                              "was_modality": edge.modality.value,
                              "assembly_semantic_verdict": "resolved"})
            elif uncertainty:
                reserved = {
                    "assembly_uncertainty", "assembly_semantic_verdict",
                    "constraint_verdict_before_assembly_uncertainty",
                }
                if reserved.intersection(edge.evidence):
                    raise GraphBuildError(
                        "classifier evidence uses reserved assembly keys")
                # Unknown external host is evidence about what this snapshot
                # could not resolve.  It is never evidence that candidate B
                # *is* that host, so the geometric finding, proof, AND exact
                # requested constraint verdict stay unchanged.
                edge = ClashRelationEdge(
                    a=edge.a,
                    b=edge.b,
                    relation=edge.relation,
                    modality=edge.modality,
                    constraint_verdict=edge.constraint_verdict,
                    refuted_by=edge.refuted_by,
                    evidence={
                        **dict(edge.evidence),
                        "assembly_uncertainty": list(uncertainty),
                        "assembly_semantic_verdict": "unresolved",
                        "constraint_verdict_before_assembly_uncertainty": (
                            edge.constraint_verdict.value),
                    },
                    verified_proof=edge.verified_proof,
                )
            yield edge

    def tally(self) -> Mapping[str, int]:
        """Свод по одному проходу. Рёбра не сохраняются — только счётчики."""
        from collections import Counter
        counter: Counter[str] = Counter()
        counter["scope:nodes"] = self.census.nodes_in_scope
        counter["scope:hulled"] = self.census.nodes_with_hull
        counter["scope:complete"] = int(self.census.refused == 0)
        for reason, count in self.census.refusals.items():
            counter[f"scope_refusal:{reason}"] = count
        adjudicated = 0
        for edge in self:
            adjudicated += 1
            counter[f"{edge.relation.value}/{edge.modality.value}"] += 1
            counter[f"constraint:{edge.constraint_verdict.value}"] += 1
            if edge.refuted_by:
                counter[f"refuted_by:{edge.refuted_by}"] += 1
        counter["candidates:adjudicated"] = adjudicated
        return dict(counter)
