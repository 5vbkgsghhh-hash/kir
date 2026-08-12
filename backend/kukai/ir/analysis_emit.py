"""analysis_emit — эмиссия волны нагрузок и пути эвакуации (парный файл к
ops_analysis.py, ровно как mep_emit.py к ops_mep.py и arch_emit.py к
ops_arch.py).

Своя зона волны: модуль не трогает ops_authoring.py, ops_struct.py,
ops_arch.py, ops_mep.py, connect.py, contour.py и ни один другой ops_*.py.
authoring.py получает АДДИТИВНО импорт и четыре строки в `_EMITTERS` — тот же
минимальный шов, которым подключились волны каркаса, архитектуры и ЭОМ.

Переиспользовано из authoring.py БЕЗ ИЗМЕНЕНИЙ (импортом, не копией): `_gid`,
`_eid`, `_cs`, `_safe`, `_pt3`, `_annot_view_res`, `_stamp_block`,
`_stamp_readback`, `EMIT_UNSUPPORTED`. Оговорка та же, что у struct_emit.py и
mep_emit.py: часть имён приватные, и лечится это повышением их до публичных в
authoring.py, а не копированием тел сюда.

ИМЕНА ПЕРЕМЕННЫХ ДЕЛЯТ ПРОСТРАНСТВО С ОБЁРТКОЙ per_op, и это стоило двух
отказов ворот на первом же прогоне (замер 09.08, обе пойманы Roslyn, ни одна
не доехала бы до пользователя): обёртка per_op заводит `__st_<oid>` под свою
SubTransaction — поэтому статус расчёта маршрута зовётся `__potstatus_<oid>`,
а не `__st_<oid>`; и у точечной нагрузки ДВА вектора в одном блоке post, так
что имя переменной чтения несёт КЛЮЧ ОБЯЗАТЕЛЬСТВА (`__vec_force_vector_<oid>`),
а не только id опа.

ГЛАВНОЕ ОБ ЭТОМ ФАЙЛЕ — ЧЕМ ЗДЕСЬ ЧИТАЮТ РЕЗУЛЬТАТ.

Четыре операции и ни одной проверки «сеттер отработал»:

* `create_point_load` — `Point`, `ForceVector`, `MomentVector`, `OrientTo`,
  `LoadCaseId`, `GetTypeId()`. Все шесть — свойства ПОСТРОЕННОГО элемента.
* `create_line_load` — то же плюс `StartPoint`/`EndPoint` вместо точки и
  `IsUniform` вместо момента.
* `create_area_load` — `GetLoops()`, то есть НАСТОЯЩИЕ рёбра построенной
  нагрузки, повершинно и с числом вершин; площадь Revit выводит из них сам и
  обязательством не является (см. ops_analysis.py).
* `create_path_of_travel` — `PathStart`/`PathEnd`/`GetCurves()`/`OwnerViewId`
  плюс типизированный статус расчёта ДО постусловий.

ДОПУСК ГЕОМЕТРИИ НЕ ЖИВЁТ НИ В РЕЕСТРЕ, НИ В C#. Точки сравниваются с
`doc.Application.VertexTolerance`, прочитанным у работающего приложения, —
приём `create_dimension` (09.08). Поэтому во ВНУТРЕННИХ единицах (футах):
переводить обе стороны в миллиметры значило бы сравнивать миллиметры с
допуском в футах. Ожидаемое число едет в C# как `U(<мм>)`, то есть его
переводит тот же Revit.

ПОЧЕМУ ОЖИДАЕМЫЕ ЗНАЧЕНИЯ ВЫПИСЫВАЮТСЯ В post ЗАНОВО, а не берутся из
переменных create: `per_op` заворачивает create в собственную область
видимости, и переменная оттуда в post — это CS0103 на машине пользователя
(контракт областей, `tests/test_emitter_scope_contract.py`). Ожидание —
литералы, и это правильно ещё и по смыслу: свидетель обязан сверять с тем,
что ПРОСИЛИ, а не с тем, что эмиттер сам себе положил в переменную.
"""
from __future__ import annotations

import math

from kukai.ir.authoring import (
    _gid, _eid, _cs, _safe, _pt3, _annot_view_res, _stamp_block,
    _stamp_readback, EMIT_UNSUPPORTED,
)
from kukai.ir.emit_model import WitnessCheck, tolerance
from kukai.ir.emit_utils import cs_line_comment_fragment, refuse_stmt
from kukai.ir.diag import Diagnostic, KirRefusal


def _si(value: float, unit: str) -> str:
    """Значение СИ -> внутренние единицы Revit, ЕГО ЖЕ средствами.

    Ни одного коэффициента в этом пакете: внутреннюю единицу силы знает
    `UnitUtils`, и спросить его дешевле, чем помнить число, которое Autodesk
    нигде не обещала не менять. Помощника-обёртки (`double FN(double)`) в
    преамбуле НЕТ намеренно — преамбула общая для всех программ, и её рост
    сдвинул бы замороженные байты эмиссий, которых эта волна не касается
    (`test_emit_model_byte_parity`).
    """

    return f"UnitUtils.ConvertToInternalUnits({value}, UnitTypeId.{unit})"


def _si_vec(values: tuple, unit: str) -> str:
    return (f"new XYZ({_si(values[0], unit)}, {_si(values[1], unit)}, "
            f"{_si(values[2], unit)})")

#: Нагрузка, у которой И сила, И момент нулевые. Autodesk документирует на
#: этот случай `ArgumentsInconsistentException` внутри транзакции; отказать
#: СТАТИЧЕСКИ дешевле и честнее — рантайм-исключение внутри транзакции
#: выглядит как наш дефект, а это ошибка автора, и назвать её надо ей самой.
#: Ремень поверх подтяжек в том же смысле, что FOUNDATION_UNSUPPORTED_KIND у
#: волны каркаса: границы отдельных чисел реестр уже держит, а вот «все шесть
#: нулевые одновременно» не выражается границей ни одного из них.
# E012, А НЕ E007 (10.08.2026). `KIR-E007` носили ПЯТЬ имён, и четыре из них
# — одна мысль: «значение закрытого перечня здесь не поддержано». Это имя ей
# НЕ родня: нагрузка нулевой величины — не неподдержанный перечень, а
# бессмысленное число, и ремонт у неё другой (задать величину, а не выбрать
# другой вариант). Остальные четыре остаются долгом, названным в
# `diag.CODES_WITH_KNOWN_ALIASES`.
ANALYSIS_ZERO_LOAD = "KIR-E012"

#: Первая версия Revit, на которой свободной (нехостированной) нагрузки в API
#: БОЛЬШЕ НЕТ. Замер, а не память: на 2024/2025/2026 перегрузки
#: PointLoad/LineLoad/AreaLoad без `ElementId hostElemId` дают CS1503/CS1501
#: против эталонных сборок. Число живёт ЗДЕСЬ одно на три операции, потому что
#: граница у них общая и разъехаться ей нельзя.
_FREE_LOAD_LAST_VER = "2023"

_LOAD_VERSION_MSG = (
    "свободная (нехостированная) нагрузка не создаётся на Revit {ver}: "
    "перегрузки {api} без носителя убраны из API в 2024 — замерено "
    "компиляцией против эталонных сборок. Все оставшиеся перегрузки требуют "
    "ElementId аналитического элемента-носителя, которого нет ни в снимке "
    "модели, ни в языке ссылок KIR; передать InvalidElementId компилятор "
    "может, но Autodesk документирует на этот аргумент ArgumentException "
    "«hostElemId is not permitted for this type of load» и нигде не обещает, "
    "что недействительный id означает «без носителя» — догадка о поведении "
    "здесь была бы тем же изобретением, что выдуманный допуск"
)


def _version_guard(ver: str, oid: str, api: str) -> None:
    """Типизированный KIR-E003 на 2024-2026 — ДО разбора чего бы то ни было.

    Отказ, а не развилка эмиссии: развилки нет по построению. Единственные
    альтернативы — построить нагрузку на чужом носителе (другой элемент) или
    не построить ничего и промолчать; обе читаются снаружи как успех.
    """
    if ver > _FREE_LOAD_LAST_VER:
        raise KirRefusal([Diagnostic(
            code=EMIT_UNSUPPORTED, op_id=oid, field_name=None,
            message_ru=_LOAD_VERSION_MSG.format(ver=ver, api=api))])


def _nz(op: dict, name: str) -> float:
    """Компонента вектора: ОТСУТСТВИЕ — это ноль, и ноль ставим МЫ.

    Род `num` не подставляет умолчаний (`validate` кладёт в норму только то,
    что автор написал), поэтому отсутствующая компонента сюда не доезжает
    вовсе. Ноль здесь — не догадка о намерении, а наше собственное действие:
    мы передаём его в API и потому ИМЕЕМ ПРАВО его засвидетельствовать (закон
    «либо значение ставит эмиттер, либо его решает Revit» —
    tests/test_silent_defaults.py).
    """
    value = op.get(name)
    return 0.0 if value is None else float(value)


def _zero_guard(op: dict, oid: str, names: tuple[str, ...]) -> None:
    if all(_nz(op, name) == 0.0 for name in names):
        raise KirRefusal([Diagnostic(
            code=ANALYSIS_ZERO_LOAD, op_id=oid, field_name=names[0],
            message_ru=("нагрузка нулевая по всем компонентам — Revit отвергнет "
                        "её внутри транзакции (ArgumentsInconsistentException); "
                        f"задайте хотя бы одну из {', '.join(names)}"))])


def _load_type_cs(op: dict, s: str, oid: str, ver: str, cs_class: str,
                  human: str, isolation: str) -> tuple[str, str]:
    """Разрешение типа нагрузки в `__ty_<s>` + C#-выражение его id.

    Ветки doc_default здесь НЕТ и быть не может: `ElementTypeGroup` не
    содержит ни `PointLoadType`, ни `LineLoadType`, ни `AreaLoadType` —
    спросить документ «твой тип нагрузки по умолчанию» невозможно по
    построению, ровно как у двери и ограждения. Пропущенный селектор
    разрешает ground.py общим правилом «единственный в пуле, иначе
    типизированный вопрос».
    """
    g = _gid(op, "load_type")
    idx = _eid(g["id"], ver, oid)
    res = (f"{cs_class} __ty_{s} = doc.GetElement({idx}) as {cs_class};\n"
           f"if (__ty_{s} == null) {{ "
           f"{refuse_stmt(oid, _cs(human + ': тип не найден (модель изменилась после grounding)'), isolation)} }}")
    return res, _cs(str(g["id"]))


def _load_case_cs(op: dict, s: str, oid: str, ver: str,
                  isolation: str) -> tuple[str, str]:
    g = _gid(op, "load_case")
    idx = _eid(g["id"], ver, oid)
    res = (f"Autodesk.Revit.DB.Structure.LoadCase __lc_{s} = "
           f"doc.GetElement({idx}) as Autodesk.Revit.DB.Structure.LoadCase;\n"
           f"if (__lc_{s} == null) {{ "
           f"{refuse_stmt(oid, _cs('случай загружения не найден (модель изменилась после grounding)'), isolation)} }}")
    return res, _cs(str(g["id"]))


#: Пришпиливание системы отсчёта + повторная запись вектора В НЕЙ.
#: Порядок обязателен: сначала система, потом числа (см. ops_analysis.py).
def _orient_and_set_cs(s: str, oid: str, isolation: str, vec_prop: str,
                       vec_expr: str, extra: str = "") -> str:
    lo = "Autodesk.Revit.DB.Structure.LoadOrientTo"
    return (
        f"if (!__el_{s}.IsOrientToPermitted({lo}.Project)) {{ "
        f"{refuse_stmt(oid, _cs('нагрузка не допускает проектную систему отсчёта'), isolation)} }}\n"
        f"__el_{s}.OrientTo = {lo}.Project;\n"
        f"__el_{s}.{vec_prop} = {vec_expr};\n"
        + extra)


def _orient_witness(s: str, oid: str) -> WitnessCheck:
    """`OrientTo` ПОСТРОЕННОГО элемента == Project.

    Не украшение и не проверка сеттера: `ForceVector` документирован как
    «oriented according to OrientTo setting», то есть без этого факта три
    числа вектора не значат ничего определённого. Свидетель силы ниже опирается
    на этот, а не наоборот.
    """
    lo = "Autodesk.Revit.DB.Structure.LoadOrientTo"
    return WitnessCheck(
        obligation_key="orientation",
        reader_cs="",
        verdict_cs=(
            f"    if (__el_{s}.OrientTo != {lo}.Project)\n"
            f"        __post.Add({_cs(oid + ': OrientTo построенной нагрузки не Project — вектор силы прочитан бы в другой системе отсчёта (semantic)')});\n"),
        message="OrientTo построенной нагрузки не Project (semantic)",
        style="guard")


def _vector_witness(s: str, oid: str, prop: str, unit: str, values: tuple,
                    tol, human: str, *, key: str) -> WitnessCheck:
    """Три компоненты вектора построенного элемента против заказанных, в СИ.

    Перевод из внутренних единиц делает сам Revit
    (`UnitUtils.ConvertFromInternalUnits`), поэтому в C# нет ни одного
    коэффициента, который мог бы разойтись с тем, которым мы писали.
    """
    fx, fy, fz = values
    # Имя переменной несёт КЛЮЧ ОБЯЗАТЕЛЬСТВА, а не только id опа: у точечной
    # нагрузки два вектора в ОДНОМ блоке post (сила и момент), и общее имя
    # `__vec_<oid>` дало бы CS0128 на машине пользователя. Поймано воротами
    # Roslyn на первом же прогоне — ровно то, ради чего они и стоят.
    var = f"__vec_{key}_{s}"
    return WitnessCheck(
        obligation_key=key,
        reader_cs=f"    var {var} = __el_{s}.{prop};\n",
        verdict_cs=(
            f"    if (Math.Abs(UnitUtils.ConvertFromInternalUnits({var}.X, UnitTypeId.{unit}) - ({fx})) > {tol.cs} ||\n"
            f"        Math.Abs(UnitUtils.ConvertFromInternalUnits({var}.Y, UnitTypeId.{unit}) - ({fy})) > {tol.cs} ||\n"
            f"        Math.Abs(UnitUtils.ConvertFromInternalUnits({var}.Z, UnitTypeId.{unit}) - ({fz})) > {tol.cs})\n"
            f"        __post.Add({_cs(oid + f': {human} построенной нагрузки не совпал с заказанным (semantic)')});\n"),
        message=f"{human} mismatch (semantic)",
        tol=tol,
        style="guard")


def _load_case_witness(s: str, oid: str, id_expr: str) -> WitnessCheck:
    return WitnessCheck(
        obligation_key="load_case",
        reader_cs=f"    var __lcid_{s} = __el_{s}.LoadCaseId;\n",
        verdict_cs=(
            f"    if (__lcid_{s} == null || __lcid_{s}.ToString() != {id_expr})\n"
            f"        __post.Add({_cs(oid + ': случай загружения построенной нагрузки не тот, что заземлён (semantic)')});\n"),
        message="load case mismatch (semantic)",
        style="guard")


def _load_type_witness(s: str, oid: str, id_expr: str) -> WitnessCheck:
    """`GetTypeId()` построенного элемента == заземлённый тип (semantic).

    `ToString()` — единственная форма сравнения id, безопасная на всех шести
    версиях (`.Value` живёт с 2024, `.IntegerValue` умирает после 2025).
    """
    return WitnessCheck(
        obligation_key="load_type",
        reader_cs=f"    var __tyid_{s} = __el_{s}.GetTypeId();\n",
        verdict_cs=(
            f"    if (__tyid_{s} == null || __tyid_{s}.ToString() != {id_expr})\n"
            f"        __post.Add({_cs(oid + ': load_type построенной нагрузки не тот, что заземлён (semantic)')});\n"),
        message="load_type mismatch (semantic)",
        style="guard")


def _load_readback(s: str, oid: str, stamp: str, extra: str = "") -> str:
    """Квитанция нагрузки: то, что ПРОЧИТАНО у построенного элемента.

    Сюда едут и величины, обязательствами не являющиеся (площадь у площадной
    нагрузки, имя случая загружения): квитанция — это наблюдение, а не
    обещание, и путать эти две вещи запрещено (`_stamp_readback` не эхает
    штамп, который мы лишь пытались записать, по той же причине).
    """
    return (
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n"
        f"    var __rb = new Dictionary<string, object>();\n"
        f"    __rb[\"id\"] = __el_{s}.Id.ToString();\n"
        + _stamp_readback(f"__el_{s}") +
        f"    try {{ __rb[\"load_case_name\"] = __el_{s}.LoadCaseName; }} catch {{ }}\n"
        f"    try {{ __rb[\"load_nature_name\"] = __el_{s}.LoadNatureName; }} catch {{ }}\n"
        f"    try {{ __rb[\"orient_to\"] = __el_{s}.OrientTo.ToString(); }} catch {{ }}\n"
        f"    try {{ __rb[\"is_hosted\"] = __el_{s}.IsHosted; }} catch {{ }}\n"
        f"    try {{ var __tid = __el_{s}.GetTypeId();\n"
        f"        if (__tid != null && __tid != ElementId.InvalidElementId) {{\n"
        f"            var __te = doc.GetElement(__tid);\n"
        f"            if (__te != null && __te.Name != null) __rb[\"type_name\"] = __te.Name;\n"
        f"        }} }} catch {{ }}\n"
        + extra +
        f"    __results[{_cs(oid)}] = __rb;\n}}")


# ── create_point_load ────────────────────────────────────────────────────────

def emit_point_load(op: dict, ver: str, stamp: str,
                    isolation: str = "atomic") -> tuple[str, str, list, str]:
    """PointLoad.Create(doc, XYZ, XYZ force, XYZ moment, PointLoadType, SketchPlane).

    Рабочая плоскость СТРОИТСЯ ЗДЕСЬ, горизонтальная, через саму точку
    нагрузки. Аргумент допускает `null` («use default plane»), и вот почему
    он тут не `null`: умолчание — рабочая плоскость АКТИВНОГО ВИДА, то есть
    вход, которого в программе нет и который на машине пользователя нам
    неизвестен. Отметка нагрузки зависела бы от того, какую вкладку человек
    открыл последней. Со своей плоскостью `Point` обязан совпасть с
    заказанной точкой — и свидетель этого требует.
    """
    oid = op["id"]
    s = _safe(oid)
    _version_guard(ver, oid, "PointLoad.Create")
    _zero_guard(op, oid, ("fx_n", "fy_n", "fz_n", "mx_nm", "my_nm", "mz_nm"))
    x, y, z = _pt3(op["xyz"])
    f = (_nz(op, "fx_n"), _nz(op, "fy_n"), _nz(op, "fz_n"))
    m = (_nz(op, "mx_nm"), _nz(op, "my_nm"), _nz(op, "mz_nm"))
    ty_res, ty_idexpr = _load_type_cs(
        op, s, oid, ver, "Autodesk.Revit.DB.Structure.PointLoadType",
        "точечная нагрузка", isolation)
    lc_res, lc_idexpr = _load_case_cs(op, s, oid, ver, isolation)
    fvec = _si_vec(f, "Newtons")
    mvec = _si_vec(m, "NewtonMeters")
    decl = f"Autodesk.Revit.DB.Structure.PointLoad __el_{s} = null;"
    create = (
        f"// create_point_load {cs_line_comment_fragment(oid)}\n"
        f"{ty_res}\n{lc_res}\n"
        f"SketchPlane __sp_{s} = SketchPlane.Create(doc, "
        f"Plane.CreateByNormalAndOrigin(XYZ.BasisZ, P({x}, {y}, {z})));\n"
        f"if (__sp_{s} == null) {{ "
        f"{refuse_stmt(oid, _cs('не удалось построить рабочую плоскость точечной нагрузки'), isolation)} }}\n"
        f"__el_{s} = Autodesk.Revit.DB.Structure.PointLoad.Create(doc, "
        f"P({x}, {y}, {z}), {fvec}, {mvec}, __ty_{s}, __sp_{s});\n"
        f"if (__el_{s} == null) {{ "
        f"{refuse_stmt(oid, _cs('PointLoad.Create вернул null'), isolation)} }}\n"
        + _orient_and_set_cs(
            s, oid, isolation, "ForceVector", fvec,
            extra=(f"__el_{s}.MomentVector = {mvec};\n"
                   f"__el_{s}.LoadCaseId = __lc_{s}.Id;\n"))
        + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))
    checks: list[WitnessCheck] = [
        WitnessCheck(
            obligation_key="position",
            reader_cs=(f"    var __pt_{s} = __el_{s}.Point;\n"
                       f"    double __vtol_{s} = doc.Application.VertexTolerance;\n"),
            verdict_cs=(
                f"    if (__pt_{s} == null\n"
                f"        || Math.Abs(__pt_{s}.X - U({x})) > __vtol_{s}\n"
                f"        || Math.Abs(__pt_{s}.Y - U({y})) > __vtol_{s}\n"
                f"        || Math.Abs(__pt_{s}.Z - U({z})) > __vtol_{s})\n"
                f"        __post.Add({_cs(oid + ': Point построенной нагрузки не совпал с заказанной точкой (geometry)')});\n"),
            message="point mismatch (geometry)",
            style="guard"),
        _orient_witness(s, oid),
        _vector_witness(s, oid, "ForceVector", "Newtons", f,
                        tolerance("create_point_load", "force_n"),
                        "вектор силы", key="force_vector"),
        _vector_witness(s, oid, "MomentVector", "NewtonMeters", m,
                        tolerance("create_point_load", "moment_nm"),
                        "вектор момента", key="moment_vector"),
        _load_case_witness(s, oid, lc_idexpr),
        _load_type_witness(s, oid, ty_idexpr),
    ]
    return decl, create, checks, _load_readback(s, oid, stamp)


# ── create_line_load ─────────────────────────────────────────────────────────

def _plane_normal(p0: tuple, p1: tuple) -> tuple[float, float, float]:
    """Нормаль рабочей плоскости, СОДЕРЖАЩЕЙ отрезок нагрузки.

    Правило детерминированное и вычисляется ЗДЕСЬ, в питоне, чтобы в C# ехали
    литералы (тот же приём, что у дуг CONTOUR):

      * концы на одной отметке -> плоскость горизонтальная (нормаль Z);
      * иначе -> ВЕРТИКАЛЬНАЯ плоскость через отрезок: её нормаль
        перпендикулярна и направлению отрезка, и вертикали, то есть
        `normalize(cross(d, Z))`;
      * отрезок строго вертикальный (обе горизонтальные проекции нулевые) ->
        `cross(d, Z)` вырождается, и любая вертикальная плоскость содержит
        отрезок; берём нормаль X — выбор произволен, но НАЗВАН, а не случаен,
        и на положение нагрузки не влияет: оба конца пришпилены свидетелем.
    """
    dx, dy, dz = p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]
    if dz == 0.0:
        return (0.0, 0.0, 1.0)
    nx, ny = dy, -dx
    norm = math.hypot(nx, ny)
    if norm == 0.0:
        return (1.0, 0.0, 0.0)
    return (nx / norm, ny / norm, 0.0)


def emit_line_load(op: dict, ver: str, stamp: str,
                   isolation: str = "atomic") -> tuple[str, str, list, str]:
    """LineLoad.Create(doc, XYZ start, XYZ end, XYZ force, XYZ moment,
    LineLoadType, SketchPlane).

    МОМЕНТ ПЕРЕДАЁТСЯ НУЛЁМ И СВИДЕТЕЛЬСТВУЕТСЯ НЕ ЗДЕСЬ. Аргумент
    обязателен, крутящей погонной нагрузки у операции нет (названный пробел,
    ops_analysis.py), а ноль в любых единицах ноль — поэтому вопрос о единице
    момента на метр здесь не возникает и выдумывать её не приходится.
    """
    oid = op["id"]
    s = _safe(oid)
    _version_guard(ver, oid, "LineLoad.Create")
    _zero_guard(op, oid, ("fx_n_per_m", "fy_n_per_m", "fz_n_per_m"))
    p0 = _pt3(op["p0_mm"])
    p1 = _pt3(op["p1_mm"])
    f = (_nz(op, "fx_n_per_m"), _nz(op, "fy_n_per_m"), _nz(op, "fz_n_per_m"))
    nx, ny, nz = _plane_normal(p0, p1)
    ty_res, ty_idexpr = _load_type_cs(
        op, s, oid, ver, "Autodesk.Revit.DB.Structure.LineLoadType",
        "линейная нагрузка", isolation)
    lc_res, lc_idexpr = _load_case_cs(op, s, oid, ver, isolation)
    fvec = _si_vec(f, "NewtonsPerMeter")
    decl = f"Autodesk.Revit.DB.Structure.LineLoad __el_{s} = null;"
    create = (
        f"// create_line_load {cs_line_comment_fragment(oid)}\n"
        f"{ty_res}\n{lc_res}\n"
        f"SketchPlane __sp_{s} = SketchPlane.Create(doc, "
        f"Plane.CreateByNormalAndOrigin(new XYZ({nx}, {ny}, {nz}), "
        f"P({p0[0]}, {p0[1]}, {p0[2]})));\n"
        f"if (__sp_{s} == null) {{ "
        f"{refuse_stmt(oid, _cs('не удалось построить рабочую плоскость линейной нагрузки'), isolation)} }}\n"
        f"__el_{s} = Autodesk.Revit.DB.Structure.LineLoad.Create(doc, "
        f"P({p0[0]}, {p0[1]}, {p0[2]}), P({p1[0]}, {p1[1]}, {p1[2]}), "
        f"{fvec}, new XYZ(0, 0, 0), __ty_{s}, __sp_{s});\n"
        f"if (__el_{s} == null) {{ "
        f"{refuse_stmt(oid, _cs('LineLoad.Create вернул null'), isolation)} }}\n"
        + _orient_and_set_cs(
            s, oid, isolation, "ForceVector1", fvec,
            extra=f"__el_{s}.LoadCaseId = __lc_{s}.Id;\n")
        + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))
    checks: list[WitnessCheck] = [
        WitnessCheck(
            obligation_key="endpoints",
            reader_cs=(f"    var __sp0_{s} = __el_{s}.StartPoint;\n"
                       f"    var __sp1_{s} = __el_{s}.EndPoint;\n"
                       f"    double __vtol_{s} = doc.Application.VertexTolerance;\n"),
            # КОНЦЫ СВЕРЯЮТСЯ СТРОГО ПО МЕСТАМ, а не «ближайший к ближайшему»,
            # как у линейных MEP-опов. Причина содержательная: у трубы ось
            # симметрична и перестановка концов ничего не меняет, а у линейной
            # нагрузки `ForceVector1` относится ИМЕННО К НАЧАЛУ, и обмен
            # концами местами — это другая нагрузка при той же геометрии.
            verdict_cs=(
                f"    if (__sp0_{s} == null || __sp1_{s} == null\n"
                f"        || Math.Abs(__sp0_{s}.X - U({p0[0]})) > __vtol_{s}\n"
                f"        || Math.Abs(__sp0_{s}.Y - U({p0[1]})) > __vtol_{s}\n"
                f"        || Math.Abs(__sp0_{s}.Z - U({p0[2]})) > __vtol_{s}\n"
                f"        || Math.Abs(__sp1_{s}.X - U({p1[0]})) > __vtol_{s}\n"
                f"        || Math.Abs(__sp1_{s}.Y - U({p1[1]})) > __vtol_{s}\n"
                f"        || Math.Abs(__sp1_{s}.Z - U({p1[2]})) > __vtol_{s})\n"
                f"        __post.Add({_cs(oid + ': StartPoint/EndPoint построенной нагрузки не совпали с заказанными (geometry)')});\n"),
            message="endpoints mismatch (geometry)",
            style="guard"),
        _orient_witness(s, oid),
        _vector_witness(s, oid, "ForceVector1", "NewtonsPerMeter", f,
                        tolerance("create_line_load", "force_n_per_m"),
                        "вектор погонной силы", key="force_vector"),
        # РАВНОМЕРНОСТЬ — ОБЕЩАНИЕ НАШЕЙ ФОРМЫ ВЫЗОВА, А НЕ УКРАШЕНИЕ.
        # Перегрузка принимает ОДИН вектор силы, то есть по документации
        # («load is uniform when force and moment vectors assigned to the
        # start and the end point are equal») построенная нагрузка обязана
        # быть равномерной. Если она не такая — это другая нагрузка при
        # правильных концах и правильном первом векторе, то есть ровно тот
        # исход, который свидетель геометрии пропустил бы.
        WitnessCheck(
            obligation_key="uniform",
            reader_cs="",
            verdict_cs=(
                f"    if (!__el_{s}.IsUniform)\n"
                f"        __post.Add({_cs(oid + ': построенная линейная нагрузка не равномерна, хотя задан один вектор силы (semantic)')});\n"),
            message="line load is not uniform (semantic)",
            style="guard"),
        _load_case_witness(s, oid, lc_idexpr),
        _load_type_witness(s, oid, ty_idexpr),
    ]
    return decl, create, checks, _load_readback(s, oid, stamp)


# ── create_area_load ─────────────────────────────────────────────────────────

def emit_area_load(op: dict, ver: str, stamp: str,
                   isolation: str = "atomic") -> tuple[str, str, list, str]:
    """AreaLoad.Create(doc, IList<CurveLoop>, XYZ force, AreaLoadType).

    Аргумента рабочей плоскости у этой перегрузки НЕТ: плоскость задают сами
    кольца. Поэтому кольцо здесь плоское и горизонтальное на `elev_mm` — и
    именно это свидетель перечитывает у построенного элемента.
    """
    oid = op["id"]
    s = _safe(oid)
    _version_guard(ver, oid, "AreaLoad.Create")
    _zero_guard(op, oid, ("fx_n_per_m2", "fy_n_per_m2", "fz_n_per_m2"))
    ring = op["outline"]
    z = op["elev_mm"]
    f = (_nz(op, "fx_n_per_m2"), _nz(op, "fy_n_per_m2"), _nz(op, "fz_n_per_m2"))
    ty_res, ty_idexpr = _load_type_cs(
        op, s, oid, ver, "Autodesk.Revit.DB.Structure.AreaLoadType",
        "площадная нагрузка", isolation)
    lc_res, lc_idexpr = _load_case_cs(op, s, oid, ver, isolation)
    fvec = _si_vec(f, "NewtonsPerSquareMeter")
    n = len(ring)
    edges = "".join(
        f"__ol_{s}.Append(Line.CreateBound("
        f"P({ring[k][0]}, {ring[k][1]}, {z}), "
        f"P({ring[(k + 1) % n][0]}, {ring[(k + 1) % n][1]}, {z})));\n"
        for k in range(n))
    decl = f"Autodesk.Revit.DB.Structure.AreaLoad __el_{s} = null;"
    create = (
        f"// create_area_load {cs_line_comment_fragment(oid)}\n"
        f"{ty_res}\n{lc_res}\n"
        f"CurveLoop __ol_{s} = new CurveLoop();\n"
        + edges +
        f"var __loops_{s} = new List<CurveLoop>();\n"
        f"__loops_{s}.Add(__ol_{s});\n"
        f"__el_{s} = Autodesk.Revit.DB.Structure.AreaLoad.Create(doc, "
        f"__loops_{s}, {fvec}, __ty_{s});\n"
        f"if (__el_{s} == null) {{ "
        f"{refuse_stmt(oid, _cs('AreaLoad.Create вернул null'), isolation)} }}\n"
        + _orient_and_set_cs(
            s, oid, isolation, "ForceVector1", fvec,
            extra=f"__el_{s}.LoadCaseId = __lc_{s}.Id;\n")
        + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))
    expected = ", ".join(f"{c}" for pt in ring for c in (pt[0], pt[1]))
    checks: list[WitnessCheck] = [
        WitnessCheck(
            obligation_key="loop_vertices",
            reader_cs=(f"    var __lps_{s} = __el_{s}.GetLoops();\n"
                       f"    double __vtol_{s} = doc.Application.VertexTolerance;\n"),
            # ДВА ДИАГНОЗА ВРОЗЬ. Число колец/вершин и их положение — разные
            # причины: Revit канонизирует кольцо (начальная вершина и
            # направление обхода — его дело), поэтому позиционное сравнение
            # обвиняло бы правильную нагрузку. Сверка идёт МНОЖЕСТВОМ: каждая
            # заказанная вершина обязана найтись среди возвращённых, и число
            # вершин обязано совпасть — вместе это исключает и лишнюю, и
            # потерянную, и сдвинутую.
            verdict_cs=(
                f"    if (__lps_{s} == null || __lps_{s}.Count != 1)\n"
                f"        __post.Add({_cs(oid + ': GetLoops построенной нагрузки вернул не одно кольцо (geometry)')});\n"
                f"    else\n    {{\n"
                f"        var __vs_{s} = new List<XYZ>();\n"
                f"        foreach (Curve __c_{s} in __lps_{s}[0]) __vs_{s}.Add(__c_{s}.GetEndPoint(0));\n"
                f"        double[] __ex_{s} = new double[] {{ {expected} }};\n"
                f"        bool __bad_{s} = __vs_{s}.Count != {n};\n"
                f"        for (int __i = 0; __i < {n} && !__bad_{s}; __i++)\n"
                f"        {{\n"
                f"            bool __hit = false;\n"
                f"            for (int __j = 0; __j < __vs_{s}.Count; __j++)\n"
                f"                if (Math.Abs(__vs_{s}[__j].X - U(__ex_{s}[__i * 2])) <= __vtol_{s}\n"
                f"                    && Math.Abs(__vs_{s}[__j].Y - U(__ex_{s}[__i * 2 + 1])) <= __vtol_{s}\n"
                f"                    && Math.Abs(__vs_{s}[__j].Z - U({z})) <= __vtol_{s})\n"
                f"                    __hit = true;\n"
                f"            if (!__hit) __bad_{s} = true;\n"
                f"        }}\n"
                f"        if (__bad_{s}) __post.Add({_cs(oid + ': вершины кольца построенной нагрузки не совпали с заказанным контуром на отметке elev_mm (geometry)')});\n"
                f"    }}\n"),
            message="loop vertices mismatch (geometry)",
            style="else_block"),
        _orient_witness(s, oid),
        _vector_witness(s, oid, "ForceVector1", "NewtonsPerSquareMeter", f,
                        tolerance("create_area_load", "force_n_per_m2"),
                        "вектор площадной силы", key="force_vector"),
        _load_case_witness(s, oid, lc_idexpr),
        _load_type_witness(s, oid, ty_idexpr),
    ]
    # Площадь — НАБЛЮДЕНИЕ, а не обещание: Revit выводит её из тех же колец,
    # что свидетель уже пришпилил повершинно. Отдельное обязательство на неё
    # потребовало бы второго, площадного допуска ради следствия уже
    # доказанного факта — то есть числа, которого вывести неоткуда.
    area_rb = (f"    try {{ __rb[\"area_m2\"] = Math.Round("
               f"UnitUtils.ConvertFromInternalUnits(__el_{s}.Area, "
               f"UnitTypeId.SquareMeters), 3); }} catch {{ }}\n")
    return decl, create, checks, _load_readback(s, oid, stamp, extra=area_rb)


# ── create_path_of_travel ────────────────────────────────────────────────────

def emit_path_of_travel(op: dict, ver: str, stamp: str,
                        isolation: str = "atomic") -> tuple[str, str, list, str]:
    """Analysis.PathOfTravel.Create(View, XYZ, XYZ, out PathOfTravelCalculationStatus).

    ПЕРЕГРУЗКА СО СТАТУСОМ ВЗЯТА НАМЕРЕННО. Без неё `null` означал бы сразу
    несколько разных вещей («маршрута нет», «точки слишком близко», «вид
    подрезан», «слишком много геометрии»), и отказ назвал бы следствие вместо
    причины. Перечисление `PathOfTravelCalculationStatus` одинаково на всех
    шести версиях (12 членов, сверено поимённо), поэтому статус едет в текст
    отказа как есть.

    СТАТУС ПРОВЕРЯЕТСЯ В create, А НЕ В post, и это не вкусовщина: `Success`
    — предусловие осмысленности всего дальнейшего. `ResultAffectedByCrop`,
    например, вернёт ЭЛЕМЕНТ с маршрутом, посчитанным по подрезанному виду,
    то есть заведомо не тот маршрут; постусловие о длине он бы прошёл.
    """
    oid = op["id"]
    s = _safe(oid)
    ns = "Autodesk.Revit.DB.Analysis"
    x0, y0, _ = _pt3(op["p0_mm"])
    x1, y1, _ = _pt3(op["p1_mm"])
    # Прямая между заказанными точками — В ПЛАНЕ, потому что третью координату
    # API отбрасывает по документации. Число вычислено ЗДЕСЬ и едет литералом
    # в миллиметрах, а в C# переводится тем же `U()`, что и сами точки.
    straight_mm = math.hypot(x1 - x0, y1 - y0)
    # `__vw_<s>` и `__vp_<s>` объявлены в decl, а не заведены в create: тела
    # create заворачиваются в собственную область видимости при изоляции
    # per_op, и объявление оттуда — CS0103 на машине пользователя
    # (`tests/test_emitter_scope_contract.py`). Здесь их читает только create,
    # но правило этого файла — объявлять в decl всё, что переживает шов.
    decl = (f"{ns}.PathOfTravel __el_{s} = null;\n"
            f"View __vw_{s} = null;\n"
            f"ViewPlan __vp_{s} = null;")
    create = (
        f"// create_path_of_travel {cs_line_comment_fragment(oid)}\n"
        # ВИД РЕЗОЛВИТСЯ ТЕМ ЖЕ ПОМОЩНИКОМ, ЧТО У АННОТАЦИЙ, а не своим: он
        # уже отказывает типизированно на `by=ref` (ни один оп KIR не создаёт
        # View, поэтому `as View` там — гарантированный CS0039, замер 28.07) и
        # уже проверяет, что id резолвится ИМЕННО в вид. Своя копия разошлась
        # бы с ним на первой же правке.
        + _annot_view_res(op, s, ver, oid, isolation) + "\n"
        f"__vp_{s} = __vw_{s} as ViewPlan;\n"
        f"if (__vp_{s} == null || __vp_{s}.IsTemplate "
        f"|| __vp_{s}.ViewType != ViewType.FloorPlan) {{ "
        f"{refuse_stmt(oid, _cs('in_view не план этажа — PathOfTravel.Create принимает только вид в плане (документировано ArgumentException «View is not a floor plan view»)'), isolation)} }}\n"
        f"{ns}.PathOfTravelCalculationStatus __potstatus_{s};\n"
        f"__el_{s} = {ns}.PathOfTravel.Create(__vp_{s}, "
        f"P({x0}, {y0}, 0), P({x1}, {y1}, 0), out __potstatus_{s});\n"
        f"if (__el_{s} == null) {{ "
        f"{refuse_stmt(oid, _cs('маршрут между заданными точками не найден, статус расчёта: ') + f' + __potstatus_{s}.ToString()', isolation)} }}\n"
        f"if (__potstatus_{s} != {ns}.PathOfTravelCalculationStatus.Success) {{ "
        f"{refuse_stmt(oid, _cs('расчёт маршрута завершился не успехом, статус: ') + f' + __potstatus_{s}.ToString()', isolation)} }}\n"
        + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))
    # `by=ref` сюда не доезжает: `_annot_view_res` отказал бы выше. Значит
    # ожидаемый id вида — литерал, и это ровно то, что нужно свидетелю:
    # сравнивать надо с тем, что ПРОСИЛИ, а не с переменной, которую эмиттер
    # сам себе положил (и которой в области видимости post уже нет).
    view_id_expr = _cs(str(op["in_view"]["value"]))
    checks: list[WitnessCheck] = [
        WitnessCheck(
            obligation_key="endpoints",
            reader_cs=(f"    var __ps_{s} = __el_{s}.PathStart;\n"
                       f"    var __pe_{s} = __el_{s}.PathEnd;\n"
                       f"    double __vtol_{s} = doc.Application.VertexTolerance;\n"),
            # Z НЕ СВЕРЯЕТСЯ ПО ДОКУМЕНТАЦИИ, А НЕ ИЗ СНИСХОДИТЕЛЬНОСТИ:
            # «The input Z coordinates are ignored and set to the view's level
            # elevation». Сверять её значило бы требовать от Revit того, чего
            # он прямо обещает не делать, — и откатывать правильный маршрут.
            verdict_cs=(
                f"    if (__ps_{s} == null || __pe_{s} == null\n"
                f"        || Math.Abs(__ps_{s}.X - U({x0})) > __vtol_{s}\n"
                f"        || Math.Abs(__ps_{s}.Y - U({y0})) > __vtol_{s}\n"
                f"        || Math.Abs(__pe_{s}.X - U({x1})) > __vtol_{s}\n"
                f"        || Math.Abs(__pe_{s}.Y - U({y1})) > __vtol_{s})\n"
                f"        __post.Add({_cs(oid + ': PathStart/PathEnd построенного маршрута не совпали с заданными точками в плане (geometry)')});\n"),
            message="path endpoints mismatch (geometry)",
            style="guard"),
        WitnessCheck(
            obligation_key="route",
            reader_cs=(f"    var __cvs_{s} = __el_{s}.GetCurves();\n"
                       f"    double __len_{s} = 0.0;\n"
                       f"    if (__cvs_{s} != null)\n"
                       f"        for (int __k = 0; __k < __cvs_{s}.Count; __k++)\n"
                       f"            __len_{s} += __cvs_{s}[__k].Length;\n"),
            # ЧТО ЗДЕСЬ УТВЕРЖДАЕТСЯ, А ЧТО НЕТ. Форму маршрута считает Revit
            # по препятствиям вида, и «обошёл ли он их правильно» проверить
            # нечем: независимой модели препятствий у нас нет, а сравнивать
            # вывод Revit с выводом Revit бессмысленно. Проверяются два факта,
            # которые от его расчёта НЕ ЗАВИСЯТ: маршрут существует как
            # геометрия (пустой список кривых при зелёном статусе — элемент
            # без содержания), и он не короче прямой между собственными
            # концами. Второе — геометрически невозможное состояние, то есть
            # настоящий отказ; равенство здесь было бы выдумкой.
            verdict_cs=(
                f"    if (__cvs_{s} == null || __cvs_{s}.Count < 1)\n"
                f"        __post.Add({_cs(oid + ': маршрут построен без единой кривой (geometry)')});\n"
                f"    else if (__len_{s} < U({straight_mm}) - __vtol_{s})\n"
                f"        __post.Add({_cs(oid + ': длина построенного маршрута меньше прямой между заданными точками (geometry)')});\n"),
            message="route is empty or shorter than the straight line (geometry)",
            style="guard"),
        WitnessCheck(
            obligation_key="owner_view",
            reader_cs=f"    var __ov_{s} = __el_{s}.OwnerViewId;\n",
            verdict_cs=(
                f"    if (__ov_{s} == null || __ov_{s}.ToString() != {view_id_expr})\n"
                f"        __post.Add({_cs(oid + ': построенный маршрут принадлежит не заказанному виду (topology)')});\n"),
            message="owner view mismatch (topology)",
            style="guard"),
    ]
    readback = (
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n"
        f"    var __rb = new Dictionary<string, object>();\n"
        f"    __rb[\"id\"] = __el_{s}.Id.ToString();\n"
        + _stamp_readback(f"__el_{s}") +
        f"    try {{ __rb[\"start_mm\"] = new double[] {{ "
        f"Math.Round(MM(__el_{s}.PathStart.X), 1), "
        f"Math.Round(MM(__el_{s}.PathStart.Y), 1), "
        f"Math.Round(MM(__el_{s}.PathStart.Z), 1) }}; }} catch {{ }}\n"
        f"    try {{ __rb[\"end_mm\"] = new double[] {{ "
        f"Math.Round(MM(__el_{s}.PathEnd.X), 1), "
        f"Math.Round(MM(__el_{s}.PathEnd.Y), 1), "
        f"Math.Round(MM(__el_{s}.PathEnd.Z), 1) }}; }} catch {{ }}\n"
        f"    try {{ var __rbc = __el_{s}.GetCurves();\n"
        f"        double __rbl = 0.0;\n"
        f"        if (__rbc != null)\n"
        f"            for (int __q = 0; __q < __rbc.Count; __q++) __rbl += __rbc[__q].Length;\n"
        f"        __rb[\"segments\"] = __rbc == null ? 0 : __rbc.Count;\n"
        f"        __rb[\"length_mm\"] = Math.Round(MM(__rbl), 1);\n"
        f"    }} catch {{ }}\n"
        f"    try {{ __rb[\"view_id\"] = __el_{s}.OwnerViewId.ToString(); }} catch {{ }}\n"
        f"    __results[{_cs(oid)}] = __rb;\n}}")
    return decl, create, checks, readback
