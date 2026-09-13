"""TRANSFERRING A FAMILY FROM DOCUMENT TO DOCUMENT — WITHOUT A FILE AND WITHOUT A PATH.

WHY THIS MODULE EXISTS

The `fresh_document` mode (23.08.2026) taught the decompiler to end up in a
FOREIGN document: all references by name, `element_id` zero (K6 68 of 68
programs, K3 54 of 54). There is nothing to accept the program with there —
there is no catalog. The same day's measurement: the unit
`АР_Квартира_1К` (27 operations, 12 occurrences) needs 11 families, and the
target «Проект1» has ZERO of them — not even the family, let alone the type.

`load_family` is unfit for this by the LETTER of its postcondition: it
checks `File.Exists`, meaning it requires a path to a `.rfa`. There is no
path and nowhere to get one — the measurement is exhaustive (23 keys of the
L0 line, 30 Revit parameter names, 17 fields of the placement index, all 20
side indexes: zero matches against PATH|FILE|SOURCE|RFA|LIBRARY|URL|DIR),
and `Family` itself has 27 members and not one path.

🔴 NO FILE IS NEEDED AT ALL, AND THIS IS VERIFIED AGAINST RevitAPI.xml, NOT
FROM MEMORY:

    M:Document.EditFamily(Family)                        6/6 (2021…2026)
    M:Document.LoadFamily(Document)                      6/6
    M:Document.LoadFamily(Document,IFamilyLoadOptions)   6/6

`EditFamily` returns the family's Document IN MEMORY; `LoadFamily(Document)`
accepts it directly. No `SaveAs`, no disk, no temp directory. There is
exactly one precondition and it is named in the refusal: BOTH documents are
open in ONE Revit session (`Application.Documents` enumerates only that one).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔴 WHY THIS IS A SOLO OP, NOT AN ORDINARY ONE. A REVIT PROHIBITION, NOT OUR
TASTE.

RevitAPI.xml states for BOTH methods, verbatim and identically across all
six:

    EditFamily          «This method may not be called if the document is
                        currently modifiable (has an open transaction)»
                        -> InvalidOperationException
    LoadFamily(Document) «…or when the target document is modifiable (e.g.
                        there is an uncommitted transaction)»
                        -> InvalidOperationException

And the body of EVERY KIR program runs inside `using (Transaction __t …)`
with `__t.Start()` (`authoring.py`, the `emit_program` assembly). So an
ordinary op, dropped into the shared body, would run into the exception
GUARANTEED and on every version — not "sometimes," but always. The door for
"an op owns its own transactions" already exists in the language
(`spec.SOLO_OPS` + `authoring._SOLO_PROGRAMS`), and its fourth occupant,
`author_family`, belongs to the same class: a second document plus its own
transactional discipline. Moving into the existing door is cheaper and more
honest than cutting an identical one right next to it.

TWO PHASES, AND THE BOUNDARY BETWEEN THEM IS MANDATORY

    PHASE A   WITHOUT a transaction: find the document, find the family,
              EditFamily, LoadFamily(doc), Close(false) in `finally`
    PHASE B   ITS OWN transaction on `doc`: Activate the type, Regenerate,
              stamp, witness

Activate changes the document and is impossible without a transaction;
LoadFamily is impossible INSIDE one. The order follows from the
prohibition, not from convenience — exactly as with `author_family`, where
the family document's transaction closes before the project's transaction
opens.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔴 THE OVERLOAD WITHOUT `IFamilyLoadOptions` IS CHOSEN DELIBERATELY, AND IT
IS ABOUT SAFETY, NOT LAZINESS.

RevitAPI.xml on `LoadFamily(Document)`: «this method automatically
suppresses the prompts Revit typically uses to deal with conflicts between
families, and assumes that any such conflict should prevent the loading»,
and among the exceptions — «when this family was found in the target
document already and the conflict caused an automatic abort of the load
operation».

In other words, NAME CONFLICT -> EXCEPTION, not a silent overwrite. This is
exactly the guarantee we need: a foreign family in the target document
cannot be overwritten by us unnoticed. The other overload would take
`RevitUIFamilyLoadOptions`, which «will show the same prompts to the user
as seen during an interactive load» — a modal window on the bridge's UI
thread, meaning a hung Revit. One's own implementation of the interface
answering "overwrite" is a deliberate decision to OVERWRITE SOMEONE ELSE'S
DATA, and making that decision silently inside a transfer operation is not
allowed. If we ever want overwriting, it will be a SEPARATE op with a
separate name.

So that a routine repeat does not pay with an exception, the family IS
SEARCHED FOR IN THE TARGET IN ADVANCE: if found, we reuse it and report
`already_present=true`, exactly the same idempotency as in `load_family`.
🔴 "Found" is decided by a CONTENT COMPARISON, not by name alone — see
F-277 in the preflight below.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔴 WHAT THIS OP CANNOT DO — NAMED, BECAUSE A SILENT OMISSION IS WORSE THAN
A GAP (03.09.2026, analysis of F-275/F-276/F-277)

1. THERE IS NO COMPENSATING DELETION AND THERE CANNOT BE ONE IN THIS FORM.
   `LoadFamily` is performed OUTSIDE a transaction — Revit requires this —
   so Phase B's rollback does not undo it, and the transaction that would
   hold `doc.Delete` does not yet exist at the moment of loading.
   `doc.Delete` has ZERO occurrences in this file, and that is not a gap
   but a property of an order dictated by someone else's law.

   Closed by TWO moves, neither of which is a deletion:
     * everything that decides "is this allowed" is moved BEFORE loading —
       the document and identity guards (F-275) and the presence of the
       requested type in the SOURCE family (F-276). Refusing before the
       effect is cheaper than removing it afterward;
     * where the refusal still comes AFTER, it NAMES THE EFFECT
       (`__effect_`): "the family is loaded and remains in the document,"
       plus the next move.

2. THE REMAINDER THIS FILE CANNOT CLOSE. Refusals from the A5 guards
   inside the transaction (`__Refuse("$program", "active document
   fingerprint changed")` and «open model binding changed») do NOT name an
   effect: their text is assembled by `emit_core._document_binding_guard` /
   `_element_identity_guard`, and there is nothing here to attach
   `__effect_` to — rewriting the emitted C# by string is forbidden to
   this tree (KIR-E005, `emit_utils.refuse_stmt`). The path to a fix lies
   in `emit_core`, as a separate change. Move 1 narrowed this remainder to
   a genuine race: for it to trigger, the document must change BETWEEN
   Phase A and Phase B.

3. THERE IS NO IDENTITY FOR A FAMILY THAT SURVIVES THE DOCUMENT BOUNDARY
   IN THE API. Measured against RevitAPI.xml for all six versions:
   `Family` has 27 members, no path, no cross-document identifier. So the
   repeat check rests on a CONTENT COMPARISON (category plus the set of
   types), and a match on both identity axes does not prove identity, and
   the receipt names the BASIS (`already_present_basis`) rather than
   passing the comparison off as identity.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from kir.contracts import ElementIdentityProof
from kir.emit_utils import (cs_identifier_fragment, cs_line_comment_fragment,
                                 cs_string_literal, failure_channel_reset_cs,
                                 failure_preprocessor_cs,
                                 failure_warnings_into_results_cs)

_cs = cs_string_literal


def _safe(oid: str) -> str:
    return cs_identifier_fragment(oid)


def emit_transfer_family_program(
        op: dict, ver: str, intent: str = "", *, stamp: str = "",
        stamp_scope: str = "",
        expected_document: Mapping[str, str] | None = None,
        expected_identities: Sequence[ElementIdentityProof] | None = None,
) -> str:
    """The whole family-transfer program. Solo: two documents, its own transaction.

    `expected_document` / `expected_identities` are accepted for the sake
    of a single signature for the `_SOLO_PROGRAMS` table and are applied to
    the TARGET document inside Phase B — the same place every other
    program applies them. They are deliberately not applied to the SOURCE
    document: it is not ours, we only read it, and the foreign-identity
    guard would be refusing on a fact the program does not control.
    """
    from kir import authoring as _authoring

    oid = op["id"]
    s = _safe(oid)
    family_name = op["family_name"]
    source_document = op["source_document"]
    type_name = op.get("type_name")
    txn_name = ("KIR: " + (intent or "transfer family"))[:80]

    # ── THE GUARDS STAND TWICE, THE FIRST TIME BEFORE THE IRREVERSIBLE STEP
    # (F-275) ────────────────────────────────────────────────────────────
    #
    # 🔴 THE DIRECTION OF THE FIX IS SET BY SOMEONE ELSE'S LAW, AND THERE IS
    # ONLY ONE. `LoadFamily` CANNOT be dragged into a transaction — that is
    # Revit's requirement (see the header), not our taste. So it is the
    # GUARDS that must move: everything deciding "is this allowed" must
    # execute BEFORE the step that has nothing to roll it back. Phase B's
    # rollback undoes Phase B; it NEVER undoes Phase A.
    #
    # BOTH ARE PORTABLE, AND THIS IS VERIFIED FROM THE GUARDS' OWN BODY, NOT
    # FROM THEIR NAME: `_document_binding_guard` reads `doc.Title`,
    # `doc.PathName`, `doc.ProjectInformation.UniqueId`;
    # `_element_identity_guard` reads `doc.GetElement(id)` against evidence
    # captured BEFORE the run. Neither looks at the family being
    # transferred, so neither needs the transfer to have already happened.
    # This op has no guard that would need it.
    #
    # THE SECOND INSTANCE IS NOT TRADED FOR THE FIRST: a race remains
    # between Phase A's read and Phase B's first mutation, and it is for
    # that race's sake that the guard inside the transaction exists at all.
    #
    # ITS OWN PRECEDENT: `authoring.emit_stairs_program` places
    # `pre_doc_guard`/`pre_identity_guard` before `StairsEditScope` and
    # repeats them inside the transaction — exactly this form, in a
    # neighbor within `_SOLO_PROGRAMS`.
    pre_doc_guard = _authoring._document_binding_guard(
        expected_document, rollback="")
    pre_id_guard = _authoring._element_identity_guard(
        expected_identities, ver, rollback="")
    doc_guard_raw = _authoring._document_binding_guard(
        expected_document, rollback="__t.RollBack(); ")
    doc_guard = (_indent(doc_guard_raw, "        ") + "\n"
                 if doc_guard_raw else "")
    # 🔴 THE SECOND GUARD HAS ITS OWN PREFIX — OTHERWISE CS0136 ON ALL SIX.
    # The guard declares locals `__kirBinding_N/Uid/Version`; emitted TWICE
    # — in the enclosing scope (Phase A) and in the nested one (the
    # transaction body) — it declares them twice, and C# forbids this
    # verbatim: «A local named '__kirBinding_0' cannot be declared in this
    # scope». Paid for on 21.08.2026 with `create_stairs`, where the same
    # double placement failed to compile on any of the six versions; the
    # fix is the same there — `symbol_prefix` on the transactional one.
    id_guard_raw = _authoring._element_identity_guard(
        expected_identities, ver, rollback="__t.RollBack(); ",
        symbol_prefix="__kirXferTxnBinding")
    id_guard = (_indent(id_guard_raw, "        ") + "\n"
                if id_guard_raw else "")

    # ── WHAT DECIDES "IS THIS ALLOWED" — BEFORE THE IRREVERSIBLE STEP, NOT
    # AFTER (F-276) ────────────────────────────────────────────────────────
    #
    # A legitimate request for a type that is NOT in the family, before
    # 03.09.2026, loaded the whole family first and only then refused with
    # Phase B's typed refusal. There is NO compensating deletion ANYWHERE
    # (`doc.Delete` has zero occurrences in this file), and this op cannot
    # introduce one: `LoadFamily` is performed OUTSIDE the transaction, and
    # Phase B's transaction is not yet open at that moment.
    #
    # So the question "does such a type exist" is asked of the SOURCE
    # document BEFORE loading. This is a pure read; it does not require the
    # transfer to have happened. The list is taken with a COLLECTOR, not
    # `Family.GetFamilySymbolIds()` — that one returns an `ISet<>` from
    # `System.dll`, which the shipped plugin does not reference (CS0012,
    # the mark-stage mine of 04.08.2026); the full argument is at `pick`
    # below.
    if type_name is not None:
        preload_check = f"""\
int __srcTypeHits_{s} = 0;
foreach (string __stn_{s} in __srcTypeList_{s})
    if (__stn_{s} == {_cs(type_name)}) __srcTypeHits_{s}++;
if (__srcTypeHits_{s} == 0)
    return __Refuse({_cs(oid)}, {_cs(
        'в семействе «' + family_name + '» исходного документа НЕТ '
        'типоразмера «' + str(type_name) + '», и это проверено ДО загрузки: '
        'загрузка необратима — она идёт вне транзакции, как требует Ревит, и '
        'откат Фазы Б её не отменяет. Типоразмеры источника: ')}
        + (__srcTypes_{s}.Length == 0
           ? {_cs('ни одного типоразмера')} : __srcTypes_{s}));
"""
    else:
        preload_check = f"""\
if (__srcTypeList_{s}.Count == 0)
    return __Refuse({_cs(oid)}, {_cs(
        'в семействе «' + family_name + '» исходного документа ни одного '
        'типоразмера — активировать нечего, и это проверено ДО загрузки: '
        'загрузка необратима, а откат Фазы Б её не отменяет')});
"""

    # ── PHASE A. NOT A SINGLE OPEN TRANSACTION ──────────────────────────────
    #
    # The document is addressed by a SUBSTRING OF THE TITLE, and this is
    # not an invention: this is exactly how the bridge selects a window
    # (`doc_contains`), and the model already knows this idiom. `Title` —
    # not `PathName` — because an unsaved document has an empty `PathName`,
    # while the title always exists.
    #
    # Zero matches and two matches are DIFFERENT refusals, and both print
    # the titles of the open documents: "not found" without a list sends
    # the author off to guess, and the next move must be visible from the
    # refusal itself.
    #
    # The target document itself is EXCLUDED from the search: transferring
    # a family into itself is not a no-op, it is a HIDDEN ADDRESS ERROR,
    # and a silent success here would teach the author something false.
    phase_a = f"""\
// transfer_family {cs_line_comment_fragment(oid)}  ФАЗА А — без транзакции
if (doc.IsModifiable)
    return __Refuse({_cs(oid)}, {_cs(
        'документ уже изменяем: EditFamily и LoadFamily(Document) запрещены '
        'при открытой транзакции (RevitAPI.xml, все шесть версий). Это '
        'соло-оп и он обязан быть единственным в своей программе')});

{pre_doc_guard}{pre_id_guard}\
Document __src_{s} = null;
int __srcHits_{s} = 0;
string __titles_{s} = "";
foreach (Document __cand_{s} in doc.Application.Documents)
{{
    if (__cand_{s} == null || !__cand_{s}.IsValidObject) continue;
    if (__cand_{s}.Equals(doc)) continue;
    if (__cand_{s}.IsFamilyDocument) continue;
    __titles_{s} = __titles_{s} + (__titles_{s}.Length == 0 ? "" : ", ") + __cand_{s}.Title;
    if (__cand_{s}.Title.IndexOf({_cs(source_document)},
            StringComparison.OrdinalIgnoreCase) >= 0)
    {{ __src_{s} = __cand_{s}; __srcHits_{s}++; }}
}}
if (__srcHits_{s} == 0)
    return __Refuse({_cs(oid)}, {_cs(
        'исходный документ «' + source_document + '» не открыт в этой сессии '
        'Ревита. Перенос идёт документ-в-документ, файл не используется, '
        'поэтому оба документа обязаны быть открыты РЯДОМ. Открыты: ')}
        + (__titles_{s}.Length == 0 ? {_cs('только целевой')} : __titles_{s}));
if (__srcHits_{s} > 1)
    return __Refuse({_cs(oid)}, {_cs(
        'подстрока «' + source_document + '» совпала с несколькими открытыми '
        'документами — адрес неоднозначен, и «первый попавшийся» здесь был бы '
        'выдумкой. Открыты: ')} + __titles_{s});

// СЕМЕЙСТВО ИЩЕТСЯ ПО ТОЧНОМУ ИМЕНИ. Подстрока годится для документа (его
// заголовок несёт расширение и суффиксы), но НЕ для семейства: имена
// семейств в одном проекте различаются суффиксом сплошь и рядом, и
// подстрочное совпадение принесло бы соседа.
Family __fam_{s} = null;
int __famHits_{s} = 0;
foreach (Family __fc_{s} in new FilteredElementCollector(__src_{s})
    .OfClass(typeof(Family)))
{{
    if (__fc_{s} != null && __fc_{s}.Name == {_cs(family_name)})
    {{ __fam_{s} = __fc_{s}; __famHits_{s}++; }}
}}
if (__famHits_{s} == 0)
    return __Refuse({_cs(oid)}, {_cs(
        'в исходном документе нет семейства «' + family_name + '»')});
if (__famHits_{s} > 1)
    return __Refuse({_cs(oid)}, {_cs(
        'в исходном документе несколько семейств с именем «' + family_name
        + '» — перенос неоднозначен')});

// ДВА ЗАПРЕТА РЕВИТА, НАЗВАННЫЕ ДО ВЫЗОВА, А НЕ ПОЙМАННЫЕ ПОСЛЕ.
// RevitAPI.xml у EditFamily: ArgumentException «when the input argument is an
// in-place family or a non-editable family. (This can be checked with the
// IsInPlace and IsEditable properties of the Family class)». Проверить
// заранее — значит вернуть автору ФАКТ О МОДЕЛИ вместо текста исключения.
if (__fam_{s}.IsInPlace)
    return __Refuse({_cs(oid)}, {_cs(
        'семейство «' + family_name + '» создано В ПРОЕКТЕ (in-place): у него '
        'нет отдельного документа, и перенести его этим механизмом нельзя '
        'ВООБЩЕ — EditFamily такие отвергает')});
if (!__fam_{s}.IsEditable)
    return __Refuse({_cs(oid)}, {_cs(
        'семейство «' + family_name + '» не редактируемо (IsEditable=false) — '
        'EditFamily его не отдаст')});

// ЧТО НЕСЁТ ИСХОДНОЕ СЕМЕЙСТВО — СНИМАЕТСЯ ОДИН РАЗ И ДО ЗАГРУЗКИ. Служит
// сразу двум: предзагрузочной проверке типоразмера (F-276) и сверке повтора
// по СОДЕРЖИМОМУ (F-277). Список СОРТИРУЕТСЯ: порядок обхода коллектора не
// обещан никем, и сравнение несортированных перечней сравнивало бы порядок.
string __srcCat_{s} = __fam_{s}.FamilyCategoryId.ToString();
List<string> __srcTypeList_{s} = new List<string>();
foreach (FamilySymbol __ss_{s} in new FilteredElementCollector(__src_{s})
    .OfClass(typeof(FamilySymbol)))
{{
    if (__ss_{s} == null || __ss_{s}.Family == null) continue;
    if (__ss_{s}.Family.Id.ToString() != __fam_{s}.Id.ToString()) continue;
    __srcTypeList_{s}.Add(__ss_{s}.Name);
}}
__srcTypeList_{s}.Sort(StringComparer.Ordinal);
string __srcTypes_{s} = String.Join(", ", __srcTypeList_{s});

{preload_check}
// ИДЕМПОТЕНТНОСТЬ ДО ВЫЗОВА, А НЕ ЧЕРЕЗ ИСКЛЮЧЕНИЕ. LoadFamily(Document) при
// конфликте имён ПРЕРЫВАЕТ загрузку исключением (это и есть наша защита от
// тихой перезаписи), поэтому штатный повтор обязан узнаваться заранее.
//
// 🔴 ИМЯ — СОГЛАШЕНИЕ, А НЕ АВТОРИТЕТ (F-277). До 03.09.2026 повтором
// объявлялось ЛЮБОЕ семейство цели с нужным `.Name`: `LoadFamily`
// пропускался, активировался типоразмер ИЗ ЧУЖОГО семейства, и квитанция
// говорила `already_present=true` — прямо против постусловия реестра
// «одноимённое семейство из другого источника никогда не подставляется».
//
// СКВОЗНОЙ ЛИЧНОСТИ У `Family` В API НЕТ, и это ЗАМЕР, а не догадка: 27
// членов на всех шести версиях (RevitAPI.xml 2021…2026), ни пути, ни
// идентификатора, переживающего границу документа. Поэтому сверяется
// СОДЕРЖИМОЕ, и обе оси названы:
//   * `FamilyCategoryId` — BuiltInCategory один и тот же во всех документах
//     сессии, и категория семейства неизменяема; расхождение здесь
//     ДОКАЗЫВАЕТ, что это другое семейство;
//   * состав типоразмеров — то единственное содержимое, которое читается без
//     открытия документа семейства.
// Совпадение обеих осей личности НЕ ДОКАЗЫВАЕТ (её нечем доказать), поэтому
// квитанция называет ОСНОВАНИЕ повтора, а не выдаёт его за тождество.
Family __dst_{s} = null;
bool __already_{s} = false;
bool __loaded_{s} = false;
int __nameHits_{s} = 0;
string __mismatch_{s} = "";
foreach (Family __dc_{s} in new FilteredElementCollector(doc)
    .OfClass(typeof(Family)))
{{
    if (__dc_{s} == null || __dc_{s}.Name != {_cs(family_name)}) continue;
    __nameHits_{s}++;
    if (__dc_{s}.FamilyCategoryId.ToString() != __srcCat_{s})
    {{
        __mismatch_{s} = {_cs('категория: в цели ')} + __dc_{s}.FamilyCategoryId.ToString()
            + {_cs(', в источнике ')} + __srcCat_{s};
        continue;
    }}
    List<string> __dstTypeList_{s} = new List<string>();
    foreach (FamilySymbol __ds_{s} in new FilteredElementCollector(doc)
        .OfClass(typeof(FamilySymbol)))
    {{
        if (__ds_{s} == null || __ds_{s}.Family == null) continue;
        if (__ds_{s}.Family.Id.ToString() != __dc_{s}.Id.ToString()) continue;
        __dstTypeList_{s}.Add(__ds_{s}.Name);
    }}
    __dstTypeList_{s}.Sort(StringComparer.Ordinal);
    string __dstTypes_{s} = String.Join(", ", __dstTypeList_{s});
    if (__dstTypes_{s} != __srcTypes_{s})
    {{
        __mismatch_{s} = {_cs('состав типоразмеров: в цели «')} + __dstTypes_{s}
            + {_cs('», в источнике «')} + __srcTypes_{s} + {_cs('»')};
        continue;
    }}
    __dst_{s} = __dc_{s}; __already_{s} = true; break;
}}
if (__dst_{s} == null && __nameHits_{s} > 0)
    return __Refuse({_cs(oid)}, {_cs(
        'в целевом документе уже есть семейство с именем «' + family_name
        + '», но это ДРУГОЕ семейство — ')} + __mismatch_{s} + {_cs(
        '. Переиспользовать его запрещено: одноимённое из другого источника '
        'подставлять нельзя. Загрузить рядом тоже нельзя — Ревит прерывает '
        'LoadFamily при конфликте имён, и это защита от тихой перезаписи. '
        'Следующий ход: переименуйте одно из двух семейств')});

if (__dst_{s} == null)
{{
    Document __fdoc_{s} = null;
    try
    {{
        try {{ __fdoc_{s} = __src_{s}.EditFamily(__fam_{s}); }}
        catch (Exception __ee_{s})
        {{
            return __Refuse({_cs(oid)}, {_cs('EditFamily отказал на семействе «'
                + family_name + '»: ')} + __ee_{s}.Message);
        }}
        if (__fdoc_{s} == null)
            return __Refuse({_cs(oid)}, {_cs(
                'EditFamily вернул null на семействе «' + family_name + '»')});
        try {{ __dst_{s} = __fdoc_{s}.LoadFamily(doc); }}
        catch (Exception __le_{s})
        {{
            return __Refuse({_cs(oid)}, {_cs(
                'LoadFamily(Document) отказал на семействе «' + family_name
                + '». Ревит прерывает загрузку при КОНФЛИКТЕ с уже '
                'существующим семейством — это защита от тихой перезаписи, а '
                'не сбой: ')} + __le_{s}.Message);
        }}
        if (__dst_{s} == null)
            return __Refuse({_cs(oid)}, {_cs(
                'LoadFamily(Document) вернул null — семейство «' + family_name
                + '» в целевой документ не приехало')});
        // 🔴 ФЛАГ НАБЛЮДЁННЫЙ, А НЕ ВЫВЕДЕННЫЙ. `!__already_` говорит «ветки
        // повтора не было», и это НЕ ТО ЖЕ САМОЕ, что «загрузка состоялась»:
        // из этой ветки есть три выхода до сюда (отказ EditFamily, null от
        // EditFamily, отказ LoadFamily), и ни на одном эффекта нет. Эффект
        // называет только тот, кто его видел.
        __loaded_{s} = true;
    }}
    finally
    {{
        // `Close(false)` СТОИТ В `finally` И ПОКРЫВАЕТ ВСЕ ВЫХОДЫ — return
        // изнутри `try`, исключение, обычный проход. Документ семейства это
        // «independent copy for editing» (RevitAPI.xml), и незакрытый он
        // остаётся жить в сессии: следующий EditFamily того же семейства
        // получит InvalidOperationException «family is already being edited»,
        // то есть наш отказ объяснял бы себя нашей же прошлой утечкой.
        try {{ if (__fdoc_{s} != null && __fdoc_{s}.IsValidObject) __fdoc_{s}.Close(false); }}
        catch (Exception) {{ }}
    }}
}}
"""

    # ── PHASE B. ITS OWN TRANSACTION ON THE TARGET DOCUMENT ─────────────────
    #
    # Types are looked up with a COLLECTOR, not `Family.GetFamilySymbolIds()`,
    # and this is not a matter of taste: that member returns
    # `ISet<ElementId>`, and on net48 `ISet<>` is declared in `System.dll`,
    # which the SHIPPED plugin does not reference — CS0012, the same mine
    # that killed the mark stage live on 04.08.2026. The full argument is
    # in `authoring._emit_load_family`, the branch without `type_name`.
    if type_name is not None:
        pick = f"""\
        foreach (FamilySymbol __sc_{s} in new FilteredElementCollector(doc)
            .OfClass(typeof(FamilySymbol)))
        {{
            if (__sc_{s} == null || __sc_{s}.Family == null) continue;
            if (__sc_{s}.Family.Id.ToString() != __dst_{s}.Id.ToString()) continue;
            __symCount_{s}++;
            if (__sc_{s}.Name == {_cs(type_name)}) __sym_{s} = __sc_{s};
        }}
        if (__sym_{s} == null)
        {{
            __t.RollBack();
            // 🔴 ТЕКСТ БОЛЬШЕ НЕ ГОВОРИТ «ПРИЕХАЛО» БЕЗУСЛОВНО: в ветке
            // повтора не приезжало ничего, и прежняя редакция врала ровно
            // там. Что произошло на самом деле, говорит `__effect_`.
            return __Refuse({_cs(oid)}, {_cs(
                'типоразмера «' + str(type_name) + '» в семействе «'
                + family_name + '» целевого документа НЕТ. Подставлять '
                'одноимённый тип из другого семейства запрещено — это чужой '
                'предмет под нужным именем')} + __effect_{s});
        }}
"""
    else:
        pick = f"""\
        foreach (FamilySymbol __sc_{s} in new FilteredElementCollector(doc)
            .OfClass(typeof(FamilySymbol)))
        {{
            if (__sc_{s} == null || __sc_{s}.Family == null) continue;
            if (__sc_{s}.Family.Id.ToString() != __dst_{s}.Id.ToString()) continue;
            __symCount_{s}++;
            if (__sym_{s} == null
                || String.CompareOrdinal(__sc_{s}.Name, __sym_{s}.Name) < 0)
                __sym_{s} = __sc_{s};
        }}
        if (__sym_{s} == null)
        {{
            __t.RollBack();
            return __Refuse({_cs(oid)}, {_cs(
                'у семейства «' + family_name + '» в целевом документе нет '
                'ни одного типоразмера')} + __effect_{s});
        }}
"""

    phase_b = f"""\
// ФАЗА Б — своя транзакция на ЦЕЛЕВОМ документе. LoadFamily внутри неё
// невозможен, Activate — вне неё невозможен, поэтому граница ровно здесь.
FamilySymbol __sym_{s} = null;
int __symCount_{s} = 0;
// 🔴 ОТКАЗ ПОСЛЕ СОСТОЯВШЕГОСЯ ЭФФЕКТА НИКОГДА НЕ «ПРОСТО ОТКАЗ» (F-276).
// Удалить загруженное семейство этому опу нечем — и это НЕ повод молчать о
// нём. Половина дефекта, закрываемая без компенсирующего удаления: назвать,
// что осталось в документе, и назвать следующий ход. Строка пуста, когда
// эффекта не было, поэтому текст отказа не обрастает ложью в ветке повтора.
string __effect_{s} = __loaded_{s} ? {_cs(
    ' 🔴 СОСТОЯВШИЙСЯ ЭФФЕКТ: семейство «' + family_name + '» УЖЕ ЗАГРУЖЕНО в '
    'целевой документ Фазой А — вне транзакции, как требует Ревит, — и '
    'ОСТАЁТСЯ в нём: откат этой транзакции его не удаляет, компенсирующего '
    'удаления у этого опа НЕТ. Следующий ход: удалить семейство вручную либо '
    'повторить перенос с верным type_name')} : "";
using (Transaction __t = new Transaction(doc, {_cs(txn_name)}))
{{
    try
    {{
        var __startStatus = __t.Start();
        if (__startStatus != TransactionStatus.Started)
            return __Refuse({_cs(oid)}, "transaction start status: " + __startStatus.ToString() + __effect_{s});
{failure_channel_reset_cs("__KirXferFailures", "        ")}\
        var __fho = __t.GetFailureHandlingOptions();
        __fho.SetFailuresPreprocessor(new __KirXferFailures());
        __fho.SetForcedModalHandling(false);
        __fho.SetClearAfterRollback(true);
        __t.SetFailureHandlingOptions(__fho);
{doc_guard}{id_guard}\
{pick}\
        if (!__sym_{s}.IsActive) {{ __sym_{s}.Activate(); doc.Regenerate(); }}
        if (!__sym_{s}.IsActive)
        {{
            __t.RollBack();
            return __Refuse({_cs(oid)}, {_cs(
                'типоразмер не активировался — «главная ловушка» загрузки '
                'семейств')} + __effect_{s});
        }}

        // ── СВИДЕТЕЛЬ. ТРИ ОСИ, КАЖДАЯ НАЗВАНА ────────────────────────────
        // Перечитывается МОДЕЛЬ, а не эхо вызова: `__dst_` мог прийти из
        // ветки «уже было», и доверять ему как доказательству значило бы
        // засчитать в успех то, чего эта программа не делала.
        Family __rb_fam_{s} = doc.GetElement(__dst_{s}.Id) as Family;
        if (__rb_fam_{s} == null)
            __post.Add({_cs(oid + ': семейства нет в целевом документе после коммита (materialize)')});
        else if (__rb_fam_{s}.Name != {_cs(family_name)})
            __post.Add({_cs(oid + ': имя семейства в цели не равно запрошенному (identity)')});
        FamilySymbol __rb_sym_{s} = doc.GetElement(__sym_{s}.Id) as FamilySymbol;
        if (__rb_sym_{s} == null || !__rb_sym_{s}.IsActive)
            __post.Add({_cs(oid + ': типоразмер не активен после коммита (semantic)')});
        else if (__rb_sym_{s}.Family == null
                 || __rb_sym_{s}.Family.Id.ToString() != __dst_{s}.Id.ToString())
            __post.Add({_cs(oid + ': типоразмер принадлежит другому семейству (identity)')});

        if (__post.Count > 0)
        {{
            __t.RollBack();
            __results["ok"] = false;
            __results["post"] = __post;
            // Нарушенное постусловие — тоже отказ ПОСЛЕ эффекта, и молчать
            // об оставшемся семействе здесь так же нельзя.
            if (__effect_{s}.Length > 0) __results["residual_effect"] = __effect_{s};
            return __results;
        }}

        var __commitStatus = __t.Commit();
        if (__commitStatus != TransactionStatus.Committed)
            return __Refuse({_cs(oid)}, "transaction commit status: " + __commitStatus.ToString() + __effect_{s});
    }}
    catch (Exception __tx_{s})
    {{
        if (__t.GetStatus() == TransactionStatus.Started) __t.RollBack();
        return __Refuse({_cs(oid)}, {_cs('перенос семейства отказал: ')} + __tx_{s}.Message + __effect_{s});
    }}
}}
"""

    # THE CENSUS LAW (`serving._result_contract_diagnostic`, KIR-X008): a
    # writing op's receipt must carry an identity key, and ITS NAME IS SET
    # BY THE REGISTRY, not by the emitter — `RESULT_FAMILY_SYMBOL.identity_field`
    # is `id`. `address.element_addresses` fetches the address of what was
    # created via that same field, so a receipt without `id` was dropping
    # an ALREADY COMPLETED transfer: the family loaded and committed, with
    # its identity left unnamed. Neighbors on this same result-spec
    # (`create_type`, `load_family`) have written `id` from the start — it
    # was exactly this emitter that was missing it.
    #
    # 🔴 `created` SEPARATES A TRANSFER FROM RECOGNIZING SOMETHING ALREADY
    # PRESENT (E-64). `id` is the op element's IDENTITY, NOT evidence of
    # birth, and A5 cleanup decides what to delete BY `created`:
    # `idempotence.collect_created_ids` skips a row EXACTLY on `created is
    # False`, and `cleanup_created` sends a real deletion program against
    # what remains. Without this key, a type that WAS ALREADY in the
    # target document (`already_present=true`) ended up on the deletion
    # list — that is, we were deleting SOMEONE ELSE'S element. The
    # reader's own comment states this case verbatim: "A5 deletes by this
    # list, and a foreign element in it would mean deleting something that
    # is not ours."
    #
    # WHY EXACTLY `!__already_`. Phase B only SELECTS the type with the
    # collector and never creates one: when `__already_` holds, the family
    # and its types already sat in the document (`LoadFamily` was skipped
    # entirely), so there was no birth. When `!__already_` holds, the
    # family arrived via `LoadFamily(doc)` together with its types — there
    # was a birth. Both sides are needed: a key that always says `false`
    # would create an ORPHAN instead of deleting someone else's element,
    # and that is WORSE.
    #
    # 🔴 `element_id` IS NOT RENAMED, BUT LEFT AS A SPEAKING DUPLICATE. This
    # name is read from outside (`idempotence.collect_created_ids` and
    # `collect_created_by_op` take `value.get("id") or
    # value.get("element_id")`), and dropping it would mean silently
    # losing a name the receipt already carries. The same device and the
    # same argument as for `panel_id` and `grid_line_id` in
    # `authoring.py`: identity is named by its canonical name, and the
    # earlier one stays alongside it.
    receipt = f"""\
var __rb_{s} = new Dictionary<string, object>();
__rb_{s}["family_name"] = {_cs(family_name)};
__rb_{s}["source_document"] = __src_{s}.Title;
__rb_{s}["already_present"] = __already_{s};
// 🔴 ВЫБОР ОБЯЗАН БЫТЬ ПРЕДЪЯВЛЕН, А НЕ ПРОСТО СДЕЛАН. Сквозной личности у
// `Family` в API нет (27 членов, 6/6), поэтому «повтор» стоит на СВЕРКЕ
// СОДЕРЖИМОГО, и читатель обязан видеть, на какой именно. `already_present`
// без основания неотличим от `.FirstOrDefault()` с хорошей репутацией.
__rb_{s}["already_present_basis"] = __already_{s} ? "name+category+type_names" : "";
__rb_{s}["symbol_name"] = __sym_{s}.Name;
__rb_{s}["symbols_in_family"] = __symCount_{s};
__rb_{s}["element_id"] = __sym_{s}.Id.ToString();
__rb_{s}["id"] = __sym_{s}.Id.ToString();
__rb_{s}["created"] = !__already_{s};
__results[{_cs(oid)}] = __rb_{s};
"""

    return _authoring._with_program_helpers(
        f"{_authoring._AUTH_PREAMBLE}\n\n"
        + phase_a + "\n"
        + phase_b + "\n"
        + receipt + "\n"
        + failure_warnings_into_results_cs("__KirXferFailures")
        + "__results[\"ok\"] = true;\n"
        "return __results;\n"
        "}\n"
        + failure_preprocessor_cs("__KirXferFailures")
        + "private static class __KirPad\n{")


def _indent(text: str, pad: str) -> str:
    return "\n".join(pad + ln if ln.strip() else ln for ln in text.splitlines())


__all__ = ["emit_transfer_family_program"]
