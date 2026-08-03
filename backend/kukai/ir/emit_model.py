"""Witness-object model for emitter post blocks (wave A2, Emission IR light).

Post blocks stop being hand-concatenated strings and become lists of
:class:`WitnessCheck` objects rendered in ONE place (:func:`render_post`).
What this buys, per the master design (Часть 3, A2):

* **Correctness by construction** — a ``WitnessCheck`` REFUSES to exist
  without a ``__post.Add`` verdict in its ``verdict_cs``; the audit-F3 class
  ("the verdict line was deleted but the reader marker survived, cert still
  said proven") becomes UNCONSTRUCTIBLE, so the translation certificate can
  consume obligation KEYS instead of substring markers and the verdict-span
  crutch dies.
* **Central tolerances** — the mm/deg numbers move from emitter literals to
  ``OpSpec.tolerances`` (registry_base); a check carries the registry-minted
  :class:`Tolerance` (03.08: ключ БОЛЬШЕ НЕ СТРОКА — см. ЗАКОН ПРОВЕНАНСА
  ДОПУСКА ниже, дефект «ссылка в пустоту» стал неконструируемым).
  Values are the EXACT current numbers (byte-parity; no "improvements").
* **Group member-POSTs** — `_emit_group` can now include member checks with
  namespaced keys (the conditional-absent/substring conflict that deferred
  them disappears with keys).

Deliberately NOT a C# AST (80/20, прибито дизайном): ``decl``/``create``/
``readback`` stay strings; a check's ``reader_cs``/``verdict_cs`` are string
fragments too.  The model's job is STRUCTURE (keys, verdict presence, one
render path), not syntax.

BYTE-GUARANTEE: :func:`render_post` must reproduce the pre-refactor bytes for
every migrated emitter — enforced by ``test_emit_model_byte_parity`` over the
frozen 607-emission corpus.  A check's fragments therefore carry their own
newlines/indentation exactly as the old f-strings did, and ``render_post``
only concatenates: ``"// post <oid>\n{\n"`` + fragments + ``"}"``.

Переходный адаптер (Д4): an emitter returns post as ``str | list[WitnessCheck]``;
``emit_program`` renders both; the cert consumes the model where present
(``witness_source="model"``) and keeps the span rule for strings until the
migration completes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from kukai.ir.emit_utils import cs_line_comment_fragment

_VERDICT_TOKEN = "__post.Add"


class EmitModelError(ValueError):
    """A malformed witness check (fail-closed at construction time)."""


# ---------------------------------------------------------------------------
# ЗАКОН ПРОВЕНАНСА ДОПУСКА (03.08.2026)
# ---------------------------------------------------------------------------
# Прецедент этого дома: `WitnessCheck` НЕЛЬЗЯ построить без `__post.Add` в
# вердикте, и целый класс дефектов (F3 — «маркер читателя остался, вердикт
# удалён, сертификат врёт») умер ПО ПОСТРОЕНИЮ.  Здесь тот же приём применён
# к числу допуска.
#
# Дефект-образец (`create_type`, найден 27.07): проверка заявляла
# `tol_key="param_mm"`, а C# сравнивала с ЗАХАРДКОЖЕННЫМ `0.5`.  Ссылка в
# пустоту, которую не видел ни один тест: `tol_key` был просто строкой, и
# никто никогда не спрашивал, разрешается ли она.  Правка допуска в реестре
# не меняла ничего, а аудит «где живут допуски» получал неверный ответ.
#
# Три закона, каждый машинный:
#
#   ЗАКОН 1 (ЧЕКАНКА).  Допуск попадает в эмиссию ТОЛЬКО как объект
#   :class:`Tolerance`, отчеканенный :func:`tolerance` из
#   ``spec.OPS[op].tolerances[key]``.  Ключа, которому в реестре никто не
#   отвечает, не существует: чеканка отказывает на месте.  Голую строку
#   `tol_key="…"` передать больше НЕЛЬЗЯ — поля с таким именем у витнеса нет.
#
#   ЗАКОН 2 (ПРОЧТЕНО, А НЕ ЗАЯВЛЕНО).  Витнес, объявивший допуск, обязан
#   содержать в своей C# ровно ту строку, которую этот объект САМ отрендерил.
#   Число, набранное рядом руками, объект не порождал ⇒ проверка не строится.
#   Декоративный `tol_key` (дефект create_type) становится неконструируемым.
#
#   ЗАКОН 3 (ОБЕЩАНИЕ ↔ РЕЕСТР ↔ ЭМИССИЯ).  Каждое `±<число>` из
#   ``OpSpec.post`` обязано быть значением в ``OpSpec.tolerances``, и каждая
#   запись реестра обязана доходить до эмитируемой C# (возмущающий оракул:
#   тронь число — байты обязаны поехать).  Это свойство ВСЕЙ таблицы, поэтому
#   живёт не в конструкторе, а в ``tests/test_tolerance_provenance.py``.
#
# ОСТАТОК, НАЗВАННЫЙ ЧЕСТНО: закон 2 — необходимое условие, не достаточное.
# Отрендеренная строка ищется подстрокой, и «5.0» могло бы совпасть с
# координатой в том же фрагменте.  Достаточную проверку даёт возмущающий
# оракул закона 3; вместе они закрывают класс.


def _compact_cs_number(value: float) -> str:
    """Кратчайший C#-литерал числа: ``1e-06`` -> ``1e-6``, ``5.0`` -> ``5.0``.

    Нужен ровно затем, чтобы подстановка из реестра НЕ ДВИГАЛА БАЙТЫ там, где
    исходник исторически набран компактно (``> 1e-6`` в set_param).
    """

    return re.sub(r"e([+-])0+(\d)", r"e\1\2", repr(float(value)))


@dataclass(frozen=True, slots=True)
class Tolerance:
    """Число допуска, ОТЧЕКАНЕННОЕ реестром (закон 1).

    Несёт своё происхождение (``op``/``key``) и запоминает КАЖДУЮ строку,
    которой само себя отрендерило — на этой памяти стоит закон 2.

    Рендеры (все записываются):
      * ``f"{tol}"``            -> ``5.0``     (обычная форма)
      * ``f"{tol:g}"``          -> ``5``       (там, где исходник набран целым)
      * ``tol.cs``              -> ``1e-6``    (компактная экспонента)
      * ``tol.deg_rad_divisor`` -> ``1800.0``  (для ``Math.PI / 1800.0``)

    ``tol.value`` — СЫРОЕ число для ПРОИЗВОДНЫХ вычислений (пол подрезки
    участка считается из допуска конца), и рендером оно НЕ СЧИТАЕТСЯ: если
    сравнение витнеса набрано через ``.value``, закон 2 такую проверку не
    построит.  Это намеренно: производное число — не то же самое, что само
    сравнение.
    """

    op: str
    key: str
    value: float
    # Не участвует ни в равенстве, ни в хеше: это память рендеров, а не часть
    # личности допуска.
    _rendered: set = field(
        default_factory=set, repr=False, compare=False, hash=False)

    def _record(self, text: str) -> str:
        self._rendered.add(text)
        return text

    @property
    def rendered(self) -> frozenset:
        """Строки, которыми этот допуск себя отрендерил (для закона 2)."""

        return frozenset(self._rendered)

    def __str__(self) -> str:
        return self._record(str(self.value))

    def __format__(self, format_spec: str) -> str:
        return self._record(format(self.value, format_spec))

    @property
    def cs(self) -> str:
        """Компактный C#-литерал (``1e-6``), см. :func:`_compact_cs_number`."""

        return self._record(_compact_cs_number(self.value))

    @property
    def deg_rad_divisor(self) -> str:
        """Делитель D для выражения ``Math.PI / D`` == этот допуск В ГРАДУСАХ.

        Допуск поворота исторически эмитируется ВЫРАЖЕНИЕМ (``Math.PI /
        1800.0``), а не числом радиан: так C# считает точно и так набрано в
        золотых файлах.  Делитель считается в ``Decimal``, потому что
        ``180.0 / 0.1`` в двоичной плавающей даёт 1799.9999999999998 — и
        байты уехали бы ради красоты.
        """

        divisor = Decimal("180") / Decimal(repr(float(self.value)))
        if divisor == divisor.to_integral_value():
            return self._record(f"{int(divisor)}.0")
        return self._record(format(divisor.normalize(), "f"))


def tolerance(op_name: str, key: str) -> Tolerance:
    """Отчеканить допуск ``key`` опа ``op_name`` из реестра (закон 1).

    Ключ, которого в ``OpSpec.tolerances`` нет, — отказ ЗДЕСЬ И СЕЙЧАС, а не
    молчаливая ссылка в пустоту, дожившая до прода (дефект create_type).
    """

    from kukai.ir import spec  # локальный импорт: реестр не знает об эмиссии

    op_spec = spec.OPS.get(op_name)
    if op_spec is None:
        raise EmitModelError(
            f"tolerance({op_name!r}, {key!r}): такого опа нет в реестре")
    tolerances = getattr(op_spec, "tolerances", None) or {}
    if key not in tolerances:
        raise EmitModelError(
            f"tolerance({op_name!r}, {key!r}): допуска с таким ключом в "
            f"реестре нет (есть: {sorted(tolerances)}) — число обязано жить в "
            "реестре, а не в эмитируемой C#")
    return Tolerance(op_name, key, float(tolerances[key]))


class ToleranceSet:
    """Допуски одного опа: ``tol["endpoint_mm"]`` чеканит и КЭШИРУЕТ.

    Кэш нужен по существу: один и тот же объект и рендерит число в C#, и
    объявляется в витнесе — закон 2 сверяет ИМЕННО его память рендеров.
    """

    __slots__ = ("_op", "_minted")

    def __init__(self, op_name: str) -> None:
        self._op = op_name
        self._minted: dict[str, Tolerance] = {}

    def __getitem__(self, key: str) -> Tolerance:
        got = self._minted.get(key)
        if got is None:
            got = self._minted[key] = tolerance(self._op, key)
        return got


def tolerances(op_name: str) -> ToleranceSet:
    """Набор допусков опа (замена ``spec.OPS[op].tolerances`` в эмиттерах)."""

    return ToleranceSet(op_name)


@dataclass(frozen=True, slots=True)
class WitnessCheck:
    """One in-transaction postcondition witness.

    ``obligation_key``  — machine key the translation certificate matches
                          against ``Obligation.key`` (never a C# substring).
    ``reader_cs``       — the C# that READS the fact (may be empty when the
                          verdict's condition reads inline).
    ``verdict_cs``      — the C# that renders the verdict; MUST contain
                          ``__post.Add`` (unconstructible otherwise — this is
                          the by-construction kill of audit-F3).
    ``message``         — the human message inside the verdict (for audits;
                          the cert never matches on it).
    ``tol``             — the registry-minted :class:`Tolerance` this check
                          compares against (None for exact/boolean checks).
                          НЕ СТРОКА: ключ нельзя объявить, его можно только
                          предъявить вместе с числом, отчеканенным реестром
                          (законы 1 и 2 выше).  ``tol_key`` осталось как
                          ПРОИЗВОДНОЕ свойство — читателям (сертификат,
                          аудиты) по-прежнему нужен машинный ключ.
    ``style``           — the render genre, documentation of shape:
                          ``guard``      condition -> verdict (no else),
                          ``else_block`` reader with null-guard verdict and an
                                         else { ... } body,
                          ``plain``      free-form fragment.
                          Styles do NOT change rendering (fragments carry
                          their own layout — byte parity); they exist so
                          audits/tools can reason about check shape.
    """

    obligation_key: str
    reader_cs: str
    verdict_cs: str
    message: str
    # compare=False СОЗНАТЕЛЬНО: равенство витнесов — это равенство
    # ЭМИТИРУЕМОЙ C#.  На этом стоит возмущающий оракул (тронь число в
    # реестре — если байты не поехали, допуск декоративный); включи объект
    # допуска в сравнение, и оракул стал бы проходить вхолостую.
    tol: "Tolerance | None" = field(default=None, compare=False)
    style: Literal["guard", "else_block", "plain"] = "plain"

    @property
    def tol_key(self) -> str | None:
        """Машинный ключ допуска — ПРОИЗВОДНОЕ от отчеканенного объекта."""

        return None if self.tol is None else self.tol.key

    def __post_init__(self) -> None:
        if not self.obligation_key or not isinstance(self.obligation_key, str):
            raise EmitModelError("WitnessCheck needs a non-empty obligation_key")
        if not isinstance(self.verdict_cs, str) \
                or _VERDICT_TOKEN not in self.verdict_cs:
            raise EmitModelError(
                f"WitnessCheck {self.obligation_key!r}: verdict_cs must "
                f"contain {_VERDICT_TOKEN} — a witness without a verdict is "
                "unconstructible (audit F3, by construction)")
        if not isinstance(self.reader_cs, str):
            raise EmitModelError(
                f"WitnessCheck {self.obligation_key!r}: reader_cs must be str")
        if self.style not in ("guard", "else_block", "plain"):
            raise EmitModelError(
                f"WitnessCheck {self.obligation_key!r}: unknown style "
                f"{self.style!r}")
        if self.tol is None:
            return
        # ЗАКОН 1: допуск предъявляется объектом из реестра, не строкой.
        if not isinstance(self.tol, Tolerance):
            raise EmitModelError(
                f"WitnessCheck {self.obligation_key!r}: tol={self.tol!r} — "
                "допуск обязан быть объектом Tolerance из реестра "
                "(emit_model.tolerance(op, key)); голой строкой/числом "
                "провенанс не объявляется")
        # ЗАКОН 2: объявленный допуск обязан быть ПРОЧИТАН — в C# витнеса
        # стоит ровно та строка, которую отчеканенный объект сам отрендерил.
        body = self.reader_cs + self.verdict_cs
        if not any(form in body for form in self.tol.rendered):
            raise EmitModelError(
                f"WitnessCheck {self.obligation_key!r}: объявлен допуск "
                f"{self.tol.op}.{self.tol.key}={self.tol.value}, но в C# "
                "проверки нет ни одной строки, которую этот допуск породил "
                f"(отрендерено: {sorted(self.tol.rendered)}) — это дефект "
                "create_type: заявленный провенанс при захардкоженном числе, "
                "неконструируемый по построению")

    def render(self) -> str:
        """The check's exact C# fragment (fragments own their layout)."""

        return self.reader_cs + self.verdict_cs


def render_post(oid: str, checks: list[WitnessCheck] | tuple[WitnessCheck, ...]) -> str:
    """Render a post block byte-identically to the legacy hand-built string.

    The frame is the universal emitter shape ``// post <oid>\\n{\\n`` ...
    ``}``; every fragment between carries its own indentation and newlines.
    An empty check list is refused: an authoring op with NO postcondition
    would be a silently-unverified element (fail-closed).
    """

    if not checks:
        raise EmitModelError(f"post block for {oid!r} has no witness checks")
    seen: set[str] = set()
    for check in checks:
        if not isinstance(check, WitnessCheck):
            raise EmitModelError(
                f"post block for {oid!r} carries a non-WitnessCheck")
        if check.obligation_key in seen:
            raise EmitModelError(
                f"post block for {oid!r}: duplicate obligation_key "
                f"{check.obligation_key!r}")
        seen.add(check.obligation_key)
    return (
        f"// post {cs_line_comment_fragment(oid)}\n{{\n"
        + "".join(check.render() for check in checks)
        + "}"
    )


@dataclass(frozen=True, slots=True)
class BarePost:
    """A frameless post block (the NETWORK genre).

    pipe_system/route_* historically emit ``// post <oid>\n`` + checks with
    NO surrounding ``{ }`` frame (their per-segment blocks carry their own
    braces).  Same validation as :func:`render_post`, frameless render.
    """

    checks: tuple[WitnessCheck, ...]

    def __post_init__(self) -> None:
        if not self.checks:
            raise EmitModelError("BarePost has no witness checks")
        seen: set[str] = set()
        for check in self.checks:
            if not isinstance(check, WitnessCheck):
                raise EmitModelError("BarePost carries a non-WitnessCheck")
            if check.obligation_key in seen:
                raise EmitModelError(
                    f"BarePost: duplicate obligation_key "
                    f"{check.obligation_key!r}")
            seen.add(check.obligation_key)


def post_to_string(
    oid: str, post: "str | list[WitnessCheck] | tuple | BarePost",
) -> str:
    """Transitional adapter (Д4): render model posts, pass strings through."""

    if isinstance(post, str):
        return post
    if isinstance(post, BarePost):
        return (f"// post {cs_line_comment_fragment(oid)}\n"
                + "".join(check.render() for check in post.checks))
    return render_post(oid, post)


__all__ = [
    "BarePost",
    "EmitModelError",
    "Tolerance",
    "ToleranceSet",
    "WitnessCheck",
    "post_to_string",
    "render_post",
    "tolerance",
    "tolerances",
]
