// Safe in-memory API model for test_type_creation_ownership.py. Actual compiler
// create/post fragments are injected. No Autodesk assemblies or Revit documents.
using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;

sealed record ElementId(long Value) {
    public static ElementId InvalidElementId => new ElementId(-1);
    public override string ToString() => Value.ToString();
}
enum BuiltInParameter { ALL_MODEL_TYPE_COMMENTS, STRUCTURAL_MATERIAL_PARAM }
enum MaterialFunctionAssignment { Structure, Substrate }
enum WallKind { Basic, Curtain }
enum StorageType { Double, String, Integer, ElementId }
sealed record ForgeTypeId(string TypeId);
static class SpecTypeId {
    public static readonly ForgeTypeId Length=new ForgeTypeId("length");
    public static readonly ForgeTypeId Number=new ForgeTypeId("number");
    public static readonly ForgeTypeId Area=new ForgeTypeId("area");
    public static readonly ForgeTypeId Angle=new ForgeTypeId("angle");
}
sealed class Definition {
    public ForgeTypeId Spec=SpecTypeId.Length; public bool Throw; public int Year=2026;
    public ForgeTypeId GetSpecTypeId() {
        if(Year!=2021 || Throw) throw new InvalidOperationException("unexpected/failed legacy spec read");
        return Spec;
    }
    public ForgeTypeId GetDataType() {
        if(Year==2021 || Throw) throw new InvalidOperationException("unexpected/failed modern spec read");
        return Spec;
    }
}
sealed class Parameter {
    public string Text; public double Number; public bool IsReadOnly;
    public string Mode = "normal"; public int Writes;
    public StorageType StorageType=StorageType.Double;
    public Definition Definition=new Definition();
    public string AsString() => Mode == "bad_readback" ? "not-the-written-stamp" : Text;
    public double AsDouble() => Number;
    public bool Set(string value) { Writes++; if (Mode == "set_false") return false; Text=value; return true; }
    public bool Set(double value) { Writes++; Number=value; return true; }
    public bool Set(ElementId value) { Writes++; Number=value.Value; return true; }
    public ElementId AsElementId() => new ElementId((long)Number);
}
abstract class Element {
    public ElementId Id; public string Name; public Document Owner;
    public Parameter Comments = new Parameter();
    public Parameter MaterialParameter = new Parameter { Number=-1 };
    public Parameter get_Parameter(BuiltInParameter key) {
        var parameter=key==BuiltInParameter.ALL_MODEL_TYPE_COMMENTS ? Comments : MaterialParameter;
        return parameter.Mode=="missing" ? null : parameter;
    }
    public abstract Element Duplicate(string name);
}
sealed class CompoundStructureLayer {
    public double Width; public MaterialFunctionAssignment Function; public ElementId MaterialId;
    public CompoundStructureLayer(double width, MaterialFunctionAssignment function, ElementId material) {
        Width=width; Function=function; MaterialId=material;
    }
}
sealed class CompoundStructure {
    public IList<CompoundStructureLayer> Layers;
    public static CompoundStructure CreateSimpleCompoundStructure(IList<CompoundStructureLayer> layers) =>
        new CompoundStructure { Layers=layers.ToList() };
    public IList<CompoundStructureLayer> GetLayers() => Layers;
    public double GetWidth() => Layers.Sum(x=>x.Width);
}
sealed class WallType : Element {
    public WallKind Kind = WallKind.Basic; public CompoundStructure Structure; public int CompoundWrites;
    public double Width => Structure.GetWidth();
    public CompoundStructure GetCompoundStructure() => Structure;
    public void SetCompoundStructure(CompoundStructure value) { CompoundWrites++; Structure=value; }
    public override Element Duplicate(string name) {
        var child=Owner.Add(new WallType { Name=name, Structure=Structure }); Owner.ConfigureNew(child); return child;
    }
}
sealed class Family { public ElementId Id; }
sealed class FamilySymbol : Element {
    public Family Family; public bool IsActive; public int Activations;
    public Dictionary<string,Parameter> Dimensions = new Dictionary<string,Parameter>();
    public IList<Parameter> GetParameters(string name) => Dimensions.TryGetValue(name,out var value)
        ? new List<Parameter>{value} : new List<Parameter>();
    public void Activate() { IsActive=true; Activations++; }
    public override Element Duplicate(string name) {
        var child=Owner.Add(new FamilySymbol { Name=name, Family=Family, IsActive=false,
            MaterialParameter=new Parameter { Number=MaterialParameter.Number, IsReadOnly=MaterialParameter.IsReadOnly },
            Dimensions=Dimensions.ToDictionary(x=>x.Key,x=>new Parameter { Number=x.Value.Number,
                IsReadOnly=x.Value.IsReadOnly,StorageType=x.Value.StorageType,Definition=x.Value.Definition }) });
        Owner.ConfigureNew(child); return child;
    }
}
sealed class Material : Element { public override Element Duplicate(string name)=>throw new NotSupportedException(); }
sealed class Document {
    public Dictionary<long,Element> Elements=new Dictionary<long,Element>();
    // Retain even rolled-back objects solely to observe whether the forbidden
    // setter was called before rollback. This is not a live-document query.
    public readonly List<Element> Added=new List<Element>();
    public long NextId=10000; public string NewStampMode="normal";
    public T Add<T>(T value,long id=0) where T:Element {
        value.Id=new ElementId(id==0 ? NextId++ : id); value.Owner=this;
        Elements[value.Id.Value]=value; Added.Add(value); return value;
    }
    public Element GetElement(ElementId id)=>Elements.TryGetValue(id.Value,out var value) ? value : null;
    public void Regenerate() { }
    public void ConfigureNew(Element element) {
        element.Comments.Mode=NewStampMode; element.Comments.IsReadOnly=NewStampMode=="readonly";
    }
}
sealed class FilteredElementCollector : IEnumerable<Element> {
    readonly Document doc; Type filter=typeof(Element);
    public FilteredElementCollector(Document document) { doc=document; }
    public FilteredElementCollector OfClass(Type type) { filter=type; return this; }
    public IEnumerator<Element> GetEnumerator()=>doc.Elements.Values.Where(x=>filter.IsInstanceOfType(x)).GetEnumerator();
    IEnumerator IEnumerable.GetEnumerator()=>GetEnumerator();
}
sealed class Transaction {
    readonly Document doc; readonly HashSet<long> ids; readonly Dictionary<long,CompoundStructure> compounds;
    readonly Dictionary<long,Dictionary<string,double>> dimensions;
    readonly Dictionary<long,string> comments; readonly Dictionary<long,double> materials;
    public Transaction(Document value) {
        doc=value; ids=doc.Elements.Keys.ToHashSet();
        compounds=doc.Elements.Values.OfType<WallType>().ToDictionary(x=>x.Id.Value,x=>x.Structure);
        dimensions=doc.Elements.Values.OfType<FamilySymbol>().ToDictionary(x=>x.Id.Value,
            x=>x.Dimensions.ToDictionary(p=>p.Key,p=>p.Value.Number));
        comments=doc.Elements.Values.ToDictionary(x=>x.Id.Value,x=>x.Comments.Text);
        materials=doc.Elements.Values.ToDictionary(x=>x.Id.Value,x=>x.MaterialParameter.Number);
    }
    public void RollBack() {
        foreach(var id in doc.Elements.Keys.Where(id=>!ids.Contains(id)).ToArray()) doc.Elements.Remove(id);
        foreach(var pair in compounds) ((WallType)doc.Elements[pair.Key]).Structure=pair.Value;
        foreach(var pair in dimensions) foreach(var p in pair.Value)
            ((FamilySymbol)doc.Elements[pair.Key]).Dimensions[p.Key].Number=p.Value;
        foreach(var pair in comments) doc.Elements[pair.Key].Comments.Text=pair.Value;
        foreach(var pair in materials) doc.Elements[pair.Key].MaterialParameter.Number=pair.Value;
    }
    public void Commit() { }
}
sealed class Result {
    public bool Ok {get;set;} public bool Duplicated {get;set;}
    public int Violations {get;set;} public string Reason {get;set;}
}
static class Program {
    static readonly List<object> Rows=new List<object>();
    static double U(double mm)=>mm/304.8;
    static double MM(double feet)=>feet*304.8;
    static Result __Refuse(string id,string reason)=>new Result { Ok=false, Reason=reason };
    static Exception __OpRefuse(string id,string reason)=>new InvalidOperationException(id+":"+reason);
    /* METHODS */
    static WallType Wall(Document d,string name,double width,string stamp,long id=0,long material=-1) {
        var wall=d.Add(new WallType { Name=name,
            Structure=CompoundStructure.CreateSimpleCompoundStructure(new List<CompoundStructureLayer> {
                new CompoundStructureLayer(U(width),MaterialFunctionAssignment.Structure,new ElementId(material)) }) },id);
        wall.Comments.Text=stamp; return wall;
    }
    static FamilySymbol Symbol(Document d,Family family,string name,double width,double depth,string stamp,long id=0,long material=-1) {
        var symbol=d.Add(new FamilySymbol { Name=name, Family=family, MaterialParameter=new Parameter { Number=material },
            Dimensions=new Dictionary<string,Parameter> {
                {"b",new Parameter { Number=U(width) }}, {"h",new Parameter { Number=U(depth) }} } },id);
        symbol.Comments.Text=stamp; return symbol;
    }
    static int Writes(Element element) => element.Comments.Writes + element.MaterialParameter.Writes +
        (element is WallType wall ? wall.CompoundWrites : ((FamilySymbol)element).Activations +
            ((FamilySymbol)element).Dimensions.Values.Sum(x=>x.Writes));
    // D-1 (06.09.2026): a composition mismatch on a type with a MATCHING address is a
    // named refusal ON THE OP, not a postcondition violation at the end of the program.
    // The rig pins the name: a bare «refused» would match any other refusal.
    static bool NamedReuseRefusal(Result result) =>
        !result.Ok && result.Violations==0 && result.Reason!=null &&
        result.Reason.Contains("тип с этим адресом уже существует с другим составом");
    static void Check(string profile,string group,string name,bool pass,Result result,object detail) {
        Rows.Add(new { profile,group,name,pass,result,detail });
    }
    static void RunSuite(string profile,Func<Document,Result> runWall,Func<Document,Result> runFamily,
                         Func<Document,Result> runWallMaterial,Func<Document,Result> runFamilyMaterial,
                         string stampA,string stampB,string stampF,string stampWM,string stampFM) {
        foreach(var scenario in new[] { "foreign_kir","manual","stale","exact","drift","ambiguous" }) {
            var doc=new Document(); Wall(doc,"BaseWall",100,null,4001);
            string stamp=scenario=="foreign_kir" ? stampA : scenario=="manual" ? "human-comment" :
                scenario=="stale" ? stampB+":extra" : stampB;
            var twin=Wall(doc,"SharedWall",scenario=="foreign_kir" ? 200 : scenario=="drift" ? 450 : 350,stamp);
            if(scenario=="ambiguous") Wall(doc,"SharedWall",350,stampB);
            var before=MM(twin.Width); var observer1=twin; var observer2=twin;
            var result=runWall(doc); bool wanted=scenario=="exact";
            Check(profile,"wall_existing","wall_"+scenario,
                result.Ok==wanted && Writes(twin)==0 && MM(twin.Width)==before && twin.Comments.Text==stamp &&
                (!wanted || !result.Duplicated) && (scenario!="drift" || NamedReuseRefusal(result)), result,
                new { before,after=MM(twin.Width),writes=Writes(twin),otherInstance1=MM(observer1.Width),otherInstance2=MM(observer2.Width) });
        }
        foreach(var scenario in new[] { "foreign_kir","manual","stale","exact","drift","ambiguous","exact_readonly" }) {
            var doc=new Document(); var family=new Family { Id=new ElementId(700) };
            Symbol(doc,family,"BaseFamily",200,200,null,500);
            string stamp=scenario=="foreign_kir" ? stampA : scenario=="manual" ? "human-comment" :
                scenario=="stale" ? stampF+":extra" : stampF;
            var twin=Symbol(doc,family,"SharedFamily",scenario=="drift" ? 700 :
                (scenario=="foreign_kir" || scenario=="manual") ? 200 : 450,500,stamp);
            if(scenario=="ambiguous") Symbol(doc,family,"SharedFamily",450,500,stampF);
            if(scenario=="exact_readonly") foreach(var p in twin.Dimensions.Values) p.IsReadOnly=true;
            var before=MM(twin.Dimensions["b"].Number); var result=runFamily(doc);
            bool wanted=scenario=="exact" || scenario=="exact_readonly";
            Check(profile,"family_existing","family_"+scenario,
                result.Ok==wanted && Writes(twin)==0 && MM(twin.Dimensions["b"].Number)==before &&
                twin.Comments.Text==stamp && !twin.IsActive && (!wanted || !result.Duplicated) &&
                (scenario!="drift" || result.Violations>0), result,
                new { before,after=MM(twin.Dimensions["b"].Number),writes=Writes(twin),twin.Activations });
        }
        foreach(var mode in new[] { "normal","missing","readonly","set_false","bad_readback" }) {
            foreach(var kind in new[] { "wall","family" }) {
                var doc=new Document { NewStampMode=mode };
                if(kind=="wall") Wall(doc,"BaseWall",100,null,4001);
                else Symbol(doc,new Family { Id=new ElementId(700) },"BaseFamily",200,200,null,500);
                var result=kind=="wall" ? runWall(doc) : runFamily(doc); bool wanted=mode=="normal";
                var made=doc.Elements.Values.SingleOrDefault(x=>x.Name==(kind=="wall" ? "SharedWall" : "SharedFamily"));
                bool pass=result.Ok==wanted && (wanted ? made!=null && result.Duplicated &&
                    made.Comments.AsString()==(kind=="wall" ? stampB : stampF) : made==null);
                Check(profile,"new_stamp","new_"+kind+"_stamp_"+mode,pass,result,new { remainingTypes=doc.Elements.Count });
            }
        }
        foreach(var kind in new[] { "wall","family" }) {
            foreach(var scenario in new[] { "new","exact","readonly","drift","missing","ambiguous","new_missing","new_ambiguous" }) {
                var doc=new Document(); var family=new Family { Id=new ElementId(700) };
                if(kind=="wall") Wall(doc,"BaseWall",100,null,4001);
                else Symbol(doc,family,"BaseFamily",200,200,null,500);
                bool missing=scenario=="missing" || scenario=="new_missing";
                bool ambiguous=scenario=="ambiguous" || scenario=="new_ambiguous";
                if(!missing) doc.Add(new Material { Name="Бетон М300" },1300);
                if(ambiguous) doc.Add(new Material { Name="Бетон М300" },1301);
                bool isNew=scenario.StartsWith("new",StringComparison.Ordinal);
                long initialMaterial=scenario=="drift" ? 1302 : 1300;
                Element twin=null;
                if(!isNew) {
                    twin=kind=="wall" ? (Element)Wall(doc,"SharedWall",350,stampWM,material:initialMaterial) :
                        Symbol(doc,family,"SharedFamily",450,500,stampFM,material:initialMaterial);
                    twin.MaterialParameter.IsReadOnly=scenario=="readonly";
                }
                int before=doc.Elements.Count;
                var result=kind=="wall" ? runWallMaterial(doc) : runFamilyMaterial(doc);
                bool wanted=scenario=="new" || scenario=="exact" || scenario=="readonly";
                var target=doc.Elements.Values.SingleOrDefault(x=>x.Name==(kind=="wall" ? "SharedWall" : "SharedFamily"));
                long material=target==null ? -1 : kind=="wall" ?
                    ((WallType)target).Structure.GetLayers()[0].MaterialId.Value : target.MaterialParameter.AsElementId().Value;
                bool pass=result.Ok==wanted && (isNew ? (wanted ? result.Duplicated && material==1300 &&
                    target.Comments.AsString()==(kind=="wall" ? stampWM : stampFM) : target==null && doc.Elements.Count==before) :
                    Writes(twin)==0 && material==initialMaterial && target==twin && !result.Duplicated) &&
                    // D-1: for a wall, material drift is the same named refusal on the op
                    // (the layer composition includes the material); for a family, the host is unchanged.
                    (scenario!="drift" || (kind=="wall" ? NamedReuseRefusal(result) : result.Violations>0));
                Check(profile,"material",kind+"_material_"+scenario,pass,result,
                    new { material,writes=twin==null ? -1 : Writes(twin),before,after=doc.Elements.Count });
            }
        }
    }
    static void RunDimensions(string profile,int year,Func<Document,Result> runFamily,string stamp) {
        foreach(string field in new[] { "b","h" }) foreach(bool existing in new[] { false,true }) {
            foreach(string scenario in new[] { "length","number","area","angle","null_definition","getter_throw","string_storage","null_spec" }) {
                var doc=new Document(); var family=new Family { Id=new ElementId(700) };
                var source=Symbol(doc,family,"BaseFamily",200,200,null,500);
                var target=existing ? Symbol(doc,family,"SharedFamily",450,500,stamp) : source;
                foreach(var item in doc.Elements.Values.OfType<FamilySymbol>())
                    foreach(var parameter in item.Dimensions.Values) parameter.Definition.Year=year;
                var selected=target.Dimensions[field];
                if(scenario=="null_definition") selected.Definition=null;
                else if(scenario=="getter_throw") selected.Definition.Throw=true;
                else if(scenario=="null_spec") selected.Definition.Spec=null;
                else if(scenario=="string_storage") selected.StorageType=StorageType.String;
                else if(scenario!="length") selected.Definition.Spec=scenario=="number" ? SpecTypeId.Number :
                    scenario=="area" ? SpecTypeId.Area : SpecTypeId.Angle;
                double before=selected.Number;
                var result=runFamily(doc);
                var attempted=doc.Added.OfType<FamilySymbol>().SingleOrDefault(x=>x.Name=="SharedFamily");
                var attemptedParameter=attempted==null ? selected : attempted.Dimensions[field];
                bool wanted=scenario=="length";
                bool retained=attempted!=null && doc.Elements.ContainsKey(attempted.Id.Value);
                bool pass=result.Ok==wanted && (existing ? Writes(target)==0 && selected.Number==before && retained :
                    Writes(source)==0 && (wanted ? retained && result.Duplicated && attemptedParameter.Writes==1 :
                        !retained && attemptedParameter.Writes==0));
                Check(profile,"dimension_"+year,"dimension_"+year+"_"+field+"_"+(existing ? "existing_" : "new_")+scenario,
                    pass,result,new { scenario,field,existing,before,after=attemptedParameter.Number,
                        parameterWrites=attemptedParameter.Writes,allTargetWrites=attempted==null ? 0 : Writes(attempted),retained });
            }
        }
    }
    public static void Main() {
        /* SUITES */
        Console.Write(JsonSerializer.Serialize(Rows));
    }
}
