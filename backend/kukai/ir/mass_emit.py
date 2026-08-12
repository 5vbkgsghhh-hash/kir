"""mass_emit — эмиссия `create_face_wall` (парный файл к ops_mass.py).

`authoring.py` получает отсюда только импорт и одну строку в `_EMITTERS` —
тот же минимальный шов, которым подключились волны площадки, профилей и тел.

ПОЧЕМУ ЗДЕСЬ НЕТ СВОЕГО ОТБОРА ГРАНИ. Грань выбирает `faceref.resolve_cs` —
БУКВАЛЬНО тот же код, что у волны названных граней: те же два родных теста
Revit (векторное произведение через `IsZeroLength`, знак `DotProduct`), тот
же закон мощности (одна — берём, ноль — отказ, две и больше — отказ С
ЧИСЛОМ) и те же тексты отказов. Написать здесь второй отбор значило бы
завести второй механизм рядом с существующим и получить два места, где закон
можно ослабить порознь.

ВТОРАЯ СТУПЕНЬ СЕЛЕКТОРА ЗДЕСЬ НЕ ЗАВОДИТСЯ, И ЭТО РАЗНЫЕ ВЕЩИ. Флаг
`KUKAI_IR_FACE_REF` гатит ФОРМУ СЕЛЕКТОРА `{"by": "face", ...}` — расширение
замороженного диалекта ссылок, которое видит схема и каждый её потребитель.
`create_face_wall` никакого нового селектора не вводит: у неё обычный
параметр-вектор `face_normal`, ровно как `side` у `create_slab_edge`, а
общими остаются ПОМОЩНИКИ ОБХОДА. Поэтому операция работает при выключенном
флаге, и это не обход гейта, а разница между «новый род ссылки» и
«переиспользованный обход геометрии».

ПОЧЕМУ ДВА ПРЕДПОЛЁТА REVIT, А НЕ СВОИ ПРОВЕРКИ. `FaceWall` — единственная
фабрика этой главы, которая привезла СВОИ валидаторы:
`IsWallTypeValidForFaceWall` и `IsValidFaceReferenceForFaceWall`, обе 6/6.
Каждая спрашивается ДО эффекта, поэтому «Revit не берёт такой тип» и «Revit
не берёт такую грань» приезжают ТИПИЗИРОВАННЫМ ОТКАЗОМ с названным следующим
ходом, а не исключением, которое квитанция запишет как `internal`. Своя
проверка на их месте была бы догадкой о правилах, которые Autodesk нигде не
перечислил полностью: документация называет три условия для грани («face of a
massing instance», «planar», «normal must not be vertical or horizontal»), а
для типа — ни одного.

СИСТЕМА КООРДИНАТ — ЕДИНСТВЕННОЕ МЕСТО, ГДЕ ЭТА ВОЛНА МОГЛА СОВРАТЬ ТИХО.
Носитель — `FamilyInstance`, и грань его тела живёт в СИМВОЛЬНЫХ координатах
(`GeometryInstance`); построенная стена — обычный элемент проекта, её грани в
МОДЕЛЬНЫХ. Поэтому свидетель НИ РАЗУ не читает координаты по ссылке на грань
массы: нормаль сверяется с ЗАПРОШЕННЫМ вектором (а его сонаправленность
модельной нормали грани уже удостоверил САМ Revit при отборе — тем же
`IsZeroLength`), положение — с ГАБАРИТОМ носителя, который Revit отдаёт в
координатах модели. Ни одного нашего преобразования между системами.
"""
from __future__ import annotations

from kukai.ir import faceref
from kukai.ir.authoring import (
    _gid, _eid, _cs, _safe, _stamp_block, _stamp_readback,
)
from kukai.ir.emit_model import WitnessCheck
from kukai.ir.emit_utils import cs_line_comment_fragment, refuse_stmt
from kukai.ir.diag import (
    Diagnostic, EMIT_UNSUPPORTED_ENUM, KirRefusal, PARSE_MISSING_FIELD)
from kukai.ir.ops_mass import FACE_WALL_LOCATION_LINES

#: `location_line` вне закрытого множества. Ремень поверх подтяжек, ровно как
#: у волны профилей (`sweep_emit`, тот же общий код): `enum`-choices уже ловит это на
#: `authoring.validate()`, а здесь стоит защита в глубину — тот, кто расширит
#: словарь, не дописав ветку, упадёт ГРОМКО, а не построит молча не то.

#: Человеческое имя операции для текстов отказа. Отказ читает человек, и
#: «FaceWall.Create вернул null» отправляет его читать документацию Autodesk
#: вместо собственной программы.
_HUMAN = "стена по грани массы"


def _host_resolve_cs(op: dict, s: str, ver: str, oid: str,
                     isolation: str) -> str:
    """Разрешение носителя в `__hsrc_<s>` (объявление — в `decl`).

    Приведения к классу здесь НЕТ НАМЕРЕННО, и это не пропуск. Годность
    носителя решает не наш `as`, а `IsValidFaceReferenceForFaceWall`, который
    спрашивается ниже и знает правило целиком («face of a massing instance»).
    Своё `as FamilyInstance` отвергло бы, например, массу на месте (in-place),
    которая является `FamilyInstance` не всегда, — то есть запретило бы то,
    что Revit разрешает, и объяснило бы это словами про класс, а не про массу.
    """
    sel = op["host"]
    if sel.get("by") == "ref":
        return f"__hsrc_{s} = __el_{_safe(sel['value'])};\n"
    return (f"__hsrc_{s} = doc.GetElement({_eid(sel['value'], ver, oid)});\n"
            f"if (__hsrc_{s} == null) {{ "
            + refuse_stmt(oid, _cs(
                f"{_HUMAN}: носитель не найден (модель изменилась после "
                f"grounding)"), isolation) + " }\n")


def _type_resolve_cs(op: dict, s: str, oid: str, ver: str,
                     isolation: str) -> str:
    """Разрешение типа стены в `__ty_<s>` плюс ПРЕДПОЛЁТ самого Revit.

    Ветки `doc_default` здесь нет по той же причине, что у краевого профиля:
    подставленный за автора тип стены снаружи неотличим от успеха. Пропущенный
    `type` разрешает `ground` общим правилом «единственный в пуле, иначе
    типизированный вопрос с кандидатами», и этот вопрос автор УВИДИТ.
    """
    sel = op.get("type")
    g = _gid(op, "type") if isinstance(sel, dict) and "__grounded__" in sel else None
    if not g or g.get("id") is None:
        raise KirRefusal([Diagnostic(
            code=PARSE_MISSING_FIELD, op_id=oid, field_name="type",
            message_ru=(f"{_HUMAN}: тип не разрешён на стадии ground — у этой "
                        f"операции нет типа по умолчанию, подставить нечего"))])
    return (
        f"__ty_{s} = doc.GetElement({_eid(g['id'], ver, oid)}) as WallType;\n"
        f"if (__ty_{s} == null) {{ "
        + refuse_stmt(oid, _cs(
            f"{_HUMAN}: тип не найден или он не WallType (модель изменилась "
            f"после grounding)"), isolation) + " }\n"
        # ПРЕДПОЛЁТ REVIT. Полного перечня допустимых типов Autodesk не даёт
        # нигде, поэтому спрашиваем сам Revit, а не угадываем правило.
        f"bool __tyok_{s} = false;\n"
        f"try {{ __tyok_{s} = FaceWall.IsWallTypeValidForFaceWall("
        f"doc, __ty_{s}.Id); }} catch {{ }}\n"
        f"if (!__tyok_{s}) {{ "
        + refuse_stmt(
            oid,
            _cs(f"{_HUMAN}: Revit не принимает этот тип стены по грани (")
            + f" + __ty_{s}.Name + " + _cs(
                "). Правило целиком Autodesk нигде не перечислил, поэтому "
                "спрошен сам Revit (IsWallTypeValidForFaceWall) — и он "
                "ответил «нет» ДО эффекта, а не исключением после. "
                "СЛЕДУЮЩИЙ ХОД: назови другой тип стены; query_types kind="
                "wall_types покажет пул"),
            isolation) + " }\n")


def emit_face_wall(op: dict, ver: str, stamp: str,
                   isolation: str = "atomic") -> tuple[str, str, list, str]:
    """Стена по НАКЛОННОЙ грани концептуальной массы, Revit 2021-2026.

    `FaceWall.Create(Document, ElementId, WallLocationLine, Reference)` — 6/6,
    версионной ветки НЕТ: подпись, оба предполёта, `HostObjectUtils`,
    `WallType.Width` и `VertexTolerance` собираются одинаково на всех шести.

    ПОЧЕМУ ЭТА ОПЕРАЦИЯ ВООБЩЕ ЕСТЬ, КОГДА ВСЯ ГЛАВА ОТКАЗАНА: у неё одной
    RevitAPI.xml называет условием броска *«document is not a project
    document»* — точную инверсию отказа шести форм массы, у которых бросает
    сам аксессор `Document.FamilyCreate` («thrown when the current document
    is project document»). Обе фразы перечитаны в КАЖДОЙ из шести RevitAPI.xml,
    а не в двух крайних. Разбор всей главы — в шапке `ops_mass.py`.
    """
    oid = op["id"]
    s = _safe(oid)
    ll = op.get("location_line")
    if ll not in FACE_WALL_LOCATION_LINES:
        raise KirRefusal([Diagnostic(
            code=EMIT_UNSUPPORTED_ENUM, op_id=oid, field_name="location_line",
            got=ll, candidates=sorted(FACE_WALL_LOCATION_LINES),
            message_ru=(f"create_face_wall: положение {ll!r} не поддержано — "
                        f"имена задаёт перечисление Revit WallLocationLine"))])
    ll_cs = FACE_WALL_LOCATION_LINES[ll]
    normal = op["face_normal"]

    # Селектор грани СОБИРАЕТСЯ ЗДЕСЬ из параметра-вектора и отдаётся
    # `faceref.resolve_cs` в его собственной форме. Так закон отбора остаётся
    # в одном файле, а у этой операции не появляется второй диалект.
    face_sel = {"by": faceref.BY_FACE, "of": op["host"],
                "predicate": {"normal": [float(x) for x in normal]}}

    # ВСЁ, ЧТО ЧИТАЕТ СВИДЕТЕЛЬ, ОБЪЯВЛЕНО ЗДЕСЬ: при `isolation="per_op"`
    # create и post попадают в РАЗНЫЕ области видимости, и имя, объявленное
    # внутри create, свидетелю не видно (CS0103 — тот самый шов, на котором
    # волна ограждений получила шесть отказов ворот). ОДНО ОБЪЯВЛЕНИЕ НА
    # СТРОКУ: контракт областей разбирает объявления построчно.
    decl = (f"FaceWall __el_{s} = null;\n"
            f"WallType __ty_{s} = null;\n"
            f"Element __hsrc_{s} = null;\n"
            f"Reference __fr_{s} = null;\n"
            f"XYZ __want_{s} = null;\n"
            f"double __farea_{s} = 0.0;\n"
            f"double __warea_{s} = 0.0;\n"
            f"double __wwid_{s} = 0.0;\n"
            f"double __wtol_{s} = 0.0;\n"
            f"int __wfn_{s} = 0;\n"
            f"bool __inbb_{s} = false;\n"
            + faceref.walk_helpers_cs(s))

    create = (
        f"// create_face_wall {cs_line_comment_fragment(oid)}\n"
        + _host_resolve_cs(op, s, ver, oid, isolation)
        + _type_resolve_cs(op, s, oid, ver, isolation)
        # ОТБОР ГРАНИ — ЧУЖИМ КОДОМ, СВОИМ ЗАКОНОМ (см. шапку модуля).
        + faceref.resolve_cs(
            face_sel, s=s, i=0, elem_var=f"__hsrc_{s}", out_var=f"__fr_{s}",
            oid=oid, label=f"{_HUMAN}: face_normal", isolation=isolation,
            view_var=None, refuse_stmt=refuse_stmt, cs_literal=_cs,
            # СЛЕДУЮЩИЙ ХОД — СЛОВАМИ ЭТОЙ ОПЕРАЦИИ. Собственный текст
            # `faceref` отсылает к `predicate.side`/`predicate.normal`, то
            # есть к словарю второй ступени селектора; у `create_face_wall`
            # таких полей нет вовсе, и отказ, посылающий автора править
            # несуществующее поле, дороже отсутствия отказа.
            normal_field="face_normal",
            next_move_zero=(
                "СЛЕДУЮЩИЙ ХОД: проверь face_normal — это внешняя нормаль "
                "грани в координатах МОДЕЛИ. И помни правило самого Revit: "
                "стену по грани он строит ТОЛЬКО по наклонной грани массы, "
                "то есть у вертикальной ([0,0,±1]) и горизонтальной "
                "(z == 0) нормали кандидата не будет никогда"),
            next_move_many=(
                "СЛЕДУЮЩИЙ ХОД: у этой массы несколько РАЗНЫХ граней с одной "
                "и той же нормалью (параллельные скаты), и выбрать из них за "
                "автора нельзя. Это НАЗВАННЫЙ предел операции: сегодня одна "
                "нормаль — один скат. Строй стену по массе, у которой скат с "
                "таким направлением один")) + "\n"
        # ПЛОЩАДЬ НАЗВАННОЙ ГРАНИ — ТОЛЬКО В КВИТАНЦИЮ. Площадь инвариантна
        # к жёсткому преобразованию экземпляра, поэтому её читать по этой
        # ссылке ЗАКОННО; координаты по ней читать было бы нельзя (символьная
        # система) — и мы их не читаем нигде.
        f"PlanarFace __mf_{s} = null;\n"
        f"try {{ __mf_{s} = __hsrc_{s}.GetGeometryObjectFromReference("
        f"__fr_{s}) as PlanarFace; }} catch {{ }}\n"
        f"if (__mf_{s} != null) __farea_{s} = __mf_{s}.Area;\n"
        # ПРЕДПОЛЁТ REVIT ПО ГРАНИ. Три условия Autodesk называет дословно, и
        # все три спрашиваются ОДНИМ вызовом — своя проверка на его месте
        # была бы переписыванием чужого правила по памяти.
        f"bool __frok_{s} = false;\n"
        f"try {{ __frok_{s} = FaceWall.IsValidFaceReferenceForFaceWall("
        f"doc, __fr_{s}); }} catch {{ }}\n"
        f"if (!__frok_{s}) {{ "
        + refuse_stmt(
            oid,
            _cs(f"{_HUMAN}: Revit не принимает эту грань как основание для "
                f"стены по грани. Его собственное правило "
                f"(IsValidFaceReferenceForFaceWall, спрошен ДО эффекта): "
                f"грань обязана принадлежать МАССЕ, быть ПЛОСКОЙ, и её "
                f"нормаль не должна быть ни вертикальной, ни горизонтальной "
                f"— то есть стену по грани строят по НАКЛОННОЙ поверхности. "
                f"СЛЕДУЮЩИЙ ХОД: для вертикальной грани строй create_wall, "
                f"для горизонтальной — перекрытие или кровлю (пола и кровли "
                f"ПО ГРАНИ в API нет вовсе, замерено 6/6 CS1061)"),
            isolation) + " }\n"
        f"try {{ __el_{s} = FaceWall.Create(doc, __ty_{s}.Id, "
        f"WallLocationLine.{ll_cs}, __fr_{s}); }}\n"
        f"catch (Exception __ex_{s}) {{ "
        + refuse_stmt(
            oid,
            _cs(f"{_HUMAN}: FaceWall.Create отказал — ")
            + f" + __ex_{s}.Message", isolation) + " }\n"
        f"if (__el_{s} == null) {{ "
        + refuse_stmt(
            oid,
            _cs(f"{_HUMAN}: создание вернуло null — Revit не принял эту "
                f"грань, хотя предполётная проверка её пропустила"),
            isolation) + " }\n"
        + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))

    checks: list[WitnessCheck] = [
        WitnessCheck(
            # ТИП ПОСТРОЕННОГО ЭЛЕМЕНТА, прочитанный обратно. Сравнение через
            # `ToString()` — единственная идиома `ElementId`, работающая на
            # всех шести: `.IntegerValue` мёртв на 2026, `.Value` не
            # существует до 2024.
            obligation_key="face_wall_type",
            reader_cs=f"    ElementId __rt_{s} = __el_{s}.GetTypeId();\n",
            verdict_cs=(
                f"    if (__rt_{s} == null || __ty_{s} == null\n"
                f"        || __rt_{s}.ToString() != __ty_{s}.Id.ToString())\n"
                f"        __post.Add({_cs(oid + ': тип построенной стены по грани не равен запрошенному (topology)')});\n"),
            message="тип построенной стены по грани не равен запрошенному (topology)",
            style="guard"),
        WitnessCheck(
            # ГЛАВНЫЙ ГЕОМЕТРИЧЕСКИЙ СВИДЕТЕЛЬ, и он читает ПОСТРОЕННУЮ
            # стену, а не наш вызов: у неё спрашиваются НАРУЖНЫЕ грани
            # (`HostObjectUtils` — те же имена, что у `faceref`), и среди них
            # обязана быть РОВНО ОДНА, сонаправленная с запрошенным вектором.
            # Ноль означает, что Revit прицепил стену не туда; больше одной —
            # что построенное тело не та призма, за которую его принимают.
            #
            # НИ ОДНОГО СВОЕГО ДОПУСКА: параллельность решает родной
            # `CrossProduct(...).IsZeroLength()`, сонаправленность — знак
            # `DotProduct`. Те же два теста, что в `faceref`, и по той же
            # причине.
            #
            # СРАВНЕНИЕ С ЗАПРОШЕННЫМ ВЕКТОРОМ, А НЕ С НОРМАЛЬЮ ГРАНИ МАССЫ —
            # это ОДНО И ТО ЖЕ утверждение, и удостоверил его САМ Revit: грань
            # попала в кандидаты только потому, что её МОДЕЛЬНАЯ нормаль
            # прошла ровно этот тест на равенство с вектором. Читать же
            # координаты по ссылке на грань экземпляра было бы чтением
            # символьной системы (см. шапку модуля).
            obligation_key="face_wall_normal",
            reader_cs=(
                f"    __want_{s} = new XYZ({float(normal[0])!r}, "
                f"{float(normal[1])!r}, {float(normal[2])!r});\n"
                f"    if (!__want_{s}.IsZeroLength()) __want_{s} = __want_{s}.Normalize();\n"
                f"    IList<Reference> __wsf_{s} = null;\n"
                f"    try {{ __wsf_{s} = HostObjectUtils.GetSideFaces("
                f"__el_{s}, ShellLayerType.Exterior); }} catch {{ }}\n"
                f"    BoundingBoxXYZ __hbb_{s} = null;\n"
                f"    try {{ __hbb_{s} = __hsrc_{s}.get_BoundingBox(null); }} catch {{ }}\n"
                f"    try {{ __wwid_{s} = __ty_{s}.Width; }} catch {{ }}\n"
                f"    try {{ __wtol_{s} = doc.Application.VertexTolerance; }} catch {{ }}\n"
                f"    double __grow_{s} = __wwid_{s} + __wtol_{s};\n"
                f"    if (__wsf_{s} != null)\n"
                f"        foreach (Reference __wr_{s} in __wsf_{s})\n"
                f"        {{\n"
                f"            PlanarFace __wp_{s} = null;\n"
                f"            try {{ __wp_{s} = __el_{s}.GetGeometryObjectFromReference("
                f"__wr_{s}) as PlanarFace; }} catch {{ }}\n"
                f"            if (__wp_{s} == null) continue;\n"
                f"            XYZ __wn_{s} = __wp_{s}.FaceNormal;\n"
                f"            if (__wn_{s}.IsZeroLength()) continue;\n"
                f"            __wn_{s} = __wn_{s}.Normalize();\n"
                f"            if (!__wn_{s}.CrossProduct(__want_{s}).IsZeroLength()) continue;\n"
                f"            if (__wn_{s}.DotProduct(__want_{s}) <= 0) continue;\n"
                f"            __wfn_{s}++;\n"
                f"            __warea_{s} = __wp_{s}.Area;\n"
                f"            XYZ __wo_{s} = __wp_{s}.Origin;\n"
                f"            if (__hbb_{s} != null && __wo_{s} != null\n"
                f"                && __wo_{s}.X >= __hbb_{s}.Min.X - __grow_{s}\n"
                f"                && __wo_{s}.X <= __hbb_{s}.Max.X + __grow_{s}\n"
                f"                && __wo_{s}.Y >= __hbb_{s}.Min.Y - __grow_{s}\n"
                f"                && __wo_{s}.Y <= __hbb_{s}.Max.Y + __grow_{s}\n"
                f"                && __wo_{s}.Z >= __hbb_{s}.Min.Z - __grow_{s}\n"
                f"                && __wo_{s}.Z <= __hbb_{s}.Max.Z + __grow_{s})\n"
                f"                __inbb_{s} = true;\n"
                f"        }}\n"),
            verdict_cs=(
                f"    if (__wfn_{s} != 1)\n"
                f"        __post.Add(__wfn_{s}.ToString() + \" \"\n"
                f"            + {_cs(oid + ': наружных граней построенной стены сонаправлены названной грани массы, а должна быть ровно одна (geometry)')});\n"),
            message=("наружных граней построенной стены сонаправлены названной "
                     "грани массы, а должна быть ровно одна (geometry)"),
            style="guard"),
        WitnessCheck(
            # ПОЛОЖЕНИЕ. Расширение габарита — на СОБСТВЕННУЮ толщину стены
            # плюс собственное число Revit, ни одного назначенного: тело
            # стены целиком лежит в полосе ±толщина от грани-носителя, а
            # грань — внутри габарита носителя, поэтому утверждение верно при
            # ЛЮБОМ `location_line` и проваливается, если стена построена не
            # по названной массе. Обе части сравнения — в координатах МОДЕЛИ.
            obligation_key="face_wall_within_host",
            reader_cs="",
            verdict_cs=(
                f"    if (!__inbb_{s})\n"
                f"        __post.Add({_cs(oid + ': наружная грань построенной стены лежит вне габарита носителя, расширенного на её собственную толщину (geometry)')});\n"),
            message=("наружная грань построенной стены лежит вне габарита "
                     "носителя, расширенного на её собственную толщину "
                     "(geometry)"),
            style="guard"),
        WitnessCheck(
            # ГРАНИЦА ВАКУУМНОСТИ, а не порог: нулевая площадь означает, что
            # не построено ничего.
            #
            # ЧИТАЕТСЯ ПЛОЩАДЬ ГРАНИ ТЕЛА, А НЕ ПАРАМЕТР, и это НЕ стилистика.
            # Первая редакция читала `HOST_AREA_COMPUTED` и подписывала
            # (geometry) — то есть удостоверяла ось, на которую не смотрела:
            # параметр может нести что угодно, включая значение, записанное
            # не геометрией. Поймал это не человек, а страж дома
            # (`test_witness_axis_honesty::GeometryClaimsMustReadGeometry`,
            # §18.3), и он прав: «свидетель подписывает ТУ ОСЬ, КОТОРУЮ
            # ЧИТАЛ». `__warea_` приходит из `PlanarFace.Area` той самой
            # наружной грани построенного тела, которую нашёл свидетель
            # нормали, — это геометрия и по источнику, и по подписи.
            obligation_key="face_wall_area_positive",
            reader_cs="",
            verdict_cs=(
                f"    if (!(__warea_{s} > 0.0))\n"
                f"        __post.Add({_cs(oid + ': площадь наружной грани построенного тела не больше нуля — не построено ничего (geometry)')});\n"),
            message=("площадь наружной грани построенного тела не больше нуля "
                     "— не построено ничего (geometry)"),
            style="guard"),
    ]

    readback = (
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n"
        f"    var __rb = new Dictionary<string, object>();\n"
        f"    __rb[\"id\"] = __el_{s}.Id.ToString();\n"
        f"    __rb[\"location_line\"] = {_cs(ll)};\n"
        f"    __rb[\"exterior_faces_codirectional\"] = __wfn_{s};\n"
        f"    __rb[\"within_host_bbox\"] = __inbb_{s};\n"
        f"    __rb[\"wall_width_mm\"] = MM(__wwid_{s});\n"
        f"    __rb[\"vertex_tolerance_mm\"] = MM(__wtol_{s});\n"
        # СЫРАЯ ПАРА, И НИ ОДНО ИЗ ДВУХ ЧИСЕЛ НЕ ВЕРДИКТ. Накрывает ли Revit
        # названную грань целиком, не сказано ни в одной из шести RevitAPI.xml
        # ни словом; утверждать равенство значило бы завести проверку, которая
        # может отвергнуть исправную работу, а назначить допуск — тот самый
        # запрещённый род. Живой прогон закроет вопрос за час, рассуждение не
        # закроет никогда.
        f"    __rb[\"named_face_area_mm2\"] = MM(MM(__farea_{s}));\n"
        f"    __rb[\"built_face_area_mm2\"] = MM(MM(__warea_{s}));\n"
        + _stamp_readback(f"__el_{s}") +
        f"    try {{ if (__ty_{s} != null && __ty_{s}.Name != null) "
        f"__rb[\"type_name\"] = __ty_{s}.Name; }} catch {{ }}\n"
        f"    __results[{_cs(oid)}] = __rb;\n}}")
    return decl, create, checks, readback
