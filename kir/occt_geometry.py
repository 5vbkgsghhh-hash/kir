"""Optional OCCT body -> self-contained, immutable geometry bundle.

Loading JSON checks a bounded manifest, bytes and hashes; it NEVER imports OCP,
parses native BRep or executes saved Python. ``read_body``/``measure`` explicitly
cross into a native parser: this is NOT a sandbox for hostile BRep. Run untrusted
native work in a separately constrained process. Hashes are integrity checks,
not signatures, proof of recipe execution, or proof of geometric equivalence.

The existing decompile.geometry_store owns L0 location/bbox; geom_extract's
GeometryStore owns quantized Revit GbSolid/GmMesh. Neither stores unquantized
OCCT BRep bytes. This small bundle is not another database or universal store.
Exact here means boundary representation, NOT exact arithmetic or BIM meaning.
"""
from __future__ import annotations

import base64
import binascii
import copy
from dataclasses import dataclass, field
from functools import lru_cache
import hashlib
import importlib.metadata
import io
import json
import math
from types import SimpleNamespace
from collections.abc import Mapping
from typing import Any

from kir.project import (ProjectError, RecipePin, _canonical, _digest, _fields,
                         _hash, _object, _thaw, output_id)


BUNDLE_SCHEMA = "kir-occt-geometry/1"
OCP_DISTRIBUTION = "cadquery-ocp-novtk"
OCP_VERSION = "7.9.3.1.1"
BINDINGS_VERSION = "7.9.3.1"
MAX_BREP_BYTES = 4 * 1024 * 1024
MAX_BUNDLE_BYTES = 16 * 1024 * 1024
MAX_MESH_VERTICES = 100_000
MAX_MESH_TRIANGLES = 100_000
_BREP_HEADER = b"\nCASCADE Topology V3, (c) Open Cascade\n"
IDENTITY_FRAME = (1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1.)


class GeometryRefusal(ValueError):
    """Named adapter refusal; previous immutable bundles remain available."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


def _number(value, field, *, positive=False):
    if type(value) not in (int, float):
        raise GeometryRefusal("invalid_input", f"{field} must be a finite number")
    try:
        result = float(value)
    except (ValueError, OverflowError) as exc:
        raise GeometryRefusal("invalid_input", f"{field} is outside numeric range") from exc
    if not math.isfinite(result) or (positive and result <= 0):
        raise GeometryRefusal("invalid_input", f"{field} must be finite" + (" and positive" if positive else ""))
    return result


def _count(value, field, maximum):
    if type(value) is not int or not 1 <= value <= maximum:
        raise GeometryRefusal("budget_exceeded", f"{field} must be 1..{maximum}")
    return value


def _vector(value, field):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise GeometryRefusal("invalid_input", f"{field} must have three coordinates")
    return tuple(_number(x, field) for x in value)


def _frame(value):
    """Row-major local-mm -> project-mm rigid, right-handed transform only."""
    if not isinstance(value, (list, tuple)) or len(value) != 16:
        raise GeometryRefusal("invalid_frame", "frame must be a 4x4 row-major matrix")
    m = tuple(_number(x, "frame") for x in value)
    if m[12:] != (0., 0., 0., 1.):
        raise GeometryRefusal("invalid_frame", "projective transforms are not supported")
    cols = [tuple(m[4 * row + col] for row in range(3)) for col in range(3)]
    for i in range(3):
        for j in range(3):
            if abs(sum(a * b for a, b in zip(cols[i], cols[j])) - (i == j)) > 1e-9:
                raise GeometryRefusal("invalid_frame", "frame must be rigid, without scale/shear")
    a, b, c = cols
    determinant = a[0] * (b[1]*c[2]-b[2]*c[1]) - b[0] * (a[1]*c[2]-a[2]*c[1]) + c[0] * (a[1]*b[2]-a[2]*b[1])
    if abs(determinant - 1) > 1e-9:
        raise GeometryRefusal("invalid_frame", "reflection requires a separate orientation contract")
    return m


def _bounded_json(value):
    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        if depth > 32:
            raise GeometryRefusal("budget_exceeded", "bundle JSON nesting exceeds 32")
        if isinstance(item, Mapping):
            pending.extend((v, depth + 1) for v in item.values())
        elif isinstance(item, (list, tuple)):
            pending.extend((v, depth + 1) for v in item)


def _mesh(value):
    _fields(value, {"vertices_mm", "triangles"}, "preview_mesh")
    vertices, triangles = value["vertices_mm"], value["triangles"]
    if not isinstance(vertices, (list, tuple)) or not isinstance(triangles, (list, tuple)):
        raise GeometryRefusal("invalid_mesh", "mesh buffers must be arrays")
    _count(len(vertices), "vertices", MAX_MESH_VERTICES)
    _count(len(triangles), "triangles", MAX_MESH_TRIANGLES)
    for point in vertices:
        _vector(point, "vertices_mm")
    for tri in triangles:
        if (not isinstance(tri, (list, tuple)) or len(tri) != 3
                or any(type(i) is not int or not 0 <= i < len(vertices) for i in tri)
                or len(set(tri)) != 3):
            raise GeometryRefusal("invalid_mesh", "triangle indices must name three distinct vertices")


def _validate(data):
    _bounded_json(data)
    _fields(data, {"schema", "manifest", "brep_base64", "preview_mesh", "bundle_sha256"}, "bundle")
    if data["schema"] != BUNDLE_SCHEMA:
        raise GeometryRefusal("unsupported_schema", "unknown geometry bundle schema")
    m = data["manifest"]
    _fields(m, {"binding", "recipe", "parameters", "source_lineage", "units", "frame",
                "backend", "brep", "preview", "measurements", "modeling_tolerance_mm",
                "semantics", "face_identity"}, "manifest")
    if m["units"] != "mm" or m["semantics"] != "geometry_only" or m["face_identity"] != "bundle_local":
        raise GeometryRefusal("unsupported_contract", "expected mm geometry-only bundle-local topology")
    _frame(m["frame"])
    _number(m["modeling_tolerance_mm"], "modeling_tolerance_mm", positive=True)
    _fields(m["backend"], {"distribution", "version", "bindings_version"}, "backend")
    if m["backend"] != {"distribution": OCP_DISTRIBUTION, "version": OCP_VERSION,
                         "bindings_version": BINDINGS_VERSION}:
        raise GeometryRefusal("unsupported_backend", "bundle requires the pinned OCCT binding")
    binding = m["binding"]
    _fields(binding, {"project_id", "instance_key", "output_key", "op_id"}, "binding")
    if binding["op_id"] != output_id(binding["project_id"], binding["instance_key"], binding["output_key"]):
        raise GeometryRefusal("integrity_mismatch", "named output address does not match op_id")
    RecipePin.from_dict(m["recipe"])
    _object(m["parameters"], "parameters")
    if not isinstance(m["source_lineage"], (list, tuple)) or any(
            not isinstance(x, str) or not x for x in m["source_lineage"]):
        raise GeometryRefusal("invalid_input", "source_lineage must be an array of nonempty strings")
    _fields(m["brep"], {"format", "sha256", "size_bytes"}, "brep")
    if m["brep"]["format"] != "occt_brep_v3_no_mesh":
        raise GeometryRefusal("unsupported_format", "expected OCCT ASCII V3 without triangulation")
    _count(m["brep"]["size_bytes"], "BRep bytes", MAX_BREP_BYTES)
    if not isinstance(data["brep_base64"], str) or len(data["brep_base64"]) > 4 * ((MAX_BREP_BYTES + 2) // 3):
        raise GeometryRefusal("budget_exceeded", "BRep encoding exceeds budget")
    try:
        raw = base64.b64decode(data["brep_base64"], validate=True)
    except (ValueError, binascii.Error) as exc:
        raise GeometryRefusal("invalid_brep_encoding", "BRep must be strict base64") from exc
    if not raw.startswith(_BREP_HEADER):
        raise GeometryRefusal("invalid_brep_encoding", "missing OCCT ASCII V3 header")
    if len(raw) != m["brep"]["size_bytes"] or hashlib.sha256(raw).hexdigest() != m["brep"]["sha256"]:
        raise GeometryRefusal("integrity_mismatch", "BRep bytes do not match manifest")
    _mesh(data["preview_mesh"])
    p = m["preview"]
    _fields(p, {"sha256", "body_sha256", "linear_deflection_mm", "angular_deflection_rad",
                "relative", "measured_upper_bound_mm"}, "preview")
    for field in ("linear_deflection_mm", "angular_deflection_rad"):
        _number(p[field], field, positive=True)
    if p["angular_deflection_rad"] > math.pi:
        raise GeometryRefusal("invalid_input", "angular deflection must not exceed pi")
    if p["relative"] is not False or p["measured_upper_bound_mm"] is not None:
        raise GeometryRefusal("unsupported_contract", "requested tessellation is not a measured error bound")
    if p["body_sha256"] != m["brep"]["sha256"] or p["sha256"] != _hash(data["preview_mesh"]):
        raise GeometryRefusal("integrity_mismatch", "preview does not match manifest")
    facts = m["measurements"]
    _fields(facts, {"volume_mm3", "area_mm2", "centroid_mm", "bbox_min_mm", "bbox_max_mm",
                    "solid_count", "face_count"}, "measurements")
    for field in ("volume_mm3", "area_mm2"):
        _number(facts[field], field, positive=True)
    for field in ("centroid_mm", "bbox_min_mm", "bbox_max_mm"):
        _vector(facts[field], field)
    if any(a > b for a, b in zip(facts["bbox_min_mm"], facts["bbox_max_mm"])):
        raise GeometryRefusal("invalid_input", "inverted measurement bbox")
    if type(facts["solid_count"]) is not int or facts["solid_count"] != 1:
        raise GeometryRefusal("unsupported_body", "first contract requires exactly one solid")
    _count(facts["face_count"], "face_count", MAX_MESH_TRIANGLES)
    _digest(data["bundle_sha256"], "bundle_sha256")
    if data["bundle_sha256"] != _hash({k: v for k, v in data.items() if k != "bundle_sha256"}):
        raise GeometryRefusal("integrity_mismatch", "bundle digest mismatch")
    if len(_canonical(data).encode("utf-8")) > MAX_BUNDLE_BYTES:
        raise GeometryRefusal("budget_exceeded", "bundle exceeds serialized size budget")


@dataclass(frozen=True, slots=True)
class GeometryBundle:
    _data: Mapping[str, Any]
    #: THIS instance's memory of ITS OWN derivatives. The bundle is immutable
    #: and named by its own BYTE digest; `rederive_preview` and `fallback_op`
    #: are deterministic functions of it and of explicit parameters, so the
    #: second answer must match the first. The memory belongs to the
    #: INSTANCE, not to the process and not to the digest: swapped bytes
    #: produce a different instance (or, before that, a `StoreCorrupt`
    #: refusal in the store), and it does not inherit its own memory.
    #: Measured 2026-09-07 (analysis of 2000 bodies): `materialize_project`
    #: called `rederive_preview` on EVERY body on every analysis — 2000
    #: bundle parses (12.1s profiled) and 2000 `fallback_op` calls with a
    #: mesh check (10.6s).
    _derived: dict = field(default_factory=dict, init=False, compare=False, repr=False)

    def __post_init__(self):
        try:
            _validate(self._data)
            object.__setattr__(self, "_data", _object(self._data, "geometry_bundle"))
        except (ProjectError, RecursionError) as exc:
            raise GeometryRefusal("invalid_bundle", str(exc)) from exc

    @property
    def digest(self):
        return self._data["bundle_sha256"]

    @property
    def body_digest(self):
        return self._data["manifest"]["brep"]["sha256"]

    @property
    def op_id(self):
        return self._data["manifest"]["binding"]["op_id"]

    def to_dict(self):
        return _thaw(self._data)

    @property
    def manifest(self):
        """A detached copy of ONLY the passport — the same as `to_dict()["manifest"]`.

        Introduced for a cost, and the cost is named: `to_dict()` thaws the
        WHOLE bundle (the BRep string and the mesh) for the sake of one
        passport field, and materialization asks for the passport twice per
        body. The copy is detached the same way as in `to_dict()`: editing the
        returned dict does not change the bundle.
        """
        return _thaw(self._data["manifest"])

    def dumps(self):
        return _canonical(self._data)

    @classmethod
    def loads(cls, source):
        if not isinstance(source, (str, bytes)):
            raise GeometryRefusal("invalid_bundle", "bundle source must be JSON text")
        try:
            raw = source.encode("utf-8") if isinstance(source, str) else source
            if len(raw) > MAX_BUNDLE_BYTES:
                raise GeometryRefusal("budget_exceeded", "bundle exceeds serialized size budget")
            def pairs(items):
                result = {}
                for key, value in items:
                    if key in result:
                        raise GeometryRefusal("invalid_bundle", "duplicate JSON object key")
                    result[key] = value
                return result
            def constant(value):
                raise GeometryRefusal("invalid_bundle", f"nonfinite JSON constant: {value}")
            return cls(json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant))
        except GeometryRefusal:
            raise
        except (UnicodeError, ValueError, RecursionError) as exc:
            raise GeometryRefusal("invalid_bundle", str(exc)) from exc

    def read_body(self):
        """Explicit native parsing, NOT a safe loader for hostile BRep bytes.

        🔴 THE FITNESS GATE IS PAID FOR ONCE PER BODY'S BYTES (2026-09-07).
        `_measure` is called here FOR THE REFUSAL, not for the number: the
        result is discarded, and only "one solid" and `BRepCheck_Analyzer` are
        checked. Measured on 2000 bodies: `read_body` 4.82s, of which
        **`_measure` 4.51s**, while the actual BRep parse is 0.31s. That is,
        thirty percent of the analysis went into re-checking the SAME bytes
        over and over: `body_sha256` is the name of exactly those bytes, and
        the gate's second answer must match the first.

        THERE IS NO WEAKENING. The body's bytes arrive only from a verified
        read: the store checks the asset payload BYTE-FOR-BYTE on every read
        (`_read_asset`), and `bundle_sha256` covers `brep_base64` in full.
        Swapped bytes produce a different `body_sha256` — a miss and the full
        gate — or a `StoreCorrupt` even earlier. The memoization does NOT
        extend to `measure()` and `rederive_preview()`: those need a NUMBER,
        and it is always computed.
        """
        k = _kernel()
        try:
            shape = k.TopoDS.TopoDS_Shape()
            k.BRepTools.BRepTools.Read_s(shape, io.BytesIO(base64.b64decode(self._data["brep_base64"])),
                                       k.BRep.BRep_Builder())
            if self.body_digest not in _VALIDATED_BODIES:
                _measure(shape, k)
                _remember_valid_body(self.body_digest)
            return shape
        except GeometryRefusal:
            raise
        except Exception as exc:
            raise GeometryRefusal("kernel_read_failed", str(exc)) from exc

    def measure(self):
        """Recompute facts explicitly; saved measurements alone are inert claims."""
        return _measure(self.read_body(), _kernel())

    def rederive_preview(self, *, max_vertices=4096, max_triangles=4096):
        """Explicit native derivation, ignoring saved mesh and measurement claims.

        Original BRep bytes, body digest, frame and source declarations remain
        unchanged. Only derived data and the whole-bundle digest are replaced.
        This is not recipe execution, an error-bound proof, or a native sandbox.

        The core is called EXACTLY ONCE per instance and set of tolerances:
        the body is immutable, the derivation is deterministic, and a repeat
        would not be a second witness — it would be the same thing computed
        again.
        """
        _count(max_vertices, "max_vertices", MAX_MESH_VERTICES)
        _count(max_triangles, "max_triangles", MAX_MESH_TRIANGLES)
        memo = ("rederive", max_vertices, max_triangles)
        remembered = self._derived.get(memo)
        if remembered is not None:
            return remembered
        try:
            k = _kernel()
            body = self.read_body()  # independently owned native shape
            # BRep may contain polygonal caches despite its asserted no-mesh
            # label. IncrementalMesh can reuse them without comparing vertices
            # to surfaces. Purge only this parsed copy before fresh derivation.
            k.BRepTools.BRepTools.Clean_s(body, True)
            faces = k.TopExp.TopExp_Explorer(body, k.TopAbs.TopAbs_FACE)
            while faces.More():
                face = k.TopoDSCast.Face_s(faces.Current())
                if k.BRep.BRep_Tool.Triangulation_s(face, k.TopLoc.TopLoc_Location()) is not None:
                    # Clean preserves polygon-only faces: they cannot supply a
                    # surface-owned rederivation and belong in mesh-only output.
                    raise GeometryRefusal("unsupported_body", "face polygon cache survived native cleanup")
                faces.Next()
            data = self.to_dict()
            preview = data["manifest"]["preview"]
            data["manifest"]["measurements"] = _measure(body, k)
            data["preview_mesh"] = _triangulate(
                body, k, preview["linear_deflection_mm"], preview["angular_deflection_rad"],
                max_vertices, max_triangles)
            preview["sha256"] = _hash(data["preview_mesh"])
            data["bundle_sha256"] = _hash({key: value for key, value in data.items()
                                          if key != "bundle_sha256"})
            derived = GeometryBundle(data)
            self._derived[memo] = derived
            return derived
        except GeometryRefusal:
            raise
        except Exception as exc:
            raise GeometryRefusal("kernel_rederive_failed", str(exc)) from exc

    def with_frame(self, frame):
        """Same body, new placement: ONLY the manifest frame and bundle digest.

        🔴 WHY THIS IS NOT A KERNEL OPERATION (measured 2026-09-07). Moving a
        body used to mean read_body() + capture_body(frame=...). For a planar
        prism the ASCII BRep survived that round trip byte for byte; for a loft
        it did NOT — parse + BRepBuilderAPI_Copy + write re-emitted the B-spline
        side faces differently, so `body_sha256` moved (e09f9279814a ->
        88464fb690b8) and a pure translation looked like a different body.

        The frame is a rigid local-mm -> project-mm transform. BRep bytes,
        preview triangles and measurements are ALL body-local: none of them
        depends on it. So a move touches neither the kernel nor the body: it
        rewrites one manifest field and rehashes. `body_sha256` is therefore
        unchanged BY CONSTRUCTION, not by a numerical accident.

        The new frame is validated like any other (rigid, right-handed, no
        scale/shear/reflection): GeometryBundle refuses what _frame refuses.
        """
        data = self.to_dict()
        data["manifest"]["frame"] = [float(value) for value in _frame(frame)]
        data["bundle_sha256"] = _hash({key: value for key, value in data.items()
                                       if key != "bundle_sha256"})
        moved = GeometryBundle(data)
        if moved.body_digest != self.body_digest:
            raise GeometryRefusal("integrity_mismatch",
                                  "a frame rebind must not touch the retained body")
        return moved

    def fallback_op(self, *, name: str, category: str = "generic_model"):
        """Project-mm triangle representation through the existing KIR validator.

        Computed once per instance and (name, category) pair: the input is
        only the bundle's immutable mesh and its frame. A FRESH copy is
        returned so the caller cannot edit someone else's memory through the
        returned value.
        """
        from kir.geometry_values import MeshValue
        from kir.mesh import validate_mesh
        memo = ("fallback", name, category)
        remembered = self._derived.get(memo)
        if remembered is not None:
            return copy.deepcopy(remembered)
        mesh = _thaw(self._data["preview_mesh"])
        frame = self._data["manifest"]["frame"]
        mesh["vertices_mm"] = [[sum(frame[4*r+i]*p[i] for i in range(3)) + frame[4*r+3]
                                 for r in range(3)] for p in mesh["vertices_mm"]]
        diagnostics = []
        if validate_mesh(mesh, self.op_id, "mesh", diagnostics) is None:
            raise GeometryRefusal("kir_fallback_refused", "; ".join(d.message_ru for d in diagnostics))
        built = MeshValue(**mesh).materialize(id=self.op_id, category=category, name=name)
        self._derived[memo] = built
        return copy.deepcopy(built)


@lru_cache(maxsize=1)
def _kernel():
    try:
        version = importlib.metadata.version(OCP_DISTRIBUTION)
        import OCP
        # ONE door into the kernel. BRepAlgoAPI/BRepOffsetAPI/BRepPrimAPI/gp were
        # added 2026-09-07 for kir.geometry_authoring: a second direct `import OCP`
        # in the tree would be a second boundary to a foreign package, and the
        # closed list (test_kir_boundary_to_the_product_is_a_closed_list) would
        # rightly name it. The pinned version is checked here exactly once.
        #
        # BRepAdaptor/BRepClass3d/BRepExtrema/GeomAbs were added 2026-09-07 for
        # kir.clash.exact and kir.refine.deviation. Those two modules had their
        # OWN `from OCP...` doors ("one door per module"), and the closed list
        # named all three plus kir.clash.project_analysis: four exits of the
        # CORE to a foreign package, three of which skipped the version pin
        # checked below. The tree has one door, not one per module.
        # GC was added 2026-09-07 for the profile arc in kir.geometry_authoring:
        # `GC_MakeArcOfCircle(start, point-on-arc, end)` — the SAME three-point
        # form that emission uses to print `Arc.Create` (`contour`,
        # decision 1). A second way to build an arc would mean a second arc.
        from OCP import (GC, BRep, BRepAdaptor, BRepAlgoAPI, BRepBndLib, BRepBuilderAPI,
                         BRepCheck, BRepClass3d, BRepExtrema, BRepGProp, BRepMesh,
                         BRepOffsetAPI, BRepPrimAPI, BRepTools, Bnd, GProp, GeomAbs,
                         TopAbs, TopExp, TopLoc, TopoDS, TopTools, gp)
        from OCP.TopoDS import TopoDS as TopoDSCast
    except (ImportError, importlib.metadata.PackageNotFoundError) as exc:
        raise GeometryRefusal("kernel_unavailable", "install kir-building[geometry]") from exc
    if version != OCP_VERSION or OCP.__version__ != BINDINGS_VERSION:
        raise GeometryRefusal("unsupported_backend", "installed OCCT binding differs from the pinned version")
    return SimpleNamespace(**{name: value for name, value in locals().items() if name not in {"version", "OCP"}})


#: Bodies whose FITNESS GATE has already been passed in this process, keyed
#: by `body_sha256`. The body's name is the name of its bytes, so an entry
#: means exactly "these BRep bytes passed `_measure` in full once." What is
#: stored is the NAME, not the shape: a mutable `TopoDS_Shape` cannot be
#: shared between readers, but 64 characters can.
_VALIDATED_BODIES: set = set()
#: The limit is named as a number: "a cache without a limit" is a leak with a
#: different name. Past it, the memoization stops remembering new entries: slower, but NEVER weaker.
_VALIDATED_BODIES_LIMIT = 200000


def _remember_valid_body(digest: str) -> None:
    if len(_VALIDATED_BODIES) < _VALIDATED_BODIES_LIMIT:
        _VALIDATED_BODIES.add(digest)


def _measure(shape, k):
    if not isinstance(shape, k.TopoDS.TopoDS_Shape) or shape.IsNull():
        raise GeometryRefusal("invalid_body", "expected a non-null OCCT shape")
    # Boolean results can wrap a single solid in a compound. Reject stray
    # faces/edges and multiple children, rather than reporting their mixture
    # as a single-body result simply because it contains one solid somewhere.
    body, depth = shape, 0
    while body.ShapeType() == k.TopAbs.TopAbs_COMPOUND:
        children = k.TopoDS.TopoDS_Iterator(body)
        if not children.More() or depth >= 32:
            raise GeometryRefusal("unsupported_body", "expected one solid, optionally compound-wrapped")
        body = children.Value()
        children.Next()
        if children.More():
            raise GeometryRefusal("unsupported_body", "compound contains multiple bodies or stray geometry")
        depth += 1
    if body.ShapeType() != k.TopAbs.TopAbs_SOLID:
        raise GeometryRefusal("unsupported_body", "first contract requires a solid")
    if not k.BRepCheck.BRepCheck_Analyzer(shape, True, False, True).IsValid():
        raise GeometryRefusal("invalid_body", "OCCT BRepCheck rejected the body")
    counts = []
    for kind in (k.TopAbs.TopAbs_SOLID, k.TopAbs.TopAbs_FACE):
        explorer = k.TopExp.TopExp_Explorer(shape, kind)
        count = 0
        while explorer.More():
            count += 1
            explorer.Next()
        counts.append(count)
    if counts[0] != 1:
        raise GeometryRefusal("unsupported_body", f"expected one solid, received {counts[0]}")
    volume, area = k.GProp.GProp_GProps(), k.GProp.GProp_GProps()
    k.BRepGProp.BRepGProp.VolumeProperties_s(shape, volume)
    k.BRepGProp.BRepGProp.SurfaceProperties_s(shape, area)
    bbox = k.Bnd.Bnd_Box()
    k.BRepBndLib.BRepBndLib.AddOptimal_s(shape, bbox, False, False)
    coords = bbox.Get()
    center = volume.CentreOfMass()
    return {"volume_mm3": _number(volume.Mass(), "volume", positive=True),
            "area_mm2": _number(area.Mass(), "area", positive=True),
            "centroid_mm": [center.X(), center.Y(), center.Z()],
            "bbox_min_mm": list(coords[:3]), "bbox_max_mm": list(coords[3:]),
            "solid_count": counts[0], "face_count": counts[1]}


def _triangulate(shape, k, linear, angular, max_vertices, max_triangles):
    """Mesh an independently owned native shape, never a caller's body."""
    mesher = k.BRepMesh.BRepMesh_IncrementalMesh(shape, linear, False, angular, False)
    if not mesher.IsDone():
        raise GeometryRefusal("kernel_mesh_failed", "OCCT mesher did not finish")
    vertices, triangles = [], []
    explorer = k.TopExp.TopExp_Explorer(shape, k.TopAbs.TopAbs_FACE)
    while explorer.More():
        face = k.TopoDSCast.Face_s(explorer.Current())
        location = k.TopLoc.TopLoc_Location()
        tri = k.BRep.BRep_Tool.Triangulation_s(face, location)
        if tri is None or not tri.NbTriangles():
            raise GeometryRefusal("kernel_mesh_failed", "a face has no triangulation")
        if len(vertices) + tri.NbNodes() > max_vertices or len(triangles) + tri.NbTriangles() > max_triangles:
            raise GeometryRefusal("budget_exceeded", "requested tessellation exceeds mesh budget; no coarsening performed")
        offset = len(vertices)
        transform = location.Transformation()
        for index in range(1, tri.NbNodes() + 1):
            point = tri.Node(index).Transformed(transform)
            vertices.append([point.X(), point.Y(), point.Z()])
        for index in range(1, tri.NbTriangles() + 1):
            a, b, c = tri.Triangle(index).Get()
            if face.Orientation() == k.TopAbs.TopAbs_REVERSED:
                b, c = c, b
            triangles.append([offset+a-1, offset+b-1, offset+c-1])
        explorer.Next()
    return {"vertices_mm": vertices, "triangles": triangles}


def capture_body(shape, *, project_id: str, instance_key: str, output_key: str,
                 recipe: RecipePin, parameters: Mapping[str, Any],
                 frame=IDENTITY_FRAME, source_lineage=(), modeling_tolerance_mm=0.01,
                 linear_deflection_mm=20.0, angular_deflection_rad=0.3,
                 max_vertices=4096, max_triangles=4096) -> GeometryBundle:
    """Copy and capture an already explicitly evaluated body, without writing files.

    No source is executed and no provenance is inferred. Budgets bound the
    captured result, not native algorithm execution; use process limits for that.
    ``modeling_tolerance_mm`` records the recipe's requested tolerance, not a
    proved Hausdorff bound. Tessellation settings have the same distinction.
    """
    _frame(frame)
    _count(max_vertices, "max_vertices", MAX_MESH_VERTICES)
    _count(max_triangles, "max_triangles", MAX_MESH_TRIANGLES)
    tolerance = _number(modeling_tolerance_mm, "modeling_tolerance_mm", positive=True)
    linear = _number(linear_deflection_mm, "linear_deflection_mm", positive=True)
    angular = _number(angular_deflection_rad, "angular_deflection_rad", positive=True)
    if angular > math.pi:
        raise GeometryRefusal("invalid_input", "angular deflection must not exceed pi")
    if not isinstance(recipe, RecipePin):
        raise GeometryRefusal("invalid_input", "recipe must be an inert RecipePin")
    if not isinstance(source_lineage, (list, tuple)) or any(
            not isinstance(item, str) or not item for item in source_lineage):
        raise GeometryRefusal("invalid_input", "source_lineage must be an array of nonempty strings")
    try:
        parameters = _object(parameters, "parameters")
        identifier = output_id(project_id, instance_key, output_key)
        k = _kernel()
        facts = _measure(shape, k)
        # Copy first: meshing and certain OCCT algorithms mutate attached data.
        copied = k.BRepBuilderAPI.BRepBuilderAPI_Copy(shape, True, False).Shape()
        stream = io.BytesIO()
        k.BRepTools.BRepTools.Write_s(copied, stream, False, False,
                                    k.TopTools.TopTools_FormatVersion.TopTools_FormatVersion_VERSION_3)
        brep = stream.getvalue()
        _count(len(brep), "BRep bytes", MAX_BREP_BYTES)
        body_digest = hashlib.sha256(brep).hexdigest()
        mesh = _triangulate(copied, k, linear, angular, max_vertices, max_triangles)
        manifest = {
            "binding": {"project_id": project_id, "instance_key": instance_key,
                        "output_key": output_key, "op_id": identifier},
            "recipe": recipe.to_dict(), "parameters": _thaw(parameters),
            "source_lineage": list(source_lineage), "units": "mm", "frame": list(frame),
            "backend": {"distribution": OCP_DISTRIBUTION, "version": OCP_VERSION,
                        "bindings_version": BINDINGS_VERSION},
            "brep": {"format": "occt_brep_v3_no_mesh", "sha256": body_digest, "size_bytes": len(brep)},
            "preview": {"sha256": _hash(mesh), "body_sha256": body_digest,
                        "linear_deflection_mm": linear, "angular_deflection_rad": angular,
                        "relative": False, "measured_upper_bound_mm": None},
            "measurements": facts, "modeling_tolerance_mm": tolerance,
            "semantics": "geometry_only", "face_identity": "bundle_local",
        }
        data = {"schema": BUNDLE_SCHEMA, "manifest": manifest,
                "brep_base64": base64.b64encode(brep).decode("ascii"), "preview_mesh": mesh}
        data["bundle_sha256"] = _hash(data)
        return GeometryBundle(data)
    except GeometryRefusal:
        raise
    except ProjectError as exc:
        raise GeometryRefusal("invalid_input", str(exc)) from exc
    except Exception as exc:
        raise GeometryRefusal("kernel_capture_failed", str(exc)) from exc


__all__ = ["GeometryRefusal", "GeometryBundle", "capture_body", "IDENTITY_FRAME"]
