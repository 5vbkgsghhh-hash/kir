"""solid_emit — эмиссия параметрических тел (парный файл к ops_solid.py).

Своя зона волны: этот модуль не трогает ни один другой `*_emit.py`.
authoring.py получает аддитивно импорт и две строки в `_EMITTERS` — тот же
минимальный шов, которым подключились волны каркаса, АР и меша.

Переиспользовано БЕЗ ИЗМЕНЕНИЙ (импортом, не копией): `_cs`, `_safe`,
`_stamp_block`, `_stamp_readback` из authoring.py; `emit_loop_cs` и меры
региона — из contour.py; `refuse_stmt` — из emit_utils (единственный владелец
формы отказа). Разбор ЗАЧЕМ этой волны, замер API 6/6 и список того, что
отказано с причиной, — в шапке ops_solid.py.

═══ ЧТО ЗДЕСЬ ЛЮБОПЫТНОГО В САМОЙ ЭМИССИИ ═════════════════════════════════

1. ЕДИНИЦЫ. `U(мм)` и `MM(фут)` линейны и без сдвига, поэтому их КОМПОЗИЦИЯ
   переводит площади и объёмы: `MM(MM(1.0))` — фут² в мм², `MM(MM(MM(1.0)))` —
   фут³ в мм³. Это точно и не заводит третьего дома для 304.8 (первые два —
   `U` и `MM`, оба уже в шапке программы). Выглядит непривычно, поэтому
   сказано прямо здесь: тройная композиция — НЕ опечатка, а куб масштаба.

2. ГЕОМЕТРИЯ ПЛОСКОСТИ ВРАЩЕНИЯ. `emit_loop_cs` печатает контур в плоскости
   XY (это ЗАКРЕПЛЁННОЕ решение CONTOUR, и трогать его волна не вправе).
   Revit же требует профиль вращения в плоскости XZ рамки. Переход делает
   ОДНО преобразование `CurveLoop.CreateViaTransform` (6/6) с базисом
   X=(1,0,0), Y=(0,0,1), Z=(0,-1,0) — правая тройка, отображающая (u,v,0) в
   (ось.x+u, ось.y, base_z+v). Свой второй эмиттер контура означал бы вторую
   дугoвую арифметику.

3. ИСКЛЮЧЕНИЕ ФАБРИКИ НЕ ЛОВИТСЯ. `CreateExtrusionGeometry` бросает
   `Autodesk.Revit.Exceptions.ApplicationException` на негодном профиле, и
   поймать его здесь было бы соблазнительно ради красивого текста. Но закон
   дома (`__KirOpRefusal` — ТИП, у отказа Revit-а свой catch) гласит: сбой
   Revit API записывается как `internal`, а не как решение компилятора.
   Перехват превратил бы чужую поломку в наш «отказ» — и снаружи это
   выглядело бы как принятое нами решение.

═══ ДОПУСК СВИДЕТЕЛЯ И ЗАПРЕТ ВАКУУМНОСТИ ═════════════════════════════════

Число допуска считается В РАНТАЙМЕ из собственного числа Revit:

    double __dt = MM(doc.Application.VertexTolerance) + EMIT_COORD_QUANTUM_MM;

и умножается на геометрию: на площадь поверхности — для объёма, на длину
границ торцов — для площади торцов. Вывод — в шапке ops_solid.py.

Рядом с каждым таким свидетелем эмитируется РАНТАЙМ-ОТКАЗ вакуумности:
допуск, не меньший измеряемой величины, означает проверку, которая не может
провалиться, и оп обязан отказать названно. Порог — не выбранное число, а
определение: `допуск >= величина`.
"""
from __future__ import annotations

import math

from kukai.ir import contour as C
from kukai.ir.authoring import _cs, _safe, _stamp_block, _stamp_readback
from kukai.ir.diag import Diagnostic, KirRefusal, TYPE_GEOM_RELATION
from kukai.ir.emit_model import WitnessCheck
from kukai.ir.emit_utils import cs_line_comment_fragment, refuse_stmt
from kukai.ir.ops_shape import DIRECTSHAPE_CATEGORIES

#: Та же честная этикетка, что у меша, с названным отличием: тело
#: параметрическое, но BIM-смысла у него ровно столько же — нисколько.
HONEST_MARK = ("KIR Solid: параметрическое тело без BIM-смысла "
               "(нет типа/параметров)")

#: Косинусный порог «нормаль грани параллельна/перпендикулярна оси Z».
#:
#: РАЗДЕЛЕНИЕ ЗДЕСЬ ТОЧНОЕ ПО ПОСТРОЕНИЮ, А НЕ ПРИБЛИЖЁННОЕ, и это стоит
#: сказать явно, иначе порог читается как подобранный на глаз:
#:
#:  * у ПРИЗМЫ торцы лежат в плоскости профиля (все точки контура печатаются
#:    с ОДНОЙ и той же координатой z), значит их нормаль — ровно ±Z; боковые
#:    грани содержат направление выдавливания, то есть саму ось Z, значит их
#:    нормаль имеет ровно нулевую Z-компоненту. Округление координат в плане
#:    ни ту, ни другую величину не трогает вовсе;
#:  * у ТЕЛА ВРАЩЕНИЯ торцы сектора — плоскости, содержащие ось, значит их
#:    нормаль ⊥ Z точно; горизонтальное ребро профиля даёт плоское кольцо с
#:    нормалью ∥ Z точно; наклонное ребро даёт конус, а он не `PlanarFace` и
#:    в сумму не попадает по типу.
#:
#: То есть математически величина равна РОВНО 0 либо РОВНО 1, и порог нужен
#: только чтобы поглотить арифметику двойной точности, которой Revit считает
#: нормаль. 1e-6 — примерно десять миллионов машинных эпсилон: с запасом от
#: шума и всё ещё в миллион раз строже любого осмысленного наклона грани.
_AXIS_COS_EPS = 1e-6


def _n(value: float) -> str:
    """Число в C#-литерал двойной точности БЕЗ потери значащих цифр.

    ``repr`` питона даёт кратчайшую строку, которая читается обратно в ТОТ ЖЕ
    double. Округлять ожидаемый объём «для красоты» нельзя: это ровно то
    место, где свидетель сравнивает с эталоном, и потерянная цифра стала бы
    погрешностью, которую никто не выводил.
    """
    return repr(float(value))


def _loops_cs(region: dict, s: str) -> str:
    """C# сборки колец региона — наружного и всех проёмов.

    Кольца строит `contour.emit_loop_cs` БЕЗ ИЗМЕНЕНИЙ: дуговая арифметика
    в пакете живёт в одном месте, и второй её дом стал бы вторым ответом на
    один вопрос.
    """
    parts = [C.emit_loop_cs(region["outer"], f"__ol_{s}")]
    for hi, hole in enumerate(region["holes"]):
        parts.append(C.emit_loop_cs(hole, f"__hl_{s}_{hi}"))
    return "\n".join(parts)


def _transform_cs(region: dict, s: str, transform_expr: str | None) -> str:
    """Список CurveLoop, при необходимости прогнанный через преобразование."""
    names = [f"__ol_{s}"] + [f"__hl_{s}_{i}" for i in range(len(region["holes"]))]
    out = [f"IList<CurveLoop> __lps_{s} = new List<CurveLoop>();"]
    for nm in names:
        if transform_expr is None:
            out.append(f"__lps_{s}.Add({nm});")
        else:
            out.append(f"__lps_{s}.Add(CurveLoop.CreateViaTransform({nm}, {transform_expr}));")
    return "\n".join(out)


def _shell_cs(s: str, oid: str, member: str, name: str, stamp: str,
              isolation: str) -> tuple[str, str, str]:
    """Общая для обеих операций оболочка DirectShape (объявления, создание).

    ОДНА оболочка на два опа, потому что она и есть один и тот же факт: тело
    кладётся в DirectShape, у DirectShape нет типа, и честная этикетка едет в
    Mark ровно тогда, когда поле свободно. Две копии этого кода разъехались
    бы на первой правке текста этикетки.

    ВСЁ, ЧТО ЧИТАЮТ ПОСТУСЛОВИЕ И КВИТАНЦИЯ, ОБЪЯВЛЕНО ЗДЕСЬ — включая сами
    ЧИСЛА ДОПУСКОВ. При isolation="per_op" блок создания заворачивается в
    свою область видимости, и переменная, объявленная внутри него, свидетелю
    не видна (CS0103 — тот самый шов, на котором падала первая версия
    эмиттера ограждений). Допуск считается в create, но живёт в decl.

    """
    decl = (f"DirectShape __el_{s} = null;\n"
            f"Solid __sol_{s} = null;\n"
            f"bool __lbl_{s} = false;\n"
            f"int __nsol_{s} = 0;\n"
            f"double __rvol_{s} = 0.0;\n"
            f"double __rcap_{s} = 0.0;\n"
            f"double __dt_{s} = 0.0;\n"
            f"double __tvol_{s} = 0.0;\n"
            f"double __tcap_{s} = 0.0;")
    head = (
        f"ElementId __cat_{s} = new ElementId(BuiltInCategory.{member});\n"
        # Категория проверяется У ДОКУМЕНТА, а не по нашей таблице: она может
        # быть выключена шаблоном проекта, и тогда CreateElement вернёт null
        # уже после того, как мы решили, что всё хорошо.
        f"if (!DirectShape.IsValidCategoryId(__cat_{s}, doc)) {{ "
        f"{refuse_stmt(oid, _cs('категория недопустима для DirectShape в этом документе'), isolation)} }}")
    tail = (
        f"if (__sol_{s} == null || __sol_{s}.Faces.Size == 0) {{ "
        f"{refuse_stmt(oid, _cs('Revit не построил тело из этого профиля (пустой Solid)'), isolation)} }}\n"
        f"__el_{s} = DirectShape.CreateElement(doc, __cat_{s});\n"
        f"if (__el_{s} == null) {{ "
        f"{refuse_stmt(oid, _cs('создание DirectShape вернуло null'), isolation)} }}\n"
        f"IList<GeometryObject> __gos_{s} = new List<GeometryObject>();\n"
        f"__gos_{s}.Add(__sol_{s});\n"
        f"__el_{s}.SetShape(__gos_{s});\n"
        f"__el_{s}.Name = {_cs(name)};\n"
        # get_Parameter вернёт null, если параметра нет — тогда этикетки просто
        # не будет, и квитанция скажет об этом честно (false), а не промолчит.
        # Непустое чужое значение не трогаем никогда.
        f"Parameter __mk_{s} = __el_{s}.get_Parameter(BuiltInParameter.ALL_MODEL_MARK);\n"
        f"if (__mk_{s} != null && !__mk_{s}.IsReadOnly && "
        f"string.IsNullOrEmpty(__mk_{s}.AsString()))\n"
        f"    __lbl_{s} = __mk_{s}.Set({_cs(HONEST_MARK)});\n"
        + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))
    return decl, head, tail


def _derived_tolerances_cs(s: str, oid: str, isolation: str, *,
                           surface_mm2: float, min_feature_vol_mm3: float,
                           cap_boundary_mm: float,
                           min_feature_cap_mm2: float) -> str:
    """Допуски свидетелей + рантайм-запрет вакуумности.

    См. шапку и шапку ops_solid.py: δ = собственный `VertexTolerance` Revit
    плюс квант нашей эмиссии; допуск объёма = δ·(площадь поверхности); допуск
    площади торцов = δ·(длина границ торцов). Оба ВЫВЕДЕНЫ из геометрии
    этого опа, поэтому и живут в эмиссии, а не в реестре констант.
    """
    out = [
        f"__dt_{s} = MM(doc.Application.VertexTolerance) + "
        f"{_n(C.EMIT_COORD_QUANTUM_MM)};",
        f"__tvol_{s} = {_n(surface_mm2)} * __dt_{s};",
        # ВАКУУМНОСТЬ — ОПРЕДЕЛЕНИЕ, А НЕ ВКУС: допуск, не меньший самой
        # мелкой объявленной величины, означает, что её исчезновение прошло бы
        # незамеченным. Такой свидетель хуже отсутствующего, поэтому здесь
        # названный отказ, а не подпись.
        f"if (__tvol_{s} >= {_n(min_feature_vol_mm3)}) {{ "
        + refuse_stmt(
            oid,
            _cs('допуск объёмного свидетеля не меньше самой мелкой объявленной '
                'части профиля — проверка не смогла бы провалиться; тело '
                'слишком тонкое или проём слишком мелкий для честной сверки'),
            isolation) + " }",
    ]
    out += [
        f"__tcap_{s} = {_n(cap_boundary_mm)} * __dt_{s};",
        f"if (__tcap_{s} >= {_n(min_feature_cap_mm2)}) {{ "
        + refuse_stmt(
            oid,
            _cs('допуск свидетеля торцов не меньше самой мелкой объявленной '
                'части профиля — проверка не смогла бы провалиться'),
            isolation) + " }",
    ]
    return "\n".join(out)


def _read_solids_cs(s: str) -> str:
    """Читатель ПОСТРОЕННОЙ геометрии: суммы по настоящим телам элемента.

    Читается РЕЗУЛЬТАТ, а не наш вызов: `get_Geometry` возвращает то, что
    Revit реально положил в элемент. `GeometryInstance` разворачивается —
    DirectShape в принципе вправе отдать геометрию завёрнутой, и свидетель,
    который этого не умеет, увидел бы НОЛЬ тел и обвинил бы Revit в том, чего
    тот не делал.
    """
    return (
        f"    var __ge_{s} = __el_{s}.get_Geometry(new Options());\n"
        f"    if (__ge_{s} != null)\n    {{\n"
        f"        foreach (GeometryObject __go_{s} in __ge_{s})\n        {{\n"
        f"            Solid __so_{s} = __go_{s} as Solid;\n"
        f"            if (__so_{s} != null && __so_{s}.Faces.Size > 0)\n"
        f"            {{ __nsol_{s}++; __rvol_{s} += __so_{s}.Volume; }}\n"
        f"            GeometryInstance __gi_{s} = __go_{s} as GeometryInstance;\n"
        f"            if (__gi_{s} != null)\n"
        f"                foreach (GeometryObject __g2_{s} in __gi_{s}.GetInstanceGeometry())\n"
        f"                {{\n"
        f"                    Solid __s2_{s} = __g2_{s} as Solid;\n"
        f"                    if (__s2_{s} != null && __s2_{s}.Faces.Size > 0)\n"
        f"                    {{ __nsol_{s}++; __rvol_{s} += __s2_{s}.Volume; }}\n"
        f"                }}\n"
        f"        }}\n    }}\n")


def _cap_reader_cs(s: str, axis_parallel: bool) -> str:
    """Сумма площадей ПЛОСКИХ граней, чья нормаль задана относительно оси Z.

    ``axis_parallel=True``  — торцы призмы (нормаль ∥ Z);
    ``axis_parallel=False`` — торцы сектора вращения (нормаль ⊥ Z).

    Кривых поверхностей эта сумма не касается ВОВСЕ — именно поэтому она
    свободна от документированной оговорки Autodesk о систематическом
    занижении площади кривых граней (разбор — в шапке ops_solid.py).
    """
    cond = (f"Math.Abs(__pf_{s}.FaceNormal.Z) > {_n(1.0 - _AXIS_COS_EPS)}"
            if axis_parallel
            else f"Math.Abs(__pf_{s}.FaceNormal.Z) < {_n(_AXIS_COS_EPS)}")
    return (
        f"    if (__sol_{s} != null)\n"
        f"        foreach (Face __f_{s} in __sol_{s}.Faces)\n        {{\n"
        f"            PlanarFace __pf_{s} = __f_{s} as PlanarFace;\n"
        f"            if (__pf_{s} != null && {cond})\n"
        f"                __rcap_{s} += MM(MM(__pf_{s}.Area));\n"
        f"        }}\n")


def _solid_count_check(s: str, oid: str) -> WitnessCheck:
    return WitnessCheck(
        obligation_key="solid_count",
        reader_cs=_read_solids_cs(s),
        verdict_cs=(
            f"    if (__nsol_{s} != 1)\n"
            f"        __post.Add({_cs(oid + ': built geometry does not hold exactly one solid (geometry)')});\n"),
        message="built geometry does not hold exactly one solid (geometry)",
        style="guard")


def _volume_check(s: str, oid: str, expected_mm3: float) -> WitnessCheck:
    # ОБЪЁМ ЗНАКОВЫЙ (RevitAPI.xml: «Returns the signed volume»). Модуль здесь
    # НЕ берётся: вывернутое тело — это не «почти то же самое», и молчаливое
    # Math.Abs сделало бы неизвестное поведение невидимым.
    return WitnessCheck(
        obligation_key="volume",
        reader_cs=f"    double __vmm_{s} = __rvol_{s} * MM(MM(MM(1.0)));\n",
        verdict_cs=(
            f"    if (Math.Abs(__vmm_{s} - {_n(expected_mm3)}) > __tvol_{s})\n"
            f"        __post.Add({_cs(oid + ': solid volume mismatch (geometry)')});\n"),
        message="solid volume mismatch (geometry)",
        style="guard")


def _cap_area_check(s: str, oid: str, expected_mm2: float,
                    axis_parallel: bool) -> WitnessCheck:
    return WitnessCheck(
        obligation_key="cap_area",
        reader_cs=_cap_reader_cs(s, axis_parallel),
        verdict_cs=(
            f"    if (Math.Abs(__rcap_{s} - {_n(expected_mm2)}) > __tcap_{s})\n"
            f"        __post.Add({_cs(oid + ': planar cap area mismatch (geometry)')});\n"),
        message="planar cap area mismatch (geometry)",
        style="guard")


def _bbox_check(s: str, oid: str, box: tuple, reader_cs: str) -> WitnessCheck:
    """Сверка габарита. ЧИТАТЕЛЬ ПРИХОДИТ ОТ ЭМИТТЕРА, а не строится здесь:
    какой ЭЛЕМЕНТ и какой ЕГО габарит считать телом операции — решение опа, а
    не общей сверки; здесь живёт только сравнение с выведенным эталоном."""
    x0, y0, z0, x1, y1, z1 = box
    return WitnessCheck(
        obligation_key="bbox",
        reader_cs=reader_cs,
        verdict_cs=(
            f"    if (__bb_{s} == null) __post.Add({_cs(oid + ': нет BoundingBox')});\n"
            f"    else if (Math.Abs(MM(__bb_{s}.Min.X) - {_n(x0)}) > __dt_{s} || "
            f"Math.Abs(MM(__bb_{s}.Max.X) - {_n(x1)}) > __dt_{s} ||\n"
            f"             Math.Abs(MM(__bb_{s}.Min.Y) - {_n(y0)}) > __dt_{s} || "
            f"Math.Abs(MM(__bb_{s}.Max.Y) - {_n(y1)}) > __dt_{s} ||\n"
            f"             Math.Abs(MM(__bb_{s}.Min.Z) - {_n(z0)}) > __dt_{s} || "
            f"Math.Abs(MM(__bb_{s}.Max.Z) - {_n(z1)}) > __dt_{s})\n"
            f"        __post.Add({_cs(oid + ': bbox extents mismatch (geometry)')});\n"),
        message="bbox extents mismatch (geometry)",
        style="else_block")


def _readback(s: str, oid: str, kind: str, op: dict, expected: dict) -> str:
    """Квитанция. Своя, а не `_readback_block`: общий блок сообщает
    LocationCurve и type_name, которых у DirectShape нет ПО ПОСТРОЕНИЮ.

    СЫРАЯ ПАРА (ожидание/замер) едет НАРУЖУ намеренно: остаток собственной
    погрешности `Solid.Volume` на кривых поверхностях нигде не документирован,
    и первый живой прогон обязан его ИЗМЕРИТЬ, а не оценить. Без этих двух
    чисел в квитанции измерять было бы нечем.
    """
    lines = [
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n",
        f"    var __rb = new Dictionary<string, object>();\n",
        f"    __rb[\"id\"] = __el_{s}.Id.ToString();\n",
        f"    __rb[\"name\"] = __el_{s}.Name;\n",
        f"    __rb[\"category\"] = {_cs(op['category'])};\n",
        f"    __rb[\"kind\"] = {_cs(kind)};\n",
        f"    __rb[\"solids\"] = __nsol_{s};\n",
        f"    __rb[\"volume_mm3_expected\"] = {_n(expected['volume_mm3'])};\n",
        f"    __rb[\"volume_mm3_measured\"] = __rvol_{s} * MM(MM(MM(1.0)));\n",
        f"    __rb[\"volume_tolerance_mm3\"] = __tvol_{s};\n",
        f"    __rb[\"profile_area_mm2\"] = {_n(expected['area_mm2'])};\n",
    ]
    lines += [
        f"    __rb[\"cap_area_mm2_expected\"] = {_n(expected['cap_area_mm2'])};\n",
        f"    __rb[\"cap_area_mm2_measured\"] = __rcap_{s};\n",
        f"    __rb[\"cap_area_tolerance_mm2\"] = __tcap_{s};\n",
    ]
    if expected.get("cap_semantics"):
        lines.append(
            f"    __rb[\"cap_area_meaning\"] = {_cs(expected['cap_semantics'])};\n")
    lines += [
        f"    __rb[\"vertex_tolerance_mm\"] = MM(doc.Application.VertexTolerance);\n",
        f"    __rb[\"bim_semantics\"] = \"none\";\n",
        f"    __rb[\"has_type\"] = false;\n",
        f"    __rb[\"schedulable_as_building_element\"] = false;\n",
        f"    __rb[\"human_editable\"] = false;\n",
        f"    __rb[\"honest_label_written\"] = __lbl_{s};\n",
        f"    __rb[\"warning\"] = {_cs('Параметрическое тело в DirectShape — геометрия без BIM-смысла: у элемента нет типа и параметров, в спецификации он не попадёт как строительный элемент, и вручную его не отредактировать. Это не стена/перекрытие/кровля, даже если объём совпадает.')};\n",
        _stamp_readback(f"__el_{s}"),
        f"    __results[{_cs(oid)}] = __rb;\n}}",
    ]
    return "".join(lines)


# ── выдавливание ────────────────────────────────────────────────────────────

def emit_solid_extrusion(op: dict, ver: str, stamp: str,
                         isolation: str = "atomic") -> tuple:
    """Профиль CONTOUR + высота -> Solid -> DirectShape.

    Оси версий нет: всё, что здесь названо, замерено 6/6 (таблица — в шапке
    ops_solid.py).

    ОБЪЁМ ВЫВЕДЕН, А НЕ ИЗМЕРЕН ПРИБЛИЖЁННО. Призма над плоской областью:
    V = A·h, где A — площадь области, посчитанная интегралом Грина по границе
    в ЗАМКНУТОЙ ФОРМЕ (дуги входят точной формулой кругового сегмента, а не
    выборкой). Проёмы вычитаются точно, потому что CONTOUR уже доказал их
    строгую внутренность и попарную непересекаемость.

    ПЛОЩАДЬ ПОВЕРХНОСТИ (нужна для вывода допуска) = 2A + P·h, где P — полная
    длина границы (наружное кольцо плюс все проёмы): боковая поверхность
    призмы над кривой длины P и высоты h равна ровно P·h при любом профиле,
    включая дуговой.
    """
    oid = op["id"]
    s = _safe(oid)
    region = op["__region__"]
    member = DIRECTSHAPE_CATEGORIES[op["category"]]
    height = float(op["height_mm"])
    base_z = op.get("base_z_mm")

    m = C.region_measures(region)
    area = m["area_mm2"]
    perim = m["perimeter_mm"]
    volume = area * height
    surface = 2.0 * area + perim * height
    cap_area = 2.0 * area
    x0, y0, x1, y1 = C.region_bbox(region)
    z0 = 0.0 if base_z is None else float(base_z)

    decl, head, tail = _shell_cs(s, oid, member, op["name"], stamp, isolation)
    loops_cs = _loops_cs(region, s)
    # ОТСУТСТВИЕ ОСТАЁТСЯ ОТСУТСТВИЕМ: без `base_z_mm` не печатается ни одного
    # преобразования, и эмиссия байт-в-байт та же, что была бы без параметра.
    transform = (None if base_z is None
                 else f"Transform.CreateTranslation(new XYZ(0, 0, U({_n(base_z)})))")
    create = (
        f"// create_solid_extrusion {cs_line_comment_fragment(oid)} — "
        f"профиль {len(region['outer'])} рёбер, {len(region['holes'])} проёмов, "
        f"площадь {area:.1f} мм², объём {volume:.1f} мм³\n"
        f"{head}\n"
        f"{loops_cs}\n"
        f"{_transform_cs(region, s, transform)}\n"
        f"__sol_{s} = GeometryCreationUtilities.CreateExtrusionGeometry("
        f"__lps_{s}, XYZ.BasisZ, U({_n(height)}));\n"
        f"{tail}\n"
        f"{_derived_tolerances_cs(s, oid, isolation, surface_mm2=surface, min_feature_vol_mm3=m['min_area_mm2'] * height, cap_boundary_mm=2.0 * perim, min_feature_cap_mm2=2.0 * m['min_area_mm2'])}")

    checks = [
        _solid_count_check(s, oid),
        _volume_check(s, oid, volume),
        # Торцы призмы — ПЛОСКИЕ грани с нормалью вдоль Z, и только они:
        # боковая поверхность прямого выдавливания вертикальна по построению.
        _cap_area_check(s, oid, cap_area, axis_parallel=True),
        _bbox_check(s, oid, (x0, y0, z0, x1, y1, z0 + height),
                    f"    var __bb_{s} = __el_{s}.get_BoundingBox(null);\n"),
    ]
    readback = _readback(s, oid, "direct_shape_solid_extrusion", op, {
        "volume_mm3": volume, "area_mm2": area, "cap_area_mm2": cap_area})
    return decl, create, checks, readback


# ── вращение ────────────────────────────────────────────────────────────────

def _cos_sin_deg(deg: float) -> tuple[float, float]:
    """(cos, sin) угла В ГРАДУСАХ, ТОЧНЫЕ на кратных 90°.

    Не педантизм: угол приходит от автора в градусах, и `math.cos(math.pi/2)`
    даёт 6.1e-17, из-за чего габарит четверти оборота печатался в C# как
    `6.123233995736766e-14` вместо нуля. Число безвредно (это 6·10⁻¹⁴ мм),
    но эталон свидетеля, набранный мусором, читается как ошибка, а сравнить
    его глазом с чертежом уже нельзя. Кратные 90° известны точно — значит и
    печатать их надо точно.
    """
    quarter, rest = divmod(deg, 90.0)
    if abs(rest) < 1e-12:
        return [(1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0)][int(quarter) % 4]
    rad = math.radians(deg)
    return math.cos(rad), math.sin(rad)


def _sector_bbox(r0: float, r1: float, sweep_deg: float) -> tuple:
    """Габарит кольцевого сектора {ρ∈[r0,r1], φ∈[0,sweep]} в плане.

    ВЫВОД. Для фиксированного φ функция ρ·cos φ монотонна по ρ, значит её
    экстремум по ρ лежит на конце отрезка [r0, r1]; для фиксированного ρ
    экстремумы по φ лежат либо на концах диапазона, либо в кардинальных
    направлениях, попавших внутрь. Значит глобальные экстремумы содержатся в
    КОНЕЧНОМ наборе (два радиуса) × (концы плюс кардинальные углы), и
    перебрать его точно — то же самое, что решить задачу. Ровно тот приём,
    которым `contour.edges_bbox` берёт экстремумы дуги.
    """
    angles = [0.0, sweep_deg]
    angles += [c for c in (90.0, 180.0, 270.0) if c <= sweep_deg]
    xs, ys = [], []
    for radius in (r0, r1):
        for angle in angles:
            cos_a, sin_a = _cos_sin_deg(angle)
            xs.append(radius * cos_a)
            ys.append(radius * sin_a)
    return min(xs), min(ys), max(xs), max(ys)


def emit_solid_revolve(op: dict, ver: str, stamp: str,
                       isolation: str = "atomic") -> tuple:
    """Профиль CONTOUR, повёрнутый вокруг вертикальной оси -> DirectShape.

    ОБЪЁМ ВЫВЕДЕН ИЗ ТЕОРЕМЫ ФУБИНИ, А НЕ ВЗЯТ ИЗ СПРАВОЧНИКА. Тело вращения
    в цилиндрических координатах есть {(ρ,φ,z) : (ρ,z) ∈ Ω, φ ∈ [0,θ]}, и
    элемент объёма равен ρ·dρ·dφ·dz. Интеграл по φ отделяется:

        V = ∫₀^θ dφ ∬_Ω ρ dρ dz = θ · ∬_Ω ρ dA = θ · M

    где M = ∬x dA — первый момент профиля относительно оси. Это и есть первая
    теорема Гульдина-Паппа (V = 2π·x̄·A при θ=2π, поскольку M = x̄·A), но
    записанная так, что частичный поворот получается ТЕМ ЖЕ выводом, а не
    отдельным допущением. Условие применимости — профиль не пересекает ось —
    здесь не предположение: Revit САМ требует x ≥ 0, и мы проверяем это
    точным габаритом с учётом дуговых экстремумов, отказывая до эмиссии.

    Момент M считается интегралом по границе ∮(x²/2)dy в замкнутой форме
    (contour.edge_measures) — с дугами, с проёмами, без выборки.

    ПЛОЩАДЬ ПОВЕРХНОСТИ (для вывода допуска) — вторая теорема Паппа тем же
    рассуждением: боковая поверхность = θ·∮x ds, плюс два плоских торца
    площадью A каждый, когда поворот неполный.
    """
    oid = op["id"]
    s = _safe(oid)
    region = op["__region__"]
    member = DIRECTSHAPE_CATEGORIES[op["category"]]
    sweep_deg = float(op["sweep_deg"])
    sweep = math.radians(sweep_deg)
    axis = op["axis_xy_mm"]
    ax, ay = float(axis[0]), float(axis[1])
    base_z = op.get("base_z_mm")
    z_base = 0.0 if base_z is None else float(base_z)

    rx0, ry0, rx1, ry1 = C.region_bbox(region)
    if rx0 < 0.0:
        # ЗАКОН REVIT, А НЕ НАШ ВКУС: RevitAPI.xml, CreateRevolvedGeometry —
        # «The loops must lie on the "right" side of the z axis (where
        # x >= 0)». Профиль, пересекающий ось, дал бы либо исключение, либо —
        # что хуже — тело, к которому теорема Фубини неприменима, и объёмный
        # свидетель сравнивал бы с числом, ничего не значащим.
        raise KirRefusal([Diagnostic(
            code=TYPE_GEOM_RELATION, op_id=oid, field_name="profile",
            got=round(rx0, 2), expected=">= 0",
            message_ru=("profile: контур вращения заходит за ось "
                        f"(минимальный радиус {rx0:.1f} мм < 0). Ось — "
                        "вертикаль через axis_xy_mm, x контура есть радиус "
                        "от неё, поэтому отрицательным он быть не может"))])

    m = C.region_measures(region)
    area = m["area_mm2"]
    moment = m["moment_x_mm3"]
    volume = sweep * moment
    full_turn = sweep_deg >= 360.0
    surface = sweep * m["x_ds_mm2"] + (0.0 if full_turn else 2.0 * area)
    # ТОРЦЫ ЕСТЬ ВСЕГДА — КАК ВЕЛИЧИНА, А НЕ КАК ГРАНЬ. У сектора их площадь
    # равна удвоенной площади профиля; у ПОЛНОГО оборота торцов не должно быть
    # вовсе, и ожидаемая величина есть НОЛЬ. Второе — не «нечего проверять», а
    # содержательная проверка ЗАМКНУЛСЯ ЛИ ОБОРОТ: собери Revit вместо кольца
    # клин, и на месте нуля окажется 2·A. Условный свидетель здесь оставил бы
    # самую вероятную поломку 360° без единого читателя.
    cap_area = 0.0 if full_turn else 2.0 * area

    sx0, sy0, sx1, sy1 = _sector_bbox(rx0, rx1, sweep_deg)

    decl, head, tail = _shell_cs(s, oid, member, op["name"], stamp, isolation)
    loops_cs = _loops_cs(region, s)
    # ПЕРЕХОД ИЗ ПЛОСКОСТИ ЭСКИЗА В ПЛОСКОСТЬ ВРАЩЕНИЯ. Правая тройка
    # (X, Y, Z) = ((1,0,0), (0,0,1), (0,-1,0)) отображает (u, v, 0) в
    # (ось.x + u, ось.y, base_z + v) — то есть радиус вдоль мирового +X,
    # отметку вдоль мирового +Z, ровно как требует рамка Revit.
    transform = f"__tf_{s}"
    frame_cs = (
        f"Transform __tf_{s} = Transform.Identity;\n"
        f"__tf_{s}.Origin = P({_n(ax)}, {_n(ay)}, {_n(z_base)});\n"
        f"__tf_{s}.BasisX = new XYZ(1, 0, 0);\n"
        f"__tf_{s}.BasisY = new XYZ(0, 0, 1);\n"
        f"__tf_{s}.BasisZ = new XYZ(0, -1, 0);\n"
        f"Frame __fr_{s} = new Frame(P({_n(ax)}, {_n(ay)}, {_n(z_base)}), "
        f"new XYZ(1, 0, 0), new XYZ(0, 1, 0), new XYZ(0, 0, 1));")
    create = (
        f"// create_solid_revolve {cs_line_comment_fragment(oid)} — "
        f"профиль {len(region['outer'])} рёбер, {len(region['holes'])} проёмов, "
        f"поворот {sweep_deg:g}°, объём {volume:.1f} мм³\n"
        f"{head}\n"
        f"{loops_cs}\n"
        f"{frame_cs}\n"
        f"{_transform_cs(region, s, transform)}\n"
        f"__sol_{s} = GeometryCreationUtilities.CreateRevolvedGeometry("
        f"__fr_{s}, __lps_{s}, 0.0, {_n(sweep)});\n"
        f"{tail}\n"
        + _derived_tolerances_cs(
            s, oid, isolation,
            surface_mm2=surface,
            # Объём самой мелкой объявленной части — θ·(её момент). Момент, а
            # не «площадь × радиус»: профиль вправе КАСАТЬСЯ оси, и оценка
            # через габаритный радиус была бы оценкой сверху, то есть
            # завышенным порогом вакуумности.
            min_feature_vol_mm3=sweep * m["min_moment_x_mm3"],
            cap_boundary_mm=2.0 * m["perimeter_mm"],
            min_feature_cap_mm2=2.0 * m["min_area_mm2"]))

    checks = [
        _solid_count_check(s, oid),
        _volume_check(s, oid, volume),
        # Торцы сектора — ПЛОСКИЕ грани с нормалью, ПЕРПЕНДИКУЛЯРНОЙ оси.
        # Горизонтальное ребро профиля даёт плоское кольцо с нормалью ВДОЛЬ
        # оси — оно торцом не является, и фильтр по нормали его исключает.
        _cap_area_check(s, oid, cap_area, axis_parallel=False),
    ]
    checks.append(_bbox_check(
        s, oid,
        (ax + sx0, ay + sy0, z_base + ry0, ax + sx1, ay + sy1, z_base + ry1),
        f"    var __bb_{s} = __el_{s}.get_BoundingBox(null);\n"))

    readback = _readback(s, oid, "direct_shape_solid_revolve", op, {
        "volume_mm3": volume, "area_mm2": area, "cap_area_mm2": cap_area,
        "cap_semantics": ("полный оборот: торцов быть не должно, ожидается ноль"
                          if full_turn else
                          "сектор: два плоских торца, ожидается удвоенная "
                          "площадь профиля")})
    return decl, create, checks, readback
