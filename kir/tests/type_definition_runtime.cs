// Test-only API. Actual generated query fragments are inserted below.
// This is NOT Autodesk execution, Connector admission or material fidelity.
using System;
using System.Linq;
using System.Collections;
using System.Collections.Generic;
using System.Text.Json;

enum BuiltInParameter { LEVEL_ELEV, LEVEL_RELATIVE_BASE_TYPE }
enum StorageType { Double, Integer }
enum WallKind { Basic, Curtain }
enum MaterialFunctionAssignment { Structure, Finish1, Insulation, Membrane }
static class UnitTypeId { public static readonly object Millimeters = new object(); }
static class UnitUtils {
    public static double ConvertFromInternalUnits(double value, object unit) {
        if (unit != UnitTypeId.Millimeters) throw new Exception("wrong unit");
        return value * 304.8;
    }
}
sealed class ElementId {
    readonly long number;
    public ElementId(long value) { number = value; }
    public static readonly ElementId InvalidElementId = new ElementId(-1);
    public int IntegerValue { get { return checked((int)number); } }
    public long Value { get { return number; } }
    public static bool operator ==(ElementId a, ElementId b) {
        return Object.ReferenceEquals(a,b) || (!Object.ReferenceEquals(a,null) && !Object.ReferenceEquals(b,null) && a.number==b.number);
    }
    public static bool operator !=(ElementId a, ElementId b) { return !(a==b); }
    public override bool Equals(object other) { return other is ElementId && this==(ElementId)other; }
    public override int GetHashCode() { return number.GetHashCode(); }
}
sealed class Category { public ElementId Id { get { return new ElementId(-2000011); } } }
sealed class Definition { public string Name { get { throw new Exception("unexpected Level"); } } }
sealed class Parameter {
    public bool HasValue { get { throw new Exception("unexpected Level"); } }
    public StorageType StorageType { get { throw new Exception("unexpected Level"); } }
    public ElementId Id { get { throw new Exception("unexpected Level"); } }
    public Definition Definition { get { throw new Exception("unexpected Level"); } }
    public bool IsReadOnly { get { throw new Exception("unexpected Level"); } }
    public double AsDouble() { throw new Exception("unexpected Level"); }
    public int AsInteger() { throw new Exception("unexpected Level"); }
}
class Element {
    protected readonly Document doc;
    readonly long number;
    readonly string uid, name;
    public Element(Document document, long id, string uniqueId, string label) { doc=document;number=id;uid=uniqueId;name=label; }
    public virtual ElementId Id { get { return new ElementId(number); } }
    public string UniqueId { get {
        if (doc.Mode=="identity_throw" && !(this is Material) || doc.Mode=="material_identity_throw" && this is Material)
            throw new Exception("secret identity");
        return uid;
    } }
    public Guid VersionGuid { get { return Guid.Parse("12345678-1234-5678-1234-567812345678"); } }
    public virtual string Name { get { return name; } }
    public Category Category { get { return new Category(); } }
    public ElementId GetTypeId() { return ElementId.InvalidElementId; }
    public Parameter get_Parameter(BuiltInParameter key) { throw new Exception("unexpected Level"); }
}
sealed class Level : Element {
    public Level(Document doc) : base(doc,700,"level","Level") { }
    public double ProjectElevation { get { throw new Exception("unexpected Level"); } }
    public double Elevation { get { throw new Exception("unexpected Level"); } }
    public IList<Parameter> GetParameters(string name) { throw new Exception("unexpected Level"); }
}
sealed class Material : Element {
    public Material(Document doc,long id,string name) : base(doc,id,"material-"+id,name) { }
    public override string Name { get {
        if (doc.Mode=="material_catalog_throw" && Id.Value==3003) throw new Exception("secret catalog getter");
        if (doc.Mode=="material_name_throw" && Id.Value==3001) throw new Exception("secret material name");
        return base.Name;
    } }
}
sealed class WallType : Element {
    public WallType(Document doc) : base(doc,800,"wall-uid","Declared wall") { }
    public WallKind Kind { get {
        if (doc.Mode=="kind_throw") throw new Exception("secret kind");
        return doc.Mode=="curtain" ? WallKind.Curtain : WallKind.Basic;
    } }
    public double Width { get { return doc.Width(); } }
    public CompoundStructure GetCompoundStructure() { return doc.Structure(true); }
}
sealed class FloorType : Element {
    public FloorType(Document doc) : base(doc,801,"floor-uid","Declared floor") { }
    public CompoundStructure GetCompoundStructure() { return doc.Structure(); }
}
sealed class CompoundStructureLayer {
    readonly Document doc;
    readonly int index;
    public CompoundStructureLayer(Document d,int i) { doc=d;index=i; }
    public double Width { get {
        if (doc.Mode=="layer_width_throw") throw new Exception("secret width");
        if (doc.Mode=="layer_nan") return double.NaN;
        return (index==0 ? doc.Mode=="wrong_width" ? 250 : doc.Mode=="membrane" ? 0 : 200 : 20)/304.8;
    } }
    public MaterialFunctionAssignment Function { get {
        if (doc.Mode=="function_throw") throw new Exception("secret function");
        return index!=0 ? MaterialFunctionAssignment.Finish1 : doc.Mode=="wrong_function" ? MaterialFunctionAssignment.Insulation
            : doc.Mode=="membrane" ? MaterialFunctionAssignment.Membrane : MaterialFunctionAssignment.Structure;
    } }
    public ElementId MaterialId { get {
        if (doc.Mode=="material_id_null") return null;
        if (index!=0 || doc.Mode=="membrane" || doc.Mode=="no_material") return ElementId.InvalidElementId;
        return new ElementId(doc.Mode=="wrong_material" ? 3002 : 3001);
    } }
}
sealed class CompoundStructure {
    readonly Document doc;
    readonly bool isWall;
    public CompoundStructure(Document d,bool wall) { doc=d;isWall=wall; }
    public bool IsVerticallyCompound { get { return isWall && (doc.Mode=="vertically_compound" || doc.Mode=="non_homogeneous"); } }
    public bool IsVerticallyHomogeneous() {
        if (doc.Mode=="homogeneous_throw") throw new Exception("secret homogeneous");
        return doc.Mode!="non_homogeneous";
    }
    public double GetWidth() { return doc.Width(); }
    public IList<CompoundStructureLayer> GetLayers() {
        if (doc.Mode=="layers_throw") throw new Exception("secret layers");
        if (doc.Mode=="layers_null") return null;
        int count=doc.Mode=="empty_layers" ? 0 : doc.Mode=="too_many_layers" ? 65 : 2;
        return Enumerable.Range(0,count).Select(i=>new CompoundStructureLayer(doc,i)).ToList();
    }
}
sealed class Document {
    public readonly string Mode;
    public int StructureReads, MaterialLookups, UidLookups;
    public Document(string mode) { Mode=mode; }
    public bool IsModifiable { get {
        if (Mode=="document_throw") throw new Exception("secret document");
        return Mode=="document_modifiable";
    } }
    public Element GetElement(string uid) {
        UidLookups++;
        if (Mode=="lookup_throw") throw new Exception("secret lookup");
        if (Mode=="missing") return null;
        if (Mode=="unsupported") return new Element(this, uid=="wall-uid"?800:801,uid,"Other");
        return uid=="wall-uid" ? (Element)new WallType(this) : new FloorType(this);
    }
    public Element GetElement(ElementId id) {
        MaterialLookups++;
        if (Mode=="material_lookup_throw") throw new Exception("secret material lookup");
        if (Mode=="material_missing") return null;
        return new Material(this,id.Value,id.Value==3002?"Steel":Mode=="material_case"?"concrete":"Concrete");
    }
    public CompoundStructure Structure(bool wall=false) {
        StructureReads++;
        if (Mode=="structure_throw") throw new Exception("secret structure");
        return Mode=="structure_null"?null:new CompoundStructure(this,wall);
    }
    public double Width() {
        if (Mode=="total_throw") throw new Exception("secret total");
        return Mode=="total_inf" ? double.PositiveInfinity : (Mode=="wrong_total" ? 300 : Mode=="membrane" ? 20 : 220)/304.8;
    }
    public IEnumerable<Element> Materials() {
        yield return new Material(this,3001,Mode=="material_case"?"concrete":"Concrete");
        yield return new Material(this,3002,"Steel");
        yield return new Material(this,3003,Mode=="ambiguous_material"?"Concrete":"Other");
    }
}
sealed class FilteredElementCollector : IEnumerable<Element> {
    readonly Document doc;
    public FilteredElementCollector(Document d) { doc=d; }
    public FilteredElementCollector OfClass(Type type) { if(type!=typeof(Material))throw new Exception("unexpected collection");return this; }
    public IEnumerator<Element> GetEnumerator() { return doc.Materials().GetEnumerator(); }
    IEnumerator IEnumerable.GetEnumerator() { return GetEnumerator(); }
}
static class Program {
    static object Query2023(Document doc) { var __results=new Dictionary<string,object>(); /* QUERY2023 */ return __results; }
    static object Query2026(Document doc) { var __results=new Dictionary<string,object>(); /* QUERY2026 */ return __results; }
    static void Main() {
        var result=new Dictionary<string,object>();
        foreach(int version in new[]{2023,2026}) foreach(string mode in new string[] { /* CASES */ }) {
            var doc=new Document(mode);
            result[version+":"+mode]=new { rows=version==2023?Query2023(doc):Query2026(doc),
                structure_reads=doc.StructureReads, material_lookups=doc.MaterialLookups, uid_lookups=doc.UidLookups };
        }
        Console.Write(JsonSerializer.Serialize(result));
    }
}
