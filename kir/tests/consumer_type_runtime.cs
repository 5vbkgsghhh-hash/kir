// A deliberately small model, not an implementation of Autodesk/Revit API.
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Text.Json;

sealed record ElementId(long Value) {
    public static ElementId InvalidElementId => new ElementId(-1);
    public int IntegerValue => checked((int)Value);
    public override string ToString() => Value.ToString();
}
enum BuiltInParameter { ALL_MODEL_INSTANCE_COMMENTS, WALL_BASE_CONSTRAINT, WALL_USER_HEIGHT_PARAM,
    FAMILY_BASE_LEVEL_PARAM, FAMILY_LEVEL_PARAM, SCHEDULE_LEVEL_PARAM, LEVEL_PARAM, FLOOR_PARAM_IS_STRUCTURAL }
enum ElementTypeGroup { WallType, FloorType }
sealed class XYZ {
    public double X,Y,Z;
    public XYZ(double x,double y,double z) { X=x;Y=y;Z=z; }
}
class Curve {
    public XYZ A,B;
    public XYZ GetEndPoint(int index) => index==0 ? A : B;
}
sealed class Line : Curve {
    public static Line CreateBound(XYZ a,XYZ b) => new Line { A=a,B=b };
}
sealed class CurveLoop : List<Curve> { public void Append(Curve curve) => Add(curve); }
sealed class CurveArray : List<Curve> { public void Append(Curve curve) => Add(curve); }
sealed class LocationCurve { public Curve Curve; }
sealed class BoundingBoxXYZ { public XYZ Min,Max; }
sealed class Parameter {
    public double Number; public ElementId ElementId; public string Text; public bool IsReadOnly => false;
    public bool HasValue => true;
    public bool Set(string value) { Text=value;return true; }
    public double AsDouble() => Number;
    public int AsInteger() => (int)Number;
    public ElementId AsElementId() => ElementId;
    public string AsString() => Text;
}
class Element {
    public Document Doc; public ElementId Id; public string Name="Fixture"; public object Location;
    public ElementId NativeType; public string TypeReadMode="same";
    public bool Valid=true;
    public string UniqueId {
        get {
            if(!Valid) throw new InvalidOperationException("fixture stale identity");
            return "fixture-element-" + Id.Value;
        }
    }
    public Guid VersionGuid {
        get {
            if(!Valid) throw new InvalidOperationException("fixture stale identity version");
            return Guid.Parse("abcde123-4567-89ab-cdef-0123456789ab");
        }
    }
    public readonly Dictionary<BuiltInParameter,Parameter> Parameters=new Dictionary<BuiltInParameter,Parameter>();
    public Parameter get_Parameter(BuiltInParameter key) => Parameters.TryGetValue(key,out var p) ? p : null;
    public ElementId GetTypeId() {
        Doc.TypeReadIds.Add(Id.Value);
        Doc.TypeReads.Add(TypeReadMode);
        if(!Valid) throw new InvalidOperationException("fixture stale replaced element");
        if(TypeReadMode=="throws") throw new InvalidOperationException("fixture native TypeId getter failed");
        return TypeReadMode=="null" ? null : TypeReadMode=="invalid" ? ElementId.InvalidElementId : new ElementId(NativeType.Value);
    }
    public ElementId ChangeTypeId(ElementId type) {
        Doc.ChangeCalls++;
        var mode=Doc.ChangeCalls==1 ? Doc.FirstChangeMode : Doc.SecondChangeMode;
        if(mode=="throw") throw new InvalidOperationException("fixture ChangeTypeId failed");
        if(mode=="no_op") return ElementId.InvalidElementId;
        if(mode=="throw_after_effect") {
            NativeType=type; Doc.MutationEffects++; throw new InvalidOperationException("fixture mutation changed state then threw");
        }
        if(mode=="replacement" || mode=="replacement_wrong") {
            Doc.MutationEffects++;
            var replacement=Doc.Add(new Element { NativeType=mode=="replacement" ? type : new ElementId(999) },900);
            Valid=false; Doc.Elements.Remove(Id.Value); return replacement.Id;
        }
        NativeType=mode=="wrong" ? new ElementId(999) : type; Doc.MutationEffects++;
        TypeReadMode=mode=="getter_throw" ? "throws" : "same"; return ElementId.InvalidElementId;
    }
    public virtual BoundingBoxXYZ get_BoundingBox(object view) => null;
    public virtual IList<ElementId> GetDependentElements(object filter) => Array.Empty<ElementId>();
}
class ElementType : Element { }
sealed class WallType : ElementType { }
sealed class FloorType : ElementType { }
sealed class Level : Element { public double Elevation => 0.0; }
sealed class Sketch : Element { public List<CurveArray> Profile; }
sealed class Wall : Element {
    public static Wall Create(Document doc,Curve curve,ElementId type,ElementId level,double height,
                              double offset,bool flipped,bool structural) {
        var wall=doc.Add(new Wall { Location=new LocationCurve { Curve=curve } },800);
        wall.Parameters[BuiltInParameter.WALL_BASE_CONSTRAINT]=new Parameter { ElementId=level };
        wall.Parameters[BuiltInParameter.WALL_USER_HEIGHT_PARAM]=new Parameter { Number=height };
        doc.Created(wall,type);
        if(doc.Scenario=="geometry_drift") curve.B.X+=500.0/304.8;
        return wall;
    }
}
sealed class Floor : Element {
    Sketch sketch;
    public static Floor Create(Document doc,IList<CurveLoop> loops,ElementId type,ElementId level) {
        var floor=doc.Add(new Floor(),800);
        floor.Parameters[BuiltInParameter.LEVEL_PARAM]=new Parameter { ElementId=level };
        floor.Parameters[BuiltInParameter.FLOOR_PARAM_IS_STRUCTURAL]=new Parameter { Number=0 };
        var profile=loops.Select(loop=>{ var a=new CurveArray();a.AddRange(loop);return a; }).ToList();
        floor.sketch=doc.Add(new Sketch { Profile=profile },801);
        doc.Created(floor,type);
        if(doc.Scenario=="geometry_drift") profile[0][0].A.X+=500.0/304.8;
        return floor;
    }
    public override IList<ElementId> GetDependentElements(object filter) => new[] { sketch.Id };
    public override BoundingBoxXYZ get_BoundingBox(object view) {
        var points=sketch.Profile[0].SelectMany(c=>new[] { c.A,c.B }).ToList();
        return new BoundingBoxXYZ { Min=new XYZ(points.Min(p=>p.X),points.Min(p=>p.Y),0),
                                    Max=new XYZ(points.Max(p=>p.X),points.Max(p=>p.Y),0) };
    }
}
sealed class Document {
    public readonly Dictionary<long,Element> Elements=new Dictionary<long,Element>();
    public readonly List<string> TypeReads=new List<string>();
    public readonly List<long> TypeReadIds=new List<long>();
    public string FirstChangeMode="normal",SecondChangeMode="normal",SecondCommitMode="normal";
    public int SubStarts,SubCommits,RollbackCalls,CommitRollbacks,SubDisposals,MutationEffects;
    public string Scenario; public int ChangeCalls,DefaultLookups; public long RequestedType;
    public T Add<T>(T element,long id) where T:Element { element.Doc=this;element.Id=new ElementId(id);Elements[id]=element;return element; }
    public Element GetElement(ElementId id) => id!=null && Elements.TryGetValue(id.Value,out var value) ? value : null;
    public ElementId GetDefaultElementTypeId(ElementTypeGroup group) {
        DefaultLookups++;return new ElementId(group==ElementTypeGroup.WallType ? 100 : 400);
    }
    public void Regenerate() { }
    // Controlled change between assignment proof and final readback. This is
    // a fixture seam, not a claim that native Revit changed type by itself.
    public void BeginFinalReadback() {
        if(!Scenario.StartsWith("late_",StringComparison.Ordinal)) return;
        foreach(var element in Elements.Values.Where(x=>x.NativeType!=null)) {
            element.TypeReadMode=Scenario=="late_null" ? "null" : Scenario=="late_throws" ? "throws" : "same";
            if(Scenario=="late_wrong") element.NativeType=new ElementId(999);
        }
    }
    public void Created(Element element,ElementId requested) {
        RequestedType=requested.Value;
        element.NativeType=Scenario=="wrong_same_name" ? new ElementId(999) : requested;
        element.TypeReadMode=Scenario.StartsWith("late_",StringComparison.Ordinal) ? "same" : Scenario;
        element.Parameters[BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS]=new Parameter();
    }
}
sealed class Transaction { public void RollBack() { } }
enum TransactionStatus { Started, Committed, RolledBack }
// Deliberately limited model of the native transaction interface. Production
// wrapper, state branching and receipt gates execute unchanged; restoration of
// these few in-memory fields is NOT evidence about native Revit rollback.
sealed class SubTransaction {
    readonly Document doc;
    Dictionary<long,(Element element,ElementId type,string mode,bool valid)> checkpoint;
    int index; bool started,ended;
    public SubTransaction(Document document) { doc=document; }
    public TransactionStatus Start() {
        index=++doc.SubStarts; started=true;
        checkpoint=doc.Elements.ToDictionary(p=>p.Key,p=>(p.Value,p.Value.NativeType,p.Value.TypeReadMode,p.Value.Valid));
        return TransactionStatus.Started;
    }
    void Restore() {
        doc.Elements.Clear();
        foreach(var item in checkpoint) {
            var state=item.Value;
            state.element.NativeType=state.type; state.element.TypeReadMode=state.mode; state.element.Valid=state.valid;
            doc.Elements[item.Key]=state.element;
        }
    }
    public TransactionStatus Commit() {
        doc.SubCommits++;
        if(index==2 && doc.SecondCommitMode=="throw") throw new InvalidOperationException("fixture subcommit failed");
        if(index==2 && doc.SecondCommitMode=="rollback") {
            Restore(); doc.CommitRollbacks++; ended=true; return TransactionStatus.RolledBack;
        }
        ended=true; return TransactionStatus.Committed;
    }
    public TransactionStatus RollBack() { Restore();doc.RollbackCalls++;ended=true;return TransactionStatus.RolledBack; }
    public bool HasStarted() => started;
    public bool HasEnded() => ended;
    public void Dispose() { doc.SubDisposals++; }
}
sealed class ProbeResult {
    public List<string> Post {get;set;} = new List<string>();
    public Dictionary<string,string[]> Checks {get;set;} = new Dictionary<string,string[]>();
    public Dictionary<string,object> Readback {get;set;} = new Dictionary<string,object>();
    public string Failure {get;set;}
    public Dictionary<string,string> Captured {get;set;} = new Dictionary<string,string>();
    public Dictionary<string,bool> Eligibility {get;set;} = new Dictionary<string,bool>();
}
static class Program {
    static readonly List<object> Rows=new List<object>();
    static double U(double mm) => mm/304.8;
    static double MM(double feet) => feet*304.8;
    static XYZ P(double x,double y,double z) => new XYZ(U(x),U(y),U(z));
    // Diagnostic-only host class name; the production guard's null/type branch
    // is not the subject of this deliberately small API model.
    static string __ClassName(object value) => value==null ? "null" : value.GetType().Name;
    static ProbeResult __Refuse(string id,string reason) => new ProbeResult { Failure=id+":"+reason };
    sealed class __KirOpRefusal : Exception {
        public readonly string Oid,Msg;
        public __KirOpRefusal(string id,string reason) : base(reason) { Oid=id;Msg=reason; }
    }
    static Exception __OpRefuse(string id,string reason) => new __KirOpRefusal(id,reason);
    /* METHODS */
    static void Probe(Func<Document,ProbeResult> run,string version,string isolation,string kind,string selector,bool laterChange,int expectedChanges=1) {
        foreach(var scenario in laterChange ? new[] { "same","wrong_same_name","null","throws" } :
                    new[] { "same","wrong_same_name","null","invalid","throws","geometry_drift","late_null","late_throws","late_wrong" }) {
            var doc=new Document { Scenario=scenario };
            doc.Add(new Level(),42);
            if(kind=="create_wall") {
                doc.Add(new WallType { Name="Requested type" },100);
                doc.Add(new WallType { Name="Changed type" },101);
                doc.Add(new WallType { Name="Second changed type" },102);
                doc.Add(new WallType { Name="Requested type" },700);
                doc.Add(new WallType { Name="Requested type" },999);
            } else {
                doc.Add(new FloorType { Name="Requested type" },400);
                doc.Add(new FloorType { Name="Requested type" },700);
                doc.Add(new FloorType { Name="Requested type" },999);
            }
            var result=run(doc);
            Rows.Add(new { version,isolation,kind,selector,scenario,laterChange,expectedChanges,result,
                requestedType=doc.RequestedType,typeReads=doc.TypeReads,changeCalls=doc.ChangeCalls,defaultLookups=doc.DefaultLookups });
        }
    }
    static void ProbeMutation(Func<Document,ProbeResult> run,string version,string isolation,bool chain) {
        foreach(var scenario in chain ? new[] { "normal","second_no_op","second_throw","second_commit_rollback","second_commit_throw" } :
                    new[] { "normal","replacement","replacement_wrong","no_op","wrong","throw","getter_throw" }) {
            var doc=new Document { Scenario=scenario };
            if(chain) {
                doc.SecondChangeMode=scenario=="second_no_op" ? "no_op" : scenario=="second_throw" ? "throw_after_effect" : "normal";
                doc.SecondCommitMode=scenario=="second_commit_rollback" ? "rollback" : scenario=="second_commit_throw" ? "throw" : "normal";
            } else doc.FirstChangeMode=scenario;
            doc.Add(new Element { NativeType=new ElementId(100) },800);
            foreach(var id in new long[] { 100,101,102,999 }) doc.Add(new WallType { Name="Fixture type" },id);
            var result=run(doc);
            var state=doc.Elements.Values.Where(e=>e.NativeType!=null).ToDictionary(e=>e.Id.ToString(),e=>e.NativeType.ToString());
            Rows.Add(new { kind="mutation",version,isolation,chain,scenario,result,state,
                changeCalls=doc.ChangeCalls,typeReadIds=doc.TypeReadIds,subStarts=doc.SubStarts,
                subCommits=doc.SubCommits,rollbackCalls=doc.RollbackCalls,commitRollbacks=doc.CommitRollbacks,
                subDisposals=doc.SubDisposals,mutationEffects=doc.MutationEffects });
        }
    }
    public static void Main() {
        /* CALLS */
        Console.Write(JsonSerializer.Serialize(Rows));
    }
}
