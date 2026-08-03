"""RAG benchmark framework.

Compares alternative RAG architectures (paths A/B/C/...) against a fixed
gold-set of Revit-task queries. Measures retrieval quality, first-shot
compile rate, repair efficiency, and e2e success.

Layout:
    paths/  -- pluggable RAGPath implementations
    gold_set.py -- curated benchmark queries with expected outcomes
    runner.py -- orchestrator that runs all paths and produces metrics
    metrics.py -- metric definitions
"""
