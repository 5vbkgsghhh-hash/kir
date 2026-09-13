"""EMISSION CORE: what BOTH the hub AND all nineteen satellites use.

🔴 WHY THIS FILE WAS STARTED (02.09.2026). The 20.08 wave carried the BODIES of
emitters out of `authoring.py` into satellites `*_emit.py` — and left HELPERS
in the hub. The result was a ring: seventeen satellites out of nineteen pulled
`kir.authoring` AT MODULE LEVEL for 29 names (`_cs` in 17, `_safe` in 17,
`_stamp_block` in 16, `_stamp_readback` in 14, `_eid` in 12, `_gid` in 9 …),
while the hub pulled the satellites LAZILY — 41 imports in 41 wrappers
(`authoring.py:7331…9502`). The laziness there stood not for load-cost reasons:
it HID THE CYCLE, and without it the package would not import at all.

The ring's cost is measured, not guessed: as long as it exists, `authoring`
cannot be imported from a satellite at module level, which means `_EMITTERS`
is forced to stay a HANDWRITTEN dict (`authoring.py:8943`) — and a handwritten
table that is obligated to agree with the registry diverges in this tree every
time (NAKAZ §4). Forty-one wrappers existed for exactly one reason: to bear
this ring.

WHAT IS HERE AND WHAT IS NOT. Here is the CLOSURE of those 29 names: the names
themselves plus 17 names they depend on, 44 definitions. Not a single line was
written anew — this is a MOVE, and it is proven by the fact that the goldens
and `test_emit_model_byte_parity` did not shift by a single byte. There is NOT
a single operation emitter here: the bodies live in the satellites,
registration lives in the satellite's registry.

`kir.authoring` re-exports everything moved, so no foreign import shifted:
`from kir.authoring import _cs` works exactly as it worked before.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import replace as _dc_replace
from typing import Any, Mapping, Sequence
from kir.contracts import ElementIdentityProof
from kir.registry_base import (SYNTHETIC_FINAL_SHIFT,
                               obligation_for_revit_param)
from kir.emit_model import (BarePost, WitnessCheck, post_to_string,
                                 render_staged_post,
                                 tolerance, tolerances)
from kir.diag import (Diagnostic, KirRefusal, PLAN_SOLO_OP, TYPE_BAD_TYPE,
                           GROUND_BAD_SELECTOR, PARSE_EXCLUSIVE_FIELDS,
                           EMIT_UNSUPPORTED)
from kir.emit_utils import (
    ELEMENT_ID_MAX,
    cs_element_id_literal,
    cs_identifier_fragment,
    cs_line_comment_fragment,
    cs_string_literal,
    failure_channel_reset_cs,
    failure_preprocessor_cs,
    failure_warnings_into_results_cs,
    program_refusal_tokens,
    refuse_stmt,
)
from kir.diag import EMIT_UNSUPPORTED  # noqa: F401  — refusal code is needed by spokes
from kir.ground import IN_EMIT_DEFAULT  # noqa: F401  — the default "Revit will decide"
from kir.midend import LINEAGE_FORM



EMIT_ID_RANGE = "KIR-E002"     # grounded id unrepresentable on this Revit version


# Mirror-copy is the last-resort path for a hosted family whose Revit symbol
# reports CanFlip*=false.  Several such cuts on one wall can defer a failure
# until the *parent* Transaction.Commit, outside the op SubTransactions.  A5
# therefore bounds that risky fallback per host; normal CanFlip operations do
# not consume the budget.
#: 🔴 /2 SINCE 13.09.2026, AND THE BUMP IS OWED TWICE OVER.
#: Wave N-2 renamed this guard's refusal («open model binding changed» →
#: `identity_changed_since_read` plus a next move) and never bumped the version,
#: which left `test_authoring.py::Ground` with SEVEN reds that no suite I ran
#: happened to cover — measured on the pristine tree today, identical names, so
#: they were mine and they were old. Today the version half moved out under its
#: own code and is emitted only on opt-in. Both are contract changes for anyone
#: who relied on this guard also pinning the saved version, which is exactly what
#: a version in the wire is for.
MODEL_BINDING_GUARD_VERSION = "kir-model-binding-guard/2"


def _cs(s: str) -> str:
    return cs_string_literal(s)


def _indent(block: str, pad: str) -> str:
    return "\n".join(pad + ln if ln.strip() else ln
                     for ln in block.splitlines())


def _safe(s: str) -> str:
    return cs_identifier_fragment(s)


def element_identity_readback_cs(
    el_var: str, *, revit_version: str, rb_var: str = "__rb",
) -> str:
    """Read one supplied Element, never resolve a returned numeric id.

    Callers determine provenance: a create caller supplies its original object;
    a query caller supplies a resolved object and must not call that original
    creation evidence. Getter failure is readback incompleteness, not rollback.
    This fragment has no transaction, lookup, or native-effect authority.
    """
    if any(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value) is None
           for value in (el_var, rb_var)):
        raise ValueError("identity reader requires C# variable identifiers")
    numeric_id = ("(long)__kirIdentityId.IntegerValue" if int(revit_version) <= 2023
                  else "__kirIdentityId.Value")
    return (
        f'    {rb_var}["element_identity"] = null;\n'
        f'    {rb_var}["element_identity_status"] = "unavailable";\n'
        f'    {rb_var}["element_identity_reason"] = "element_missing";\n'
        f"    try\n    {{\n"
        f"        Element __kirIdentityEl = {el_var};\n"
        f"        if (__kirIdentityEl != null)\n        {{\n"
        f'            {rb_var}["element_identity_reason"] = "identity_incomplete";\n'
        f"            var __kirIdentityId = __kirIdentityEl.Id;\n"
        f"            if (__kirIdentityId != null)\n            {{\n"
        f"                long __kirIdentityNumber = {numeric_id};\n"
        f"                string __kirIdentityUid = __kirIdentityEl.UniqueId;\n"
        f"                if (__kirIdentityNumber > 0 && !String.IsNullOrWhiteSpace(__kirIdentityUid))\n"
        f"                {{\n"
        f'                    string __kirIdentityVersion = __kirIdentityEl.VersionGuid.ToString("N");\n'
        f'                    {rb_var}["element_identity"] = new Dictionary<string, object>\n'
        f"                    {{\n"
        f'                        {{"schema_version", {_cs(ElementIdentityProof.SCHEMA_VERSION)}}},\n'
        f'                        {{"element_id", __kirIdentityNumber}},\n'
        f'                        {{"unique_id", __kirIdentityUid}},\n'
        f'                        {{"version_guid", __kirIdentityVersion}}\n'
        f"                    }};\n"
        f'                    {rb_var}["element_identity_status"] = "captured";\n'
        f'                    {rb_var}["element_identity_reason"] = null;\n'
        f"                }}\n            }}\n        }}\n"
        f"    }}\n    catch\n    {{\n"
        f'        {rb_var}["element_identity"] = null;\n'
        f'        {rb_var}["element_identity_status"] = "unavailable";\n'
        f'        {rb_var}["element_identity_reason"] = "identity_unreadable";\n'
        f"    }}\n"
    )


def _eid(val: int, ver: str, op_id: str) -> str:
    """ElementId literal, version-aware (the gate-caught divergence)."""
    try:
        return cs_element_id_literal(val, ver)
    except ValueError:
        if not (isinstance(val, int) and not isinstance(val, bool)
                and 1 <= val <= ELEMENT_ID_MAX):
            message = (
                f"id {val} вне положительного 64-битного пространства "
                "ElementId")
        else:
            message = (
                f"id {val} вне 32-битного пространства ElementId Revit {ver}")
        raise KirRefusal([Diagnostic(
            code=EMIT_ID_RANGE, op_id=op_id, got=val,
            message_ru=message)])


def _gid(op: dict, param: str) -> dict:
    return op[param]["__grounded__"]


def _level_expr(op: dict, s: str, ver: str, oid: str,
                isolation: str = "atomic") -> tuple[str, str]:
    """(resolution C#, level id C#-expr for topology checks). Ref -> the
    created level variable; pinned -> GetElement + stale guard.

    The guard distinguishes WHY ``as Level`` failed.  Measured live 27.07
    twice (``create_beam`` x16, two runs ~74 min apart, one editor, one local
    file, journalctl kukai-backend): X003 claimed "уровень не найден (модель
    изменилась после grounding)" 130-460ms after ``ground_snapshot`` had just
    returned the SAME level catalogue — too little time for a human edit.
    ``doc.GetElement(id) as Level`` returns null for two different reasons
    that used to share one fixed message: the id no longer resolves at all
    (consistent with genuine drift) and the id resolves to something that
    was never a Level.  The second case does NOT by itself prove a grounding
    bug: ``ground.py``'s ``by: element_id`` path is a documented, deliberate
    pass-through (existence/kind re-checked only here, at runtime — see
    ``ground.py`` module docstring) — a wrong id can equally come from the
    calling side.  So the message states the observed FACT (wrong runtime
    type) and stops there; it must not invent a cause the guard cannot see,
    same discipline as the lie ``test_hangs_and_lies.py`` already found and
    fixed for "NewFamilyInstance вернул null" / "NewElbowFitting: failed to
    insert elbow" — one layer deeper: baked into this guard's own static C#
    string rather than a raw Revit message, so the earlier fix (which only
    reads ``serving._translate_runtime``'s input) never saw it.
    """
    lv = _gid(op, "level")
    if lv.get("via") == "ref":
        rv = "__el_" + _safe(lv["ref"])
        return (f"Level __lv_{s} = {rv};", f"{rv}.Id.ToString()")
    raw = f"__lv_raw_{s}"
    vanished = _cs("уровень не найден (модель изменилась после grounding)")
    wrong_type = _cs("id уровня резолвится не в Level, а в ")
    tail = _cs(" — причина (дрейф модели или неверный id) не определена рантаймом")
    msg_expr = (f"({raw} == null ? {vanished} : "
                f"{wrong_type} + __ClassName({raw}) + {tail})")
    res = (f"Element {raw} = doc.GetElement({_eid(lv['id'], ver, oid)});\n"
           f"Level __lv_{s} = {raw} as Level;\n"
           f"if (__lv_{s} == null) {{ {refuse_stmt(oid, msg_expr, isolation)} }}")
    return res, _cs(str(lv["id"]))


_AUTH_PREAMBLE = r"""
// KIR authoring program — generated. One txn; commit only after in-txn
// postcondition checks pass; any guard failure rolls back (zero-trace).
double U(double mm) => UnitUtils.ConvertToInternalUnits(mm, UnitTypeId.Millimeters);
double MM(double ft) => UnitUtils.ConvertFromInternalUnits(ft, UnitTypeId.Millimeters);
XYZ P(double x, double y, double z) => new XYZ(U(x), U(y), U(z));
Func<string, string, Dictionary<string, object>> __Refuse = (string __oid, string __msg) =>
{
    var __e = new Dictionary<string, object>();
    __e["error"] = "stale_or_failed"; __e["op_id"] = __oid; __e["message"] = __msg;
    return __e;
};
var __results = new Dictionary<string, object>();
var __post = new List<string>();
""".strip("\n")


#: Class-name helper. NOT in the preamble: a program that does not call it is
#: not obligated to carry it. Measured 04.08.2026 — under unconditional
#: emission the declaration landed in 812 of 1292 emissions, while only 144
#: called it; the remaining 668 carried dead C# and, worse, shifted the
#: frozen bytes (`test_emit_model_byte_parity`) of programs the edit did not
#: touch. The ratchet is obligated to click on a change in emission, not on
#: growth of the preamble.
_CLASS_NAME_HELPER_CS = """\
// Имя класса БЕЗ обращения к среде выполнения за типом: та форма записи
// целиком отвергается валидатором безопасности моста версий до 06.07.2026,
// который всё ещё стоит на части флота, — тело браковалось бы на машине
// пользователя ДО компиляции, и сервер об этом не узнавал бы.
// Object.ToString() у Element и у исключений — это полное имя типа CLR:
// из Autodesk.Revit.DB его перекрывают только ElementId, UV, XYZ, WorksetId,
// ScheduleFieldId и PolymeshFacet (замер по индексу ловушек), и ни один из
// них сюда не передаётся. Исключение дописывает ": сообщение" и стек,
// поэтому срез идёт по первому переводу строки и первому двоеточию.
// Результат побайтно равен прежнему .Name.
Func<object, string> __ClassName = (__cnObj) =>
{
    if (__cnObj == null) return "";
    string __cn = __cnObj.ToString();
    if (__cn == null) return "";
    int __cnCut = __cn.IndexOf((char)10);
    if (__cnCut >= 0) __cn = __cn.Substring(0, __cnCut);
    __cnCut = __cn.IndexOf(':');
    if (__cnCut >= 0) __cn = __cn.Substring(0, __cnCut);
    __cn = __cn.Trim();
    __cnCut = __cn.LastIndexOf('.');
    return __cnCut >= 0 && __cnCut + 1 < __cn.Length
        ? __cn.Substring(__cnCut + 1) : __cn;
};
"""


def _with_class_name_helper(program: str) -> str:
    """Insert the ``__ClassName`` declaration ONLY if the program calls it.

    The declaration is placed in the preamble (before ``__results``), that is
    strictly before any operation code — the same visibility as ``__Refuse``.
    Verified with the live compiler on 2021 and 2026 in both isolation modes.
    """
    if "__ClassName(" not in program:
        return program
    anchor = "var __results = new Dictionary<string, object>();"
    if anchor not in program:
        raise AssertionError(
            "программа зовёт __ClassName, но в ней нет якоря преамбулы — "
            "объявление было бы потеряно, и это CS0103 на машине пользователя")
    return program.replace(anchor, _CLASS_NAME_HELPER_CS + anchor, 1)


#: MESH SURFACE CANONICALIZATION. Declared under the same rule as
#: ``__ClassName``: only if the program calls it — otherwise the declaration
#: would ride along in every emission and shift the frozen bytes of programs
#: the edit does not touch.
#:
#: WHY THIS EXISTS AT ALL. The face-count witness on ``create_directshape``
#: closes the silence of ``Fallback.Salvage`` only halfway: a rebuild that
#: preserves the face COUNT but shifts a vertex passes it silently. The exact
#: predicate is already written and proven live — ``mesh_surface_payload`` in
#: ``decompile/geometry_acceptance.py`` (the idempotence rig reads the built
#: element with it via a SEPARATE post-commit read). Here that same predicate
#: is what gets computed — but INSIDE the transaction, so a mismatch rolls
#: back instead of merely describing.
#:
#: WHY THE PREIMAGE IS COMPARED, NOT SHA-256. Measurement on the live compile
#: service (:52412, 09.08.2026): ``System.Security.Cryptography.SHA256`` and
#: ``SHA256Managed`` build 4/6 and throw CS1069 on 2025 and 2026 — the type is
#: forwarded to an assembly absent from the client's reference closure (the
#: same asymmetry that ``tests/bridge_reference_closure.py`` already recorded
#: for ``MD5``). A hash cannot exist in emitted C#. So Python pre-registers
#: the digest's PREIMAGE, and C# builds the same one from the built element
#: and compares strings: preimage equality is strictly stronger than hash
#: equality, and canonicalization in the code remains ONE.
#:
#: InvariantCulture is not pedantry: ``NegativeSign`` and the digits
#: themselves depend on the user's machine locale, while the preimage is
#: obligated to be the same bytes that Python computed.
_MESH_CANON_HELPER_CS = """\
// Округление половиной ОТ НУЛЯ на решётке канона — тот же закон, что у
// decompile.geom_extract._round_mm (floor(s+0.5) / ceil(s-0.5)), а не
// Math.Round: Math.Round(MidpointRounding.ToEven) увёл бы ровно половину
// граничных вершин в соседнюю ячейку и прообраз разошёлся бы с питоновским.
Func<double, double, long> __KirCanonUnit = (__cuMm, __cuGrid) =>
{
    double __cuS = __cuMm / __cuGrid;
    return __cuS >= 0.0
        ? (long)Math.Floor(__cuS + 0.5)
        : (long)Math.Ceiling(__cuS - 0.5);
};
// Лексикографический порядок по целым — тот же, что у python sorted() над
// кортежами: сначала поэлементно, при равенстве — по длине.
Comparison<long[]> __KirCanonCmp = (__ccA, __ccB) =>
{
    int __ccN = __ccA.Length < __ccB.Length ? __ccA.Length : __ccB.Length;
    for (int __ccI = 0; __ccI < __ccN; __ccI++)
    {
        if (__ccA[__ccI] < __ccB[__ccI]) return -1;
        if (__ccA[__ccI] > __ccB[__ccI]) return 1;
    }
    return __ccA.Length.CompareTo(__ccB.Length);
};
// Оболочку JSON (__cpHead/__cpTail) присылает Python — она выведена из того же
// канонизатора, а не набрана здесь второй раз. List.Sort нестабилен, и это
// безразлично: порядок полный по ВСЕМ девяти числам, значит равные строки
// неразличимы по значению.
Func<List<long[]>, string, string, string> __KirCanonPayload =
    (__cpRows, __cpHead, __cpTail) =>
{
    __cpRows.Sort(__KirCanonCmp);
    var __cpSb = new StringBuilder(__cpHead);
    for (int __cpI = 0; __cpI < __cpRows.Count; __cpI++)
    {
        if (__cpI > 0) __cpSb.Append(',');
        long[] __cpR = __cpRows[__cpI];
        for (int __cpJ = 0; __cpJ < 3; __cpJ++)
        {
            __cpSb.Append(__cpJ == 0 ? "[[" : ",[");
            for (int __cpK = 0; __cpK < 3; __cpK++)
            {
                if (__cpK > 0) __cpSb.Append(',');
                __cpSb.Append(__cpR[__cpJ * 3 + __cpK].ToString(
                    System.Globalization.CultureInfo.InvariantCulture));
            }
            __cpSb.Append(']');
        }
        __cpSb.Append(']');
    }
    __cpSb.Append(__cpTail);
    return __cpSb.ToString();
};
"""


#: WHAT IS OCCUPIED ON THE CURTAIN GRID AXIS. Declared under the same rule as
#: ``__ClassName``: once per program and only if it is called.
#:
#: 🔴 WHY NOT PER-OP, LIKE THE NEIGHBORING ``__gDist``/``__gMem``. Measured on
#: this same edit: a per-op helper costs **+3480 B of C# per line**, meaning
#: a facade of twenty lines gets heavier by 70 KB (+26%). This helper, unlike
#: its neighbors, depends on the op in NO WAY WHATSOEVER — it takes the grid,
#: axis, and point as arguments — so a per-op copy would be a cost without a
#: subject. This tree already fixed a defect today that hauled 18 KB for no
#: reason (`6d09726b`).
#:
#: 🔴 THE AXIS IS READ, NOT ASSERTED. That ``u`` gives the horizontal was
#: bought by ONE live run on 26.08.2026 on ONE straight wall in Revit 2026 —
#: that is too little for a law covering all carriers and versions. The
#: direction is taken from the ``FullCurve`` of the already-existing line:
#: the reading holds on a curved carrier too, and if another kind of grid
#: turns out to have u/v reversed.
#:
#: ``__ClassName`` is deliberately NOT called here: it is inserted by the
#: same technique, and keeping the order of two insertions straight would
#: have to be done by hand — a second carrier of order, bound to diverge
#: someday.
_GRID_OCC_HELPER_CS = """\
Func<CurtainGrid, bool, XYZ, string> __KirGridOcc = (__goG, __goU, __goP) =>
{
    try
    {
        ICollection<ElementId> __goS = __goU
            ? __goG.GetUGridLineIds()
            : __goG.GetVGridLineIds();
        if (__goS == null || __goS.Count == 0)
            return "линий этой оси в сетке НЕТ ни одной — значит причина НЕ в занятой координате";
        var __goB = new List<string>();
        var __goDs = new List<double>();
        string __goA = "ось назвать нечем: ни одна существующая линия не читается";
        foreach (ElementId __goE in __goS)
        {
            CurtainGridLine __goL = doc.GetElement(__goE) as CurtainGridLine;
            if (__goL == null) continue;
            double __goD = -1.0;
            // 🔴 ЯРЛЫК КООРДИНАТЫ ВЫБИРАЕТСЯ ПО ОСИ, А НЕ ОДИН НА ОБЕ.
            // У вертикальной линии высота середины не различает НИЧЕГО:
            // она у всех такая же. Подписать её «высота» значило бы дать
            // автору величину, которая не отвечает на его вопрос, — та же
            // форма, что и весь этот дефект.
            string __goW = "положение не прочитано";
            try
            {
                Curve __goC = __goL.FullCurve;
                IntersectionResult __goR = __goC.Project(__goP);
                if (__goR != null) __goD = MM(__goR.Distance);
                XYZ __goM = __goC.Evaluate(0.5, true);
                XYZ __goV = (__goC.GetEndPoint(1) - __goC.GetEndPoint(0)).Normalize();
                if (Math.Abs(__goV.Z) < 0.01)
                {
                    __goA = "эта ось ГОРИЗОНТАЛЬНА: линия идёт вдоль носителя на постоянной ВЫСОТЕ, и двигать надо ВЫСОТУ — третью координату точки";
                    __goW = "высота " + Math.Round(MM(__goM.Z), 1).ToString(
                        System.Globalization.CultureInfo.InvariantCulture) + " мм";
                }
                else
                {
                    __goA = "эта ось ВЕРТИКАЛЬНА: линия идёт снизу вверх в постоянном месте вдоль носителя, и двигать надо положение ВДОЛЬ носителя — первые две координаты точки";
                    __goW = "в плане (" + Math.Round(MM(__goM.X), 1).ToString(
                        System.Globalization.CultureInfo.InvariantCulture) + ", "
                        + Math.Round(MM(__goM.Y), 1).ToString(
                        System.Globalization.CultureInfo.InvariantCulture) + ") мм";
                }
            }
            catch { }
            // 🔴 НЕПРОЧИТАННОЕ РАССТОЯНИЕ НЕ ПЕЧАТАЕТСЯ ЧИСЛОМ И СОРТИРУЕТСЯ
            // ПОСЛЕДНИМ. Пока перечень шёл в порядке прибытия, `-1.0`
            // печаталось как «до запрошенной точки -1 мм» — величина, которой
            // не бывает. С сортировкой по расстоянию это стало НЕСУЩИМ: -1
            // встал бы ВПЕРЕДИ настоящей причины (0 мм) и вытеснил бы её из
            // показанных. Сортируем по MaxValue, печатаем словом.
            __goDs.Add(__goD < 0.0 ? Double.MaxValue : __goD);
            __goB.Add(__goE.ToString() + " (" + __goW + ", "
                + (__goD < 0.0 ? "расстояние до запрошенной точки НЕ ПРОЧИТАНО"
                   : "до запрошенной точки " + Math.Round(__goD, 1).ToString(
                        System.Globalization.CultureInfo.InvariantCulture) + " мм") + ")");
        }
        // ВЫРОЖДЕННЫЙ ВХОД: линии на оси ЕСТЬ, но ни одна не перечиталась.
        // Без этой ветки печаталось бы «линий этой оси уже 0: » — утверждение,
        // прямо противоположное тому, что мы только что видели в сетке.
        if (__goB.Count == 0)
            return __goA + "; линий этой оси в сетке " + __goS.Count.ToString(
                System.Globalization.CultureInfo.InvariantCulture)
                + ", но НИ ОДНА не перечитывается — назвать занятое нечем";
        // 🔴 РЕЖЕМ ПО РЕЛЕВАНТНОСТИ, А НЕ ПО ПОРЯДКУ ПРИБЫТИЯ, и релевантность
        // здесь ТОЧНАЯ: расстояние до запрошенной точки. Причина отказа — та
        // линия, у которой оно 0 мм, и после сортировки она стоит ПЕРВОЙ,
        // то есть переживает любое усечение. Порядок прибытия (по ElementId)
        // не связан с вопросом ничем и вытеснил бы причину случайно.
        double[] __goK = __goDs.ToArray();
        string[] __goT = __goB.ToArray();
        Array.Sort(__goK, __goT);
        int __goN = __goT.Length < 6 ? __goT.Length : 6;
        var __goP2 = new List<string>();
        for (int __goI = 0; __goI < __goN; __goI++) __goP2.Add(__goT[__goI]);
        // 🔴 ЧИСЛО ПОКАЗАННОГО БЕРЁТСЯ ИЗ ТОГО ЖЕ СПИСКА, ЧТО УЕХАЛ ЧИТАТЕЛЮ
        // (идиома `_shown_of` в `ground.py`). Сегодня в этом дереве подпись
        // «ПОКАЗАНЫ 12 ИЗ 48» стояла над ПЯТЬЮ строками (`f132cb8e`) ровно
        // потому, что число объявляли в одном месте, а резали в другом.
        string __goMore = __goT.Length > __goP2.Count
            ? " ПОКАЗАНЫ " + __goP2.Count.ToString(
                System.Globalization.CultureInfo.InvariantCulture) + " БЛИЖАЙШИХ ИЗ "
              + __goT.Length.ToString(
                System.Globalization.CultureInfo.InvariantCulture)
              + " — остальные дальше и причиной быть не могут"
            : "";
        return __goA + "; линий этой оси уже " + __goT.Length.ToString(
            System.Globalization.CultureInfo.InvariantCulture) + ": "
            + String.Join(", ", __goP2) + __goMore
            + ". Revit возвращает null БЕЗ СООБЩЕНИЯ, когда линия этой оси в этом месте УЖЕ ЕСТЬ:"
            + " расстояние 0 мм у одной из перечисленных и есть причина."
            + " СЛЕДУЮЩИЙ ХОД: сдвинь точку по названной оси так, чтобы до каждой существующей линии стало больше нуля";
    }
    catch { return "перечитать линии этой оси не удалось"; }
};
"""


def _with_grid_occ_helper(program: str) -> str:
    """Insert ``__KirGridOcc`` ONLY if the program calls it."""
    if "__KirGridOcc(" not in program:
        return program
    anchor = "var __results = new Dictionary<string, object>();"
    if anchor not in program:
        raise AssertionError(
            "программа зовёт __KirGridOcc, но в ней нет якоря преамбулы — "
            "объявление было бы потеряно, и это CS0103 на машине пользователя")
    return program.replace(anchor, _GRID_OCC_HELPER_CS + anchor, 1)


def _with_mesh_canon_helper(program: str) -> str:
    """Insert the surface canonicalizer ONLY if the program calls it.

    The same seam and the same anchor as ``__ClassName``: the declaration is
    obligated to stand before any operation code, otherwise the
    ``create_directshape`` witness gets CS0103 on the user's machine, not on
    ours.
    """
    # 🔴 CONDITION EXPANDED ON 19.08.2026, AND WITHOUT THIS THE NEW WITNESS
    # WOULD HAVE SHIPPED BROKEN. The check stood on ONE name out of the three
    # declared in the block; `sketch_loops_witness` calls `__KirCanonUnit`
    # and `__KirCanonCmp`, but does NOT call `__KirCanonPayload` (that one is
    # hardwired to 3x3 triangles and does not fit rings of variable length).
    # A program with a slab would not have gotten the declaration at all —
    # CS0103 on the user's machine, exactly the outcome this seam was put up
    # to prevent. We ask for ALL names in the block, not just one.
    if not any(name in program for name in
               ("__KirCanonPayload(", "__KirCanonUnit(", "__KirCanonCmp")):
        return program
    anchor = "var __results = new Dictionary<string, object>();"
    if anchor not in program:
        raise AssertionError(
            "программа зовёт __KirCanonPayload, но в ней нет якоря преамбулы — "
            "объявление было бы потеряно, и это CS0103 на машине пользователя")
    return program.replace(anchor, _MESH_CANON_HELPER_CS + anchor, 1)


def _with_program_helpers(program: str) -> str:
    """Both conditional preamble declarations, each only if it is called."""

    return _with_grid_occ_helper(
        _with_mesh_canon_helper(_with_class_name_helper(program)))


def _stamp_block(el_var: str, stamp: str) -> str:
    if not stamp.startswith("kir:a5:"):
        # Public/chat emission remains byte-compatible.  Only an A5 run treats
        # this value as an authoritative ownership receipt used for orphan
        # reconciliation and cleanup.
        return (f'try {{ Parameter __cm = {el_var}.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); '
                f'if (__cm != null && !__cm.IsReadOnly) __cm.Set({_cs(stamp)}); }} catch {{ }}')
    return (
        f'try {{ Parameter __cm = {el_var}.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); '
        f'if (__cm == null) throw new InvalidOperationException("A5 stamp parameter missing"); '
        f'if (__cm.IsReadOnly) throw new InvalidOperationException("A5 stamp parameter is read-only"); '
        f'if (!__cm.Set({_cs(stamp)}) || __cm.AsString() != {_cs(stamp)}) '
        f'throw new InvalidOperationException("A5 stamp readback mismatch"); }} '
        f'catch (Exception __stampEx) {{ throw new InvalidOperationException('
        f'"A5 stamp write failed: " + __stampEx.Message, __stampEx); }}')


def _stamp_readback(el_var: str, rb_var: str = "__rb", type_level: bool = False) -> str:
    """Read the stamp from Revit; never echo the value we merely attempted."""
    bip = ("ALL_MODEL_TYPE_COMMENTS" if type_level
           else "ALL_MODEL_INSTANCE_COMMENTS")
    return (f"    try {{ var __stampParam = {el_var}.get_Parameter(BuiltInParameter.{bip}); "
            f"if (__stampParam != null) {rb_var}[\"stamp\"] = __stampParam.AsString(); }} catch {{ }}\n")


def _pt3(pt: list) -> tuple:
    return (pt[0], pt[1], pt[2] if len(pt) > 2 else 0)


def _endpoint_check(el_var: str, oid: str, p0, p1, tol: float, three_d: bool) -> str:
    x0, y0, z0 = _pt3(p0)
    x1, y1, z1 = _pt3(p1)
    orient_z = (f' + Math.Pow(MM(__a.Z) - {z0}, 2)' if three_d else '')
    orient_z_b = (f' + Math.Pow(MM(__b.Z) - {z0}, 2)' if three_d else '')
    zc = (f' || Math.Abs(MM(__e0.Z) - {z0}) > {tol} || Math.Abs(MM(__e1.Z) - {z1}) > {tol}'
          if three_d else "")
    return (
        f"var __lc = {el_var}.Location as LocationCurve;\n"
        f"    if (__lc == null) __post.Add({_cs(oid + ': нет LocationCurve')});\n"
        f"    else\n    {{\n"
        f"        var __a = __lc.Curve.GetEndPoint(0); var __b = __lc.Curve.GetEndPoint(1);\n"
        f"        double __da = Math.Pow(MM(__a.X) - {x0}, 2) + Math.Pow(MM(__a.Y) - {y0}, 2){orient_z};\n"
        f"        double __db = Math.Pow(MM(__b.X) - {x0}, 2) + Math.Pow(MM(__b.Y) - {y0}, 2){orient_z_b};\n"
        f"        var __e0 = __da <= __db ? __a : __b; var __e1 = __da <= __db ? __b : __a;\n"
        f"        if (Math.Abs(MM(__e0.X) - {x0}) > {tol} || Math.Abs(MM(__e0.Y) - {y0}) > {tol} ||\n"
        f"            Math.Abs(MM(__e1.X) - {x1}) > {tol} || Math.Abs(MM(__e1.Y) - {y1}) > {tol}{zc})\n"
        f"            __post.Add({_cs(oid + ': endpoints mismatch (geometry)')});\n"
        f"    }}")


def _level_check_expr(el_var: str, oid: str, bip: str, id_expr: str) -> str:
    """id_expr is a C# string expression (literal or <var>.Id.ToString())."""
    return (
        f"var __bp = {el_var}.get_Parameter(BuiltInParameter.{bip});\n"
        f"    if (__bp == null || __bp.AsElementId() == null || __bp.AsElementId().ToString() != {id_expr})\n"
        f"        __post.Add({_cs(oid + ': level binding mismatch (topology)')});")


def _split_witness(
    key: str, body: str, message: str, *,
    lead: str = "    ", tail: str = "\n",
    tol=None,
    style: str = "else_block",
) -> WitnessCheck:
    reader, sep, verdict = body.partition("\n")
    return WitnessCheck(
        obligation_key=key,
        reader_cs=lead + reader + sep,
        verdict_cs=verdict + tail,
        message=message,
        tol=tol,
        style=style,  # type: ignore[arg-type]
    )


def shifted_point(pt, shift) -> list | tuple:
    """The point shifted by `shift`. AT ZERO SHIFT — THE SAME POINT.

    🔴 RETURNING THE ORIGINAL OBJECT HERE IS NOT AN OPTIMIZATION, IT IS
    PARITY. `6000 + 0.0` gives `6000.0`, and that is a DIFFERENT LITERAL in
    the emitted C#: the harmless-looking "add zero" would shift bytes in
    every emission of the corpus that has ends (646 of 2340 per the
    07.09.2026 measurement), fixing nothing in any of them. The same
    technique, for the same reason, stands in `geom.shifted_host_shape`
    (`moved = bool(...)`).

    Exactly the components the point HAS get shifted: a planar 2D point has
    no Z, and assigning it a third coordinate would mean changing the shape
    of the data for the sake of arithmetic.
    """
    if not any(shift):
        return pt
    return [pt[i] + shift[i] for i in range(min(len(pt), len(shift)))] + list(pt[len(shift):])


def final_shift(op: Mapping) -> tuple:
    """The result of the last lawful writer FOR THIS OP, via one reader.

    🔴 ONE READ FOR EIGHT EMITTERS (E-3, 07.09.2026). `emit_program` attaches
    `spec.SYNTHETIC_FINAL_SHIFT` to the op's copy only under a NONZERO shift;
    the field now has nine readers — wall, pipe, duct, tray, conduit, two
    stock shapes, beam, and truss. `op.get(...) or (0.0, 0.0, 0.0)` written
    nine times is nine places where the default can diverge; here it is one.
    The field's name is still declared exactly once
    (`registry_base.SYNTHETIC_FINAL_SHIFT`), and here it is IMPORTED, not
    rewritten as a literal.
    """
    return op.get(SYNTHETIC_FINAL_SHIFT) or (0.0, 0.0, 0.0)


# ═══ WHAT THE PROGRAM'S TAIL DOES WITH THIS OP'S RESULT (E-4, 08.09.2026) ═══
#
# 🔴 ONE LAW, TWO CONSUMERS, NOT A SINGLE SECOND OPINION. The question "will
# someone downstream rewrite my parameter" and "will someone downstream
# delete my element" is a question about the PROGRAM, while the emitter is
# called per single op and does not see the program. `geom.program_shift_after`
# (the result of the last writer by COORDINATES) is built exactly the same
# way: the program's TAIL is taken and treated as ONE body.
#
# The emitters have exactly two consumers — `authoring.emit_program` and
# `translation_cert.certify_op` — and both call THESE functions. If each
# computed it on its own, the emission and its proof would diverge on the
# first edit: the certificate checks the stage STRICTLY and would declare
# unproven exactly what the emitter itself printed.
#
# WHY NOT A SYNTHETIC FIELD ON THE OP (like `__final_shift__`). A field needs
# a writer, and there would be two writers (`emit_program` and
# `certify_program`), and the closed list of the field's owners would have
# to be kept by hand. Here the fact travels as a CALL PARAMETER: both
# consumers have the whole program, there is nothing to attach to someone
# else's dict.


def program_tail_writes(ops: Sequence, index: int) -> tuple:
    """`(rewritten obligation keys, id of the deleting op)` for `ops[index]`.

    Computed over the program's TAIL (`index` excluded: an op does not
    rewrite or delete itself). Addressing is `by: ref` only, as with
    `geom.program_shift_after`: a `set_param` on a foreign `element_id`
    pertains to an element this program did not create, and no creation
    obligation is pinned to it.

    The Revit parameter name is translated into an obligation key by the SOLE
    reader of the registry table — `registry_base.obligation_for_revit_param`.
    """

    origin = ops[index]
    oid = origin.get("id")
    op_name = origin.get("op")
    if not oid or not op_name:
        return frozenset(), None
    rewritten: set = set()
    deleted_by = None
    for later in ops[index + 1:]:
        target = later.get("target")
        if not (isinstance(target, Mapping) and target.get("by") == "ref"
                and target.get("value") == oid):
            continue
        name = later.get("op")
        if name == "set_param":
            key = obligation_for_revit_param(op_name, later.get("param"))
            if key is not None:
                rewritten.add(key)
        elif name == "delete":
            deleted_by = later.get("id")
    return frozenset(rewritten), deleted_by


def restage_for_program_tail(post, rewritten, deleted_by):
    """The op's witnesses, adjusted for what the program's tail does.

    TWO TRANSFORMATIONS, AND NEITHER IS A WEAKENING:

    * **rewritten parameter → operation stage.** The same predicate, the
      same tolerance, the same obligation key; ONLY the moment of execution
      changes — the end of ITS OWN operation instead of the end of the
      program. The form is not invented anew: `set_param.value_held` (E-1)
      and `change_type.type_assignment`
      (docs/OPERATION_WITNESS_STAGE_RU.md) are closed exactly this way. The
      operation stage is printed BEFORE `doc.Regenerate()`, so only a
      witness that reads a PARAMETER, not geometry, is entitled to move
      there — and the registry table by construction holds only parameters
      (the row's third member is a BuiltInParameter, checked by the
      emission test).

    * **element deleted by this same program → no final witnesses.** Not
      "the check was dropped": a witness of ABSENCE already stands in the
      same emission and belongs to the DELETING op (`// post D`:
      `doc.GetElement(__delid) != null`). Attaching a second one on the
      creation side would mean setting up a second truth about one fact. And
      the final creation block, left in place, would read the DELETED
      element after `doc.Delete` — measured 08.09: `doc.Delete` at 86,
      `// post W` at 96 of the same emission.

    🔴 A NAMED UNKNOWN (not closed here). The deletion branch drops the
    final witnesses RELYING on the deletion happening within the same
    transaction: in `atomic` that is a guarantee (a `delete` refusal rolls
    back the whole program, and the created element is gone too). In
    `per_op`, neighbors are committed one at a time, and if `delete` fails
    at runtime, the wall will be left WITHOUT final geometry witnesses.
    There is no live Revit in this tree (0 runs), the parity corpus carries
    no such chain at all (0 of 2361), and inventing behavior on this point
    would be worse than naming the gap.

    AT AN EMPTY TAIL, THE SAME OBJECT IS RETURNED. This is not an
    optimization, it is parity: rebuilding the tuple would shift nothing in
    the bytes, but `dataclasses.replace` on every witness of the corpus is
    an unnecessary risk where there is nothing to change.
    """

    if not rewritten and deleted_by is None:
        return post
    bare = isinstance(post, BarePost)
    checks = tuple(post.checks if bare else post)
    if deleted_by is not None:
        kept = tuple(c for c in checks if c.stage != "final")
    else:
        kept = tuple(
            _dc_replace(c, stage="operation")
            if c.stage == "final" and c.obligation_key in rewritten else c
            for c in checks)
    if not kept:
        return kept
    return BarePost(kept) if bare else list(kept)


def render_tail_adjusted_post(oid: str, post, rewritten, deleted_by) -> tuple:
    """`(operation_cs, final_cs)` adjusted for the program's tail.

    An empty set is legal here in EXACTLY ONE CASE — when all of the op's
    witnesses were final ones and there is no element left at the final
    stage: it was deleted by this same program. An ordinary empty post is
    still a refusal (`render_staged_post` fail-closed): an op without a
    witness is a silently unverified element.
    """

    adjusted = restage_for_program_tail(post, rewritten, deleted_by)
    if deleted_by is not None and not adjusted:
        return "", ""
    # Every OTHER empty post goes to `render_staged_post` and gets its
    # refusal there: substituting it with our own exception would mean
    # setting up a second message about one error.
    return render_staged_post(oid, adjusted)


def endpoint_witness(
    el_var: str, oid: str, p0, p1, tol, three_d: bool,
    *, lead: str = "    ", tail: str = "\n",
    shift: tuple = (0.0, 0.0, 0.0),
) -> WitnessCheck:
    """Model form of :func:`_endpoint_check` (public: struct_emit uses it).

    ``tol`` — a :class:`Tolerance` minted by the registry, not a number: the
    tolerance's provenance is presented as an object (law 1, emit_model.py).

    ``shift`` — the summed `delta_mm` of lawful `move_elements` of the SAME
    PROGRAM standing AFTER this op (`geom.program_shift_after`). The final-
    stage witness is obligated to check against the RESULT of the last
    lawful writer, not the first writer's authorial intent: authorial ends
    are correct at the end of THEIR OWN operation, but by the end of the
    PROGRAM a move has lawfully rewritten them. The default is zero shift,
    in which case the bytes are word-for-word unchanged.
    """

    p0 = shifted_point(p0, shift)
    p1 = shifted_point(p1, shift)
    return _split_witness(
        "endpoints", _endpoint_check(el_var, oid, p0, p1, tol, three_d),
        "endpoints mismatch (geometry)", lead=lead, tail=tail,
        tol=tol, style="else_block")


def level_chain_witness(
    el_var: str, oid: str, id_expr: str,
    *, key: str = "level_binding", lead: str = "    ", tail: str = "\n",
) -> WitnessCheck:
    """Model form of :func:`_level_chain_check` (public: struct_emit uses it)."""

    return _split_witness(
        key, _level_chain_check(el_var, oid, id_expr),
        "level binding mismatch (topology)", lead=lead, tail=tail,
        style="guard")


def bbox_extents_witness(
    el_var: str, oid: str, xmin, xmax, ymin, ymax, tol,
    *, key: str = "bbox",
) -> WitnessCheck:
    """Shared floor/roof/slab bbox-extents witness (public for struct_emit).

    ``tol`` — a :class:`Tolerance` from the registry (the ``bbox_mm`` key of
    its own op).

    A BOUNDARY, NAMED 21.08.2026: this witness measures ONLY X and Y and is
    correct exactly for a planar sketch. Its carriers have no sloped plane
    by construction — the analysis is in the block above.
    """

    return WitnessCheck(
        obligation_key=key,
        reader_cs=f"    var __bb = {el_var}.get_BoundingBox(null);\n",
        verdict_cs=(
            f"    if (__bb == null) __post.Add({_cs(oid + ': нет BoundingBox')});\n"
            f"    else if (Math.Abs(MM(__bb.Min.X) - {xmin}) > {tol} || Math.Abs(MM(__bb.Max.X) - {xmax}) > {tol} ||\n"
            f"             Math.Abs(MM(__bb.Min.Y) - {ymin}) > {tol} || Math.Abs(MM(__bb.Max.Y) - {ymax}) > {tol})\n"
            # 🔴 THE MEASURED VALUE GETS PRINTED. For the third time since
            # 20.08 a message of the "did not match" kind has cost a live
            # run: the reader sees the expected value in the program, but
            # NOBODY sees the measured one — when postconditions are
            # violated the transaction rolls back and there will be no
            # receipt with numbers at all.
            f"        __post.Add({_cs(oid + ': bbox extents mismatch (geometry): ')}\n"
            f"            + \"[\" + MM(__bb.Min.X).ToString(\"F1\") + \" \" + MM(__bb.Max.X).ToString(\"F1\")\n"
            f"            + \" | \" + MM(__bb.Min.Y).ToString(\"F1\") + \" \" + MM(__bb.Max.Y).ToString(\"F1\") + \"]\"\n"
            f"            + {_cs(f' против авторских [{xmin} {xmax} | {ymin} {ymax}] при допуске {tol} мм')});\n"),
        message="bbox extents mismatch (geometry)",
        tol=tol,
        style="else_block")


def canon_unit(mm: float, grid: float) -> int:
    """The Python half of ``__KirCanonUnit``: mm on the canon grid, in
    INTEGERS.

    🔴 TWO PLACES OBLIGATED TO AGREE, AND WE DO NOT SET UP A THIRD. The
    rounding law is half-away-from-zero (``floor(s+0.5)`` / ``ceil(s-0.5)``),
    the same one used by ``decompile.geom_extract._round_mm`` and by the C#
    helper above. ``Math.Round``/``round()`` are forbidden here by both:
    banker's rounding would carry EXACTLY HALF of the boundary vertices into
    the neighboring cell, and the preimage would diverge from the image
    silently — that is, the witness would go red on correct geometry.

    Equality of the two halves is pinned by ``test_sketch_loops_witness`` on
    a table of boundary values (exact halves, negatives, zero): our named
    defect class is a value declared in one place and read in another, and
    it is cured by checking EQUALITY OF THE DECLARATIONS, not by a third
    copy.
    """
    scaled = float(mm) / float(grid)
    return (math.floor(scaled + 0.5) if scaled >= 0.0
            else math.ceil(scaled - 0.5))


def loops_payload_expected(rings, grid) -> str:
    """The expected ring signature — ONE for all sources.

    Factored out separately because Revit has several sources of rings
    (``Sketch.Profile`` for a slab and ceiling, ``BeamSystem.Profile`` for a
    beam system, ``GetBoundary()`` for a pad), while the CANON of the
    signature is obligated to be one: two signatures of one value will
    diverge on the first edit, and that is our named defect class.
    """
    # 🔴 VERTICES ARE SORTED BY NUMBER, NOT BY STRING (24.08.2026, live Revit).
    #
    # A `sorted(<ready-made strings>)` used to stand here, while the C# half
    # sorts pairs `__slv.Sort(__KirCanonCmp)` — NUMERICALLY. The two halves
    # matched right up to the first vertex of a different MAGNITUDE: «12000»
    # is lexicographically less than «8000», numerically it is greater. Our
    # named defect class in pure form: a value declared in two places with
    # nothing bringing them together — the `test_sketch_loops_witness` test
    # pinned equality of the ROUNDINGS, but nobody asked about the ORDER.
    #
    # THE MEASURED COST: the sketch witness went red on CORRECT geometry for
    # any ring where coordinates of different magnitude sit next to each
    # other (in a real building that is almost every floor slab). There was
    # nothing to see this with while floor slabs did not make it through at
    # all — 0 of 82 in the K3 port — and the very first ring that did make
    # it through (0..6000 × 8000..12000) rolled back the whole program.
    #
    # The order repeats `__KirCanonCmp` verbatim: X first, then Y. Rings are
    # still compared with each other by STRING — the C# side does the same
    # there (`__slr.Sort(StringComparer.Ordinal)`), and there is no
    # divergence.
    g = float(getattr(grid, "value", grid))
    return ";".join(sorted(
        "|".join(
            "%d,%d" % pair
            for pair in sorted(
                (canon_unit(pt[0], g), canon_unit(pt[1], g)) for pt in ring))
        for ring in rings))


def loops_verdict_cs(var: str, oid: str, expected: str, n_rings: int,
                     what: str) -> str:
    """The verdict on the ring signature — ONE for all sources.

    A READ REFUSAL AND A SHAPE MISMATCH ARE DIFFERENT OUTCOMES, AND BOTH ARE
    NAMED. Merging them into one code would ask the reader to interpret a
    message that carries no distinction: "failed to read" is OUR fault to
    fix, "diverged" is the PROGRAM's fault to fix.
    """
    return (f"    if ({var} == null)\n"
            f"        __post.Add({_cs(oid + f': {what} построенного элемента не прочитан(ы) — форма НЕ ПРОВЕРЕНА (geometry)')});\n"
            f"    else if ({var} != {_cs(expected)})\n"
            f"        __post.Add({_cs(oid + f': sketch loops mismatch, expected {n_rings} loop(s) (geometry)')});\n")


def curve_ring_payload_cs(v: str, loops_stmt: str, grid) -> str:
    """C# that canonicalizes ALREADY-ASSEMBLED rings of curves into a
    signature.

    ``loops_stmt`` is obligated to declare ``List<List<Curve>> __slL_<v>`` —
    what exactly ends up there is decided by the caller: for a slab it is
    ``Sketch.Profile``, for a beam system it is ``BeamSystem.Profile`` as one
    ring. Canonicalization, sorting, and printing here are ONE for everyone,
    because the signature is obligated to be comparable across sources.
    """
    return (
        f"    string __slf_{v} = null;\n"
        f"    try\n    {{\n"
        f"{loops_stmt}"
        f"        if (__slL_{v} != null)\n        {{\n"
        f"            var __slr_{v} = new List<string>();\n"
        f"            foreach (var __slc_{v} in __slL_{v})\n"
        f"            {{\n"
        f"                var __slv_{v} = new List<long[]>();\n"
        f"                foreach (Curve __slq_{v} in __slc_{v})\n"
        f"                {{\n"
        f"                    XYZ __slp_{v} = __slq_{v}.GetEndPoint(0);\n"
        f"                    __slv_{v}.Add(new long[] {{ "
        f"__KirCanonUnit(MM(__slp_{v}.X), {grid}), "
        f"__KirCanonUnit(MM(__slp_{v}.Y), {grid}) }});\n"
        f"                }}\n"
        f"                __slv_{v}.Sort(__KirCanonCmp);\n"
        f"                var __slb_{v} = new StringBuilder();\n"
        f"                for (int __sli_{v} = 0; __sli_{v} < __slv_{v}.Count; __sli_{v}++)\n"
        f"                {{\n"
        f"                    if (__sli_{v} > 0) __slb_{v}.Append('|');\n"
        f"                    __slb_{v}.Append(__slv_{v}[__sli_{v}][0].ToString("
        f"System.Globalization.CultureInfo.InvariantCulture));\n"
        f"                    __slb_{v}.Append(',');\n"
        f"                    __slb_{v}.Append(__slv_{v}[__sli_{v}][1].ToString("
        f"System.Globalization.CultureInfo.InvariantCulture));\n"
        f"                }}\n"
        f"                __slr_{v}.Add(__slb_{v}.ToString());\n"
        f"            }}\n"
        f"            __slr_{v}.Sort(StringComparer.Ordinal);\n"
        f"            __slf_{v} = string.Join(\";\", __slr_{v});\n"
        f"        }}\n"
        f"    }}\n"
        f"    catch (Exception) {{ __slf_{v} = null; }}\n")


def profile_loops_witness(
    el_var: str, oid: str, cs_class: str, rings, grid,
    *, key: str = "profile_loops",
) -> WitnessCheck:
    """PROFILE SHAPE for an element whose profile is read DIRECTLY, without a
    sketch.

    The occasion is `create_beam_system`: its witness ALREADY walked every
    curve of the profile and read BOTH ends, then collapsed everything into
    four bounding-box numbers. The evidence was already fully in hand, and
    only the comparison was discarding it.
    """
    expected = loops_payload_expected(rings, grid)
    v = _safe(oid)
    loops_stmt = (
        f"        var __slL_{v} = new List<List<Curve>>();\n"
        f"        var __slE_{v} = doc.GetElement({el_var}.Id) as {cs_class};\n"
        f"        CurveArray __slA_{v} = __slE_{v} == null ? null : __slE_{v}.Profile;\n"
        f"        if (__slA_{v} == null || __slA_{v}.Size == 0) __slL_{v} = null;\n"
        f"        else\n        {{\n"
        f"            var __slO_{v} = new List<Curve>();\n"
        f"            foreach (Curve __slX_{v} in __slA_{v}) __slO_{v}.Add(__slX_{v});\n"
        f"            __slL_{v}.Add(__slO_{v});\n"
        f"        }}\n")
    return WitnessCheck(
        obligation_key=key,
        reader_cs=curve_ring_payload_cs(v, loops_stmt, grid),
        verdict_cs=loops_verdict_cs(f"__slf_{v}", oid, expected, len(rings),
                                    "профиль"),
        message="profile loops mismatch (geometry)",
        tol=grid,
        style="guard")


def path_points_witness(
    el_var: str, oid: str, path, grid, *, key: str = "path_points",
) -> WitnessCheck:
    """PATH SHAPE — FOR AN OPEN POLYLINE, NOT A RING.

    🔴 A PATH IS NOT A RING, AND THE RING WITNESS HERE WOULD HAVE ACCUSED
    CORRECT GEOMETRY. A ring takes ONE vertex per edge — the loop closure
    returns the walk to the start, and the last point coincides with the
    first. An open path has no closure: taking one point per edge would lose
    the path's END, and a shift of the last vertex would pass unnoticed. So
    here BOTH ends of every curve are taken.

    🔴 BOTH ENDS BELONG TO THEIR OWN EDGE, NOT A SHARED BAG (04.09.2026).
    Before this fix, all ends of all edges were poured into ONE ring, and the
    shared canonicalizer sorted the resulting multiset. For a ring that
    sorting is CORRECT — the walk is closed, the starting vertex and
    direction belong to Revit — but for an OPEN path it erased ORDER, that
    is, exactly the quantity that defines a path:

        path A-B-C-D and path A-C-B-D gave THE SAME signature
        `0,0|3000,9000|3000,9000|8000,0|8000,0|12000,5000`
        (measured on the tree 04.09.2026, both paths compile ok=True)

    because the multiset {A,B,B,C,C,D} is indistinguishable from
    {A,C,C,B,B,D} under any sort. The witness was NOT blind at all in this —
    shifting any point by 1 mm changes the signature — and that is exactly
    why the defect survived unnoticed: every prior control moved a vertex, it
    never permuted one.

    THE COST IS THE SAME AS FOR THE 24.08 FIX BELOW, AND IT IS RECORDED IN
    THE SAME PLACE: a wrong signature produces `__t.RollBack()` of the WHOLE
    program on CORRECT geometry, accusing the author of someone else's
    mistake. Here it arrives from the other side — the signature will MATCH
    for two DIFFERENT paths, meaning a railing built not as the author
    intended will be signed off green.

    WHAT EXPRESSES THE ORDER, AND WHY THIS IS NOT A SECOND CANONICALIZER.
    Every edge becomes ITS OWN ring of two points, and from there the SAME
    helper does the work (`loops_payload_expected` in Python,
    `curve_ring_payload_cs` -> `__slv.Sort(__KirCanonCmp)` +
    `__slr.Sort(StringComparer.Ordinal)` in C#). Not a single new line of law
    appeared: edges are sorted against each other by STRING exactly like
    sketch rings, ends within an edge by NUMBER exactly like ring vertices.
    The multiset of EDGES determines the path uniquely up to reversal (a
    graph path is recoverable from its set of edges), and reversal is exactly
    the freedom Revit is entitled to choose for itself — just as it chooses
    the starting point of a ring's walk.

    WHAT IS LOST BY THIS IS NAMED HONESTLY: the signature is no longer
    indifferent to a RE-SPLITTING of the path. It never truly was — an edge
    that Revit cuts in two added a new vertex to the bag twice — so what is
    removed is not a property, but this docstring's earlier description of
    it.

    WHAT IS READ: ``Railing.GetPath()``. The evidence exists and is measured,
    not assumed — the corpus carries 1058 paths (`railing_path_index`), and
    exactly as many refusals of «railing is a path element and has no closed
    Sketch profile»: a railing has no sketch by construction, the path is
    read by a DIFFERENT call.

    🔴 AND THE CANON'S RECORD «GetPath() returns 1-5 straight lines» IS
    REFUTED BY THE SAME MEASUREMENT: 2093 curves across 1058 paths —
    **1790 lines and 303 ARCS**, path length up to EIGHT curves. An arc,
    however, is stored as ONE curve (the record has `arc_midpoints_mm`), so
    reading by endpoints is correct for it too; the arc's convexity is not
    part of the signature and remains the bounding box's concern.
    """
    # AN EDGE IS ITS OWN RING OF TWO ENDS. A single flat list of all ends
    # (`pts`) used to stand here, and the shared sort erased order: see the
    # 04.09 analysis in the docstring. The shared helper receives a LIST OF
    # RINGS exactly like a sketch — not a single new carrier of the law was
    # set up.
    edges = [[(a[0], a[1]), (b[0], b[1])] for a, b in zip(path, path[1:])]
    # 🔴 THE SIGNATURE IS COMPUTED BY THE SHARED HELPER, NOT THIS FUNCTION
    # (24.08.2026).
    #
    # A local `sorted(<ready-made strings>)` used to stand here — a third
    # carrier of the same law, even though the C# half is ONE for all three
    # sites (`curve_ring_payload_cs` → `__slv.Sort(__KirCanonCmp)`,
    # NUMERICALLY). The 24.08 ring fix was made in `loops_payload_expected`,
    # two of the three sites started calling the helper, and this one kept
    # computing on its own — and diverged on the very first pair of vertices
    # of DIFFERENT magnitude: «12000» is lexicographically LESS THAN «8000»,
    # numerically GREATER.
    #
    # THE COST, REPRODUCED OFFLINE: path [[0,0],[8000,0],[12000,0]] gives
    # `ok=True` with zero diagnostics, in C# the expectation that ships is
    # `0,0|12000,0|8000,0|8000,0`, while that same C# builds
    # `0,0|8000,0|8000,0|12000,0` → `__post.Count > 0` → `__t.RollBack()` of
    # the WHOLE program on CORRECT geometry, accusing the author of someone
    # else's mistake. Corpus: 1058 paths, and a real railing's magnitude
    # differs almost always. Prior path tests did not see this because all
    # their vertices were of ONE magnitude (0, 4000, 2500) — there both laws
    # agree.
    #
    # The lesson is worth more than the fix: once a defect shape is caught,
    # look for a second carrier IN THE SAME PASS. Here it was not looked for,
    # and one fix failed to reach its neighbor TWICE in a row.
    expected = loops_payload_expected(edges, grid)
    v = _safe(oid)
    loops_stmt = (
        f"        List<List<Curve>> __slL_{v} = null;\n"
        f"        var __slP_{v} = {el_var}.GetPath();\n"
        f"        if (__slP_{v} != null && __slP_{v}.Count > 0)\n        {{\n"
        f"            __slL_{v} = new List<List<Curve>>();\n"
        # BOTH ENDS, BUT WITHIN THEIR OWN EDGE: the curve is placed TWICE
        # (itself and reversed), and the shared canonicalizer will take
        # `GetEndPoint(0)` of each copy — that is, the start and end of
        # EXACTLY THIS edge. Every edge ships as a separate ring, so the
        # path survives an edge reordering, but not a reversal of the path
        # or a reversal of an edge — and that is correct: Revit chooses
        # those.
        f"            foreach (Curve __slx_{v} in __slP_{v})\n"
        f"            {{\n"
        f"                var __slo_{v} = new List<Curve>();\n"
        f"                __slo_{v}.Add(__slx_{v});\n"
        f"                __slo_{v}.Add(__slx_{v}.CreateReversed());\n"
        f"                __slL_{v}.Add(__slo_{v});\n"
        f"            }}\n"
        f"        }}\n")
    return WitnessCheck(
        obligation_key=key,
        reader_cs=curve_ring_payload_cs(v, loops_stmt, grid),
        verdict_cs=loops_verdict_cs(f"__slf_{v}", oid, expected, len(edges),
                                    "путь"),
        message="path points mismatch (geometry)",
        tol=grid,
        style="guard")


def sketch_loops_witness(
    el_var: str, oid: str, rings: Sequence[Sequence[Sequence[float]]],
    grid: float, *, key: str = "sketch_loops",
) -> WitnessCheck:
    """SKETCH SHAPE, NOT ITS BOUNDING BOX — the witness reads VERTICES.

    WHY, BY ARITHMETIC. ``bbox_extents_witness`` pins FOUR numbers (xmin,
    xmax, ymin, ymax). An L-shaped contour of six vertices has TWELVE
    coordinates, meaning eight are free: the inner corner can be moved
    anywhere within the bounding box, a notch can be lost, an opening filled
    in — the witness stays green, and it signs off on the ``(geometry)``
    axis. This is our cardinal invariant, violated in the witness itself:
    signing off on an axis it never read.

    WHAT THIS ONE CATCHES, BY NAME: a shifted vertex (the multiset changes),
    a lost notch (the ring's vertex count changes), a filled-in opening (the
    RING COUNT changes).

    WHY A MULTISET, NOT A POSITIONAL LIST — THIS IS A REQUIREMENT, NOT TASTE.
    Revit canonicalizes the ring: the starting vertex and the walk direction
    belong to IT, not to the author (recorded in the canon on
    ``__ReadLoops``: positional lists «land on the wrong edge»). The
    comparison is obligated to be stable under a rotation of the ring and
    under a change of direction — a sorted multiset is exactly that BY
    CONSTRUCTION, and it is cheaper than searching for the rotation.

    BOUNDARIES, NAMED, NOT SILENCED:

    * **an arc gives only its ends.** The ring is read via ``GetEndPoint(0)``
      of every curve, meaning an arc's convexity is not part of the
      multiset. An arc replaced by a chord with the same ends is NOT caught
      by this witness — it continues to be guarded by the bounding box,
      which stays paired with this one;
    * **vertex order is not pinned.** A permutation giving a different (even
      self-intersecting) polygon on the SAME vertices will pass. The ban on
      self-intersection stands earlier — ``KIR-T004`` at decompile time;
    * **the bounding box is NOT dropped.** It catches an arc-to-chord swap
      and is cheaper; the two witnesses judge DIFFERENT things and both
      stay.
    """
    expected = loops_payload_expected(rings, grid)
    v = _safe(oid)
    loops_stmt = (
        f"        List<List<Curve>> __slL_{v} = null;\n"
        f"        var __slk_{v} = new List<Sketch>();\n"
        f"        foreach (ElementId __sld_{v} in {el_var}.GetDependentElements(null))\n"
        f"        {{\n"
        f"            var __sls_{v} = doc.GetElement(__sld_{v}) as Sketch;\n"
        f"            if (__sls_{v} != null) __slk_{v}.Add(__sls_{v});\n"
        f"        }}\n"
        # EXACTLY ONE SKETCH — OTHERWISE A REFUSAL, NOT A CHOICE. Measured
        # on the corpus: 174 elements have TWO dependent sketches, and
        # taking the "first" would mean bearing witness to the wrong
        # profile. A refusal here is more honest than a choice.
        f"        if (__slk_{v}.Count == 1)\n        {{\n"
        f"            __slL_{v} = new List<List<Curve>>();\n"
        f"            foreach (CurveArray __slc0_{v} in __slk_{v}[0].Profile)\n"
        f"            {{\n"
        f"                var __slo_{v} = new List<Curve>();\n"
        f"                foreach (Curve __slx_{v} in __slc0_{v}) __slo_{v}.Add(__slx_{v});\n"
        f"                __slL_{v}.Add(__slo_{v});\n"
        f"            }}\n"
        f"        }}\n")
    return WitnessCheck(
        obligation_key=key,
        reader_cs=curve_ring_payload_cs(v, loops_stmt, grid),
        verdict_cs=loops_verdict_cs(f"__slf_{v}", oid, expected, len(rings),
                                    "эскиз"),
        message="sketch loops mismatch (geometry)",
        tol=grid,
        style="guard")


def spline_points_witness(
    el_var: str, oid: str, points: Sequence[Sequence[float]], tol,
    *, key: str = "spline_points",
) -> WitnessCheck:
    """THE DECLARED CURVE POINT LIES ON THE BUILT SKETCH.

    WHY A SEPARATE WITNESS, BY ARITHMETIC. For a spline edge, both
    neighboring witnesses are blind exactly where the curve lives:
    `sketch_loops_witness` reads ``GetEndPoint(0)``, that is, the ENDS of
    edges — and the ends are the same for a straight line and for any curve
    between them; the bounding box on a spline UNDERSTATES by construction
    (`contour.edges_bbox` — the shape between the points is Revit's choice,
    we know only our own chord sampling). So without this check, an op would
    build a curve and sign off on the ``(geometry)`` axis without ever
    reading it.

    WHAT THIS PROVES AND WHY IT MIGHT FAIL. The author declared that the
    curve passes THROUGH these points. The comparison side is the curve read
    FROM THE BUILT SKETCH, not our own variable or our own sampling. Revit is
    free to simplify the curve, replace it with a segment, drop a point —
    every such outcome widens the distance and turns the witness red. This is
    exactly how the check differs from confirming a setter.

    🔴 THE SKETCH'S ELEVATION IS TAKEN FROM THE SKETCH ITSELF, NOT FROM THE
    MODEL'S ZERO, AND WITHOUT THIS THE WITNESS WOULD BE MEASURING THE
    STORY'S HEIGHT. The contour is emitted in the model's XY plane
    (``P(x, y, 0)``), while `Floor.Create` places the sketch AT THE LEVEL:
    the 3D distance from our point to the curve would carry the level's
    elevation in full and would go red on correct geometry ever more
    strongly the higher the story. So the probe point is raised to the
    elevation read off the profile's first curve.

    A BOUNDARY, NAMED HONESTLY: the technique is correct for a HORIZONTAL
    sketch. A profile whose ends diverge in Z is a NAMED refusal, not a
    silent substitution of the first elevation: a sloped sketch means this
    check's premise does not hold, and staying silent about that would be
    exactly the outcome that is forbidden.

    THE TOLERANCE IS DERIVED, NOT ASSIGNED: Revit's own ``VertexTolerance``
    ("two points closer than this are considered coincident") plus the
    coordinate print quantum (`contour.EMIT_COORD_QUANTUM_MM`) — our own
    boundary already differs from the ideal by that amount. ⚠️ NOT VERIFIED
    LIVE: if Revit rebuilds the Hermite curve into a NURBS approximation, the
    points may drift further, and the first live run is obligated to confirm
    the tolerance or refute it. A false red there would roll back the
    program WITHOUT effect — costly, but that is not a silently-wrong
    outcome, and that is what is absolutely forbidden.
    """
    from kir import contour as C

    v = _safe(oid)
    pts_cs = ", ".join(f"new double[] {{ {float(x)}, {float(y)} }}"
                       for x, y in points)
    reader_cs = (
        f"    List<Curve> __spC_{v} = null;\n"
        f"    var __spK_{v} = new List<Sketch>();\n"
        f"    foreach (ElementId __spD_{v} in {el_var}.GetDependentElements(null))\n"
        f"    {{\n"
        f"        var __spS_{v} = doc.GetElement(__spD_{v}) as Sketch;\n"
        f"        if (__spS_{v} != null) __spK_{v}.Add(__spS_{v});\n"
        f"    }}\n"
        # EXACTLY ONE SKETCH — OTHERWISE A REFUSAL, NOT A CHOICE. The same
        # law and the same number as in `sketch_loops_witness`: 174 elements
        # of the corpus have TWO dependent sketches, and the "first" would
        # bear witness to the wrong profile.
        f"    if (__spK_{v}.Count == 1)\n    {{\n"
        f"        __spC_{v} = new List<Curve>();\n"
        f"        foreach (CurveArray __spA_{v} in __spK_{v}[0].Profile)\n"
        f"            foreach (Curve __spX_{v} in __spA_{v}) __spC_{v}.Add(__spX_{v});\n"
        f"    }}\n"
        f"    double __spTol_{v} = MM(doc.Application.VertexTolerance) + {tol};\n"
        f"    double __spWorst_{v} = -1.0;\n"
        f"    bool __spFlat_{v} = true;\n"
        f"    double __spZ_{v} = 0.0;\n"
        f"    if (__spC_{v} != null && __spC_{v}.Count > 0)\n    {{\n"
        f"        __spZ_{v} = __spC_{v}[0].GetEndPoint(0).Z;\n"
        f"        foreach (Curve __spY_{v} in __spC_{v})\n"
        f"        {{\n"
        f"            if (Math.Abs(MM(__spY_{v}.GetEndPoint(0).Z - __spZ_{v})) > __spTol_{v}\n"
        f"                || Math.Abs(MM(__spY_{v}.GetEndPoint(1).Z - __spZ_{v})) > __spTol_{v})\n"
        f"                __spFlat_{v} = false;\n"
        f"        }}\n"
        f"        var __spP_{v} = new double[][] {{ {pts_cs} }};\n"
        f"        foreach (double[] __spQ_{v} in __spP_{v})\n"
        f"        {{\n"
        f"            XYZ __spT_{v} = new XYZ(U(__spQ_{v}[0]), U(__spQ_{v}[1]), __spZ_{v});\n"
        f"            double __spBest_{v} = double.MaxValue;\n"
        f"            foreach (Curve __spY2_{v} in __spC_{v})\n"
        f"            {{\n"
        f"                try {{ double __spDd_{v} = MM(__spY2_{v}.Distance(__spT_{v}));\n"
        f"                       if (__spDd_{v} < __spBest_{v}) __spBest_{v} = __spDd_{v}; }} catch {{ }}\n"
        f"            }}\n"
        f"            if (__spBest_{v} > __spWorst_{v}) __spWorst_{v} = __spBest_{v};\n"
        f"        }}\n"
        f"    }}\n")
    verdict_cs = (
        f"    if (__spC_{v} == null)\n"
        f"        __post.Add({_cs(oid + ': профиль эскиза не прочитан — кривая не засвидетельствована (geometry)')});\n"
        f"    else if (!__spFlat_{v})\n"
        f"        __post.Add({_cs(oid + ': эскиз не горизонтален — свидетель кривой здесь неприменим (geometry)')});\n"
        f"    else if (__spWorst_{v} > __spTol_{v})\n"
        f"        __post.Add({_cs(oid + ': объявленная точка кривой не легла на построенный эскиз (geometry)')});\n")
    return WitnessCheck(
        obligation_key=key,
        reader_cs=reader_cs,
        verdict_cs=verdict_cs,
        message="spline points off the built sketch (geometry)",
        tol=tol,
        style="guard")


def level_binding_witness(
    el_var: str, oid: str, bip: str, id_expr: str,
    *, key: str = "base_constraint", lead: str = "    ", tail: str = "\n",
) -> WitnessCheck:
    """Model form of :func:`_level_check_expr` (public: struct_emit uses it)."""

    return _split_witness(
        key, _level_check_expr(el_var, oid, bip, id_expr),
        "level binding mismatch (topology)", lead=lead, tail=tail,
        style="guard")


def type_assignment_declarations(oid: str) -> str:
    s = _safe(oid)
    return f"ElementId __requestedType_{s} = null;\nElementId __assignedType_{s} = null;"


def type_assignment_witness(el_var: str, type_var: str, oid: str) -> WitnessCheck:
    """Check this operation's assignment, not an invariant after later edits."""
    s = _safe(oid)
    return WitnessCheck(
        obligation_key="type_assignment", stage="operation",
        reader_cs=(
            f"    try {{ __requestedType_{s} = {type_var}.Id;\n"
            f"        __assignedType_{s} = {el_var}.GetTypeId(); }} catch {{ }}\n"),
        verdict_cs=(
            f"    if (__requestedType_{s} == null || __requestedType_{s} == ElementId.InvalidElementId\n"
            f"        || __assignedType_{s} == null || __assignedType_{s} == ElementId.InvalidElementId\n"
            f"        || !__assignedType_{s}.Equals(__requestedType_{s}))\n"
            f"        __post.Add({_cs(oid + ': type assignment mismatch or unavailable (operation)')});\n"),
        message="type assignment mismatch or unavailable (operation)", style="guard")


def type_assignment_readback_cs(el_var: str, oid: str) -> str:
    """Retained operation observation and a separate fresh final TypeId read."""
    s = _safe(oid)
    return (
        f'    __rb["type_assignment"] = new Dictionary<string, object> {{\n'
        f'        {{"scope", "operation_end_before_commit"}},\n'
        f'        {{"requested_type_id", __requestedType_{s} == null ? null : __requestedType_{s}.ToString()}},\n'
        f'        {{"observed_type_id", __assignedType_{s} == null ? null : __assignedType_{s}.ToString()}} }};\n'
        f'    __rb["type_id"] = null; __rb["type_id_status"] = "unavailable";\n'
        f'    __rb["type_id_reason"] = "type_id_unreadable";\n'
        f'    try {{ var __finalType = {el_var}.GetTypeId();\n'
        f'        if (__finalType != null && __finalType != ElementId.InvalidElementId) {{\n'
        f'            __rb["type_id"] = __finalType.ToString(); __rb["type_id_status"] = "captured";\n'
        f'            __rb["type_id_reason"] = null;\n'
        f'        }} else __rb["type_id_reason"] = "type_id_missing"; }} catch {{ }}\n')


def _readback_block(
    s: str,
    oid: str,
    stamp: str,
    *,
    location_rotation: bool = False,
    family_state: bool = False,
    vertical_extent: bool = False,
    extent_prefix: str = "__vex",
    extra_rows_cs: str = "",
    identity_version: str | None = None,
) -> str:
    """The op's receipt. ``extra_rows_cs`` — ready-made ``__rb[...] = ...``
    lines.

    🔴 WHY SOMEONE ELSE'S LINES HERE, RATHER THAN THE OP'S OWN RECEIPT
    (04.09.2026). An op whose ``ResultSpec.identity_field`` is not ``id`` is
    obligated to put ITS OWN identity field into the receipt, otherwise
    ``address.element_addresses`` will not find it at all. Assembling a
    second receipt block for this would mean setting up a second carrier of
    its form — exactly the defect class already paid for by the ``hosted``
    branch of the railing (its own receipt has already diverged from this
    one on the stamp and on ``type_name``). The empty default does not shift
    a single byte for any prior caller.
    ``identity_version`` explicitly opts selected emitters into the shared
    original-object identity reader. Its unavailable result is not rollback;
    all other callers keep the historical readback bytes.
    """
    identity = (element_identity_readback_cs(f"__el_{s}", revit_version=identity_version)
                if identity_version is not None else "")
    identifier = (f'    try {{ __rb["id"] = __el_{s}.Id.ToString(); }} catch {{ }}\n'
                  if identity_version is not None else f'    __rb["id"] = __el_{s}.Id.ToString();\n')
    rotation = (
        f"    try {{ var __lp2 = __el_{s}.Location as LocationPoint;\n"
        f"        if (__lp2 != null) __rb[\"rotation_deg\"] = "
        f"Math.Round(__lp2.Rotation * 180.0 / Math.PI, 6); }} catch {{ }}\n"
        if location_rotation else ""
    )
    state = (
        f"    try {{ var __fi2 = __el_{s} as FamilyInstance;\n"
        f"        if (__fi2 != null) {{\n"
        f"            __rb[\"mirrored\"] = __fi2.Mirrored;\n"
        f"            __rb[\"hand_flipped\"] = __fi2.HandFlipped;\n"
        f"            __rb[\"facing_flipped\"] = __fi2.FacingFlipped;\n"
        f"        }} }} catch {{ }}\n"
        if family_state else ""
    )
    # 🔴 E3.1 19.08: THE REFERENCE COMES BACK AS A NUMBER. The author wrote
    # "Floor 4" — the receipt hands back the ELEVATION it turned into,
    # alongside what actually resulted. This is NOT a guard: `__rb` ships
    # into the receipt AFTER the commit and rolls nothing back, so here it
    # is safe to name a quantity for which equality would be dangerous (see
    # the one-sided guard `vertical_extent`). The measurement that bought
    # this: 420 columns of 2500 mm instead of 3600–4500 passed the witness,
    # the acceptance check, and THREE audits — not a single receipt field
    # carried either the expected or the actual elevation, and the author
    # had NOTHING to check them against. This one pair of numbers would have
    # been enough on the very first receipt.
    extent = (
        f"    try {{ var __rbb = __el_{s}.get_BoundingBox(null);\n"
        f"        if (__rbb != null) {{\n"
        f"            __rb[\"vertical_extent_mm\"] = new double[] {{ "
        f"Math.Round(MM(__rbb.Min.Z), 1), Math.Round(MM(__rbb.Max.Z), 1) }};\n"
        f"            __rb[\"vertical_extent_expected_mm\"] = new double[] {{ "
        f"Math.Round({extent_prefix}Lo_{s}, 1), Math.Round({extent_prefix}Hi_{s}, 1) }};\n"
        f"        }} }} catch {{ }}\n"
        if vertical_extent else ""
    )
    return (
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n"
        f"    var __rb = new Dictionary<string, object>();\n"
        + identifier + identity
        + extra_rows_cs
        + _stamp_readback(f"__el_{s}") +
        f"    try {{ var __lc2 = __el_{s}.Location as LocationCurve;\n"
        f"        if (__lc2 != null) {{\n"
        f"            var __s2 = __lc2.Curve.GetEndPoint(0); var __e2 = __lc2.Curve.GetEndPoint(1);\n"
        f"            __rb[\"start_mm\"] = new double[] {{ Math.Round(MM(__s2.X), 1), Math.Round(MM(__s2.Y), 1), Math.Round(MM(__s2.Z), 1) }};\n"
        f"            __rb[\"end_mm\"] = new double[] {{ Math.Round(MM(__e2.X), 1), Math.Round(MM(__e2.Y), 1), Math.Round(MM(__e2.Z), 1) }};\n"
        f"        }} }} catch {{ }}\n"
        f"    try {{ var __tid = __el_{s}.GetTypeId();\n"
        f"        if (__tid != null && __tid != ElementId.InvalidElementId) {{\n"
        f"            var __te = doc.GetElement(__tid);\n"
        f"            if (__te != null && __te.Name != null) __rb[\"type_name\"] = __te.Name;\n"
        f"        }} }} catch {{ }}\n"
        + rotation +
        state +
        extent +
        f"    __results[{_cs(oid)}] = __rb;\n}}")


#: The one sentence every "your base moved" refusal says, so the reader learns a
#: single next move instead of three phrasings of it.
IDENTITY_NEXT = ("следующий ход: прочитай элемент заново (query_element_state) "
                 "и повтори от свежей базы")

#: 🔴 A SAVE IS NOT A SUBSTITUTION, AND UNTIL 13.09.2026 THE WIRE SAID IT WAS.
#: `VersionGuid`'s period is «between two saves, synchronize to central and
#: reload latest» (RevitAPI.xml 2023), so the owner pressing Save advances it on
#: every element while changing none of them. Both halves of the identity guard
#: used to refuse with one code, `identity_changed_since_read` — so a saved file
#: was indistinguishable from a swapped element, and a whole republication
#: refused naming a change that never happened. The version half now has its own
#: code and its own next move, which says what actually happened.
IDENTITY_VERSION_CODE = "identity_version_differs_after_save"
IDENTITY_VERSION_NEXT = ("элемент тот же (unique_id совпал); версия изменилась "
                         "сохранением/синхронизацией — перечитай элемент и повтори")


def expected_identity_check(op: dict, var: str, oid: str,
                            isolation: str = "atomic") -> str:
    """Refuse before the write if the element is no longer the one that was read.

    🔴 WHY AT THE OP AND NOT ONLY AT THE PROGRAM (13.09.2026). The program-level
    pin (`_element_identity_guard`) answers "something this program depends on
    moved"; it addresses by ElementId and cannot serve a target named by
    UniqueId at all, because there is no number at compile time. This check sits
    where the target was just resolved, so the refusal names the OP whose base
    went stale — which is what the author has to re-read.

    `VersionGuid` is checked second and is NOT the strong half here.

    🔴 CORRECTION, 13.09.2026, AND IT IS A CORRECTION OF MY OWN TEXT. The line
    that stood here said the guid «returns the DOCUMENT's episode, identical for
    every element». That was inferred from ONE live coincidence — the guid read
    on an unsaved document equalled the UniqueId episode prefix — and
    RevitAPI.xml 2023 does not support it. `Element.VersionGuid`: «If element
    version Guid is the same for a certain element in two instances of the saved
    file then we guarantee that the two elements are identical. One element
    version covers a period of time that is larger than a single transaction: it
    is a period between two saves, synchronize to central and reload latest.
    Thus, in an opened document in-between saves or synchronize actions, this
    version cannot be used to determine if any particular element has changed.»
    So it IS a per-element version; the word «версия элемента» is true. What is
    false is any use of it as an in-session freshness guard — and the docs say so
    themselves. Third time I have let an inference run ahead of its evidence.

    What that means for this comparison, stated as two failure modes rather than
    a preference: in-session it can never fire when it should (the version does
    not move), and across a save it fires when it should NOT (the saved version
    advances while the element is untouched) — so a document SAVE used to make
    every stored `expected_identity` refuse with «элемент изменился».

    🔴 THE FORM THIS NOW EMITS (lead's word, 13.09.2026). `unique_id` is the only
    strong field and is ALWAYS compared. `version_guid` is optional, is carried by
    the receipt whenever the producer read it, and is compared ONLY when the
    operation asks for it (`compare_version: true`) — opt-in, default off. When it
    does fire it refuses with its OWN code, so the owner saving the file cannot be
    read as someone swapping the element. Inside a session the value is guarded by
    `expected_current` and by nothing else; that is the half measured live the
    same day (§3: fired on a real change, silent on none).
    """
    expected = op.get("expected_identity")
    if not expected:
        return ""
    uid = expected["unique_id"]
    out = [
        f"\nif ({var}.UniqueId != {_cs(uid)}) {{ "
        + refuse_stmt(oid, _cs("identity_changed_since_read: элемент по этому адресу — "
                               "уже не тот, что был прочитан; " + IDENTITY_NEXT), isolation)
        + " }",
    ]
    version = expected.get("version_guid")
    if expected.get("compare_version") and version:
        out.append(
            f"if ({var}.VersionGuid.ToString(\"N\") != {_cs(version.lower())}) {{ "
            + refuse_stmt(oid, _cs(IDENTITY_VERSION_CODE + ": " + IDENTITY_VERSION_NEXT),
                          isolation)
            + " }")
    return "\n".join(out)


def _target_res(op: dict, s: str, ver: str, oid: str,
                isolation: str = "atomic") -> str:
    """Resolve a write-target (element_id | unique_id | ref) into Element __tg_<s>.

    🔴 `unique_id` IS THE ONLY ADDRESS THAT SURVIVES A SESSION (13.09.2026).
    `ElementId` is an address inside one document and Revit reuses it after a
    deletion, so a program that edits what a PREVIOUS publication created can
    only name its target by number if nothing was deleted in between — and it
    cannot know that. `doc.GetElement(string)` takes the UniqueId directly; the
    refusal below then says the element is gone, instead of a write silently
    landing on whatever now holds that number.
    """
    tgt = op["target"]
    base = expected_identity_check(op, f"__tg_{s}", oid, isolation)
    if tgt["by"] == "ref":
        rv = "__el_" + _safe(tgt["value"])
        return f"Element __tg_{s} = (Element){rv};" + base
    if tgt["by"] == "unique_id":
        gone = ("элемент с этим UniqueId не найден в документе — он удалён или "
                "это другой документ; следующий ход: прочитай элемент заново "
                "(query_element_state) и повтори от свежей базы")
        return (f"Element __tg_{s} = null;\n"
                f"try {{ __tg_{s} = doc.GetElement({_cs(tgt['value'])}); }} catch {{ }}\n"
                f"if (__tg_{s} == null) {{ {refuse_stmt(oid, _cs(gone), isolation)} }}\n"
                # A number can be reused; a UniqueId cannot. Re-reading it off the
                # element costs nothing and turns "GetElement did not throw" into
                # "this is the element I named".
                f"if (__tg_{s}.UniqueId != {_cs(tgt['value'])}) "
                f"{{ {refuse_stmt(oid, _cs('документ вернул элемент с другим UniqueId'), isolation)} }}"
                + base)
    return (f"Element __tg_{s} = doc.GetElement({_eid(tgt['value'], ver, oid)});\n"
            f"if (__tg_{s} == null) {{ {refuse_stmt(oid, _cs('элемент не найден (модель изменилась после grounding)'), isolation)} }}"
            + base)


def _level_chain_check(el_var: str, oid: str, id_expr: str) -> str:
    """Topology: level binding via the version-safe BIP chain (witness pattern).

    A LINK IS ACCEPTED ONLY IF IT HOLDS A REAL ElementId. The transition
    condition used to be `HasValue`, which for a reference parameter is true
    even when the value equals InvalidElementId: measured 27.07 on a beam —
    `FAMILY_LEVEL_PARAM: HasValue=True, AsElementId=-1`. The chain broke off
    at an empty link, compared «-1» against the expected id, and accused a
    correctly built element. "The parameter is populated" and "the parameter
    exists" are different things, and the chain itself is obligated to tell
    them apart."""
    def link(bip: str, first: bool = False) -> str:
        head = (f"Parameter __lp = {el_var}.get_Parameter(BuiltInParameter.{bip});\n"
                if first else
                f"    if (__lp == null || !__lp.HasValue "
                f"|| __lp.AsElementId() == null "
                f"|| __lp.AsElementId() == ElementId.InvalidElementId) "
                f"__lp = {el_var}.get_Parameter(BuiltInParameter.{bip});\n")
        return head
    return (
        link("FAMILY_BASE_LEVEL_PARAM", first=True)
        + link("FAMILY_LEVEL_PARAM")
        + link("SCHEDULE_LEVEL_PARAM")
        + link("LEVEL_PARAM")
        + f"    if (__lp == null || __lp.AsElementId() == null || __lp.AsElementId().ToString() != {id_expr})\n"
        f"        __post.Add({_cs(oid + ': level binding mismatch (topology)')});")


def _symbol_res(op: dict, s: str, oid: str, ver: str,
                isolation: str = "atomic") -> str:
    g = _gid(op, "symbol")
    if g.get("via") == "ref":
        # A8, 13.08.2026: A SYMBOL CREATED BY THIS SAME PROGRAM.
        #
        # The branch is copied from `_level_expr` — the one kind of
        # reference that has been consumed for years — and invents no new
        # mechanism: both producers (`create_type`, `load_family`) declare
        # `FamilySymbol __el_<oid>` and put the symbol exactly there, so no
        # cast is needed. `doc.GetElement` is deliberately NOT called here:
        # a freshly created symbol has no id in the snapshot taken BEFORE
        # execution, and querying the snapshot would mean looking for
        # something that cannot be in it.
        #
        # There is no null check either, and that is not carelessness: a
        # refusal by the producing op quenches the dependent one through
        # `__ok_<s>` (a typed "reference op refused"), exactly as with a
        # level. A second null-guard would give a DIFFERENT message for the
        # same cause.
        rv = "__el_" + _safe(g["ref"])
        return (f"FamilySymbol __sy_{s} = {rv};\n"
                f"if (!__sy_{s}.IsActive) {{ __sy_{s}.Activate(); doc.Regenerate(); }}")
    return (f"FamilySymbol __sy_{s} = doc.GetElement({_eid(g['id'], ver, oid)}) as FamilySymbol;\n"
            f"if (__sy_{s} == null) {{ {refuse_stmt(oid, _cs('типоразмер не найден (модель изменилась после grounding)'), isolation)} }}\n"
            f"if (!__sy_{s}.IsActive) {{ __sy_{s}.Activate(); doc.Regenerate(); }}")


def _loop_pts(pts: list, name: str, z: str = "0") -> list:
    out = [f"CurveLoop {name} = new CurveLoop();"]
    n = len(pts)
    for k in range(n):
        a, b = pts[k], pts[(k + 1) % n]
        out.append(f"{name}.Append(Line.CreateBound(P({a[0]}, {a[1]}, {z}), P({b[0]}, {b[1]}, {z})));")
    return out


def _annot_view_res(op: dict, s: str, ver: str, oid: str,
                    isolation: str = "atomic") -> str:
    """Resolve in_view (element_id ONLY) into View __vw_<s>, with a typed
    null-guard AND an explicit is-a-View check (a stale/wrong id resolving to
    a non-View element must not silently proceed — VIEW-BINDING LAW starts
    with in_view actually being a view). ASSIGNMENT only: every caller's post
    block reads __vw_<s>, so the declaration lives in the caller's decl
    (emitter scope contract — per_op wraps create in its own try scope).

    28.07 finding (per_op gate run): a ``ref`` target USED TO be accepted
    here and cast with ``__el_<ref> as View`` — but no op anywhere in the KIR
    surface creates a View (create_view does not exist, per spec's own
    anti-scope note), so ``__el_<ref>``'s STATIC C# type is always some other
    concrete Revit class (Wall/FamilyInstance/Pipe/...), never View, and
    `as` between two unrelated non-polymorphic Revit API classes is an
    UNCONDITIONAL Roslyn CS0039 — not a per-model accident, a guaranteed
    refusal for every possible ref value. Emitting that branch at all meant
    the ONLY way to discover this was a live compile failure deep in the
    gate/A5 path. Refused HERE instead, at emission/plan time, typed —
    before any C# exists to be wrong."""
    tgt = op["in_view"]
    if tgt["by"] == "ref":
        raise KirRefusal([Diagnostic(
            code=GROUND_BAD_SELECTOR, op_id=oid, field_name="in_view",
            expected={"by": "element_id"}, got=tgt,
            message_ru=(
                "in_view: ref на оп этой же программы недопустим — ни один "
                "оп KIR не создаёт View, поэтому ref всегда указывает на "
                "НЕ-вид и «as View» никогда не скомпилируется; укажите "
                "element_id существующего вида"))])
    return (f"__vw_{s} = doc.GetElement({_eid(tgt['value'], ver, oid)}) as View;\n"
            f"if (__vw_{s} == null) {{ {refuse_stmt(oid, _cs('in_view: вид не найден (модель изменилась после grounding, либо id — не View)'), isolation)} }}")


def program_hash(grounded_ops: list[dict]) -> str:
    blob = json.dumps(grounded_ops, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:8]


#: The shape of an authorial program's stable identity lives in ONE place,
#: `midend.LINEAGE_FORM`. The token gets the prefix `p` (project) — the
#: receipt's reader is obligated to SEE which mode produced the address,
#: without looking into the compiler.


def lineage_token(lineage: str) -> str:
    """A short, stable token for an authorial program, from its long identity."""
    if not isinstance(lineage, str) or not LINEAGE_FORM.match(lineage):
        raise ValueError("invalid program lineage")
    return "p" + hashlib.sha1(lineage.encode("utf-8")).hexdigest()[:8]


def _program_stamp(grounded_ops: list[dict], stamp_scope: str = "",
                   lineage: str = "") -> str:
    """The program's stamp: a stable address for the authorial thing, or the
    previous hash.

    🔴 D-1 (audit 06.09.2026). The stamp used to be a SHA1 of the WHOLE
    grounded program, and the type-ownership marker
    `kir:{stamp}:{op_id}` is built from it. Measurement: editing the height
    of a NEIGHBORING wall 3000→3100 changed the marker
    `kir:29d89dc8:WT1` → `kir:2f2eb590:WT1`, and republishing the same
    residential complex re-emitted `create_wall_type` with a NEW address.
    From there the ownership guard fired — correctly! ("a same-named type
    does not belong to this exact request") — and a lawful republication was
    refused wholesale.

    The cause is not the guard, it is the ADDRESS: it was named "this whole
    program," while the author meant "this thing of my project." If the
    envelope carries the authorial program's stable identity (`lineage`; for
    the Project path this is `project_id`, living through all revisions),
    the address is built FROM IT, and editing a neighbor does not move it. A
    bare program without an identity keeps the PREVIOUS behavior byte for
    byte: there is nothing to weaken in something that has no stable name.

    🔴 WHAT THIS ADDRESS DOES NOT GIVE, AND THIS IS THE MAIN POINT. The
    owner's word: "a stable address by itself does not grant the right to
    overwrite an existing type." The address answers "is this my thing," not
    "am I allowed to change it": recreation at a matching address remains a
    READ, and a divergence in composition is a named refusal
    (`_emit_create_wall_type`). Changing an existing type is a separate
    operation that does not exist in the language, and the refusal names
    exactly that.
    """

    address = lineage_token(lineage) if lineage else program_hash(grounded_ops)
    if stamp_scope:
        if not re.fullmatch(r"a5:[0-9a-f]{12}:[0-9a-f]{16}", stamp_scope):
            raise ValueError("invalid internal A5 stamp scope")
        return f"kir:{stamp_scope}:{address}"
    return f"kir:{address}"


def _document_binding_guard(
    expected_document: Mapping[str, str] | None,
    *,
    rollback: str,
) -> str:
    """Emit an internal A5 active-document invariant.

    The guard is empty by default, preserving public compiler bytes.  A5
    supplies the exact title/path/project UID captured before the run; every
    write transaction re-checks them before its first mutation.
    """

    if expected_document is None:
        return ""
    required = {"title", "path_name", "project_uid"}
    if (not isinstance(expected_document, Mapping)
            or set(expected_document) != required
            or any(not isinstance(expected_document[key], str)
                   for key in required)
            or not expected_document["title"]):
        raise ValueError("invalid internal document fingerprint")
    mismatch = (
        f"!String.Equals(doc.Title ?? \"\", {_cs(expected_document['title'])}, "
        f"StringComparison.Ordinal) || "
        f"!String.Equals(doc.PathName ?? \"\", "
        f"{_cs(expected_document['path_name'])}, StringComparison.Ordinal) || "
        f"!String.Equals(doc.ProjectInformation == null ? \"\" : "
        f"(doc.ProjectInformation.UniqueId ?? \"\"), "
        f"{_cs(expected_document['project_uid'])}, StringComparison.Ordinal)")
    return (
        f"if ({mismatch})\n"
        f"{{ {rollback}return __Refuse(\"$program\", "
        f"\"active document fingerprint changed\"); }}\n")


def _element_identity_guard(
    expected_identities: Sequence[ElementIdentityProof] | None,
    revit_version: str,
    *,
    rollback: str,
    symbol_prefix: str = "__kirBinding",
    compare_version: bool = False,
) -> str:
    """Emit exact dependency guards inside the write transaction.

    This second check detects an address now resolving to another UniqueId, and —
    only when asked — a different saved VersionGuid. It does not close every
    read-to-write race: VersionGuid does not track individual in-session edits. A
    mutation based on observed values additionally needs the observation's
    document revision checked at the execution boundary, or suitable native value
    preconditions.

    🔴 THE TWO HALVES ARE NOW TWO CONDITIONS WITH TWO CODES (13.09.2026, lead's
    word). They used to be one `||` chain refusing with
    `identity_changed_since_read`, which meant the owner pressing Save — which
    advances `VersionGuid` on every element and changes none of them — was
    reported as the element having been swapped. The UniqueId half is always
    checked and keeps its code; the version half is opt-in and carries
    `IDENTITY_VERSION_CODE`, whose next move says a save happened.
    """

    if expected_identities is None:
        return ""
    if (isinstance(expected_identities, (str, bytes, bytearray))
            or not isinstance(expected_identities, Sequence)
            or not all(isinstance(item, ElementIdentityProof)
                       for item in expected_identities)):
        raise ValueError(
            "expected_identities must contain ElementIdentityProof values")
    if not re.fullmatch(r"__[A-Za-z][A-Za-z0-9]*", symbol_prefix):
        raise ValueError("invalid element identity guard symbol prefix")
    by_id: dict[int, ElementIdentityProof] = {}
    for proof in expected_identities:
        prior = by_id.get(proof.element_id)
        if prior is not None and prior != proof:
            raise ValueError(
                "one ElementId has contradictory expected identities")
        by_id[proof.element_id] = proof
    if not by_id:
        return ""

    blocks = [
        f"// {MODEL_BINDING_GUARD_VERSION}: exact open-model dependencies"
    ]
    for index, element_id in enumerate(sorted(by_id)):
        proof = by_id[element_id]
        literal = _eid(element_id, revit_version, "$program")
        blocks.extend((
            f"Element {symbol_prefix}_{index} = null;",
            f"string {symbol_prefix}Uid_{index} = \"\";",
        ))
        if compare_version and proof.version_guid:
            blocks.append(f"string {symbol_prefix}Version_{index} = \"\";")
        blocks.extend((
            "try",
            "{",
            f"    {symbol_prefix}_{index} = doc.GetElement({literal});",
            f"    if ({symbol_prefix}_{index} != null)",
            "    {",
            f"        {symbol_prefix}Uid_{index} = "
            f"{symbol_prefix}_{index}.UniqueId ?? \"\";",
        ))
        if compare_version and proof.version_guid:
            blocks.append(
                f"        {symbol_prefix}Version_{index} = "
                f"{symbol_prefix}_{index}.VersionGuid.ToString(\"N\");")
        blocks.extend((
            "    }",
            "}",
            "catch { }",
            f"if ({symbol_prefix}_{index} == null ||",
            f"    !String.Equals({symbol_prefix}Uid_{index}, "
            f"{_cs(proof.unique_id)}, StringComparison.Ordinal))",
            f"{{ {rollback}return __Refuse(\"$program\", "
            f"\"identity_changed_since_read: ElementId {element_id} "
            f"[{MODEL_BINDING_GUARD_VERSION}]; {IDENTITY_NEXT}\"); }}",
        ))
        if compare_version and proof.version_guid:
            blocks.extend((
                f"if (!String.Equals({symbol_prefix}Version_{index}, "
                f"{_cs(proof.version_guid)}, StringComparison.Ordinal))",
                f"{{ {rollback}return __Refuse(\"$program\", "
                f"\"{IDENTITY_VERSION_CODE}: ElementId {element_id} "
                f"[{MODEL_BINDING_GUARD_VERSION}]; {IDENTITY_VERSION_NEXT}\"); }}",
            ))
    return "\n".join(blocks) + "\n"
