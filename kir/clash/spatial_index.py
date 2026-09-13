"""An internal deterministic broad-phase index for clash readers.

The index only *supplies candidates* and never serves as an oracle of truth.
Queries are allowed to return extras; a consumer publishing a geometric fact
must ask an independent narrow phase. In particular, the postcondition of
clash resolution may not take third-party bodies from this index alone.
"""
from __future__ import annotations

import math
import statistics
from typing import Callable, Iterator, Sequence

from kir.clash import hulls as H


def nonnegative_finite(value: object, name: str) -> float:
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(float(value)) or float(value) < 0.0):
        raise ValueError(f"{name} must be a finite non-negative number")
    return float(value)


def positive_finite(value: object, name: str) -> float:
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(float(value)) or float(value) <= 0.0):
        raise ValueError(f"{name} must be a finite positive number")
    return float(value)


def choose_cell_size(records: Sequence[H.HullRecord], *,
                     upper_median: bool = False) -> float:
    """Two medians of the maximum extent, with a historical 1 mm floor.

    Detect used the statistical median, while resolve used the upper-middle
    element of an even sample. The difference affects speed, not correctness;
    the caller can keep each subsystem's previous law.
    """
    spans = [max(hi[i] - lo[i] for i in range(3))
             for lo, hi in (record.bounds() for record in records)]
    if not spans:
        return 1000.0
    if upper_median:
        spans.sort()
        median = spans[len(spans) // 2]
    else:
        median = statistics.median(spans)
    return max(2.0 * median, 1.0)


def bounds_overlap(a: H.HullRecord, b: H.HullRecord, slack: float) -> bool:
    alo, ahi = a.bounds()
    blo, bhi = b.bounds()
    return all(alo[k] - slack <= bhi[k] and blo[k] - slack <= ahi[k]
               for k in range(3))


class SpatialIndex:
    """A uniform AABB grid with explicit handling of giant hulls.

    The stream of pairs is globally free of repeats without a shared ``seen``:
    records are traversed in a stable source-id order, and a pair is emitted
    only from its lower-ranked vertex. Memory is therefore bounded by the
    index and one neighbourhood, not by the number of candidate pairs.
    """

    def __init__(self, records: Sequence[H.HullRecord] = (), *,
                 cell: float | None = None, slack: float = 0.0,
                 max_cells_per_hull: int = H.MAX_CELLS_PER_HULL,
                 upper_median: bool = False):
        self.records = tuple(records)
        self.slack = nonnegative_finite(slack, "slack")
        chosen = (choose_cell_size(self.records, upper_median=upper_median)
                  if cell is None else cell)
        self.cell = positive_finite(chosen, "cell")
        if (isinstance(max_cells_per_hull, bool)
                or not isinstance(max_cells_per_hull, int)
                or max_cells_per_hull <= 0):
            raise ValueError(
                "max_cells_per_hull должен быть положительным целым")
        self.max_cells_per_hull = max_cells_per_hull

        self.buckets: dict[tuple[int, int, int], list[int]] = {}
        self.oversized: list[int] = []
        cells_per: list[int] = []
        for index, record in enumerate(self.records):
            lo, hi = record.bounds()
            lo = tuple(lo[k] - self.slack for k in range(3))
            hi = tuple(hi[k] + self.slack for k in range(3))
            i0, i1, count = self._cell_range(lo, hi)
            cells_per.append(count)
            if count > self.max_cells_per_hull:
                self.oversized.append(index)
                continue
            for x in range(i0[0], i1[0] + 1):
                for y in range(i0[1], i1[1] + 1):
                    for z in range(i0[2], i1[2] + 1):
                        self.buckets.setdefault((x, y, z), []).append(index)

        occupancy = [len(items) for items in self.buckets.values()]
        self.stats = {
            "cell_mm": round(self.cell, 3),
            "cells": len(self.buckets),
            "oversized_hulls": len(self.oversized),
            "max_cells_per_hull": max(cells_per) if cells_per else 0,
            "mean_cells_per_hull": (
                round(sum(cells_per) / len(cells_per), 3)
                if cells_per else 0.0),
            "max_bucket": max(occupancy) if occupancy else 0,
            "mean_bucket": (
                round(sum(occupancy) / len(occupancy), 3)
                if occupancy else 0.0),
        }

    @property
    def giants(self) -> list[int]:
        """A compatible name used by the resolver's neighbourhood."""
        return self.oversized

    def _cell_range(self, lo, hi):
        i0 = [math.floor(lo[k] / self.cell) for k in range(3)]
        i1 = [math.floor(hi[k] / self.cell) for k in range(3)]
        count = 1
        for k in range(3):
            count *= i1[k] - i0[k] + 1
        return i0, i1, count

    def query_bounds(self, lo, hi, *, expand: float = 0.0) -> set[int]:
        """Return a conservative candidate set for an arbitrary AABB."""
        expand = nonnegative_finite(expand, "expand")
        lo = tuple(float(lo[k]) - expand for k in range(3))
        hi = tuple(float(hi[k]) + expand for k in range(3))
        i0, i1, count = self._cell_range(lo, hi)
        if count > self.max_cells_per_hull:
            return set(range(len(self.records)))
        result = set(self.oversized)
        for x in range(i0[0], i1[0] + 1):
            for y in range(i0[1], i1[1] + 1):
                for z in range(i0[2], i1[2] + 1):
                    result.update(self.buckets.get((x, y, z), ()))
        return result

    def query_record(self, index: int) -> set[int]:
        lo, hi = self.records[index].bounds()
        # Records were inserted with exactly this expansion. Querying the same
        # cells preserves the previous broad phase through the shared bucket.
        return self.query_bounds(lo, hi, expand=self.slack)

    def iter_candidate_pairs(
            self, *, slack: float = 0.0,
            pair_filter: Callable[[H.HullRecord, H.HullRecord], bool] | None = None,
            records: Sequence[H.HullRecord] | None = None,
    ) -> Iterator[tuple[int, int]]:
        """Lazily yield candidate pairs in canonical source-id order."""
        requested = nonnegative_finite(slack, "slack")
        if requested > self.slack + 1e-12:
            raise ValueError(
                f"сетка построена со slack={self.slack}, запрошено {requested}: "
                "широкая фаза перестала бы быть надмножеством")
        # The compatible wrapper in ``detect`` has historically accepted
        # ``records`` separately from the grid. The normal path supplies the
        # same records the index was built from; an explicit sequence
        # preserves the old edge-case contract without handing the index
        # ownership of the detector's semantics.
        pair_records = self.records if records is None else tuple(records)
        if len(pair_records) != len(self.records):
            raise ValueError("records length does not match the spatial index")
        order = sorted(
            range(len(pair_records)),
            key=lambda i: (str(getattr(pair_records[i], "source_id", "")), i),
        )
        rank = {record_index: position
                for position, record_index in enumerate(order)}
        for position, i in enumerate(order):
            neighbours = sorted(self.query_record(i), key=rank.__getitem__)
            for j in neighbours:
                if rank[j] <= position:
                    continue
                # The historical ``candidate_pairs`` fed the callback the
                # record with the smaller *index* first. Traversal now goes by
                # source-id, but the callback's orientation stays byte-for-byte
                # compatible even for an undesirable asymmetric filter.
                pair = (i, j) if i < j else (j, i)
                a, b = pair_records[pair[0]], pair_records[pair[1]]
                if pair_filter is not None and not pair_filter(a, b):
                    continue
                if bounds_overlap(a, b, requested):
                    yield pair
