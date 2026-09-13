"""JSON Schema deduplication via `$defs`/`$ref` — WITHOUT losing expressiveness.

THE TRIGGER IS MEASURED (03.08.2026). The KIR schema is 22 631 tokens, and
that is 70.7% of everything sent to the model on the first turn (44 615). At
the same time **66% of the schema is verbatim repetition**: the selector
`{by: name|element_id|default|family_type}` is spelled out anew 27–102
times, because `schema_gen._catalog_selector` expands the full `oneOf` for
EVERY selector parameter of EVERY op.

WHY THIS COMES BEFORE TIERS. A measurement of three variants:

    today                          22 631 tokens   1.00x
    all 39 ops + $ref               7 719 tokens   2.93x   ← nothing hidden
    tier 1 (21 ops), no $ref       11 669 tokens   1.94x
    tier 1 + $ref                   4 488 tokens   5.04x

Deduplication ALONE beats tiers and costs **zero honesty**: not a single op
disappears from the context. Tiers, on the other hand, pay with visibility,
and the price is already measured — from the refusal log, 4.8% of
compilations are FABRICATED ops (`create_rebar`, `create_elevator`,
`create_vent_shaft`): what the model does not see, it makes up.

WHY A POST-PASS, NOT A CHANGE TO THE GENERATOR. Writing `$defs` by hand would
mean setting up a second source of truth about the selector's shape: the
generator changes — the table falls behind, and the schema starts
describing the wrong language. Here, instead, the common subtrees are FOUND
in the finished schema, so there is nothing for it to diverge from the
generator on, by construction. And, most important — the transformation is
REVERSIBLE, so the identity is not a promise but a checkable fact:
`expand(hoist(s)) == s` byte for byte (test `test_schema_dedup.py`).

WHAT IS NOT DONE HERE. The schema is not shortened "by meaning": not a
single constraint is loosened, not a single `description` is dropped. The
saving comes exclusively from repetition. If cutting meaning is ever needed
— that is a different decision, with a different price, and it must be made
separately.

WIRED IN ON 09.08.2026 — and wired in NOT HERE. `program_schema()` still
returns the flat schema (one source of truth about the language), and the
extraction is done by `schema_transport.program_schema_for_tool()` at the
tool boundary — `serving.inject_revit_ir_schema`. The condition there is
MEASURED, not assumed: `$ref` arrives intact and is four times cheaper on
both live transports (openrouter/deepseek 42 390→11 751 tokens,
openai/gpt-5.6-sol via CLIProxy 20 628→3 633, both pairs — HTTP 200), while
on gemini/vertex litellm expands `$defs` back by itself, so the extraction
is not applied there: it would save nothing.

AN OPEN RISK, NAMED HONESTLY AND STILL OPEN: whether the working model holds
onto `$defs`/`$ref` as well as it does a flat schema. Constrained decoding is
OFF in prod — the schema travels to the model as text — so this is about
understanding, not decoder grammar. It is measured that references ARRIVE
and that they are CHEAPER; it is NOT measured that the model builds from
them just as well. This is an A/B on `kir_dojo`/`mission_bench`, and it now
costs one variable: `KUKAI_KIR_SCHEMA_DEDUP=0` — the flat arm, `=1` — the
collapsed one, the rest of the run byte-for-byte the same.
"""
from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from kir.emit_utils import ELEMENT_ID_MAX

#: Threshold: a subtree lands in `$defs` only if it is WORTHWHILE. The
#: condition is computed, not assigned — see `_net_saving`.
_REF_OVERHEAD = len('{"$ref":"#/$defs/"}')

#: The minimum length of the canonical representation. Below it a reference
#: is almost always more expensive than the body (`{"type":"string"}` — 19
#: bytes against 26 for the reference), and hoisting would make the schema
#: BIGGER while still formally being "deduplication".
_MIN_BODY = 40


def _canon(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


#: Keywords whose VALUE is itself a schema.
_SCHEMA_VALUE = frozenset({
    "items", "additionalProperties", "propertyNames", "contains", "not",
    "if", "then", "else", "additionalItems", "unevaluatedItems",
    "unevaluatedProperties",
})

#: Keywords whose value is A LIST of schemas.
_SCHEMA_LIST = frozenset({"oneOf", "anyOf", "allOf", "prefixItems"})

#: Keywords whose value is A MAP "name → schema". The map itself is NOT a
#: schema — only its values are.
_SCHEMA_MAP = frozenset({
    "properties", "$defs", "definitions", "patternProperties",
    "dependentSchemas",
})


def _walk(node: Any):
    """Subtrees standing in a SCHEMA POSITION, except the root.

    POSITION DECIDES EVERYTHING, and this is not pedantry — it is
    correctness. The first edition walked the dict indiscriminately and
    hoisted, among other things, the `properties` map as a whole. The result
    was `{"type":"object","properties":{"$ref":"#/$defs/..."}}`, and such a
    schema is REVERSIBLE (the identity test let it through), but INVALID:
    inside `properties` the key `$ref` is read as the name of a property
    called "$ref", not as a reference. That is, the model would get an
    object that "has a property $ref", instead of a description of the
    operation.

    Caught by the name-readability test on 03.08 — it complained about 44
    unnamed forms, and behind that cosmetic issue lay a real defect. The
    lesson is exactly the one already recorded in this package: identity is
    NOT ENOUGH, the intermediate form must also be valid in its own right.
    """
    if isinstance(node, dict):
        yield from _walk_children(node)


def _walk_children(node: dict):
    for key, value in node.items():
        if key in _SCHEMA_VALUE:
            yield from _walk_schema(value)
        elif key in _SCHEMA_LIST and isinstance(value, list):
            for item in value:
                yield from _walk_schema(item)
        elif key in _SCHEMA_MAP and isinstance(value, dict):
            for item in value.values():
                yield from _walk_schema(item)


def _walk_schema(node: Any):
    """A node IN A SCHEMA POSITION: it is itself a candidate, and so are its children."""
    if isinstance(node, dict):
        yield node
        yield from _walk_children(node)


def _net_saving(body_len: int, occurrences: int, name_len: int) -> int:
    """How many bytes hoisting saves: it was `n * body`, it became `body + n * ref`."""
    ref_len = _REF_OVERHEAD + name_len
    return occurrences * body_len - (body_len + occurrences * ref_len)


def _num(value: Any) -> str:
    """A number in the name: no trailing tail and no dot, a minus sign spelled out as a word."""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).replace(".", "p")
    return text.replace("-", "neg")


def _ref_tail(node: Any) -> str | None:
    """A short name for a nested node: the tail of a reference, or the name of its own shape.

    Names are assigned BEFORE references are substituted, so a nested node
    here is almost always still expanded. The `$ref` branch is kept for a
    repeat call on an already-collapsed tree — otherwise the name would
    depend on processing order, and it must depend only on the content.
    """
    if not isinstance(node, dict):
        return None
    ref = node.get("$ref")
    if isinstance(ref, str):
        return ref.rsplit("/", 1)[-1]
    return _semantic_name(node)


#: 🔴 THE SUBJECT OF A POINT, READ OFF ITS NAME (13.09.2026). A union of point
#: forms is named by WHERE the point comes from, because that is the whole
#: question the model has about the slot: a world coordinate, an address on the
#: grids, or a point taken from an element of this same program. The classes are
#: recognized from the names of the members, which were themselves recognized
#: structurally — nothing is guessed here.
_POINT_ORIGINS = ("world", "grid", "element")


def _point_classes(tail: str | None) -> set[str] | None:
    """Where a point form may come from, or None when this is not a point form.

    A union of unions is absorbed rather than re-derived: `point_xyz_element`
    is itself a name this function produced, and its classes are written in it.
    """
    if not tail:
        return None
    if tail.startswith("point_at_element"):
        return {"element"}
    if tail.startswith("pt_xy"):          # pt_xy, pt_xyz and their bounded forms
        return {"world"}
    if tail.startswith("grid_address_"):
        return {"grid"}
    if tail.startswith("point_xy"):       # a union named by this same rule
        found = {origin for origin in _POINT_ORIGINS if origin in tail.split("_")}
        return found or None
    return None


#: A description that names its subject in ONE word. The schema says it itself;
#: reading it is not inventing meaning. The list is closed on purpose — the day
#: it grows into prose matching, it stops being recognition.
_DESCRIBED = {"VersionGuid": "version_guid", "UniqueId": "unique_id"}


def _semantic_name(body: dict) -> str | None:
    """A readable name, for when the shape can be RECOGNIZED.

    The name is seen by the MODEL, and `#/$defs/pt_xy` explains the shape to
    it, while `#/$defs/shape_30` does not. There is one rule: we name only
    what is recognized structurally. Inventing a "meaningful" name where no
    meaning was derived is worse than an honest sequence number — that is
    exactly the substitution this package is paying for.
    """
    keys = set(body)

    # A selector: an object with `by: {"const": ...}`.
    props = body.get("properties")
    if isinstance(props, dict):
        by = props.get("by")
        if isinstance(by, dict) and isinstance(by.get("const"), str):
            return f"sel_by_{by['const']}"
        # A contour/region: an object with `shape: {"const": ...}`.
        shape = props.get("shape")
        if isinstance(shape, dict) and isinstance(shape.get("const"), str):
            return f"region_{shape['const']}"
        # RELATE: an address from grids — an object with `at_grid`. The
        # dimensionality is visible from the presence of `z_mm`, and this is
        # exactly the case the rule was written for: the shape is RECOGNIZED
        # structurally, not guessed.
        if "at_grid" in props:
            if "offset_mm" in props:
                return "grid_address_world_offset"
            return "grid_address_xyz" if "z_mm" in props else "grid_address_xy"
        # The <line> node in its full form: a grid name plus an optional offset.
        if set(props) <= {"grid", "offset_mm", "toward"} and "grid" in props:
            return "grid_line"
        # The READ BASE of a write: {unique_id, version_guid}. Recognized
        # structurally by exactly those two keys — the pair comes from one
        # place (`element_identity` of a receipt / `query_element_state`), so
        # naming it tells the model where to GET it, which is the whole
        # difficulty of this slot. `shape_20` told it nothing.
        if set(props) == {"unique_id", "version_guid"}:
            return "read_identity"
        # A region with holes: an outer contour that is required, holes that are
        # not. The pair of keys IS the form, and «region_with_holes» tells the
        # model what to put where; `shape_0` told it nothing.
        if set(props) <= {"outer", "holes"} and body.get("required") == ["outer"]:
            return "region_with_holes"
        # A point taken from an ELEMENT of this same program. The z-form is part
        # of the subject: a named level face, an elevation in millimetres, or
        # neither (a plan point).
        if "at_element" in props and set(props) <= {"at_element", "point", "z", "z_mm"}:
            if "z_mm" in props:
                return "point_at_element_z_mm"
            return "point_at_element_z_level" if "z" in props else "point_at_element"
        # The sketch plane of an extrusion: an origin and a normal.
        if {"normal", "origin_mm"} <= set(props):
            return "sketch_plane"
        # A node of a routed graph: its own id and where it stands.
        if set(props) == {"id", "xyz_mm"}:
            return "graph_node"
        # An edge of a contour, bowed: the edge number plus the bow.
        if "edge" in props and set(props) <= {"edge", "bulge", "dir", "radius_mm"}:
            return "edge_arc"
        # An edge of a contour, routed through explicit points.
        if set(props) == {"edge", "via_mm"}:
            return "edge_via_points"
        # One parameter assignment: the name and the value.
        if set(props) == {"param", "value"}:
            return "param_assignment"
        # A measured value: the number and the unit it is in. This is the form
        # the compiler demands instead of a bare number (`KIR-T001`).
        if set(props) == {"value", "unit"}:
            return "measured_value"
        # The filters of a query, recognized by their closed set of keys.
        if set(props) == {"level_name", "name_contains", "structural"}:
            return "query_filters"
        # A value carried by ONE named key: `{"material": …}`. The key is the
        # subject, so it goes into the name.
        if len(props) == 1 and body.get("required") == list(props):
            return "only_" + next(iter(props))

    # A union of selectors — we enumerate the kinds, that is exactly its meaning.
    if keys == {"oneOf"} and isinstance(body["oneOf"], list):
        tails = [_ref_tail(v) for v in body["oneOf"]]
        if all(t and t.startswith("sel_by_") for t in tails):
            return "sel_" + "_or_".join(t[len("sel_by_"):] for t in tails)
        if all(isinstance(v, dict) and set(v) == {"type"} for v in body["oneOf"]):
            return "scalar_" + "_or_".join(v["type"] for v in body["oneOf"])
        # A union of regions — the shapes it admits are its meaning.
        if all(t and t.startswith("region_") for t in tails):
            return "region_" + "_or_".join(t[len("region_"):] for t in tails)
        # A union of point forms — named by WHERE the point may come from, and
        # by its dimensionality. Both are read off the members, not guessed.
        classes = [_point_classes(t) for t in tails]
        if classes and all(classes):
            present = set().union(*classes)
            order = [origin for origin in _POINT_ORIGINS if origin in present]
            xyz = any(t and ("xyz" in t or t.endswith("_z_mm") or t.endswith("_z_level"))
                      for t in tails)
            return f"point_{'xyz' if xyz else 'xy'}_" + "_".join(order)
        # A union of the forms a PARAMETER VALUE may take: a scalar, a measured
        # value, or a value carried by one named key.
        if any(t == "measured_value" for t in tails) or any(
                t and t.startswith("only_") for t in tails):
            return "param_value_any"
        # An axis: either a name, or a grid line with an offset.
        if set(t for t in tails if t) == {"str_64", "grid_line"}:
            return "axis_name_or_grid_line"

    # Arrays.
    if body.get("type") == "array":
        items = body.get("items")
        lo, hi = body.get("minItems"), body.get("maxItems")
        if isinstance(items, dict) and set(items) == {"type"} and lo == hi:
            if items["type"] == "number":
                return {2: "pt_xy", 3: "pt_xyz"}.get(lo) or f"nums_{lo}"
            return f"{items['type']}s_{lo}"
        # The same fixed-length tuple of numbers, but bounded. The bound IS the
        # meaning of this slot, exactly as it is for a bare number below.
        if (isinstance(items, dict) and set(items) <= {"type", "minimum", "maximum"}
                and items.get("type") == "number" and lo == hi and lo in (2, 3)):
            base = {2: "pt_xy", 3: "pt_xyz"}[lo]
            low, high = items.get("minimum"), items.get("maximum")
            if low is not None and high is None:
                return f"{base}_min_{_num(low)}"
            if low is None and high is not None:
                return f"{base}_max_{_num(high)}"
            if low is not None:
                return f"{base}_{_num(low)}_{_num(high)}"
        tail = _ref_tail(items)
        if tail:
            span = (f"_{_num(lo)}_{_num(hi)}" if lo is not None and hi is not None
                    else "")
            return f"list_{tail}{span}"

    # Numbers and strings with bounds — the bound IS their meaning.
    if keys <= {"type", "minimum", "maximum"} and body.get("type") in (
            "number", "integer"):
        lo, hi = body.get("minimum"), body.get("maximum")
        if body["type"] == "integer" and lo == 1 and hi == ELEMENT_ID_MAX:
            return "element_id"
        if lo is not None and hi is not None:
            return f"{body['type']}_{_num(lo)}_{_num(hi)}"
    if keys <= {"type", "minLength", "maxLength", "pattern"} and body.get(
            "type") == "string" and body.get("maxLength") is not None:
        trimmed = "_trimmed" if "pattern" in body else ""
        if body.get("minLength") == body.get("maxLength"):
            return f"str_{_num(body['maxLength'])}_exact{trimmed}"
        return f"str_{_num(body['maxLength'])}{trimmed}"
    # A string that may not be one of a named set: the exclusion is its subject.
    if keys <= {"type", "minLength", "maxLength", "not"} and body.get(
            "type") == "string" and isinstance(body.get("not"), dict):
        excluded = _ref_tail(body["not"])
        if excluded:
            cap = _num(body["maxLength"]) if body.get("maxLength") is not None else "any"
            return f"str_{cap}_not_{excluded}"
    # A string whose description names its subject in one word (closed list).
    if body.get("type") == "string" and isinstance(body.get("description"), str):
        head = body["description"].split(",")[0].split()[0]
        if head in _DESCRIBED:
            return _DESCRIBED[head]

    # Enumerations: a dict of kinds is recognized by its composition, the rest by the head of the list.
    if keys <= {"type", "enum"} and isinstance(body.get("enum"), list):
        values = body["enum"]
        if set(values) == set(_kind_enum_values()):
            return "kind_enum"
        if all(isinstance(v, str) for v in values) and len(values) <= 4:
            return "enum_" + "_".join(values)
        return f"enum_{len(values)}"
    return None


def _kind_enum_values() -> list[str]:
    """A dict of object kinds — read from the registry, not rewritten."""
    from kir import spec
    return sorted(spec.KINDS) + [spec.KIND_ESCAPE]


def hoist(schema: dict) -> dict:
    """A schema with `$defs`: repeating subtrees hoisted out, everything else as before.

    Deterministic: names and order depend only on the schema's CONTENT, not
    on traversal order and not on the Python version. Otherwise the same
    registry would produce different schemas between runs, and any hash
    built on top of it would become meaningless.
    """
    if not isinstance(schema, dict):
        raise TypeError("hoist ожидает объект схемы")
    if "$defs" in schema:
        raise ValueError("схема уже содержит $defs — повторный хойст запрещён")

    counts: dict[str, int] = {}
    bodies: dict[str, dict] = {}
    for node in _walk(schema):
        key = _canon(node)
        counts[key] = counts.get(key, 0) + 1
        bodies.setdefault(key, node)

    # Candidates: occur more than once AND hoisting is WORTHWHILE. Sorted by
    # (descending length, canon) — long ones first, so that nested common
    # pieces get picked up too; canon as the second key gives full
    # determinism.
    candidates = sorted(
        (key for key, count in counts.items()
         if count > 1 and len(key) >= _MIN_BODY),
        key=lambda key: (-len(key), key))

    names: dict[str, str] = {}
    used: set[str] = set()
    for index, key in enumerate(candidates):
        body = bodies[key]
        name = _semantic_name(body) or f"shape_{index}"
        if name in used:
            name = f"{name}_{index}"
        if _net_saving(len(key), counts[key], len(name)) <= 0:
            continue
        names[key] = name
        used.add(name)

    if not names:
        return json.loads(_canon(schema))

    def in_schema_position(node: Any, *, skip: str | None) -> Any:
        """Substitution is allowed HERE: the node stands where a schema is expected."""
        if isinstance(node, dict):
            key = _canon(node)
            if key in names and key != skip:
                return {"$ref": f"#/$defs/{names[key]}"}
            return descend(node, skip=skip)
        return node

    def descend(node: dict, *, skip: str | None) -> dict:
        """Descending by keys: a reference may be substituted only in schema
        positions, while data (`const`, `enum`, `required`, `description`)
        passes through as is."""
        out: dict = {}
        for key, value in node.items():
            if key in _SCHEMA_VALUE:
                out[key] = in_schema_position(value, skip=skip)
            elif key in _SCHEMA_LIST and isinstance(value, list):
                out[key] = [in_schema_position(item, skip=skip)
                            for item in value]
            elif key in _SCHEMA_MAP and isinstance(value, dict):
                out[key] = {name: in_schema_position(item, skip=skip)
                            for name, item in value.items()}
            else:
                out[key] = value
        return out

    defs = {names[key]: descend(bodies[key], skip=key)
            for key in sorted(names, key=lambda k: names[k])}
    out = descend(schema, skip=None)
    # `$defs` is placed AFTER the other keys: the schema's header must read
    # first, for both a human and the model.
    out["$defs"] = defs
    return out


def expand(schema: dict) -> dict:
    """The inverse function: return a flat schema by expanding all `$ref`s.

    It exists not for convenience but for proof. As long as `expand(hoist(s))`
    equals `s` byte for byte, the claim "we lost nothing" is a fact that a
    machine checks. Without it, this would be a promise, and promises in
    this house have already let us down.
    """
    defs = schema.get("$defs") or {}
    if not isinstance(defs, dict):
        raise ValueError("$defs должен быть объектом")

    def resolve(node: Any, depth: int = 0) -> Any:
        """The expansion walks the SAME positions the hoisting walked.

        Symmetry is mandatory: expanding wider than was collapsed would mean
        mistaking for a reference some data that simply happens to have a
        `$ref` key (and such a field can in principle occur inside `const`
        or `enum`).
        """
        if depth > 32:
            raise ValueError("циклическая ссылка $ref")
        if not isinstance(node, dict):
            return node
        ref = node.get("$ref")
        if isinstance(ref, str) and len(node) == 1:
            prefix = "#/$defs/"
            if not ref.startswith(prefix):
                raise ValueError(f"неподдерживаемая ссылка {ref!r}")
            name = ref[len(prefix):]
            if name not in defs:
                raise ValueError(f"висячая ссылка {ref!r}")
            return resolve(defs[name], depth + 1)
        out: dict = {}
        for key, value in node.items():
            if key in _SCHEMA_VALUE:
                out[key] = resolve(value, depth)
            elif key in _SCHEMA_LIST and isinstance(value, list):
                out[key] = [resolve(item, depth) for item in value]
            elif key in _SCHEMA_MAP and isinstance(value, dict):
                out[key] = {name: resolve(item, depth)
                            for name, item in value.items()}
            else:
                out[key] = value
        return out

    # The root IS the schema itself, and it must be expanded as a whole, not
    # key by key. A key-by-key walk called `resolve` on the VALUE of the
    # `properties` key, that is, on the map "name → schema", not on a
    # schema; inside the map property names are not keywords, and references
    # underneath them stayed unexpanded. Caught only by checking identity —
    # invisible to the eye.
    return resolve({key: value for key, value in schema.items()
                    if key != "$defs"})


def lift_property_defs(schema: dict, property_name: str) -> dict:
    """Embed one generated anonymous schema in an object without dangling refs.

    Hoisted `#/$defs/...` references address the whole schema resource, not
    the nearest property. Move its definitions to that root on a detached
    copy. This is not a general bundler for independently identified resources.
    """
    result = deepcopy(schema)
    child = result["properties"][property_name]
    if "$defs" not in child:
        return result
    if "$id" in child:
        raise ValueError("cannot lift definitions from an independent schema resource")
    definitions = child["$defs"]
    existing = result.get("$defs", {})
    if not isinstance(definitions, dict) or not isinstance(existing, dict):
        raise ValueError("$defs must be an object")
    if existing.keys() & definitions.keys():
        raise ValueError("embedded schema definition names collide with the wrapper")
    result["$defs"] = {**existing, **child.pop("$defs")}
    return result


def measure(schema: dict) -> dict:
    """What the hoist gained — in numbers, not by feel."""
    flat = _canon(schema if "$defs" not in schema else expand(schema))
    packed = _canon(hoist(schema) if "$defs" not in schema else schema)
    return {
        "flat_bytes": len(flat),
        "packed_bytes": len(packed),
        "ratio": round(len(flat) / len(packed), 3) if packed else 0.0,
        "defs": len((hoist(schema) if "$defs" not in schema
                     else schema).get("$defs", {})),
    }


__all__ = ["expand", "hoist", "lift_property_defs", "measure"]
