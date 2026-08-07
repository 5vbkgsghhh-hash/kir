"""Dependency-neutral constants shared by extraction and census balancing."""
from __future__ import annotations


# Stable census key for elements that have no Revit category.  It is not
# "other": absence of a category is a countable document fact.
NO_CATEGORY_KEY = "no_category"

