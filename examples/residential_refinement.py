"""Explicit schematic lineage around the unchanged residential recipe.

Run with optional geometry dependencies: python examples/residential_refinement.py
--store NEW.sqlite. Existing generator source and all recipe pins are retained.
This creates a five-revision example history, not native BIM or engineering proof.
"""
from __future__ import annotations

import argparse
import json

from examples import residential_project as towers
from examples import residential_with_podium as composed
from kir.project import ProjectRevision, _digest
from kir.project_refinement import (RefinementError, annotate_schematic_refinement,
                                    carry_schematic_refinement, refinement_view)
from kir.project_store import ProjectStore, ProjectStoreError, StoreConflict


_ROLE_BY_OP = {"create_level": "level", "create_floor_by_contour": "slab",
               "create_wall": "wall", "create_room": "space",
               "create_wall_type": "wall_type"}

#: Suffix of the instance in which the CONCEPT keeps living.
CONCEPT_SUFFIX = "-concept"


def _authored_parts(outputs):
    """Authored partition of descendants into parts of the SOURCE shape.

    🔴 THIS IS AN ASSERTION BY THE AUTHOR, NOT MEANING RECOGNITION. No one
    looks at the geometry and "recognizes" the atrium: the parts are named
    here, in the example, exactly because they are known here. The partition
    is strict (each descendant in one part), and `atrium` and `north_facade`
    do not overlap — otherwise the question "which part produced this wall"
    would stop having an answer.

    `north_facade` — walls with index 0: measuring the section's axes gives
    them `p0=(0,0) p1=(14000,0)`, i.e. the `y=0` side, which is exactly what
    the facade edit moves. The other three sides are `envelope`: the atrium
    and facade edits do not touch them, and mixing them with the facade would
    mean declaring a recompute where there is none.
    """
    parts = {}
    for output in outputs:
        key, name = output.key, output.operation["op"]
        if name == "create_floor_by_contour":
            part = "atrium"
        elif name == "create_wall":
            part = "north_facade" if key.endswith("-wall-0") else "envelope"
        elif name == "create_level":
            part = "storey_levels"
        elif name == "create_room":
            part = "spaces"
        else:
            part = "section_body"
        parts.setdefault(part, []).append(key)
    return parts


def _concept_instance(project, previous):
    """The concept instance: the same `concept-volume` output, a separate key.

    🔴 WHY A SEPARATE INSTANCE, NOT "LEAVE THE OUTPUT NEXT TO THE 21". The
    roles contract requires members to cover an instance's outputs EXACTLY
    and in order; the concept volume has no role and can have none (it is
    the source, not a descendant). So either the coverage contract is broken,
    or the concept gets its own instance. The second is more honest and
    cheaper: the section's program stays exactly the same (measured: 23 ops
    before and after), and the source finally LIVES in the head — without
    this there is no one to address "change the atrium outline AFTER
    detailing" to.
    """
    from kir.project import ModuleInstance

    parameters = {**dict(previous.parameters), "representation": "concept"}
    return ModuleInstance(previous.key + CONCEPT_SUFFIX, previous.module_key,
                          list(previous.outputs), parameters,
                          metadata={"role": "preserved_conceptual_source",
                                    "native_execution": "not_run"})


def _section(project):
    if type(project) is not ProjectRevision:
        raise RefinementError("example_scope_mismatch", "expected an exact ProjectRevision")
    instance = next((item for item in project.instances if item.key == "tower-a"), None)
    if instance is None or instance.parameters.get("representation") not in ("concept", "section"):
        raise RefinementError("example_scope_mismatch", "expected the example's conceptual/refined tower-a")
    return instance


def develop_section(project: ProjectRevision, *, source: ProjectRevision | None = None,
                    height_mm: float = 3600, setback_mm: float = 900) -> ProjectRevision:
    """Generate with the existing pin check, then annotate/carry one whole snapshot."""
    previous = _section(project)
    concept = previous.parameters["representation"] == "concept"
    if source is not None and type(source) is not ProjectRevision:
        raise RefinementError("source_binding_mismatch", "source must be an exact ProjectRevision")
    if concept and source is not None and source.dumps() != project.dumps():
        raise RefinementError("source_binding_mismatch", "first annotation uses the actual pre-refinement project")
    if not concept:
        if source is None:
            raise RefinementError("source_snapshot_required", "continued refinement requires its exact historical source")
        refinement_view(project, previous.key, source=source)
    candidate = towers.develop_section(project, height_mm=height_mm, setback_mm=setback_mm)
    replacement = next(item for item in candidate.instances if item.key == previous.key)
    kept = _concept_instance(project, previous) if concept else next(
        (item for item in project.instances if item.key == previous.key + CONCEPT_SUFFIX), None)
    if concept:
        # The concept is placed into the same revision as the section. The
        # record's historical pin stays as before (what it was derived
        # from), and `live_instance_key` says where the same output lives
        # NOW.
        staged = candidate.revise(expected_revision=candidate.revision_id,
                                  instances=[*candidate.instances, kept])
        # The generator sets the `refines` alias to the OLD concept address
        # (`tower-a/concept-volume`), while the concept now lives in its own
        # instance. The alias is required to match the record's source —
        # otherwise one fact has two addresses, and `source_alias_mismatch`
        # correctly does not let that through. We strip it here and let
        # `_annotated` set the exact one.
        # The generator sets the `refines` alias to the OLD concept address
        # (`tower-a/concept-volume`), while the concept now lives in its own
        # instance. The alias is required to match the record's source —
        # otherwise one fact has two addresses, and `source_alias_mismatch`
        # correctly does not let that through.
        from dataclasses import replace as _replace
        replacement = _replace(replacement, metadata={
            key: value for key, value in dict(replacement.metadata).items()
            if key not in ("refines", "refinement")})
        replacement = annotate_schematic_refinement(project, replacement,
            source_instance_key=previous.key, source_output_key="concept-volume",
            roles={output.key: _ROLE_BY_OP.get(output.operation["op"]) for output in replacement.outputs},
            losses=("concept_twist_removed", "concept_top_taper_removed"),
            inactive_parameters=("twist_deg",),
            parts=_authored_parts(replacement.outputs),
            live_instance_key=kept.key, project=staged)
    else:
        replacement = carry_schematic_refinement(previous, replacement, project=project)
    # Candidate is an unsaved value. The published proposal remains a direct
    # child of the caller's base, with no hidden intermediate history rewrite.
    if concept:
        # 🔴 ONE REVISION, NOT TWO. The previous version placed the concept in
        # a SECOND `revise`, and the proposal stopped being a DIRECT child of
        # the caller's base: the store's `expected_revision` stopped matching
        # (measured: 28 `StoreConflict` refusals in the strip). This is
        # exactly what the comment below warns about, and it was written
        # before me.
        instances = [replacement if item.key == previous.key else item
                     for item in project.instances]
        result = project.revise(expected_revision=project.revision_id,
                                instances=[*instances, kept])
        source = project
    else:
        result = project.replace_instance(replacement, expected_revision=project.revision_id)
    refinement_view(result, previous.key, source=source)
    return result


def continue_section(store: ProjectStore, *, expected_revision: str,
                     height_mm: float = 4200., setback_mm: float = 1800.) -> ProjectRevision:
    previous = store.head()
    if previous.revision_id != expected_revision:
        raise StoreConflict("refinement edit requires the expected current head")
    instance = _section(previous)
    source = None
    if instance.parameters["representation"] != "concept":
        try:
            source_id = _digest(instance.metadata["refinement"]["source"]["revision_id"], "source.revision_id")
        except (KeyError, TypeError, ValueError) as exc:
            raise RefinementError("legacy_unbound_refinement", "stored section lacks an exact typed source reference") from exc
        source = store.get(source_id)
    proposal = develop_section(previous, source=source, height_mm=height_mm, setback_mm=setback_mm)
    store.commit(proposal, expected_revision=expected_revision)
    return proposal


def create_store(path) -> ProjectStore:
    """NEW file only; a later failure may leave an explicit saved prefix."""
    store = composed.create_store(path, stage="podium")
    continue_section(store, expected_revision=store.head().revision_id, height_mm=3600., setback_mm=900.)
    continue_section(store, expected_revision=store.head().revision_id)
    return store


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", required=True, metavar="NEW_SQLITE")
    args = parser.parse_args(argv)
    try:
        store = create_store(args.store)
        project = store.head()
        source_id = project.instances[0].metadata["refinement"]["source"]["revision_id"]
        print(json.dumps({"schema": "kir-residential-refinement-example/1", "history_length": len(store.history()),
            "project_revision_id": project.revision_id, "refinement": refinement_view(project, "tower-a", source=store.get(source_id)),
            "stored_ancestry": "not_claimed_by_refinement_view", "native_execution": "not_run"}, ensure_ascii=False))
        return 0
    except (RefinementError, ProjectStoreError, ValueError) as exc:
        parser.exit(2, f"refinement not completed: {exc}\nA saved prefix may remain if storage began.\n")


if __name__ == "__main__":
    raise SystemExit(main())
