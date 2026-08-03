"""Constants and thresholds for the KUKAI Audit Engine."""

from __future__ import annotations

from kukai.audit.models import Category

# Default thresholds
MAX_WARNINGS_THRESHOLD = 100
MAX_CRITICAL_WARNINGS = 0
MIN_FLOOR_HEIGHT_M = 2.4
MAX_FLOOR_HEIGHT_M = 6.0
MAX_BBOX_DIMENSION_M = 500.0

# Default categories to check
DEFAULT_CATEGORIES = [c.value for c in Category]
