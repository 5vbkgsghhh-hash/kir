# -*- coding: utf-8 -*-
"""SLICES of corpus runs — small, real captures for the F5 acceptance.

🔴 WHAT LIVES HERE AND WHAT IT IS NOT. Each subdirectory holds REAL L0
lines from a real decompile run, narrowed down to the SEEDS of a subject,
their reference closure, and a named number of neighbors. Not one value is
invented.

THERE ARE TWO SUBJECTS, and each slice names its own in the `предмет`
field of `SLICE.json`:

* `floor_opening` — a door and a SLAB with an opening ring in its profile
  (the host is edited): `bench_A`, `k4_geom_wave2`, `len_ar_me_r24_v1`,
  `k2v33_join2`;
* `wall_opening` — OPENINGS IN WALLS and their host walls (the opening
  itself is edited): `mnvnk_k1_layers_walls`, `k4_geom_wave2_walls`.
No slice is a BUILDING: it has dozens of neighbors, not thousands, and it
proves the rule's independence from a single run, not scale.

What exactly was thrown out is written as a NUMBER in `SLICE.json` next to
each slice: the source run, its sha256, the seeds, how many elements out of
how many, how many categories were recounted, and how many receipts were
dropped as non-derivable.

Slices are edited ONLY by the cutter (`make_slice.py`), and this is
checked: `test_a_slice_is_reproducible_from_the_corpus` re-cuts from the
corpus and compares BYTE-FOR-BYTE. For this, compression is made
deterministic (`mtime=0`).
"""
