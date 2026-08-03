"""arch_emit — эмиссия create_ceiling / create_railing (парный файл к
ops_arch.py, ровно как struct_emit.py к ops_struct.py).

Своя зона волны: этот модуль не трогает ops_authoring.py, ops_struct.py,
connect.py, contour.py и любой другой ops_*.py. authoring.py получает
аддитивно импорт и две строки в _EMITTERS — тот же минимальный шов, которым
подключилась волна каркаса.

Переиспользовано из authoring.py БЕЗ ИЗМЕНЕНИЙ (импортом, не копией): _gid,
_eid, _cs, _safe, _level_expr, _stamp_block, _readback_block, _loop_pts,
EMIT_UNSUPPORTED, плюс ПУБЛИЧНЫЕ модели свидетелей level_chain_witness и
bbox_extents_witness. Тот же список, что у struct_emit.py, с той же оговоркой
в его шапке: часть имён — приватные (с подчёркиванием), и если будущий проход
захочет чистый шов, лечится это повышением их до публичных в authoring.py, а
не копированием тел сюда.

ГЛАВНОЕ ОБ ЭТОМ ФАЙЛЕ. Обе операции написаны по ЗАМЕРУ компайл-сервиса на
шести версиях (2021-2026), а не по памяти об API. Замер и его следствия
разобраны в шапке ops_arch.py; здесь — только то, что видно в коде:

* потолок на 2021 — типизированный отказ ЦЕЛИКОМ (не развилка эмиссии, как у
  create_floor): Ceiling.Create нет до 2022, а doc.Create.NewCeiling нет
  вообще ни на одной версии, значит альтернативного пути не существует;
* ограждение — две перегрузки Railing.Create, и обе живут на всех шести;
* путь ограждения кладётся ОТКРЫТОЙ ломаной: _loop_pts (общий помощник
  контуров) замыкает кольцо через (k+1)%n и здесь НЕ ГОДИТСЯ — у него своя
  причина существования. Замыкающий сегмент, которого нет в источнике, — это
  выдуманная геометрия, а не «мелочь округления».
"""
from __future__ import annotations

from kukai.ir.authoring import (
    _gid, _eid, _cs, _safe, _level_expr, _stamp_block, _stamp_readback,
    _readback_block, _loop_pts, EMIT_UNSUPPORTED,
    level_chain_witness, bbox_extents_witness,
)
from kukai.ir.emit_model import WitnessCheck
from kukai.ir.emit_utils import cs_line_comment_fragment, refuse_stmt
from kukai.ir.diag import Diagnostic, KirRefusal, PARSE_MISSING_FIELD
from kukai.ir.ops_arch import RAILING_PLACEMENT_MEMBERS

#: Разновидность create_railing вне закрытого множества {path, hosted}.
#: Ремень поверх подтяжек: `enum`-choices ParamSpec уже ловит это на
#: authoring.validate() (KIR-T003), а эта проверка — защита в глубину внутри
#: самого эмиттера, ровно как FOUNDATION_UNSUPPORTED_KIND у волны каркаса.
#: Сюда попадёт тот, кто расширит choices, не дописав ветку: пусть падает
#: ГРОМКО, а не строит молча не то.
RAILING_UNSUPPORTED_VARIETY = "KIR-E006"


def _grounded_type_cs(op: dict, s: str, oid: str, ver: str, param: str,
                      cs_class: str, human: str, isolation: str) -> str:
    """Разрешение типа в переменную __ty_<s>.

    Ветки doc_default здесь НЕТ намеренно, и это не упрощение. У ограждения
    типа по умолчанию не существует в API вовсе (ElementTypeGroup.RailingType
    не компилируется ни на одной из шести версий — замерено), а у потолка он
    есть, но сознательно не используется: «тип потолка по умолчанию» на чужом
    здании почти никогда не тот тип, что стоял в источнике, и подмена типа
    снаружи неотличима от успеха. Пропущенный `type` разрешает ground.py
    общим правилом «единственный в пуле, иначе типизированный вопрос».
    """
    sel = op.get(param)
    g = _gid(op, param) if isinstance(sel, dict) and "__grounded__" in sel else None
    if not g or g.get("id") is None:
        raise KirRefusal([Diagnostic(
            code=PARSE_MISSING_FIELD, op_id=oid, field_name=param,
            message_ru=(f"{human}: тип не разрешён на стадии ground — у этой "
                        f"операции нет типа по умолчанию, подставить нечего"))])
    return (f"{cs_class} __ty_{s} = doc.GetElement({_eid(g['id'], ver, oid)}) "
            f"as {cs_class};\n"
            f"if (__ty_{s} == null) {{ "
            f"{refuse_stmt(oid, _cs(human + ': тип не найден (модель изменилась после grounding)'), isolation)} }}")


# ── create_ceiling ───────────────────────────────────────────────────────────

def emit_ceiling(op: dict, ver: str, stamp: str,
                 isolation: str = "atomic") -> tuple[str, str, list, str]:
    """Потолок по замкнутому контуру, Revit 2022+.

    Ceiling.Create(doc, IList<CurveLoop>, ElementId typeId, ElementId levelId)
    — подтверждено компиляцией на 2022/2023/2024/2025/2026 и опровергнуто на
    2021 (CS0117: 'Ceiling' does not contain a definition for 'Create').
    """
    oid = op["id"]
    s = _safe(oid)
    if ver < "2022":
        # ОСЬ ВЕРСИЙ ЗДЕСЬ — ОТКАЗ, А НЕ РАЗВИЛКА. У create_floor на 2021 есть
        # куда свернуть (legacy doc.Create.NewFloor), у потолка — некуда:
        # NewCeiling не существует НИ НА ОДНОЙ из шести версий (замерено,
        # CS1061). Единственные альтернативы отказу — построить не потолок
        # (перекрытие) или не построить ничего и промолчать; обе читаются
        # снаружи как успех, и обе запрещены §18.1.
        raise KirRefusal([Diagnostic(
            code=EMIT_UNSUPPORTED, op_id=oid, field_name=None,
            message_ru=(
                f"потолок не создаётся на Revit {ver}: Ceiling.Create "
                f"появился только в 2022, а legacy-пути к потолку "
                f"(doc.Create.NewCeiling) в API нет ни на одной версии "
                f"2021-2026 — замерено компиляцией. Обходного пути нет: "
                f"перекрытие вместо потолка было бы другим элементом, "
                f"другой категории"))])
    holes = op.get("holes") or []
    lv_res, lv_idexpr = _level_expr(op, s, ver, oid, isolation)
    ct = _grounded_type_cs(op, s, oid, ver, "type", "CeilingType",
                           "потолок", isolation)
    outline = op["outline"]
    geo = [f"var __loops_{s} = new List<CurveLoop>();"]
    geo += _loop_pts(outline, f"__ol_{s}")
    geo.append(f"__loops_{s}.Add(__ol_{s});")
    for hi, hole in enumerate(holes):
        geo += _loop_pts(hole, f"__hl_{s}_{hi}")
        geo.append(f"__loops_{s}.Add(__hl_{s}_{hi});")
    make = (f"__el_{s} = Ceiling.Create(doc, __loops_{s}, __ty_{s}.Id, "
            f"__lv_{s}.Id);")
    # Смещение от уровня. Единственная вертикальная степень свободы потолка с
    # ЗАМЕРЕННЫМ параметром (CEILING_HEIGHTABOVELEVEL_PARAM, 6/6). Отсутствие
    # параметра оставляет C# без единой строки об этом — отсутствие остаётся
    # отсутствием, а не нулём.
    height_offset = op.get("height_offset_mm")
    ho_set = ""
    if height_offset is not None:
        ho_set = (
            f"\nParameter __cho_{s} = __el_{s}.get_Parameter("
            f"BuiltInParameter.CEILING_HEIGHTABOVELEVEL_PARAM);\n"
            f"if (__cho_{s} == null || __cho_{s}.IsReadOnly) {{ "
            f"{refuse_stmt(oid, _cs('CEILING_HEIGHTABOVELEVEL_PARAM недоступен у потолка'), isolation)} }}\n"
            f"__cho_{s}.Set(U({height_offset}));")
    decl = f"Ceiling __el_{s} = null;"
    create = (f"// create_ceiling {cs_line_comment_fragment(oid)}\n{ct}\n{lv_res}\n"
              + "\n".join(geo) + f"\n{make}\n"
              f"if (__el_{s} == null) {{ "
              f"{refuse_stmt(oid, _cs('создание потолка вернуло null'), isolation)} }}\n"
              + ho_set
              + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))
    from kukai.ir.emit_model import tolerances
    tol = tolerances("create_ceiling")
    xs = [pt[0] for pt in outline]
    ys = [pt[1] for pt in outline]
    checks: list[WitnessCheck] = [
        level_chain_witness(f"__el_{s}", oid, lv_idexpr),
        bbox_extents_witness(f"__el_{s}", oid, min(xs), max(xs),
                             min(ys), max(ys), tol["bbox_mm"]),
    ]
    if height_offset is not None:
        checks.append(WitnessCheck(
            obligation_key="height_offset",
            reader_cs=(f"    var __chop = __el_{s}.get_Parameter("
                       f"BuiltInParameter.CEILING_HEIGHTABOVELEVEL_PARAM);\n"),
            verdict_cs=(
                f"    if (__chop == null || Math.Abs(MM(__chop.AsDouble()) - "
                f"{height_offset}) > {tol['height_offset_mm']})\n"
                f"        __post.Add({_cs(oid + ': height offset mismatch (geometry)')});\n"),
            message="height offset mismatch (geometry)",
            tol=tol["height_offset_mm"], style="guard"))
    return decl, create, checks, _readback_block(s, oid, stamp)


# ── create_railing ───────────────────────────────────────────────────────────

def _path_pts(pts: list, name: str, z: str = "0") -> list:
    """ОТКРЫТАЯ ломаная в CurveLoop — n точек дают n-1 сегментов.

    Отдельный помощник, а не аргумент к _loop_pts: у _loop_pts замыкание
    зашито в `(k + 1) % n` и является его СМЫСЛОМ (контур перекрытия обязан
    быть кольцом). Ограждение — не кольцо: прямой марш это две точки, и
    замыкающий сегмент вернул бы в модель геометрию, которой в источнике
    нет.  CurveLoop в Revit не обязан быть замкнутым, поэтому тот же тип
    контейнера подходит обоим.
    """
    out = [f"CurveLoop {name} = new CurveLoop();"]
    for k in range(len(pts) - 1):
        a, b = pts[k], pts[k + 1]
        out.append(f"{name}.Append(Line.CreateBound("
                   f"P({a[0]}, {a[1]}, {z}), P({b[0]}, {b[1]}, {z})));")
    return out


def _emit_railing_path(op: dict, ver: str, stamp: str,
                       isolation: str) -> tuple[str, str, list, str]:
    """Свободное ограждение по собственному пути.

    Railing.Create(doc, CurveLoop, ElementId railingTypeId,
                   ElementId baseLevelId) — 6/6.
    """
    oid = op["id"]
    s = _safe(oid)
    path = op["path"]
    lv_res, lv_idexpr = _level_expr(op, s, ver, oid, isolation)
    rt = _grounded_type_cs(op, s, oid, ver, "type", "RailingType",
                           "ограждение", isolation)
    geo = _path_pts(path, f"__pth_{s}")
    decl = f"Railing __el_{s} = null;"
    create = (f"// create_railing(path) {cs_line_comment_fragment(oid)}\n"
              f"{rt}\n{lv_res}\n" + "\n".join(geo) + "\n"
              f"__el_{s} = Railing.Create(doc, __pth_{s}, __ty_{s}.Id, "
              f"__lv_{s}.Id);\n"
              f"if (__el_{s} == null) {{ "
              f"{refuse_stmt(oid, _cs('создание ограждения вернуло null'), isolation)} }}\n"
              + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))
    from kukai.ir.emit_model import tolerance
    tol = tolerance("create_railing", "bbox_mm")
    xs = [pt[0] for pt in path]
    ys = [pt[1] for pt in path]
    checks: list[WitnessCheck] = [
        # Уровень ограждения НЕ ловится общей BIP-цепочкой
        # (level_chain_witness): у неё звенья FAMILY_BASE_LEVEL/FAMILY_LEVEL/
        # SCHEDULE_LEVEL/LEVEL_PARAM, а базовый уровень ограждения лежит в
        # STAIRS_RAILING_BASE_LEVEL_PARAM (замерено, 6/6). Свой свидетель, а
        # не «сойдёт и так»: чужая цепочка молча вернула бы null и обвинила
        # правильно построенный элемент.
        WitnessCheck(
            # Ключ обязательства ОБЩИЙ у обеих ветвей — "anchor", то, к чему
            # ограждение привязано: свободное к УРОВНЮ, лестничное к ХОЗЯИНУ.
            # Так сертификат перевода (translation_cert.py) закрывает одно
            # обязательство любой из двух эмиссий, ровно как у
            # create_foundation с его общим "footprint" на isolated/slab.
            obligation_key="anchor",
            reader_cs=(f"    var __rlp_{s} = __el_{s}.get_Parameter("
                       f"BuiltInParameter.STAIRS_RAILING_BASE_LEVEL_PARAM);\n"),
            verdict_cs=(
                f"    if (__rlp_{s} == null || __rlp_{s}.AsElementId() == null\n"
                f"        || __rlp_{s}.AsElementId().ToString() != {lv_idexpr})\n"
                f"        __post.Add({_cs(oid + ': base level mismatch (topology)')});\n"),
            message="base level mismatch (topology)", style="guard"),
        bbox_extents_witness(f"__el_{s}", oid, min(xs), max(xs),
                             min(ys), max(ys), tol),
    ]
    return decl, create, checks, _readback_block(s, oid, stamp)


def _emit_railing_hosted(op: dict, ver: str, stamp: str,
                         isolation: str) -> tuple[str, str, list, str]:
    """Ограждение, ПРИНАДЛЕЖАЩЕЕ лестнице или пандусу.

    Railing.Create(doc, ElementId hostId, ElementId railingTypeId,
                   RailingPlacementPosition) — 6/6.

    Это, а не путь, и есть вся популяция ограждений реального здания: на K2
    OST_StairsRailing 203 штук. Свести их к варианту `path` значило бы
    ВЫДУМАТЬ путь там, где источник даёт хозяина, и потерять саму привязку —
    ту самую «привязку к лестнице/пандусу», которая обязана быть выражена или
    отказана, но никогда не подменена.
    """
    oid = op["id"]
    s = _safe(oid)
    host_sel = op["host"]
    position = op.get("position")
    if position is None:
        raise KirRefusal([Diagnostic(
            code=PARSE_MISSING_FIELD, op_id=oid, field_name="position",
            message_ru=(
                "create_railing(variety=hosted): position обязателен — "
                "RailingPlacementPosition решает, где на лестнице встанет "
                "ограждение (по проступям или по косоуру), и подставить одно "
                "из двух за пользователя значит поставить его не туда молча"))])
    member = RAILING_PLACEMENT_MEMBERS[position]
    # ХОЗЯИН ОБЪЯВЛЯЕТСЯ ВО ВНЕШНЕЙ ОБЛАСТИ, а не в блоке создания. Это не
    # стиль: при isolation="per_op" блоки создания и постусловий попадают в
    # РАЗНЫЕ области видимости, и переменная, объявленная внутри create,
    # свидетелю не видна. Первая версия этого эмиттера так и падала — живые
    # ворота дали CS0103 '__hst_R1 does not exist in the current context'
    # ровно на шести per_op-прогонах. Тот же шов, о котором предупреждает
    # шапка compile_gate_offline.py («ворота обязаны компилировать ровно то,
    # что поедет в модель»).
    if host_sel.get("by") == "ref":
        # Ссылка внутри программы: create_stairs той же программы. Плановая
        # стадия уже проверила существование цели по DAG.
        host_decl = ""
        host_res = ""
        host_id_cs = "__el_" + _safe(host_sel["value"]) + ".Id"
    else:
        host_decl = f"\nElement __hst_{s} = null;"
        host_res = (
            f"__hst_{s} = doc.GetElement("
            f"{_eid(host_sel['value'], ver, oid)});\n"
            f"if (__hst_{s} == null) {{ "
            f"{refuse_stmt(oid, _cs('лестница/пандус-хост не найден (модель изменилась после grounding)'), isolation)} }}\n")
        host_id_cs = f"__hst_{s}.Id"
    rt = _grounded_type_cs(op, s, oid, ver, "type", "RailingType",
                           "ограждение", isolation)
    # ЭТА ПЕРЕГРУЗКА ВОЗВРАЩАЕТ КОЛЛЕКЦИЮ, А НЕ ЭЛЕМЕНТ. Замерено
    # присваиванием в объявленный тип: Railing.Create(doc, hostId, typeId,
    # position) -> ICollection<ElementId> на всех шести версиях. Первый круг
    # проб этого не увидел, потому что проверял `var __r = ...` — такая
    # строка компилируется при ЛЮБОМ типе справа и потому не доказывает
    # ничего; ворота вернули CS0266. Смысл коллекции физический: у марша
    # ограждение может встать с ДВУХ сторон сразу, и одна операция создаёт
    # несколько элементов. Прятать «лишние» в квитанции нельзя — созданное и
    # не показанное неотличимо от мусора в модели, а A5 сверяет владение
    # именно по id из квитанции.
    decl = (f"Railing __el_{s} = null;\n"
            f"ICollection<ElementId> __ids_{s} = null;" + host_decl)
    create = (f"// create_railing(hosted) {cs_line_comment_fragment(oid)}\n"
              f"{rt}\n{host_res}"
              f"__ids_{s} = Railing.Create(doc, {host_id_cs}, __ty_{s}.Id, "
              f"RailingPlacementPosition.{member});\n"
              f"if (__ids_{s} == null || __ids_{s}.Count == 0) {{ "
              f"{refuse_stmt(oid, _cs('создание ограждения на хосте не вернуло ни одного элемента'), isolation)} }}\n"
              f"foreach (var __rid_{s} in __ids_{s})\n{{\n"
              f"    var __rr_{s} = doc.GetElement(__rid_{s}) as Railing;\n"
              f"    if (__rr_{s} == null) {{ "
              f"{refuse_stmt(oid, _cs('созданное ограждение не читается как Railing'), isolation)} }}\n"
              f"    " + _stamp_block(f"__rr_{s}", f"{stamp}:{oid}") + "\n"
              f"    if (__el_{s} == null) __el_{s} = __rr_{s};\n}}")
    checks: list[WitnessCheck] = [
        # Принадлежность хозяину — топология, и её обязан подтвердить сам
        # элемент, а не наше намерение. Проверяется КАЖДОЕ созданное
        # ограждение, а не первое: если API вернул два, а хозяину принадлежит
        # одно, программа не выполнена. Railing.HasHost (bool) и
        # Railing.HostId (ElementId — замерено присваиванием) 6/6.
        WitnessCheck(
            obligation_key="anchor",   # см. комментарий в ветке path
            reader_cs="",
            verdict_cs=(
                f"    foreach (var __hid_{s} in __ids_{s})\n    {{\n"
                f"        var __hr_{s} = doc.GetElement(__hid_{s}) as Railing;\n"
                f"        if (__hr_{s} == null || !__hr_{s}.HasHost\n"
                f"            || __hr_{s}.HostId == null\n"
                f"            || __hr_{s}.HostId == ElementId.InvalidElementId\n"
                f"            || __hr_{s}.HostId.ToString() != {host_id_cs}.ToString())\n"
                f"            __post.Add({_cs(oid + ': ограждение не принадлежит запрошенному хосту (topology)')});\n"
                f"    }}\n"),
            message="ограждение не принадлежит запрошенному хосту (topology)",
            style="guard"),
    ]
    # Квитанция своя, а не _readback_block: тот сообщает РОВНО ОДИН id, и на
    # этой ветке умолчал бы о втором ограждении марша.
    readback = (
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n"
        f"    var __rb = new Dictionary<string, object>();\n"
        f"    __rb[\"id\"] = __el_{s}.Id.ToString();\n"
        f"    __rb[\"created_ids\"] = __ids_{s}.Select("
        f"__i => __i.ToString()).ToArray();\n"
        f"    __rb[\"created_count\"] = __ids_{s}.Count;\n"
        + _stamp_readback(f"__el_{s}") +
        f"    __results[{_cs(oid)}] = __rb;\n}}")
    return decl, create, checks, readback


def emit_railing(op: dict, ver: str, stamp: str,
                 isolation: str = "atomic") -> tuple[str, str, list, str]:
    """Развилка по закрытому множеству {path, hosted}.

    Здесь же — УСЛОВНО ОБЯЗАТЕЛЬНЫЕ поля, которые ParamSpec.required выразить
    не может по построению (`path`+`level` нужны только варианту path, `host`
    — только hosted; статическое required=True требовало бы их у обеих
    ветвей). Тот же шов и та же причина, что у emit_foundation: типизированный
    KIR-P005 здесь, а не голый KeyError, который выше поймается как
    KIR-P000 «внутренняя ошибка» — fail-closed, но диагностика хуже.
    """
    variety = op.get("variety")
    if variety == "path":
        if op.get("path") is None:
            raise KirRefusal([Diagnostic(
                code=PARSE_MISSING_FIELD, op_id=op.get("id"), field_name="path",
                message_ru="create_railing(variety=path): path обязателен")])
        if op.get("level") is None:
            raise KirRefusal([Diagnostic(
                code=PARSE_MISSING_FIELD, op_id=op.get("id"),
                field_name="level",
                message_ru=("create_railing(variety=path): level обязателен — "
                            "у свободного ограждения базовый уровень задаём "
                            "мы, вывести его неоткуда"))])
        return _emit_railing_path(op, ver, stamp, isolation)
    if variety == "hosted":
        if op.get("host") is None:
            raise KirRefusal([Diagnostic(
                code=PARSE_MISSING_FIELD, op_id=op.get("id"), field_name="host",
                message_ru=("create_railing(variety=hosted): host обязателен "
                            "— это и есть лестница/пандус, которому "
                            "ограждение принадлежит"))])
        return _emit_railing_hosted(op, ver, stamp, isolation)
    raise KirRefusal([Diagnostic(
        code=RAILING_UNSUPPORTED_VARIETY, op_id=op.get("id"),
        field_name="variety", got=variety, candidates=["path", "hosted"],
        message_ru=(f"create_railing: разновидность {variety!r} не поддержана "
                    f"(в API ровно две перегрузки Railing.Create — по пути и "
                    f"по хосту)"))])
