"""ONE selected geometry through the eyes of three readers — or a named refusal.

G02 says: preview, analysis and backend must all read ONE geometry with a
known revision, frame and tolerance. Before 2026-09-07 there was nothing to ASK
this with: the `standalone_export` scene has `geometry_reference` and `frame`,
emission has the same materialization rows, while the analysis report
(`ProjectClashReport.to_dict`) names NEITHER the bundle, NOR the body, NOR the
frame at all; none of the three had a modeling tolerance (measured:
`.work/marathon-fable-20260907/geo/`).

This is a cross-check instrument, not a second source of truth: it computes
nothing anew and invents nothing. Whatever a reader did not name goes into
`limits` BY NAME and is never replaced by a neighbor's value.
"""
from __future__ import annotations

from typing import Any, Mapping

from kir.occt_geometry import GeometryRefusal


IDENTITY_FIELDS = ("bundle_sha256", "body_sha256", "revision", "frame",
                   "modeling_tolerance_mm")


def _row(source: Mapping[str, Any], revision: str) -> dict:
    return {"bundle_sha256": source.get("source_bundle_sha256"),
            "body_sha256": source.get("source_body_sha256"),
            "revision": revision,
            "frame": tuple(float(v) for v in source["frame"]) if source.get("frame") else None,
            "modeling_tolerance_mm": source.get("modeling_tolerance_mm")}


def from_materialization(materialization) -> dict[str, dict]:
    """DirectShape emission reads EXACTLY this program and these source rows."""
    payload = materialization.to_dict()
    return {row["op_id"]: _row(row, payload["project_revision_id"]) for row in payload["sources"]}


def from_scene(descriptor: Mapping[str, Any]) -> dict[str, dict]:
    """A standalone-scene descriptor. The body reference and the source row are separate."""
    source = descriptor["source"]
    revision = source["project_revision_id"]
    rows = {row["op_id"]: _row(row, revision) for row in source["body_sources"]}
    for operation in source["operations"]:
        reference = operation.get("geometry_reference")
        if reference is None:
            continue
        seen = rows.get(operation["op_id"])
        if seen is None:
            raise GeometryRefusal("reader_disagreement",
                                  f"{operation['op_id']}: сцена ссылается на тело без строки-источника")
        if (seen["bundle_sha256"] != reference["bundle_sha256"]
                or seen["body_sha256"] != reference["body_sha256"]):
            raise GeometryRefusal("reader_disagreement",
                                  f"{operation['op_id']}: ссылка сцены и её строка-источник назвали разные тела")
    return rows


def from_analysis(report) -> tuple[dict[str, dict], list[str]]:
    """The analysis report + the LIST OF WHAT IT DOES NOT NAME.

    Only `to_dict()` is read — what the report says out loud. As of 2026-09-07
    it names `body_geometry` (bundle, body, frame, modeling tolerance); before
    that day it only had a revision and a frame as an object field, and
    `limits` printed three lines. An empty `limits` is not decoration: it is a
    MEASUREMENT that the third reader has stopped staying silent.
    """
    payload = report.to_dict()
    geometry = payload.get("body_geometry") or {}
    rows, limits = {}, []
    for oid in sorted(payload["body_ids"]):
        row = geometry.get(oid) or {}
        frame = row.get("frame")
        if frame is None:
            # Old-shaped report: the frame is not yet spoken aloud.
            frame = report.body_frames.get(oid)
        rows[oid] = {"bundle_sha256": row.get("bundle_sha256"),
                     "body_sha256": row.get("body_sha256"),
                     "revision": payload["revision"],
                     "frame": tuple(float(v) for v in frame) if frame else None,
                     "modeling_tolerance_mm": row.get("modeling_tolerance_mm")}
    if not all(rows[oid]["bundle_sha256"] and rows[oid]["body_sha256"] for oid in rows):
        limits.append("analysis: отчёт не называет ни bundle_sha256, ни body_sha256 выбранного тела")
    if not all(rows[oid]["frame"] for oid in rows):
        limits.append("analysis: отчёт не называет фрейм выбранного тела")
    if not all(rows[oid]["modeling_tolerance_mm"] for oid in rows):
        limits.append("analysis: отчёт не называет допуск моделирования выбранного тела")
    return rows, limits


def one_geometry(readers: Mapping[str, Mapping[str, Mapping[str, Any]]]) -> dict[str, dict]:
    """Reduces the readers to ONE row per body, or refuses by name.

    Disagreement is `reader_disagreement` with the field name and both values.
    A silent field is not agreement: it goes into `unnamed_by`, and a reader
    that named NOTHING about the body gets `reader_saw_no_body`.
    """
    if not isinstance(readers, Mapping) or len(readers) < 2:
        raise GeometryRefusal("invalid_input", "сверка требует не меньше двух названных читателей")
    ids: set = set()
    for rows in readers.values():
        ids |= set(rows)
    agreed = {}
    for oid in sorted(ids):
        row, unnamed = {}, {}
        for name, rows in readers.items():
            if oid not in rows:
                raise GeometryRefusal("reader_saw_no_body", f"{oid}: читатель {name!r} не видел этого тела")
            for field in IDENTITY_FIELDS:
                value = rows[oid].get(field)
                if value is None:
                    unnamed.setdefault(field, []).append(name)
                    continue
                if field in row and row[field] != value:
                    raise GeometryRefusal(
                        "reader_disagreement",
                        f"{oid}.{field}: {row[field]!r} против {value!r} у читателя {name!r}")
                row[field] = value
        agreed[oid] = {**row, "unnamed_by": {k: sorted(v) for k, v in sorted(unnamed.items())}}
    return agreed


__all__ = ["IDENTITY_FIELDS", "from_materialization", "from_scene", "from_analysis",
           "one_geometry", "GeometryRefusal"]
