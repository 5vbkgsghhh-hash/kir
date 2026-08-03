"""Curated norm leaves per discipline (Phase 5 — data, grows by curation).

Each module exports ``LEAVES: list[NormLeaf]`` for one discipline, curated against
the real norms.db and verified by tests/test_norm_tree.py's grounding invariant.
norm_tree.ROOT attaches them by discipline id.
"""
