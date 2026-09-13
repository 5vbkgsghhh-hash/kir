// SpatialModel extractor — read-only walk of the live Revit BIM into the checker's contract.
// Runs as the BODY of Kukai.UserCode.Execute(Document doc, UIDocument uidoc) via op_revit exec.
// Classifier-clean: no GetType/reflection/IO. Returns a Dictionary the Python wrapper normalizes
// (room.function is assigned Python-side via classify.py from room.name). All lengths -> mm.
//
// checker v2 truth-extraction (roadmap 'extract truth instead of fabricating'):
//   * rooms: real ceiling height from UpperLimit+LimitOffset when the room is bounded
//     (height_source="bounded"), else the unbounded ROOM_HEIGHT param ("param"), else null.
//     Department parameter emitted for apartment stamping.
//   * doors: host wall id emitted; the legacy is_exterior (one-side-null heuristic) is STILL
//     emitted for the v1 path, but v2's normalize() discards it — derive.py re-establishes
//     exteriority positively from envelope membership.
//   * windows: measured height (type param else instance bbox) + location point emitted;
//     area_m2 = width x MEASURED height when known (the old width x 1.4 fiction only remains
//     as the legacy fallback when no height is measurable, flagged by height_mm=null).
//   * stairs: REAL geometry from the Stairs element (ActualRiserHeight / ActualRisersNumber /
//     ActualTreadDepth / min ActualRunWidth over its runs) — null when not derivable
//     (in-place/legacy stairs). Nothing is hardcoded.
//   * walls: wall function (Interior/Exterior/...) emitted for envelope corroboration,
//     plus thickness_mm (Wall.Width) so the envelope rule can reach a room boundary on the face.
double FT = 304.8;       // feet -> mm
double FT2 = 0.092903;   // ft^2 -> m^2

// --- ОТКАЗ ОДНОГО ЭЛЕМЕНТА НЕ ЕСТЬ ОТКАЗ ЗДАНИЯ (§18.2) -----------------------
// Замер 20.08.2026, документ MNVNK_ATR_PD_B14_K6_AR_R2022 (Revit 2023, только
// чтение): get_FromRoom(phase) БРОСАЕТ на 246 дверях из 1230 — «The target
// instance does not exist in the given phase». Весь файл был ОДНИМ незащищённым
// обходом, поэтому одна дверь из 1230 гасила чтение ВСЕГО здания: 1102 комнаты,
// 2952 окна, уровни и стены не доезжали вовсе, а наружу выходило одно
// предложение БЕЗ АДРЕСА.
//
// Контракт §18.2 дословно: всякий запрошенный элемент даёт РЯД либо
// ТИПИЗИРОВАННУЮ КВИТАНЦИЮ. Молчание запрещено. Поэтому:
//   * тело каждого цикла обёрнуто в СВОЙ try — падает элемент, а не прогон;
//   * отказ едет ДАННЫМИ (`failures`), с этапом, id элемента и текстом;
//   * дверь, у которой в этой фазе нет комнаты, — это ФАКТ О ЗДАНИИ: она
//     получает РЯД, а причина едет полем `room_link`, а не исчезает.
//
// Список ОБРЕЗАН намеренно: отчёт не должен становиться длиннее предмета, а
// 246 одинаковых строк прозы — это форма 19. Полное число едет отдельно, и
// читатель обязан видеть ОБА: `failures_total` против длины `failures`.
int FAIL_CAP = 200;
int failTotal = 0;
var failures = new List<object>();
// GetType здесь не зовётся сознательно: шапка файла объявляет «no reflection»,
// и текст сообщения адрес называет не хуже имени класса.
Action<string, string, string> note = (stage, eid, msg) => {
    failTotal++;
    if (failures.Count < FAIL_CAP)
        failures.Add(new Dictionary<string, object> {
            {"stage", stage}, {"element_id", eid}, {"reason", msg}
        });
};

Phase phase = null;
foreach (Phase ph in doc.Phases) phase = ph;   // last phase (fallback)
// prefer the phase the ROOMS actually live in — door FromRoom/ToRoom are phase-specific, and
// rooms may sit in an earlier phase (e.g. "Стадия 1") than the document's last phase.
var _firstRoom = new FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Rooms)
    .WhereElementIsNotElementType().Cast<SpatialElement>().FirstOrDefault(r => r.Area > 1e-6);
if (_firstRoom != null) {
    var _rp = _firstRoom.get_Parameter(BuiltInParameter.ROOM_PHASE);
    if (_rp != null && _rp.AsElementId() != ElementId.InvalidElementId) {
        var _ph = doc.GetElement(_rp.AsElementId()) as Phase;
        if (_ph != null) phase = _ph;
    }
}

// --- levels (sorted bottom->top, index assigned) ---
var levels = new List<object>();
var lvElev = new Dictionary<string, double>();   // level id -> elevation (mm)
var lvOrder = new FilteredElementCollector(doc).OfClass(typeof(Level)).Cast<Level>()
    .OrderBy(l => l.Elevation).ToList();
for (int i = 0; i < lvOrder.Count; i++) {
    var l = lvOrder[i];
    double elevMm = Math.Round(l.Elevation * FT, 1);
    lvElev[l.Id.ToString()] = elevMm;
    levels.Add(new Dictionary<string, object> {
        {"id", l.Id.ToString()}, {"name", l.Name},
        {"elevation_mm", elevMm}, {"index", i}
    });
}

// --- rooms (placed only); name kept raw, function classified Python-side ---
var rooms = new List<object>();
var bopts = new SpatialElementBoundaryOptions();
int roomsUnplaced = 0;
foreach (var sp in new FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Rooms)
         .WhereElementIsNotElementType().Cast<SpatialElement>()) {
  try {
    // НЕРАЗМЕЩЁННАЯ КОМНАТА ТЕПЕРЬ СЧИТАЕТСЯ, А НЕ ПРОПАДАЕТ МОЛЧА. У неё нет
    // ни площади, ни границ, поэтому рядом ей не быть — но её ЧИСЛО решает,
    // что стоит в знаменателе всякой доли по комнатам. Замер 20.08.2026:
    // 629 из 1102 (57 %) в MNVNK_ATR_PD_B14_K6. «Комнат 473» и «комнат 1102» —
    // два разных здания под одним именем, и различить их можно только этим.
    if (sp.Area <= 1e-6) { roomsUnplaced++; continue; }
    // 🔴 ЧИТАЮТСЯ ВСЕ КОНТУРЫ, А НЕ ТОЛЬКО segs[0] (S-01, 29.08.2026). Стояло
    // `foreach (var s in segs[0])` — шахта, атриум и вырез под лестницу
    // исчезали ещё В СЪЁМЕ, до питона. Выведенная площадь выходила больше
    // настоящей, а HAB060 молчал: его порог расхождения ОТНОСИТЕЛЬНЫЙ (10 %),
    // и вклад шахты в него укладывается — замер: комната 10x10 м с шахтой
    // 2x2 м даёт 100 против заявленных Revit'ом 96, то есть 4.2 %.
    // Первый контур наружный, остальные — дыры. ТОТ ЖЕ разбор, что в
    // `decompile/extract.py` и в `decompile/fold._room_contains`: два
    // производителя ОДНОЙ модели обязаны терять или сохранять одно и то же.
    var bnd = new List<object>();
    var holes = new List<object>();
    var segs = sp.GetBoundarySegments(bopts);
    if (segs != null) {
        for (int li = 0; li < segs.Count; li++) {
            var pts = new List<object>();
            foreach (var s in segs[li]) {
                var p = s.GetCurve().GetEndPoint(0);
                pts.Add(new List<object> { Math.Round(p.X * FT, 1), Math.Round(p.Y * FT, 1) });
            }
            if (li == 0) bnd = pts; else holes.Add(pts);
        }
    }
    // v2 truth: bounded ceiling from UpperLimit + LimitOffset − BaseOffset; else the
    // unbounded ROOM_HEIGHT param; else null. NEVER a fabricated constant.
    object h = null;
    string hsrc = null;
    var rm = sp as Autodesk.Revit.DB.Architecture.Room;
    if (rm != null) {
        Level upper = null;
        try { upper = rm.UpperLimit; } catch { upper = null; }
        if (upper != null) {
            double topMm = Math.Round(upper.Elevation * FT, 1) + Math.Round(rm.LimitOffset * FT, 1);
            double baseMm = 0.0;
            lvElev.TryGetValue(sp.LevelId.ToString(), out baseMm);
            baseMm += Math.Round(rm.BaseOffset * FT, 1);
            double bounded = Math.Round(topMm - baseMm, 1);
            if (bounded > 0) { h = bounded; hsrc = "bounded"; }
        }
        if (h == null) {
            double ub = 0.0;
            try { ub = rm.UnboundedHeight; } catch { ub = 0.0; }
            if (ub > 1e-6) { h = Math.Round(ub * FT, 1); hsrc = "param"; }
        }
    }
    if (h == null) {
        var hp = sp.get_Parameter(BuiltInParameter.ROOM_HEIGHT);
        if (hp != null && hp.HasValue) { h = Math.Round(hp.AsDouble() * FT, 1); hsrc = "param"; }
    }
    string dept = null;
    var dp = sp.get_Parameter(BuiltInParameter.ROOM_DEPARTMENT);
    if (dp != null && dp.HasValue) dept = dp.AsString();
    string rnum = "";
    var np = sp.get_Parameter(BuiltInParameter.ROOM_NUMBER);
    if (np != null && np.HasValue) rnum = np.AsString() ?? "";
    rooms.Add(new Dictionary<string, object> {
        {"id", sp.Id.ToString()}, {"name", sp.Name}, {"number", rnum},
        {"level_id", sp.LevelId.ToString()},
        {"area_m2", Math.Round(sp.Area * FT2, 2)}, {"height_mm", h},
        {"height_source", hsrc}, {"department", dept}, {"boundary", bnd},
        {"boundary_holes", holes}
    });
  } catch (Exception ex) {
    note("room", sp != null ? sp.Id.ToString() : "?", ex.Message);
  }
}

// --- doors (FromRoom/ToRoom via phase; host wall emitted; legacy is_exterior kept for v1) ---
var doors = new List<object>();
foreach (var d in new FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Doors)
         .WhereElementIsNotElementType().Cast<FamilyInstance>()) {
  try {
    double x = 0, y = 0;
    var lp = d.Location as LocationPoint;
    if (lp != null) { x = Math.Round(lp.Point.X * FT, 1); y = Math.Round(lp.Point.Y * FT, 1); }
    object fr = null, to = null;
    // ЗДЕСЬ ЖИЛА СМЕРТЬ ВСЕГО ПРОГОНА. Пара фазозависимых вызовов — 246 отказов
    // из 1230 дверей на живом документе. Ловится ОТДЕЛЬНО от остального тела,
    // потому что исход у неё СВОЙ и он не «дверь плохая»: дверь есть, у неё есть
    // место, ширина и хозяин, а комнаты в ЭТОЙ фазе нет.
    string link = phase != null ? "ok" : "no_phase";
    if (phase != null) {
        try {
            var rfrom = d.get_FromRoom(phase); var rto = d.get_ToRoom(phase);
            if (rfrom != null) fr = rfrom.Id.ToString();
            if (rto != null) to = rto.Id.ToString();
            if (fr == null && to == null) link = "no_room_in_phase";
        } catch (Exception ex) {
            link = "refused";
            note("door_phase_link", d.Id.ToString(), ex.Message);
        }
    }
    // LEGACY (v1 only): 'one side null' exterior heuristic. v2 normalize() discards this —
    // derive.py re-establishes exteriority positively from envelope membership.
    //
    // 🔴 ОТКАЗ НЕ СМЕЕТ ЧИТАТЬСЯ КАК ЗАМЕР. При `link == "refused"` обе стороны
    // null НЕ ПОТОМУ, что дверь наружная, а потому, что мы не смогли спросить.
    // Прежняя формула сделала бы из НАШЕГО отказа уличный выход — и на этом
    // документе выдала бы 246 фальшивых наружных дверей. Поэтому здесь false, а
    // правду несёт `room_link`.
    bool ext = link == "refused" ? false : (fr == null || to == null);
    double w = 900.0;
    var wp = d.Symbol.get_Parameter(BuiltInParameter.DOOR_WIDTH);
    if (wp == null || !wp.HasValue) wp = d.Symbol.get_Parameter(BuiltInParameter.FAMILY_WIDTH_PARAM);
    if (wp != null && wp.HasValue) w = Math.Round(wp.AsDouble() * FT, 1);
    object host = d.Host != null ? d.Host.Id.ToString() : null;
    string did_lvl = d.LevelId != null ? d.LevelId.ToString() : (lvOrder.Count > 0 ? lvOrder[0].Id.ToString() : "0");
    doors.Add(new Dictionary<string, object> {
        {"id", d.Id.ToString()}, {"level_id", did_lvl}, {"location", new List<object> { x, y }},
        {"width_mm", w}, {"from_room_id", fr}, {"to_room_id", to}, {"is_exterior", ext},
        {"host_wall_id", host}, {"room_link", link}
    });
  } catch (Exception ex) {
    note("door", d != null ? d.Id.ToString() : "?", ex.Message);
  }
}

// --- windows (measured height + location; area = width x measured height when known) ---
var windows = new List<object>();
foreach (var win in new FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Windows)
         .WhereElementIsNotElementType().Cast<FamilyInstance>()) {
  try {
    double w = 1200.0;
    var wp = win.Symbol.get_Parameter(BuiltInParameter.WINDOW_WIDTH);
    if (wp == null || !wp.HasValue) wp = win.Symbol.get_Parameter(BuiltInParameter.FAMILY_WIDTH_PARAM);
    if (wp != null && wp.HasValue) w = Math.Round(wp.AsDouble() * FT, 1);
    // v2 truth: measured opening height — type param first, else instance bbox Z-extent.
    object hgt = null;
    var hp2 = win.Symbol.get_Parameter(BuiltInParameter.WINDOW_HEIGHT);
    if (hp2 == null || !hp2.HasValue) hp2 = win.Symbol.get_Parameter(BuiltInParameter.FAMILY_HEIGHT_PARAM);
    if (hp2 != null && hp2.HasValue && hp2.AsDouble() > 1e-6) {
        hgt = Math.Round(hp2.AsDouble() * FT, 1);
    } else {
        var wbb = win.get_BoundingBox(null);
        if (wbb != null) {
            double dz = Math.Round((wbb.Max.Z - wbb.Min.Z) * FT, 1);
            if (dz > 1e-6) hgt = dz;
        }
    }
    // area: measured product when height known; legacy width x 1.4 fiction ONLY as the v1
    // fallback (height_mm=null marks it unmeasured for v2's derivation).
    double area = hgt != null ? Math.Round((w / 1000.0) * ((double)hgt / 1000.0), 2)
                              : Math.Round((w / 1000.0) * 1.4, 2);
    object wloc = null;
    var wlp = win.Location as LocationPoint;
    if (wlp != null) wloc = new List<object> {
        Math.Round(wlp.Point.X * FT, 1), Math.Round(wlp.Point.Y * FT, 1) };
    object host = win.Host != null ? win.Host.Id.ToString() : null;
    object roomId = null;
    // ВТОРОЙ НОСИТЕЛЬ ТОГО ЖЕ ВЫЗОВА, И ОН НАЙДЕН ПОТОМУ, ЧТО ЕГО ИСКАЛИ ПОСЛЕ
    // ПЕРВОГО. На документе 20.08 окна бросили НОЛЬ раз — но это факт о ТОМ
    // документе, а не о вызове: он тот же самый и фаза та же. Незащищённым он
    // остался бы ровно до первого документа, где окно стоит в другой фазе.
    string wlink = phase != null ? "ok" : "no_phase";
    if (phase != null) {
        try {
            var rt = win.get_ToRoom(phase) ?? win.get_FromRoom(phase);
            if (rt != null) roomId = rt.Id.ToString(); else wlink = "no_room_in_phase";
        } catch (Exception ex) {
            wlink = "refused";
            note("window_phase_link", win.Id.ToString(), ex.Message);
        }
    }
    string wlvl = win.LevelId != null ? win.LevelId.ToString() : (lvOrder.Count > 0 ? lvOrder[0].Id.ToString() : "0");
    windows.Add(new Dictionary<string, object> {
        {"id", win.Id.ToString()}, {"level_id", wlvl}, {"host_wall_id", host},
        {"room_id", roomId}, {"width_mm", w}, {"area_m2", area},
        {"height_mm", hgt}, {"location", wloc}, {"room_link", wlink}
    });
  } catch (Exception ex) {
    note("window", win != null ? win.Id.ToString() : "?", ex.Message);
  }
}

// --- stairs (REAL geometry from the Stairs element; null when not derivable) ---
var stairs = new List<object>();
foreach (var st in new FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Stairs)
         .WhereElementIsNotElementType().Cast<Element>()) {
  try {
    string baseLv = "0", topLv = "0";
    var bp = st.get_Parameter(BuiltInParameter.STAIRS_BASE_LEVEL_PARAM);
    var tp = st.get_Parameter(BuiltInParameter.STAIRS_TOP_LEVEL_PARAM);
    if (bp != null && bp.AsElementId() != ElementId.InvalidElementId) baseLv = bp.AsElementId().ToString();
    if (tp != null && tp.AsElementId() != ElementId.InvalidElementId) topLv = tp.AsElementId().ToString();
    var bb = st.get_BoundingBox(null);
    double bz = bb != null ? Math.Round(bb.Min.Z * FT, 1) : 0.0;
    double tz = bb != null ? Math.Round(bb.Max.Z * FT, 1) : 0.0;
    var fp = new List<object>();
    if (bb != null) {
        double x0 = Math.Round(bb.Min.X * FT, 1), y0 = Math.Round(bb.Min.Y * FT, 1);
        double x1 = Math.Round(bb.Max.X * FT, 1), y1 = Math.Round(bb.Max.Y * FT, 1);
        fp.Add(new List<object> { x0, y0 }); fp.Add(new List<object> { x1, y0 });
        fp.Add(new List<object> { x1, y1 }); fp.Add(new List<object> { x0, y1 });
    }
    // v2 truth: real run/riser/tread geometry off the Stairs element — no hardcoding.
    object runW = null, risers = null, tread = null;
    var stObj = st as Autodesk.Revit.DB.Architecture.Stairs;
    if (stObj != null) {
        try {
            int nr = stObj.ActualRisersNumber;
            if (nr > 0) risers = nr;
        } catch { }
        try {
            double td = stObj.ActualTreadDepth;
            if (td > 1e-6) tread = Math.Round(td * FT, 1);
        } catch { }
        try {
            double minW = double.MaxValue;
            foreach (ElementId runId in stObj.GetStairsRuns()) {
                var run = doc.GetElement(runId) as Autodesk.Revit.DB.Architecture.StairsRun;
                if (run != null && run.ActualRunWidth > 1e-6 && run.ActualRunWidth < minW)
                    minW = run.ActualRunWidth;
            }
            if (minW < double.MaxValue) runW = Math.Round(minW * FT, 1);
        } catch { }
    }
    stairs.Add(new Dictionary<string, object> {
        {"id", st.Id.ToString()}, {"base_level_id", baseLv}, {"top_level_id", topLv},
        {"base_z", bz}, {"top_z", tz}, {"run_width_mm", runW},
        {"riser_count", risers}, {"tread_depth_mm", tread}, {"footprint", fp},
        {"kind", "element"}
    });
  } catch (Exception ex) {
    note("stair", st != null ? st.Id.ToString() : "?", ex.Message);
  }
}

// --- walls (wall function emitted for envelope corroboration) ---
var walls = new List<object>();
foreach (var wl in new FilteredElementCollector(doc).OfClass(typeof(Wall)).Cast<Wall>()) {
  try {
    var lc = wl.Location as LocationCurve;
    if (lc == null) continue;
    var c = lc.Curve;
    var a = c.GetEndPoint(0); var b = c.GetEndPoint(1);
    double hmm = 3000.0;
    var hp = wl.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM);
    if (hp != null && hp.HasValue) hmm = Math.Round(hp.AsDouble() * FT, 1);
    string wfunc = null;
    try { if (wl.WallType != null) wfunc = wl.WallType.Function.ToString(); } catch { }
    string wlvl = wl.LevelId != null ? wl.LevelId.ToString() : (lvOrder.Count > 0 ? lvOrder[0].Id.ToString() : "0");
    walls.Add(new Dictionary<string, object> {
        {"id", wl.Id.ToString()}, {"level_id", wlvl},
        {"curve", new List<object> {
            new List<object> { Math.Round(a.X * FT, 1), Math.Round(a.Y * FT, 1) },
            new List<object> { Math.Round(b.X * FT, 1), Math.Round(b.Y * FT, 1) } }},
        {"height_mm", hmm}, {"is_structural", wl.StructuralUsage != StructuralWallUsage.NonBearing},
        {"function", wfunc},
        // Wall.Width in feet → mm. A room boundary lies on the wall FACE, half
        // a width off the axis: without it HAB042 read a closed room as open (2026-09-09).
        {"thickness_mm", Math.Round(wl.Width * FT, 1)}
    });
  } catch (Exception ex) {
    note("wall", wl != null ? wl.Id.ToString() : "?", ex.Message);
  }
}

// `failures_total` против `failures.Count` — ОБА, и это не дублирование:
// первое говорит, сколько ОТКАЗОВ БЫЛО, второе — сколько мы ПОКАЗАЛИ. Одно
// число вместо двух превратило бы обрезание списка в тихую потерю.
// `rooms_unplaced` стоит рядом с `rooms` по той же причине: доля по комнатам
// без него считается от знаменателя, которого читатель не выбирал.
return new Dictionary<string, object> {
    {"building_id", doc.Title}, {"levels", levels}, {"rooms", rooms}, {"doors", doors},
    {"windows", windows}, {"stairs", stairs}, {"walls", walls},
    {"failures", failures}, {"failures_total", failTotal}, {"failures_cap", FAIL_CAP},
    {"phase_name", phase != null ? phase.Name : null},
    {"counts", new Dictionary<string, object> {
        {"levels", levels.Count}, {"rooms", rooms.Count}, {"rooms_unplaced", roomsUnplaced},
        {"doors", doors.Count}, {"windows", windows.Count},
        {"stairs", stairs.Count}, {"walls", walls.Count},
        {"failures", failTotal} }}
};
