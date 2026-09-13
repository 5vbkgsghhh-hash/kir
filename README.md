<p align="center">
  <img src="assets/logo.png" width="180" alt="KIR logo"/>
</p>

# KIR

KIR is a Python toolkit for describing building models, generating Revit API code,
and working with saved model data. A program contains operations such as creating
a wall, placing a door or changing a parameter. The compiler checks their inputs,
resolves references and generates C# for the selected Revit version.

The project is under active development. This checkout contains version 0.8.1
with unreleased changes. Documentation is in English; runtime diagnostics and the
authoring course are currently in Russian. See the [changelog](docs/CHANGELOG.md)
for recent changes and known issues.

<p align="center">
  <img src="assets/tower-side-by-side.png" alt="The same tower twice in Revit" width="720"/>
</p>

| Component | Supported work |
|---|---|
| Compiler | Typed building operations, units, references and C# generation for Revit 2021–2026 |
| Project store | Saved revisions, diffs, proposals and continued editing |
| Revit extraction | Native element data and relationships, collected inside Revit |
| Capture tools | Offline inspection and supported edits to previously extracted data |
| Geometry and analysis | Optional OCCT bodies, previews and clash analysis |
| MCP server | Authoring, inspection and compilation tools for MCP clients |

Operation support varies by Revit version and workflow. Use `kir ops NAME` to
inspect an operation's parameters and limitations.

## Installation

Python 3.12 or newer is required. Install the released package with:

```bash
python -m pip install kir-building
```

For the current source and the examples in this repository:

```bash
git clone https://github.com/5vbkgsghhh-hash/kir.git
cd kir
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
```

On Windows, create the environment with `py -3.12 -m venv .venv` and activate it
with `.\.venv\Scripts\Activate.ps1`.
Revit is not needed for code generation or offline capture tools. To execute the
generated code, you need Revit and a compatible execution backend; see
[Connector installation](docs/CONNECTOR_INSTALLATION_RU.md).

Optional dependencies can be installed from the checkout:

```bash
python -m pip install -e '.[geometry]'  # OCCT geometry
python -m pip install -e '.[mcp]'       # MCP server
python -m pip install -e '.[dev]'       # development tools and pytest
```

Run `kir doctor` to inspect the available capabilities. `kir demo` builds a small
example program, generates C# for the supported versions and runs its design checks.

## Example

This program describes one level and four walls around a 6 × 4 m room:

```python
from kir import compile_program
from kir.dsl import envelope, create_level, create_wall, build

envelope(intent="a room, 6 x 4 m")
level = create_level(elev_mm=0, name="Level 1")
corners = [(0, 0), (6000, 0), (6000, 4000), (0, 4000)]
for start, end in zip(corners, corners[1:] + corners[:1]):
    create_wall(p0_mm=start, p1_mm=end, level=level, height_mm=3000)

program = build()
out = compile_program(program, revit_version="2026", bulk=True)
print(out.ok)  # True
```

`program` is a JSON-compatible dictionary. `out.csharp` contains the generated
Revit code; `out.diagnostics` contains any compiler diagnostics. This example
uses the target document's default wall type. Other operations may require a catalogue
from the target document.

`kir.dsl` collects operations into the current program and returns handles for
references. `kir.sdk` provides an explicit builder API and macros such as
`stack`. Both APIs are generated from the same registry:

| Registry | Count |
|---|---:|
| Registered operations | 83 |
| Generated SDK builders | 83 |

See the [language guide](docs/KIR.md) for the JSON format, selectors and compilation
stages.

## Model references

A family name must be resolved against the target document. Without a model
catalogue, the following door program returns `KIR-G103`:

```python
from kir import compile_program
from kir.dsl import envelope, create_level, create_wall, create_door, build

envelope(intent="a wall with a door")
level = create_level(elev_mm=0, name="Level 1")
wall = create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], level=level, height_mm=3000)
create_door(host=wall, offset_mm=1200, symbol="0915 x 2134mm")
program = build()

missing_catalog = compile_program(program, revit_version="2026", bulk=True)
print(missing_catalog.diagnostics[0].code)  # KIR-G103

# Illustrative catalogue for this compilation example.
snapshot = {"door_symbols": [{"id": 700, "name": "0915 x 2134mm"}]}
out = compile_program(program, revit_version="2026", snapshot=snapshot, bulk=True)
print(out.ok)  # True
```

For execution, the catalogue must come from the actual Revit document; `700` here
is an example ID. A name absent from the supplied catalogue returns `KIR-G101`
with candidate values.

## Projects and captured models

Authored projects can be saved with their revisions, module instances and output
identities. The [residential example](examples/residential_project.py) creates a
concept, develops a section and changes it after reloading:

```bash
python examples/residential_project.py --stage changed | python -m kir project inspect -
```

The project API also supports [proposals](docs/PROJECT_PROPOSALS_RU.md),
[refinement](docs/PROJECT_REFINEMENT_RU.md) and
[persisted tasks](docs/PROJECT_TASKS_RU.md). These features track authoring state;
applying a revision to Revit has its own preparation, execution and readback steps.

The extractor runs inside Revit. Its saved captures can then be inspected and
edited offline with `kir capture`. That command works on capture directories;
it does not open RVT files directly. Capture reports distinguish represented,
approximate, source-only and unknown fields.

- [Project API and storage](docs/PROJECT.md)
- [Capture inspection and editing](docs/CAPTURE_OFFLINE_EDIT_RU.md)
- [Extraction and reverse compilation](docs/BUILDING_GRAPH.md)

## Geometry and analysis

The optional `geometry` extra provides OCCT-based body construction and
transforms. Stored bodies can be displayed, compared and checked for clashes.
Approximate representations are supported as well; the reported geometry source
and accuracy affect what a finding can establish.

Design checks cover selected room, access and enclosure properties. Their reports
include rules that could not be evaluated. Review the inputs and supported profile
before using a result in a design decision.

- [Geometry API](docs/GEOMETRY.md)
- [Clash analysis](docs/CLASH.md)
- [Checker rules](docs/CHECKER_RULES_RU.md)
- [Wall and floor reference surfaces](docs/REFERENCE_SURFACES_RU.md)

## MCP server

Install the `mcp` extra, then start the stdio server:

```bash
python -m kir.mcp
```

Streamable HTTP requires a private token file (0600 on POSIX):

```bash
python -m kir.mcp --http --port 8765 --token-file /path/to/private-token --out-root .
```

The client sends that token in its `Authorization: Bearer` header. HTTP file
output stays under `--out-root` and does not overwrite existing files. Remote
binding additionally requires explicit opt-in and a trusted HTTPS proxy; see
the [HTTP access contract](docs/KIR.md#mcp-http-access-and-output-files).
A stdio client should use the interpreter from the environment where KIR is
installed, for example:

```json
{"command": "/path/to/venv/bin/python", "args": ["-m", "kir.mcp"]}
```

| Tool | Purpose | Revit required |
|---|---|---|
| `kir_author` | Run an authoring script in the sandbox and return a program | No |
| `kir_spec` | Inspect operation parameters and limits | No |
| `kir_compile` | Generate version-specific Revit C# | No |
| `kir_rehearse` | Inspect the checks available for a program | No |
| `kir_preview` | Generate a plan preview | No |
| `kir_open` | Read the selected open document's context | Yes |
| `kir_write` | Execute a program in that document | Yes |

`kir_author` requires the supported Linux sandbox facilities. Live tools require a
configured host connection. `kir_write` has no confirmation prompt by default;
set `KIR_MCP_CONFIRM=always` or `session` if your integration should ask before a
write.

## More examples

Run these from a source checkout:

| Example | Demonstrates |
|---|---|
| [tower_numpy.py](examples/tower_numpy.py) | Repeated storeys with scaling and rotation |
| [contour_shapely.py](examples/contour_shapely.py) | A floor plate and walls derived from a computed contour |
| [residential_project.py](examples/residential_project.py) | Saving, reloading and changing an authored project |
| [residential_with_podium.py](examples/residential_with_podium.py) | A project with an OCCT podium; requires the geometry extra |

The scripts in `examples/` are included in the repository and source distribution,
but are not installed by the wheel. See [examples/README.md](examples/README.md)
for their dependencies and commands.

## Current limits

- Live Revit tests cover selected scenarios. Code generation for a version does
  not establish support for every family, model or execution workflow.
- Extraction completeness, IR representation and successful reconstruction are
  separate measures. Testing on a broader set of working models is still needed.
- Editing an existing floor sketch checks loop containment and area change.
  Curved boundaries are tessellated; tilted sketch planes are refused, and
  new-sketch creation has a separate, limited acceptance contract.
- HAB042 uses captured wall widths when available. Missing widths and the rule's
  partial-enclosure scope limit what a quiet report establishes.
- Connector installation, transport and recovery need validation in the target
  environment. The [protocol](connector/revit/PROTOCOL.md) and
  [preparation guide](docs/CONNECTOR_PREPARATION_RU.md) describe those requirements.

## Development

After installing the `dev` extra, run the bundled self-test:

```bash
python -m kir.selftest
```

This is a selected suite. Additional unit, contract and integration tests live
under `kir/tests/`, the subpackage test directories and `connector/revit/tests/`.
Some need optional dependencies or a Revit environment. Use
`python tools/readme_numbers.py --check` to check the registry counts and Python
examples on this page.

**Lint: a narrow baseline, and nothing that reformats.** The `dev` extra brings
`ruff` along with `pytest`. `ruff check kir tools examples build_support` runs the
selection declared in `pyproject.toml`: four rule families — `E9`, `F63`, `F7`,
`F82`, that is code which does not parse, a comparison whose operand types make it
always true, a misplaced statement, and a name used but never defined. `F401`
(unused import) is deliberately not selected: several `__init__.py` publish the
package surface by re-exporting, and flagging that would report the design as a
defect. There is no formatter pass and no style ratchet. `examples/recipes` is
excluded from the ordinary run and checked separately with the two names the recipe
namespace actually supplies (`param`, `project_output_id`), so an injected name is
not silenced everywhere. The required `lint` job of
`.github/workflows/kir-evidence.yml` runs both commands and recomputes this page's
numbers; indentation and line endings come from `.editorconfig` at the tree root.

Build output, model data and internal working documents stay outside the public
source tree.

## License

[Apache License 2.0](LICENSE).
