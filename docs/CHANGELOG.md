# Changelog

Changes to `kir-building`. Dates are UTC. Unreleased lists changes in the source
checkout.

## 0.8.4 — 2026-09-13

### Added

- Every refusal of the `revit_ir` door carries `next_ru` — a move that exists in
  the mode's own palette, stamped structurally from one carrier rather than
  written per refusal. The authoring stage tells a person what went wrong in
  words; the code and the source lines travel in `diagnostics`.
- Hold a receipt as a record in a real store: the second plan is read from the
  archive on disk — the program from its plan evidence, the identities from the
  product's retained create claims — so repeating the same program emits zero
  operations without any memory of the first run. A batch reads its previous
  publications through the same store; an unknown address is a refusal by name,
  not a silent «first run».
- Merge an approval into the building instead of duplicating it:
  `republish_for_transfer` calls the republication plan, the derived program and
  the previous publication as they are. On a repeat the door calls the executor
  zero times (7 kept, 0 created); with no previous publication it creates 7.
- Distinguish what was just authored from what was already there in the window
  frame: `fresh`, `ground` and their Russian captions travel in the frame, with
  the element-name seam measured at 0.035 ms of a 5.355 ms frame.

### Changed

- `version_guid` is optional, and it is compared only when the caller asks:
  `unique_id` is the one strong field of an element's identity, and a version
  mismatch after a save is its own refusal (`identity_version_differs_after_save`)
  rather than a silent substitution. No stored bytes changed.
- Shrink the `revit_ir` description from 29 874 to 1 508 characters with not one
  operation name and no examples: the input envelope comes from the schema, the
  budget as a number from the compiler, and the operation counts from the
  registry (77 that write, 6 that read). Addresses replace the listing:
  `spec(<name>)` for one contract, `spec()` for the catalogue.
- One author for the approval button's caption (`preview.TRANSFER_BUTTON_RU`).

### Fixed

- `VersionGuid` is an element's version between saves, not a token of freshness.
  The mechanism text in `emit_core` claimed otherwise; it is removed, and the
  documented behaviour is what the code now says.

## 0.8.3 — 2026-09-13

### Added

- Write by identity, not only read by it: all four mutating operations accept
  `{by: unique_id}`, and a mutation may declare the state it was authored
  against — `expected_identity` refuses with `identity_changed_since_read`,
  `expected_current` with `value_changed_since_read` where a VersionGuid is
  blind. A deletion states its dependents before the effect, not after.
- Turn a republication plan into a program: `keep` emits nothing, `update` sets
  parameters by identity, `replace` creates, rebinds and deletes in that order,
  `delete` deletes. A repeat with nothing changed emits no operation at all.
- Let a batch of programs introduce itself through receipts: a reference to a
  neighbouring link's output resolves to a `unique_id` for a write target or an
  `element_id` for a selector slot, so no identity is typed by hand. A repeated
  batch emits zero operations per link; a lost receipt is a refusal, not a
  second create.
- Carry `focus=` in the panel frame: what the human asked about is lit and the
  rest is dimmed.
- `docs/KIR_CHEATSHEET.md`: an authoring reference whose thirteen examples are
  compiled for Revit 2023 and 2026 by `tools/cheatsheet_check.py`, including
  columns and beams, pipe and duct routes, room function and the HAB022 ceiling.
  The source distribution now carries it.

### Changed

- Name the shapes of the generated schema by their subject rather than by a
  sequence number: `region_with_holes`, `point_at_element`, `sketch_plane`,
  `graph_node`, `measured_value`, `param_assignment`, `query_filters`,
  `unique_id`, `version_guid` and the rest — 86 of 86 recognized, where 55 were.
  A name in `$defs` is read by the model, and `shape_30` tells it nothing.
- Shrink the first touch of the MCP door from 123 672 to 65 416 bytes
  (≈41 000 → ≈21 800 tokens): `kir_compile` carries an outline of the program
  instead of the slot list of 86 branches, and the contract of one operation is
  served by `kir_spec`, as intended.
- Bind the wire of /2 to what it refused: refused rows and completeness travel
  in the response and in the digest, so a partial binding no longer costs the
  identities of its neighbours.
- Say one thing about a region in the slot hint and in the compiler's refusal:
  `{outer: shape, holes?: [shapes]}` has a single carrier.
- Remove the browser window from the product (`kir/app`, `frontend/standalone`,
  the standalone HTTP server and its CLI, `kir/viewer/assets.py`). The display
  file format and the scene library stay; the product's surface is the KIR mode
  in the Revit panel.

### Fixed

- Check norms against a section on an existing level: a level the program only
  mentions enters the model without an invented elevation, and the elevations of
  bodies for clash judging come from the batch's own `create_level`.
- Build the door's schema for every one of the 83 operations, including the
  `identity` kind, so an invented kind fails a test instead of going silent.
- Sort the `identity` kind into every reader of the registry that classifies
  kinds: the shape carriers (it has none), the transform table (it is flat — a
  storey move does not move "I have read this"), and the scalar kinds. The guard
  now walks the readers rather than the known cases, so the next kind that is
  added and not sorted is found by a test.
- Print the full form of a region once in a contract that has two region slots:
  `create_solid_blend` went from 3143 to 2100 characters without prose against a
  channel of 3300, so its tail — parameter bounds and witness tolerances —
  reaches the model again.

## 0.8.2 — 2026-09-13

### Fixed

- Ask git about the delivered files only where the repository owns the tree. An
  installed package has no commit of its own, so the emission-provenance guard
  read whatever repository happened to enclose the virtual environment: a project
  that ignores its own `venv/` made `python -m kir.selftest` report two failures
  while the package was intact.
- Put the source checkout on the import path in the documented walkthrough
  command. `python examples/final_result_walkthrough.py` left two of its eleven
  steps unable to import the neighbouring examples.
- Preserve explicit program lineage through typed planning and lowering. Passing
  the same program directly or as a `PlannedProgram` now produces the same native
  ownership markers; editing a neighbouring wall no longer renames its type's
  owner on the typed path.
- Isolate concurrent capture saves with per-call temporary directories. A failed
  save cannot remove another save's staging directory or adopt an old partial
  capture; existing destination permissions are preserved.
- Locate the standalone inspector's viewer assets in the installed package.
- Resolve hoisted definitions from the full MCP/serving argument-schema root,
  and expose optional lineage through the existing SDK/DSL and JSON envelope.
- Reject nonfinite HTTP/MCP JSON before actions; report unknown effects when a
  result fails to serialize after an action. MCP confirmation requires a real
  boolean, not the truthiness of a string.
- Require a page session token for app mutations. The published walkthrough
  obtains it through HTTP and cleans up its child process on failed startup.

- Validate a new opening against an existing floor sketch before editing it;
  refuse outside, crossing, touching and nested-opening loops. Use the sketch's
  elevation and roll back when the observed area change disagrees. Selected
  inside/outside/crossing cases were checked in Revit 2026.
- Carry wall thickness from native extraction and L0 into HAB042 enclosure
  checks. Coverage accounts for wall faces and avoids double-counting spans;
  missing thickness is reported explicitly.
- Include the native-readback parity helper in the installed self-test.

- Regenerate host geometry before creating slab edges, joining newly created
  elements or reading a newly placed mass for a face wall. Slab edges now use
  persistent edge references.
- Read the native reference-level parameter when validating extrusion roofs.
- Allow observation and bounded layer edits of homogeneous compound wall types,
  preserving their native compound flag.
- Account for later host movement in door and window position checks. Movement
  observations regenerate geometry before and after the move.
- Set the requested head position for tags with leaders. Spatial-tag diagnostics
  use the class-name helper supported by the Connector policy.
- Recognize the APS metric generic-model template filename when creating a
  family. Family-transfer receipts now count all symbols in the family.
- Display the captured scene when an existing building is opened in the app,
  and indicate edits that are not represented in that scene.
- Reuse the app's checked state reader during analysis and retain journal
  diagnostics in the program card.

### Changed

- Explicit-lineage plans use signed evidence schema `/5`. Plans without an
  explicit lineage retain `/4` and their previous digests. Existing `/4` execution
  archives remain read-only historical records; loading does not upgrade or
  authorize replay. The KIR input language version remains `1.0`.
- Add a Python workflow for a stored full/selected CREATE followed by one Level
  elevation edit, qualified readback and durable settlement. Recovery looks up
  the existing operation instead of resending a mutation.
- Connect explicit staged CREATE projections to durable parent-receipt links and
  one-send publication. Original shared levels/types are imported, not recreated.
- Add authenticated MCP HTTP serving with explicit remote-origin policy and
  confined output files, plus read-only `project clash-report` and `doctor --env`
  CLI commands. Environment diagnostics never print variable values.

- Updated product documentation and source comments to English. Runtime
  diagnostics and the authoring course remain in Russian.
- Restored installation and API guides in the public repository. Internal work
  plans and session reports remain local.
- Preserved the compact repository layout and the current wheel module selection.

### Known limitations

- New Level-edit and staged/archive protocol checks are offline acceptance, not
  new Revit execution evidence or preservation of dependent building geometry.
  Existing native types created with older unstable ownership markers are not
  silently adopted or rewritten by the lineage fix.
- Existing floor sketch checks use tessellated boundaries and an area-change
  tolerance. Tilted sketch planes are refused; new-sketch creation does not claim
  the same opening validation.
- HAB042 can underestimate enclosure when the input describes wall axes without
  wall widths.
- APS tests cover selected scenarios. Desktop Connector setup, transport and
  engineering acceptance require separate validation. Extrusion roofs require a
  suitable active view.

## 0.8.1 — 2026-09-08

### Fixed

- Record background decompile failures and cancellations in the run status.
  A run awaiting its first page reports `starting`.
- Show the requested object, dimensions, level and available action in the program
  card. Detailed diagnostics remain available separately. Extrusion solids now
  appear in the preview.
- Add a dark preview theme and dim elements outside the selected focus.
- Use native document identity, when supplied by the host, to scope program
  journals. New documents no longer restore journals from unrelated documents
  with the same name. Legacy name-based records are reported explicitly.

## 0.8.0 — 2026-09-08

### Changed

- Separate cache budgets for asset bytes and revision structure. Reuse checked
  revisions for history, scene export and analysis, reducing repeated parsing and
  materialization on large projects.
- Keep the app responsive during analysis by avoiding a full store audit on every
  state poll. Some latency remained in scene materialization and garbage collection.
- Open saved captures alongside authored projects with `--open-capture`. Supported
  door and opening edits can be saved to a new directory and continued after a
  restart. A changed source revision is reported as `capture_revision_moved`.
- Add editing support for rectangular wall openings, plus `openings` and
  `editable_now` fields in element inspection.
- Match Revit parameter names to operation obligations so later parameter edits
  are checked at the appropriate stage. Creation followed by deletion is checked
  through the deleting operation.
- Include MEP system, connector and slope information in repair eligibility.
  Unsupported runs are rejected with a reason.

### Fixed

- Detect thin boolean results in the body's oriented frame, including tilted
  plates. Unsupported spline profiles and blends with holes remain explicit refusals.
- Reject superseded task assignments before interpreting their returned content.
- Check test sources for machine-specific paths. CI rebuilds the viewer and
  compares it with the packaged copy.

## 0.7.0 — 2026-09-07

### Added

- A standalone app for projects, revisions, background tasks, proposals and clash
  analysis. It supports multiple projects and continued work after a restart.
- The `kir capture` command for opening, inspecting, editing, saving and exporting
  previously extracted model data.
- Transaction-owning units for bounded native edits, including floor sketches and
  type-layer changes. They track reservation, execution and readback separately;
  unsupported versions and uncertain outcomes return explicit statuses.
- An OCCT authoring path for stored bodies, including supported profiles,
  rotations and mirrors. Scene display, analysis and emission share the same body
  and frame. The geometry extra is required.
- Comparison of authored and observed elements by `UniqueId`, with separate
  outcomes for mismatches, missing identities and unavailable observations.
- A field ledger with `represented`, `approximate`, `source_data` and `unknown`
  states, available through `kir capture ledger`.
- A construction scheduling model for panels, cranes, crews, zones and events,
  with saved state and resumable execution. It does not provide a safety assessment.

### Changed

- Reduced repeated store checks during edits and re-analysis. Project history and
  geometry reads use revision-aware caches.
- Expose backend, preview, witness, reverse and clash capabilities through
  `kir ops NAME` and the MCP `kir_spec` response.
- Bind capture edits to their source revision and preserve unknown fields through
  save and reopen. Capture access metadata is stored in the cache rather than
  written into the source capture.
- Persist recipe progress, task attempts and refinement decisions across restarts.
  Conflicting assignments have a bounded replanning path.
- Include recipe changes, renamed output identities and changed parameters in
  `kir project diff`.
- Require a declared wall type for gap refinement and report unsupported profiles,
  self-intersections and unresolved choices.

### Fixed

- Place a hosted door relative to the host's updated position. Invalid references
  to deleted elements and geometry outside coordinate limits are rejected.
- Preserve refinement decisions and opening placement when the source changes.
  Decisions that no longer apply are returned for review.
- Handle metadata changes and empty change-reason sets without losing relevant
  dependencies or raising an unrelated `KeyError`.
- Save captures through a staged directory, preserving nested sidecars and
  rejecting incomplete targets, escaping symlinks and directory cycles.
- Reject repairs that worsen existing conflicts. Incomparable measures produce
  `proposal_unverifiable`.
- Include the required parity helpers and tests in the installed self-test.
- Check created elements at their final position after later moves. For repeated
  writes, validate intermediate values at the operation stage.
- Preserve a run's axis during supported repairs and reject MEP repairs that
  would ignore connector, system or slope constraints.
- Keep guessed or unavailable room-function evidence out of HAB003 and HAB010
  conclusions.
- Expose the authoring modules through `import kir`, remove the unused
  `CompileOutput.per_version` field and suggest nearby names for `NameError`.

### Validation scope

The release was checked through offline compilation, stored-project workflows and
capture slices. Those checks did not establish live Revit execution or integration
with a paid model provider. Large-project benchmarks also showed substantial
remaining edit and reopen latency.

## 0.6.0 — 2026-09-04

### Added

- The `kir` command with `demo`, `build`, `ops`, `skill`, `course` and `doctor`.
- Separate CLI exit codes for success, a rejected program and a run that could
  not start.

### Fixed

- Convert placement coordinates for room, area and space tags to Revit's internal
  units.
- Validate ceiling profiles with holes and preserve the order of railing-path
  vertices.
- Include all created elements when cleaning up a failed multi-element operation,
  including railings.
- Use actual arc boundaries when checking nested profile rings. A failed roof
  slope read no longer falls back to a flat roof without reporting the loss.
- Reject unsupported holes in blends and revolves that exceed coordinate limits.
- Reject numeric overflow, invalid boolean values and derived geometry outside
  coordinate limits.
- Treat truncated catalogues as incomplete when resolving types, families and grids.
- Report failed or incomplete model comparisons rather than agreement. Models with
  no shared room identities and rooms outside their declared region are handled
  explicitly.

### Requirements

The MCP server requires the `mcp` extra. Example scripts are available in the
repository; live execution requires a configured Revit host. Diagnostics and the
authoring course are in Russian.

## 0.5.0 and earlier

Earlier changes are recorded in Git history.
