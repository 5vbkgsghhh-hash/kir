"""Revit-Coder integration — Phase 1 pilot.

Provides an alternative code generation path via fine-tuned 14B model
hosted on Kaggle, accessed via OpenAI-compatible router on VPS.

Activated via KUKAI_USE_REVIT_CODER=1. See:
docs/superpowers/specs/2026-05-01-revit-coder-integration-design.md
"""
from kukai.revit_coder.types import (
    ModelContext,
    RevitCoderResult,
    RevitCoderError,
)

__all__ = ["ModelContext", "RevitCoderResult", "RevitCoderError"]
