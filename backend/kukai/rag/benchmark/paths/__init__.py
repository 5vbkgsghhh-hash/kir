"""Pluggable RAGPath implementations for benchmark comparison."""

from kukai.rag.benchmark.paths.base import RAGPath, RAGResult, RepairHint
from kukai.rag.benchmark.paths.path_a import PathA
from kukai.rag.benchmark.paths.path_b import PathB
from kukai.rag.benchmark.paths.path_c import PathC
from kukai.rag.benchmark.paths.path_d import PathD
from kukai.rag.benchmark.paths.path_off import PathOff

__all__ = [
    "RAGPath",
    "RAGResult",
    "RepairHint",
    "PathA",
    "PathB",
    "PathC",
    "PathD",
    "PathOff",
]
