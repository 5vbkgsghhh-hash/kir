"""mep_emit — эмиссия волны ЭОМ/гибких/заготовок (парный файл к ops_mep.py,
ровно как arch_emit.py к ops_arch.py и struct_emit.py к ops_struct.py).

Своя зона волны: модуль не трогает ops_authoring.py, ops_struct.py, ops_arch.py,
connect.py, contour.py и ни один другой ops_*.py. authoring.py получает
АДДИТИВНО импорт и пять строк в `_EMITTERS` — тот же минимальный шов, которым
подключились волны каркаса и архитектуры.

Переиспользовано из authoring.py БЕЗ ИЗМЕНЕНИЙ (импортом, не копией): `_gid`,
`_eid`, `_cs`, `_safe`, `_pt3`, `_level_expr`, `_stamp_block`,
`_stamp_readback`, `_readback_block`, плюс ПУБЛИЧНЫЕ модели свидетелей
`endpoint_witness` и `level_binding_witness`. Оговорка та же, что у
struct_emit.py: часть имён приватные, и лечится это повышением их до публичных
в authoring.py, а не копированием тел сюда.

ГЛАВНОЕ ОБ ЭТОМ ФАЙЛЕ — ЧЕМ ЗДЕСЬ ЧИТАЮТ РЕЗУЛЬТАТ.

Пять операций, четыре разных способа перечитать построенное, и ни один из них
не «проверить, что сеттер отработал»:

* `create_conduit` — ось `LocationCurve` (её считает Revit, а не мы) + уровень
  через `RBS_START_LEVEL_PARAM` + ТИП через `GetTypeId()`. Тип сверяется
  потому, что `Conduit.Create` документировано принимает `InvalidElementId` и
  в этом случае МОЛЧА подставляет тип документа по умолчанию: единственная
  операция волны, у которой API сам предлагает тихую подмену.
* `create_pipe_placeholder` / `create_duct_placeholder` — то же плюс
  `IsPlaceholder`. Это ВЕСЬ содержательный остаток заготовки: без него
  операция неотличима от обычной трубы, и «заготовка» была бы словом в
  журнале, а не фактом в модели.
* `create_flex_duct` / `create_flex_pipe` — `Points`, то есть ВЕСЬ путь
  целиком, с числом точек и порядком. Концов здесь недостаточно по существу:
  выброшенная середина оставила бы концы на месте, и трасса поехала бы при
  зелёном вердикте.

ЗАЧЕМ ОЖИДАЕМЫЙ ПУТЬ ВЫПИСЫВАЕТСЯ В post ЗАНОВО, а не берётся из `List<XYZ>`,
собранного в create: `per_op` заворачивает create в собственную область
видимости, и переменная оттуда в post — это CS0103 на машине пользователя
(контракт областей, `tests/test_emitter_scope_contract.py`). Ожидание —
литералы, и это правильно ещё и по смыслу: свидетель обязан сверять с тем, что
ПРОСИЛИ, а не с тем, что эмиттер сам себе положил в переменную.
"""
from __future__ import annotations

from kukai.ir.authoring import (
    _gid, _eid, _cs, _safe, _pt3, _level_expr, _stamp_block, _stamp_readback,
    _readback_block, endpoint_witness, level_binding_witness,
)
from kukai.ir.emit_model import WitnessCheck, tolerances
from kukai.ir.emit_utils import cs_line_comment_fragment, refuse_stmt


def _type_witness(el_var: str, oid: str, type_id_expr: str, human: str,
                  *, key: str) -> WitnessCheck:
    """`GetTypeId()` построенного элемента == заземлённый тип (semantic).

    Читается РЕЗУЛЬТАТ: `Element.GetTypeId()` возвращает тип, который несёт
    созданный элемент, а не аргумент, который мы передали. `ToString()` —
    единственная форма сравнения id, безопасная на всех шести версиях
    (`.Value` живёт с 2024, `.IntegerValue` умирает после 2025).
    """

    return WitnessCheck(
        obligation_key=key,
        reader_cs=f"    var __ty = {el_var}.GetTypeId();\n",
        verdict_cs=(
            f"    if (__ty == null || __ty.ToString() != {type_id_expr})\n"
            f"        __post.Add({_cs(oid + f': {human} mismatch (semantic)')});\n"),
        message=f"{human} mismatch (semantic)",
        style="guard")


def _emit_conduit(op: dict, ver: str, stamp: str,
                  isolation: str = "atomic") -> tuple:
    """Electrical.Conduit.Create(Document, conduitTypeId, XYZ, XYZ, levelId).

    ПОРЯДОК АРГУМЕНТОВ КАК У ЛОТКА, А НЕ КАК У ТРУБЫ: уровень идёт ПОСЛЕДНИМ,
    после обеих точек. Подпись снята с эталонных сборок и скомпилирована на
    2021-2026 до написания этой строки.
    """
    oid = op["id"]
    s = _safe(oid)
    ct = _gid(op, "conduit_type")
    x0, y0, z0 = _pt3(op["p0_mm"])
    x1, y1, z1 = _pt3(op["p1_mm"])
    decl = f"Autodesk.Revit.DB.Electrical.Conduit __el_{s} = null;"
    lv_res, lv_idexpr = _level_expr(op, s, ver, oid, isolation)
    create = (
        f"// create_conduit {cs_line_comment_fragment(oid)}\n"
        + lv_res + "\n"
        f"__el_{s} = Autodesk.Revit.DB.Electrical.Conduit.Create(doc, "
        f"{_eid(ct['id'], ver, oid)}, "
        f"P({x0}, {y0}, {z0}), P({x1}, {y1}, {z1}), __lv_{s}.Id);\n"
        f"if (__el_{s} == null) {{ {refuse_stmt(oid, _cs('Conduit.Create вернул null'), isolation)} }}\n"
        + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))
    checks: list[WitnessCheck] = [
        endpoint_witness(
            f"__el_{s}", oid, op["p0_mm"], op["p1_mm"],
            tolerances("create_conduit")["endpoint_mm"], True),
        level_binding_witness(
            f"__el_{s}", oid, "RBS_START_LEVEL_PARAM", lv_idexpr,
            key="reference_level"),
        _type_witness(f"__el_{s}", oid, _cs(str(ct["id"])), "conduit type",
                      key="conduit_type"),
    ]
    return decl, create, checks, _readback_block(s, oid, stamp)


def _emit_placeholder(op: dict, ver: str, stamp: str, isolation: str,
                      *, op_name: str, cs_class: str, type_param: str,
                      human_type: str, human_ru: str) -> tuple:
    """Общее тело `Pipe.CreatePlaceholder` / `Duct.CreatePlaceholder`.

    ОДНА реализация на две операции намеренно: подписи различаются ровно
    пространством имён и именем параметра типа, а свидетели совпадают
    буква в букву. Две копии разошлись бы на первой же правке — тот самый
    класс, из-за которого `route_mep` не копировал `connect`, а параметризовал
    его.
    """
    oid = op["id"]
    s = _safe(oid)
    st = _gid(op, "system_type")
    tt = _gid(op, type_param)
    x0, y0, z0 = _pt3(op["p0_mm"])
    x1, y1, z1 = _pt3(op["p1_mm"])
    decl = f"{cs_class} __el_{s} = null;"
    lv_res, lv_idexpr = _level_expr(op, s, ver, oid, isolation)
    create = (
        f"// {op_name} {cs_line_comment_fragment(oid)}\n"
        + lv_res + "\n"
        f"__el_{s} = {cs_class}.CreatePlaceholder(doc, "
        f"{_eid(st['id'], ver, oid)}, {_eid(tt['id'], ver, oid)}, "
        f"__lv_{s}.Id, P({x0}, {y0}, {z0}), P({x1}, {y1}, {z1}));\n"
        f"if (__el_{s} == null) {{ "
        f"{refuse_stmt(oid, _cs(f'{human_ru} вернул null'), isolation)} }}\n"
        + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))
    checks: list[WitnessCheck] = [
        endpoint_witness(
            f"__el_{s}", oid, op["p0_mm"], op["p1_mm"],
            tolerances(op_name)["endpoint_mm"], True),
        level_binding_witness(
            f"__el_{s}", oid, "RBS_START_LEVEL_PARAM", lv_idexpr,
            key="reference_level"),
        # Единственный бит, отличающий заготовку от обычного участка, и
        # поэтому единственный, ради которого операция вообще существует.
        # Читается СВОЙСТВО ПОСТРОЕННОГО ЭЛЕМЕНТА (Pipe.IsPlaceholder /
        # Duct.IsPlaceholder, обе есть на 2021-2026), а не аргумент вызова.
        WitnessCheck(
            obligation_key="is_placeholder",
            reader_cs="",
            verdict_cs=(
                f"    if (!__el_{s}.IsPlaceholder)\n"
                f"        __post.Add({_cs(oid + ': созданный элемент не заготовка (semantic)')});\n"),
            message="созданный элемент не заготовка (semantic)",
            style="guard"),
        _type_witness(f"__el_{s}", oid, _cs(str(tt["id"])), human_type,
                      key=type_param),
    ]
    return decl, create, checks, _readback_block(s, oid, stamp)


def _emit_pipe_placeholder(op: dict, ver: str, stamp: str,
                           isolation: str = "atomic") -> tuple:
    return _emit_placeholder(
        op, ver, stamp, isolation,
        op_name="create_pipe_placeholder",
        cs_class="Autodesk.Revit.DB.Plumbing.Pipe",
        type_param="pipe_type", human_type="pipe type",
        human_ru="Pipe.CreatePlaceholder")


def _emit_duct_placeholder(op: dict, ver: str, stamp: str,
                           isolation: str = "atomic") -> tuple:
    return _emit_placeholder(
        op, ver, stamp, isolation,
        op_name="create_duct_placeholder",
        cs_class="Autodesk.Revit.DB.Mechanical.Duct",
        type_param="duct_type", human_type="duct type",
        human_ru="Duct.CreatePlaceholder")


def _flex_readback(s: str, oid: str, stamp: str) -> str:
    """Квитанция гибкого участка: ВЕСЬ путь, а не пара концов.

    Общий `_readback_block` читает `Location as LocationCurve`; у гибкого
    элемента там сплайн Эрмита, и его концы — производная от точек. В
    квитанцию едет первичное: `Points` как плоский массив мм.
    """
    return (
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n"
        f"    var __rb = new Dictionary<string, object>();\n"
        f"    __rb[\"id\"] = __el_{s}.Id.ToString();\n"
        + _stamp_readback(f"__el_{s}") +
        f"    try {{ var __pp2 = __el_{s}.Points;\n"
        f"        if (__pp2 != null) {{\n"
        f"            var __path = new List<double[]>();\n"
        f"            for (int __k = 0; __k < __pp2.Count; __k++)\n"
        f"                __path.Add(new double[] {{ Math.Round(MM(__pp2[__k].X), 1), "
        f"Math.Round(MM(__pp2[__k].Y), 1), Math.Round(MM(__pp2[__k].Z), 1) }});\n"
        f"            __rb[\"path_mm\"] = __path;\n"
        f"        }} }} catch {{ }}\n"
        f"    try {{ var __tid = __el_{s}.GetTypeId();\n"
        f"        if (__tid != null && __tid != ElementId.InvalidElementId) {{\n"
        f"            var __te = doc.GetElement(__tid);\n"
        f"            if (__te != null && __te.Name != null) __rb[\"type_name\"] = __te.Name;\n"
        f"        }} }} catch {{ }}\n"
        f"    __results[{_cs(oid)}] = __rb;\n}}")


def _emit_flex(op: dict, ver: str, stamp: str, isolation: str,
               *, op_name: str, cs_class: str, type_param: str,
               human_type: str, human_ru: str) -> tuple:
    """Общее тело `FlexDuct.Create` / `FlexPipe.Create` (перегрузка без
    касательных: Document, systemTypeId, typeId, levelId, IList<XYZ>).

    Перегрузка с касательными существует на всех шести версиях и НЕ
    используется: касательная — это направление входа в трассу, у операции
    такого входа нет, а подставить «разумную» значило бы построить изгиб,
    которого автор не просил. Autodesk пишет, что нулевой/неверный вектор
    игнорируется, то есть честного нейтрального значения у аргумента нет —
    он либо несёт замысел, либо не должен передаваться вовсе.
    """
    oid = op["id"]
    s = _safe(oid)
    st = _gid(op, "system_type")
    tt = _gid(op, type_param)
    path = op["path"]
    tol = tolerances(op_name)["point_mm"]
    decl = f"{cs_class} __el_{s} = null;"
    lv_res, lv_idexpr = _level_expr(op, s, ver, oid, isolation)
    pts_cs = "".join(
        f"__pts_{s}.Add(P({pt[0]}, {pt[1]}, {pt[2]}));\n" for pt in path)
    create = (
        f"// {op_name} {cs_line_comment_fragment(oid)}\n"
        + lv_res + "\n"
        f"var __pts_{s} = new List<XYZ>();\n"
        + pts_cs +
        f"__el_{s} = {cs_class}.Create(doc, {_eid(st['id'], ver, oid)}, "
        f"{_eid(tt['id'], ver, oid)}, __lv_{s}.Id, __pts_{s});\n"
        f"if (__el_{s} == null) {{ "
        f"{refuse_stmt(oid, _cs(f'{human_ru} вернул null'), isolation)} }}\n"
        + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))
    expected = ", ".join(f"{c}" for pt in path for c in (pt[0], pt[1], pt[2]))
    n = len(path)
    checks: list[WitnessCheck] = [
        WitnessCheck(
            obligation_key="path_points",
            reader_cs=f"    var __pp = __el_{s}.Points;\n",
            # ДВА СЛУЧАЯ ВРОЗЬ, а не один. Число точек и их положение —
            # разные диагнозы: Autodesk документирует, что совпадающие точки
            # ВЫБРАСЫВАЮТСЯ («duplicate points don't take into account»), и
            # такой путь вернулся бы короче заказанного. Одно слово
            # «geometry mismatch» на оба случая назвало бы следствие вместо
            # причины — цена этой экономии уже измерена на диаметре
            # прямоугольного воздуховода (30.07, Snowdon).
            verdict_cs=(
                f"    if (__pp == null || __pp.Count != {n})\n"
                f"        __post.Add({_cs(oid + f': flex path point count mismatch — Revit вернул другое число точек, чем {n} заказанных (geometry)')});\n"
                f"    else\n    {{\n"
                f"        double[] __ex = new double[] {{ {expected} }};\n"
                f"        bool __bad = false;\n"
                f"        for (int __i = 0; __i < {n}; __i++)\n"
                f"        {{\n"
                f"            var __q = __pp[__i];\n"
                f"            if (Math.Abs(MM(__q.X) - __ex[__i * 3]) > {tol} ||\n"
                f"                Math.Abs(MM(__q.Y) - __ex[__i * 3 + 1]) > {tol} ||\n"
                f"                Math.Abs(MM(__q.Z) - __ex[__i * 3 + 2]) > {tol})\n"
                f"                __bad = true;\n"
                f"        }}\n"
                f"        if (__bad) __post.Add({_cs(oid + ': flex path points mismatch (geometry)')});\n"
                f"    }}\n"),
            message="flex path points mismatch (geometry)",
            tol=tol,
            style="else_block"),
        level_binding_witness(
            f"__el_{s}", oid, "RBS_START_LEVEL_PARAM", lv_idexpr,
            key="reference_level"),
        _type_witness(f"__el_{s}", oid, _cs(str(tt["id"])), human_type,
                      key=type_param),
    ]
    return decl, create, checks, _flex_readback(s, oid, stamp)


def _emit_flex_duct(op: dict, ver: str, stamp: str,
                    isolation: str = "atomic") -> tuple:
    return _emit_flex(
        op, ver, stamp, isolation,
        op_name="create_flex_duct",
        cs_class="Autodesk.Revit.DB.Mechanical.FlexDuct",
        type_param="flex_duct_type", human_type="flex duct type",
        human_ru="FlexDuct.Create")


def _emit_flex_pipe(op: dict, ver: str, stamp: str,
                    isolation: str = "atomic") -> tuple:
    return _emit_flex(
        op, ver, stamp, isolation,
        op_name="create_flex_pipe",
        cs_class="Autodesk.Revit.DB.Plumbing.FlexPipe",
        type_param="flex_pipe_type", human_type="flex pipe type",
        human_ru="FlexPipe.Create")
