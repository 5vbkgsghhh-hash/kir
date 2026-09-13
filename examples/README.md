🇷🇺 [Russian version](README.ru.md)

# Examples

Two runnable demonstrations of the division of labour KIR is built around:
**Python computes the form, KIR builds it** — and every approximation is named in
millimetres, because an approximation you did not name is a silently wrong answer.

Both files are verbatim copies of the scripts that produced the outputs below, run on
**2026-07-28** against the real compiler and the real Revit assemblies of all six
versions. Their `sys.path` bootstrap lines reflect the backend tree they ran in; they
become runnable in-repo when the code lands here on **August 9, 2026**.

## [`residential_project.py`](residential_project.py) — save, reload and change

Added in the persistent-project foundation. Three twisted concept volumes become
one developed three-storey section plus two unchanged concept volumes. After JSON
reload, Python changes the section's height and terrace setback while retaining
its named output IDs and opening coordinates. The section is a new, simple design,
not an exact native reconstruction of the original twisted shape.

```bash
PYTHONPATH=. python examples/residential_project.py --stage changed | PYTHONPATH=. python -m kir project inspect -
```

This example needs the installed project dependencies and runs without Revit.
It emits authoring-project JSON, not a live BIM receipt or an idempotent patch.
See [the project contract](../docs/PROJECT.md) for export, API and scope.
The two historical geometry examples below are separate demonstrations.

For a persisted podium/three-tower composition, see
[`residential_with_podium.py`](residential_with_podium.py) and the
[geometry workflow](../docs/PROJECT_GEOMETRY_RU.md). Optional OCCT is required.
[`residential_refinement.py`](residential_refinement.py) adds an explicit
historical source anchor, output roles and named losses without changing the
original generator pins. Its [typed contract](../docs/PROJECT_REFINEMENT_RU.md)
does not claim faithful shape conversion, structural safety or live Revit acceptance.

[`residential_agent_workflow.py`](residential_agent_workflow.py) runs two actual
recipe-worker processes against the same saved project, accepts their independent
changes in a new coordinator, preserves an overlapping conflict and continues
the section in a later task. See the [pilot contract and viewer steps](../docs/RESIDENTIAL_AGENT_PILOT_RU.md).
This deterministic driver is not an LLM scheduler or a finished BIM design.

[`residential_typed_section.py`](residential_typed_section.py) adds a separate
explicit wall/floor type library, retains the section's 21 named members, and
continues a saved section without replacing its types or neighbouring geometry.
See [inputs, preservation guarantees and native limitations](../docs/TYPED_SECTION_RU.md).
This is authored type composition and dependency-aware planning, not repeated
native publication or proof of physical wall/floor geometry.

## [`tower_numpy.py`](tower_numpy.py) — a tower with a waist

numpy computes a sinusoidal waist and a decaying twist; KIR's `stack` macro repeats the
storey. `stack.transform` only interpolates linearly, so the script *prints the divergence
between its polyline and the true sine* instead of pretending there is none.

```text
100 строк питона → 6 опов написано → 840 после экспансии → 780 элементов (программ KIR: 3)
этажей 60, талия 30%, закрутка 120°
ломаная против синуса: 217 мм по радиусу
компиляция: 6/6 версий ['2021', '2022', '2023', '2024', '2025', '2026']
```

(100 lines of Python → 6 authored ops → 840 after expansion → 780 elements in 3 KIR
programs; 60 storeys, 30% waist, 120° total twist; piecewise vs. true sine: 217 mm along
the radius; compiles on 6/6 versions.)

Note the "3 KIR programs": the compiler caps validated ops per program, and the example
shows the building as a *batch of programs* rather than hiding the limit.

## [`contour_shapely.py`](contour_shapely.py) — a curved floor plate

"The storey is a 14 m ribbon along a curved spine." The ribbon's outline is an offset of a
curve — something you compute with shapely (`buffer` + `simplify`), not by hand. KIR
receives the finished contour and does what shapely cannot: places the slab, walls the
perimeter, and owns units and API versions.

```text
95 строк питона → 19 опов написано → 19 после экспансии → 19 элементов (программ KIR: 1)
контур: 176 вершин из buffer → 18 после simplify (допуск 220 мм)
среднее отклонение контура: 89 мм, площадь этажа 1343 м²
компиляция: 6/6 версий ['2021', '2022', '2023', '2024', '2025', '2026']
```

(95 lines of Python → 19 ops → 19 elements in 1 program; the raw buffer's 176 vertices are
simplified to 18 within a 220 mm tolerance; the *actual* mean contour deviation — measured
as symmetric-difference area over perimeter, not the promised tolerance — is 89 mm; floor
area 1343 m²; compiles on 6/6 versions.)

The distinction in that third line is the house style: `simplify` *promises* at most
220 mm; the script measures what the deviation actually *was*.

## Why the SDK cannot lie

The Python surface is generated from the op registry at import time — 35 builders for 35
registry ops (2026-07-28). The SDK adds no semantics: it cannot express anything the
registry lacks, and it cannot hide a refusal. See
[docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md#1-one-source-of-truth-the-registry).
