# KIR cheat sheet — write a building as a program

This page is the whole surface you need to author, compile and apply the ten
task families below. Every code block on this page is executed and compiled for
Revit 2023 and 2026 by `tools/cheatsheet_check.py`; a block that stops compiling
fails that check.

`kir` never guesses. Where a value is missing it refuses **by name** and prints
the next move, in Russian, exactly as quoted in the refusal table at the end.

---

## 1. The shape of a program

```text
envelope(...)          one per program: intent, and permissions such as allow_destructive
  op, op, op ...       the operations, in order; each returns a handle
program = build()      the finished program object
compile_program(program, revit_version="2023"|..."2026", snapshot=..., bulk=True)
  -> out.ok            True when the program is ready to run
  -> out.csharp        the generated C# for that Revit version
  -> out.diagnostics   refusals: .code, .message_ru
```

Three facts that decide most questions:

* **Units are millimetres.** Every length argument ends in `_mm`. Angles end in
  `_deg`. A plain number in a `value:` slot is refused (`KIR-T001`).
* **Points are lists.** `p0_mm=[x, y]` in plan, `xyz=[x, y, z]` in space.
  The coordinate limit is 16 000 000 mm from the origin.
* **A handle is a reference.** `wall = create_wall(...)` can be passed straight
  into `host=wall`; no id bookkeeping.

A program is authored, then compiled, then applied. Authoring never touches
Revit; compiling never touches Revit; only the applied C# does.

---

## 2. Selectors: how to point at a thing

Four forms. Which ones a slot accepts is part of that slot's contract.

```text
by_element_id(8145901)                 # {"by": "element_id", "value": 8145901}
by_name("Level 1")                     # {"by": "name", "value": "Level 1"}
by_name("Generic - 200", kind="wall_types")
by_default()                           # the document's default for that pool
by_ref(wall)                           # a handle produced earlier in this program
```

| slot | accepts |
|---|---|
| `create_wall.level`, `.type`, `.top_level` | `name`, `element_id`, `default`, `ref` |
| `create_floor_by_contour.level`, `.type` | `name`, `element_id`, `default`, `ref` |
| `create_door.symbol`, `create_window.symbol` | `name`, `element_id`, `default`, `ref` |
| `place_family.symbol` | `name`, `element_id`, `default`, `family_type`, `ref` |
| `create_door.host`, `create_window.host`, `create_opening.host` | `element_id`, `ref` |
| `set_param.target`, `delete.target`, `move_elements.targets` | `element_id`, `ref` |

**A mutation never takes a name.** `set_param(target=by_name("Wall 1"), ...)`
is refused with `KIR-T001`: two walls can carry one name, and a silent choice
between them is indistinguishable from the right one. Read the id first
(`query_list`), then mutate by id.

---

## 3. The catalogue (snapshot)

Names such as `"0915 x 2134mm"` or `"Level 1"` are resolved against the
document's catalogue. Pass it to `compile_program` as `snapshot=`:

```text
snapshot = {
  "levels":        [{"id": 311, "name": "Level 1", "elev_mm": 0.0}],
  "wall_types":    [{"id": 400, "name": "Generic - 200"}],
  "floor_types":   [{"id": 500, "name": "Generic 150mm"}],
  "door_symbols":  [{"id": 700, "name": "0915 x 2134mm"}],
  "window_symbols":[{"id": 701, "name": "0915 x 1220mm"}],
  "family_symbols":[{"id": 800, "name": "1200x600mm"}],
}
```

* no snapshot, but a name or a default is used → `KIR-G103`;
* a snapshot that does not carry that name → `KIR-G101`, with the pool named;
* only ids and handles → no snapshot needed at all.

---

## 4. Operation reference

Required arguments first, then optional with their defaults. `sel` is a
selector from §2.

### Levels and walls

```text
create_level(elev_mm, *, name=None)                                  -> level
create_wall(p0_mm, p1_mm, level, *, height_mm=3000.0, type=None,
            arc=None, base_offset_mm=None, location_line=None,
            top_level=None, top_offset_mm=None)                      -> wall
```
* `location_line` is one of the Revit wall location lines; omit it to keep the
  type's own.
* `arc={"bulge": 0.4}` turns the segment into an arc; omit for a straight wall.
* A wall bound by `top_level` ignores `height_mm`.

### Openings in walls: doors and windows

```text
create_door(host, offset_mm, *, sill_mm=None, symbol=None,
            mirrored=False, hand_flipped=False, facing_flipped=False)
create_window(host, offset_mm, *, sill_mm=900.0, symbol=None,
              mirrored=False, hand_flipped=False, facing_flipped=False)
```
* `offset_mm` is measured **along the host wall from its start point**, not in
  world coordinates.
* If the host wall is moved later in the same program, the final position of the
  door follows the host. The receipt reports the position that resulted.

### Floors and openings through them

```text
create_floor_by_contour(contour, level, *, type=None,
                        height_offset_mm=None)                       -> floor
create_opening(variety, *, host=None, p0_mm=None, p1_mm=None,
               outline=None, contour=None, cut=None)
```
* `variety="wall_rect"` cuts a rectangle in a wall between `p0_mm` and `p1_mm`
  (both `[x, y, z]`).
* `variety="host_face"` cuts through a floor, roof or ceiling. Give either
  `outline=[[x, y], ...]` (a closed polygon, listed once) or a `contour`, plus
  `cut="vertical"` or `cut="perpendicular"`.
* A `contour` is `{"outer": {"shape": "poly", "points_mm": [[x, y], ...]}}`.
  An edge may be bowed: `"arcs": [{"edge": 1, "bulge": 0.4}]`.
* An opening whose loop leaves the floor's profile, crosses it, touches it
  within 1 mm or nests inside an existing opening is refused **before any
  effect**, and the unit rolls back if the observed area change disagrees with
  the loop area.

### Families

```text
load_family(path, *, type_name=None)                                 -> symbol
place_family(*, xyz=None, p0_mm=None, p1_mm=None, host=None, level=None,
             symbol=None, rotation_deg=0.0, mirrored=False,
             hand_flipped=False, facing_flipped=False, ref_dir=None,
             top_level=None, base_offset_mm=None, top_offset_mm=None)
create_type(source_type, new_name, width_mm, *, category="structural",
            depth_mm=None, param_width_name="b", param_depth_name="h",
            material=None)                                           -> symbol
```
* `load_family(path=...)` takes a path **on the machine that runs Revit**.
  Its result is a symbol handle: pass it to `place_family(symbol=...)`.
  A family is loaded once; the type is activated before the first placement.
* `create_type` derives a new type from an existing one by width (and depth).

### Columns and beams

```text
create_column(xy, level, *, category="structural", symbol=None,
              rotation_deg=0.0, top_xy=None, base_offset_mm=None,
              top_level=None, top_offset_mm=None)
create_beam(p0_mm, p1_mm, level, *, symbol=None)
```
* `category` is `"structural"` or `"architectural"`, and it chooses the
  catalogue the symbol is resolved against: `column_symbols_structural` or
  `column_symbols_architectural`. A structural name looked up in the
  architectural pool is `KIR-G101`, not a near match.
* A column is bound by `top_level` (preferred) or by `top_offset_mm`.
  `top_xy` makes it slanted: the top lands over that plan point.
* `create_beam` takes two **spatial** points (`[x, y, z]`), not plan points.

### Pipe and duct routes

```text
route_pipe_system(nodes, segments, level, *, system_type=None,
                  pipe_type=None, diameter_mm=None)
route_duct_system(nodes, segments, level, *, system_type=None,
                  duct_type=None, diameter_mm=None)
```
* `nodes` is a list of `{"id": "n1", "xyz_mm": [x, y, z]}` — the ids are yours
  and live only inside this call.
* `segments` is a list of `{"from": "n1", "to": "n2"}`. A segment naming an id
  that is not in `nodes` is refused before emission.
* The catalogues are named per route: pipes resolve `system_type` against
  `piping_system_types` and `pipe_type` against `pipe_types`; ducts resolve
  `system_type` against `duct_system_types` and `duct_type` against
  `duct_types`.
* `diameter_mm` applies to the whole route. Fittings at the corners are
  Revit's own; KIR does not place them one by one.

### Rooms

```text
create_room(xy, level, *, name=None, function=None, number=None,
            upper_offset_mm=None)
```
* A room needs an enclosure that already exists at the point `xy`. In ONE
  program the walls must be authored BEFORE the room; if the contour is built
  by a neighbouring move, the room belongs to the NEXT program — otherwise
  Revit returns area 0 and the postcondition rolls the transaction back.
* 🔴 **Name `upper_offset_mm`.** `NewRoom` takes the document's default upper
  limit (8 feet = **2438 mm**), which is BELOW the habitability norm of
  **2500 mm**, so rule **HAB022** will justly call the room unfit. The default
  is Revit's, not KIR's, and KIR does not quietly replace it.
* 🔴 **Name `function`.** Without it the kind of the room is GUESSED from
  `name` by a dictionary that knows 23 names out of 81 across eight languages —
  and in German not one. The closed list is:
  `жилая`, `кухня`, `санузел`, `коридор`, `лестница`, `лифт_холл`, `прихожая`,
  `входная_группа`, `тех`, `прочее`.

### Editing what is already there

```text
set_param(target, param, value)
move_elements(targets, delta_mm)
delete(target)                      # requires envelope(allow_destructive=True)
join_elements(first, second)
```
* `value` is `{"value": 3300, "unit": "mm"}` for a length, `{"value": 30,
  "unit": "raw"}` for a number in Revit's own units, a plain string for text,
  `True`/`False` for a flag. A bare number is refused: `KIR-T001`.
* `move_elements(targets=[...])` takes a **list**, and `delta_mm` is `[dx, dy, dz]`.
* `delete` removes the element together with everything Revit destroys with it.
  Ask for the dependents before you delete, not after.

### Reading the model

```text
query_list(kind, *, where=None,
           fields=["id","name","category","type_name","level_name"], limit=100)
query_count(kind, *, where=None, group_by=None)
query_element_state(unique_id, *, include_type_definition=False)
query_types(pool)
query_inspect(target)
```
`kind` is one of the model kinds: `level`, `wall`, `floor`, `door`, `window`,
`room`, `ceiling`, `roof`, `column_structural`, `furniture`, `generic_model`,
`grid`, `group`, `pipe`, `duct`, and so on.
`query_element_state` is the one that answers with the element's **identity**:
its `unique_id` and version, the values you compare before a second edit.

---

## 5. Ten worked examples

Every block below is compiled for 2023 and 2026 by `tools/cheatsheet_check.py`.

### T01 — a room: one level and four walls

```python
from kir.dsl import envelope, create_level, create_wall, build

envelope(intent="a level and four walls around one room")
level = create_level(elev_mm=0, name="Level 1")
corners = [(0, 0), (6000, 0), (6000, 4000), (0, 4000)]
for i in range(4):
    create_wall(p0_mm=list(corners[i]), p1_mm=list(corners[(i + 1) % 4]),
                level=level, height_mm=3000)
program = build()
```

### T02 — a door and a window in the same wall

```python
from kir.dsl import envelope, create_level, create_wall, create_door, create_window, build

envelope(intent="a wall carrying a door and a window")
level = create_level(elev_mm=0, name="Level 1")
wall = create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], level=level, height_mm=3000)
create_door(host=wall, offset_mm=1200, symbol="0915 x 2134mm")
create_window(host=wall, offset_mm=3600, sill_mm=900, symbol="0915 x 1220mm")
program = build()
snapshot = {"door_symbols": [{"id": 700, "name": "0915 x 2134mm"}],
            "window_symbols": [{"id": 701, "name": "0915 x 1220mm"}]}
```

### T03 — a floor with two openings through it

```python
from kir.dsl import envelope, create_level, create_floor_by_contour, create_opening, build

envelope(intent="a slab with a stair opening and a shaft")
level = create_level(elev_mm=3000, name="Level 2")
floor = create_floor_by_contour(
    contour={"outer": {"shape": "poly",
                       "points_mm": [[0, 0], [8000, 0], [8000, 5000], [0, 5000]]}},
    level=level)
create_opening(variety="host_face", host=floor, cut="vertical",
               outline=[[1000, 1000], [3000, 1000], [3000, 3000], [1000, 3000]])
create_opening(variety="host_face", host=floor, cut="vertical",
               outline=[[5000, 1000], [6000, 1000], [6000, 2000], [5000, 2000]])
program = build()
```

### T04 — two storeys

```python
from kir.dsl import envelope, create_level, create_wall, build

envelope(intent="the same plan repeated on two levels")
first = create_level(elev_mm=0, name="Level 1")
second = create_level(elev_mm=3300, name="Level 2")
corners = [(0, 0), (6000, 0), (6000, 4000), (0, 4000)]
for level in (first, second):
    for i in range(4):
        create_wall(p0_mm=list(corners[i]), p1_mm=list(corners[(i + 1) % 4]),
                    level=level, height_mm=3000)
program = build()
```

### T05 — load a family and place one of its types

```python
from kir.dsl import envelope, create_level, load_family, place_family, build

envelope(intent="load a table family and place one instance")
level = create_level(elev_mm=0, name="Level 1")
symbol = load_family(
    path=r"C:\ProgramData\Autodesk\RVT 2023\Libraries\English\Furniture\Table.rfa",
    type_name="1200x600mm")
place_family(symbol=symbol, xyz=[2000, 2000, 0], level=level, rotation_deg=90.0)
program = build()
```

### T06 — change a wall that already exists

```python
from kir.dsl import envelope, set_param, by_element_id, build

envelope(intent="raise an existing wall to 3300 mm")
set_param(target=by_element_id(8145901), param="height_mm",
          value={"value": 3300, "unit": "mm"})
program = build()
```

### T07 — move a door after its wall has moved

```python
from kir.dsl import envelope, move_elements, by_element_id, build

envelope(intent="the host wall moved 600 mm; the door follows")
move_elements(targets=[by_element_id(8145902)], delta_mm=[600, 0, 0])
program = build()
```

### T08 — delete an element together with its dependents

```python
from kir.dsl import envelope, delete, by_element_id, build

envelope(intent="remove the partition and whatever Revit removes with it",
         allow_destructive=True)
delete(target=by_element_id(8145901))
program = build()
```

### T09 — change a level's elevation

```python
from kir.dsl import envelope, set_param, by_element_id, build

envelope(intent="lift Level 2 from 3000 to 3300 mm")
set_param(target=by_element_id(311), param="elev_mm",
          value={"value": 3300, "unit": "mm"})
program = build()
```

### T10 — two edits of one wall, authored from one reading

```python
from kir.dsl import envelope, set_param, by_element_id, build

envelope(intent="two edits of the same wall, from one reading of it")
wall = by_element_id(8145901)
set_param(target=wall, param="height_mm", value={"value": 3300, "unit": "mm"})
set_param(target=wall, param="comments", value="reviewed 2026-09-13")
program = build()
```

### P01 — a frame: columns on a grid, bound by the level above

```python
from kir.dsl import envelope, create_level, create_column, build

envelope(intent="four structural columns carried to the level above")
first = create_level(elev_mm=0, name="Level 1")
second = create_level(elev_mm=3300, name="Level 2")
for x in (0, 6000):
    for y in (0, 4000):
        create_column(xy=[x, y], level=first, top_level=second,
                      category="structural", symbol="300 x 300mm")
program = build()
snapshot = {"column_symbols_structural": [{"id": 900, "name": "300 x 300mm"}]}
```

### P02 — a pipe route of three nodes and two segments

```python
from kir.dsl import envelope, create_level, route_pipe_system, build

envelope(intent="a domestic water route along two walls")
level = create_level(elev_mm=0, name="Level 1")
route_pipe_system(
    nodes=[{"id": "n1", "xyz_mm": [0, 0, 300]},
           {"id": "n2", "xyz_mm": [4000, 0, 300]},
           {"id": "n3", "xyz_mm": [4000, 3000, 300]}],
    segments=[{"from": "n1", "to": "n2"}, {"from": "n2", "to": "n3"}],
    level=level, diameter_mm=50,
    system_type="Хозяйственно-бытовая", pipe_type="Стандарт")
program = build()
snapshot = {"piping_system_types": [{"id": 910, "name": "Хозяйственно-бытовая"}],
            "pipe_types": [{"id": 911, "name": "Стандарт"}]}
```

A duct route is the same shape with `route_duct_system`, `duct_type=` and the
`duct_system_types` / `duct_types` catalogues.

### P03 — a habitable room: the walls first, then `function` and the ceiling

```python
from kir.dsl import envelope, create_level, create_wall, create_room, build

envelope(intent="a living room that HAB022 will accept")
level = create_level(elev_mm=0, name="Level 1")
corners = [(0, 0), (4000, 0), (4000, 3000), (0, 3000)]
for i in range(4):                      # the enclosure FIRST, in this program
    create_wall(p0_mm=list(corners[i]), p1_mm=list(corners[(i + 1) % 4]),
                level=level, height_mm=3000)
create_room(xy=[2000, 1500], level=level, name="Комната", number="101",
            function="жилая",           # the kind is named, not guessed
            upper_offset_mm=2700)       # 2438 mm by default would fail HAB022
program = build()
```

Both edits ride in **one** program, so they are applied inside one transaction
against one state of the document. Two programs authored from the same reading
and applied one after another are a different thing: the second one is authored
against a wall that has already changed. Read the element again
(`query_element_state`) between programs.

---

## 6. Refusals, and the next move

A refusal carries a code, the slot it is about, and a line that starts with
`СЛЕДУЮЩИЙ ХОД:` — the next move. The texts below are the actual ones.

| code | what happened | the next move |
|---|---|---|
| `KIR-P003` | `` `create_level`: слота 'height_mm' у этого опа НЕТ `` | the field belongs to another op; open that op's contract |
| `KIR-P005` | `` `create_wall`: не задан ОБЯЗАТЕЛЬНЫЙ слот `level` `` | name the level; there is deliberately no default |
| `KIR-T001` | `число без единиц запрещено — укажите {value, unit: mm\|raw}` | wrap it: `{"value": 3300, "unit": "mm"}` |
| `KIR-T001` | `target: by обязан быть element_id либо ref, пришло 'name'` | read the id first, then mutate by id |
| `KIR-G103` | `программа требует снапшот модели (census) для ground-стадии` | pass `snapshot=` to `compile_program`, or use ids only |
| `KIR-G101` | `door_symbols: «НЕТ ТАКОГО» не найден` | the pool is named in the message; take a name from it |
| `KIR-D001` | `delete требует allow_destructive=true в конверте программы` | `envelope(..., allow_destructive=True)` |

Two rules behind all of them:

* **A missing value is never invented.** `create_wall` has no default level
  because a guessed level is indistinguishable from a named one once the
  building exists.
* **An unknown field is never dropped silently.** It means the author has a
  different operation in mind, and the refusal says which slots this one has.

---

## 7. Limits

| limit | value |
|---|---|
| operations in one authored program | 100 000 |
| operations in one bulk program | 200 000 |
| distance of any coordinate from the origin | 16 000 000 mm |
| default wall height when `height_mm` is omitted | 3000 mm |

Anything larger is refused before emission, not discovered in Revit.

---

## 8. Applying a program

```text
out = compile_program(program, revit_version="2023", snapshot=snapshot, bulk=True)
if out.ok:
    csharp = out.csharp          # this text is what runs inside Revit
else:
    for d in out.diagnostics:
        print(d.code, d.message_ru)
```

The generated C# opens its own transaction, checks its preconditions before any
effect, and rolls back when an observation disagrees with the plan. A refusal
from the compiler costs nothing; a refusal inside Revit leaves the document as
it was.
