"""ops_annotation — annotation tirage beyond ops_doc seed (KIR_DOC_SPEC.md).

create_dimension / create_tag / create_text: the ops_annotation.md family
0% -> tirage. VIEW-SPACE core (PtView2D vs PtModel3D, VIEW-BINDING LAW) lives
in docspace.py and is REUSED here, never reinvented (per KIR_DOC_SPEC.md
"эмиттер клонирует ядро, не координатную модель заново").

in_view / target / refs[] are write-target selectors (kind="target_w": pinned
element_id OR an intra-program `ref` to an earlier create_* op) — there is no
`views`/`sheets` snapshot pool yet (KIR_DOC_SPEC.md GROUND §: "добавить в
serving _SNAPSHOT_CS — сейчас есть view/sheet KINDS в query, пул для ground
нужен" — that pool is a Fable-level registry_base.py change, NOT made here).
Resolution is therefore id-pinned/ref only, exactly like `target` in
set_param/delete and `host` in create_window/create_door — no new snapshot
pool, no grounded=(...) entry needed for this v1 tirage.

FLAGGED GAP (not invented around): dim_type/tag_type/text_type are spec'd as
"каталог проекта на ground (sole-entry/candidates)" — that needs a
dimension_types/tag_types/text_note_types snapshot pool, which does not exist
in known_pools (registry_base.py, Fable-level). These three params are
therefore ALSO plain target_w (element_id-pinned only, optional) here, NOT
sole-entry-resolved; when omitted the emitter falls back to the document's
default type (GetDefaultElementTypeId, same in-emit-default pattern as
create_wall's `type`). This is a real, flagged gap versus the spec's GROUND
ambition, not a silent guess — see KIR_ANNOTATION_GAPS note in this module's
tests for the follow-up.

Registry module — see REGISTRY_MODULES.md. Add ops HERE, not in spec.py.
"""
from __future__ import annotations

from kukai.ir.registry_base import *  # noqa: F401,F403 (OpSpec/ParamSpec/DEFAULTS/LIST_*/...)

OPS = [
    # dimension — a size between >=2 refs (elements or grids), drawn in
    # in_view's 2D plane at line_at [u,v]. VIEW-BINDING LAW (semantic witness):
    # every ref must be visible in in_view — checked post-commit (no snapshot
    # visibility pool exists yet; witness is the only layer that can prove it).
    OpSpec(
        name="create_dimension",
        effect=EffectKind.CREATE,
        result=RESULT_ELEMENT,
        family="authoring",
        params=(
            ParamSpec("in_view", "target_w", required=True),
            ParamSpec("refs", "refs_w", required=True,
                      ref_kinds=(ReferenceKind.ELEMENT,)),
            ParamSpec("line_at", "pt_view2d", required=True),
            ParamSpec("dim_type", "target_w"),          # optional catalog typoразмер
        ),
        capability=(("create", "dimension"),),
        # 28.07 (live E5 measurement, FAS_R23 Revit 2023): the "line_at
        # reproduced" clause is retired — once the dimension line's own
        # direction became geometry-derived (the first reference's face
        # normal, not a fixed view axis), "offset along a fixed axis" is no
        # longer a meaningful invariant, and Dimension.Curve stays ALWAYS
        # UNBOUND regardless (Revit API Developer Guide) — see
        # _emit_dimension's docstring for the full law.
        post=("dimension exists in in_view (materialize); References bound "
              "to all refs, none empty (topology); every ref visible in "
              "in_view (semantic, VIEW-BINDING LAW); measured value is "
              "receipt-only, not gated — it depends on which geometric "
              "reference resolves per element (Exterior/Interior face "
              "choice), and no independent expectation exists to compare "
              "against"),
        writes_model=True,
    ),
    # tag — a mark on target, drawn in in_view. `at` is REQUIRED (not
    # defaulted): IndependentTag.Create has no point-less overload on either
    # version branch, and a compile-time "near the target" default would need
    # the target's 2D position in in_view — unavailable without a witness/
    # geometry round-trip. A human places the tag point explicitly in the
    # Revit UI; the IR asks for the same (no invented auto-placement).
    OpSpec(
        name="create_tag",
        effect=EffectKind.CREATE,
        result=RESULT_ELEMENT,
        family="authoring",
        params=(
            ParamSpec("in_view", "target_w", required=True),
            ParamSpec("target", "target_w", required=True,
                      ref_kinds=(ReferenceKind.ELEMENT,)),
            ParamSpec("at", "pt_view2d", required=True),
            ParamSpec("leader", "bool"),
            ParamSpec("tag_type", "target_w"),
        ),
        capability=(("create", "tag"),),
        post=("tag exists in in_view, TaggedLocalElementId == target (semantic, "
              "VIEW-BINDING LAW: target must be visible in in_view); at "
              "reproduced ±tol in view-space (geometry)"),
        writes_model=True,
        # 03.08: «±tol» получил адрес — головка марки сверяется в осях вида
        # с тем же 10 мм, что стояло литералом в _emit_tag.
        tolerances={"head_mm": 10.0},
    ),
    # text — a note (± leader) in in_view at view-space `at`; width_mm
    # (optional, TextNote.Width — the ONE per-instance sheet-space size Revit
    # exposes; font HEIGHT is TextNoteType-owned, not per-instance, so it is
    # NOT modeled here, see module docstring) is compiler-owned size-from-
    # intent via the resolved view's own Scale, read at RUNTIME from in_view
    # (docspace.view_scale_to_model_mm mirrors the SAME formula as a pure-
    # python proof/test helper — the compiler cannot know view_scale at
    # python-emit-time, only after the view is resolved in C#, exactly like
    # emit_view2d_to_xyz_cs never hardcodes a basis).
    OpSpec(
        name="create_text",
        effect=EffectKind.CREATE,
        result=RESULT_ELEMENT,
        family="authoring",
        params=(
            ParamSpec("in_view", "target_w", required=True),
            ParamSpec("at", "pt_view2d", required=True),
            ParamSpec("content", "str_long", required=True),
            ParamSpec("width_mm", "mm", min_val=1.0, max_val=5000.0),
            ParamSpec("text_type", "target_w"),
            ParamSpec("leader_to", "target_w",
                      ref_kinds=(ReferenceKind.ELEMENT,)),
        ),
        capability=(("create", "text_note"),),
        post=("text note exists in in_view at `at` ±tol (geometry); content "
              "matches verbatim (re-read, semantic); when leader_to given, "
              "a leader exists, its endpoint matches the target's in-view "
              "bounding-box center, and leader_to is visible in in_view "
              "(VIEW-BINDING LAW)"),
        writes_model=True,
        # 03.08: «±tol» точки вставки — те же 5 мм, что в _emit_text.
        # НАЗВАНО ЧЕСТНО: допуск ширины (`__wmm * 0.15 + 5.0`) сюда НЕ
        # внесён — это относительная поправка на подгонку Revit под контент,
        # а не обещание `post`; вносить её значило бы выдать за контракт то,
        # чего контракт не обещает.
        tolerances={"location_mm": 5.0},
    ),
]
