"""Build-time module selection; intentionally included in sdist, not wheel.

Package discovery remains kir*. Keep the original per-module test predicate:
package exclusion alone can turn excluded directories into package data.
"""
import os
import tomllib

from setuptools.command.build_py import build_py


HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(HERE, "pyproject.toml"), "rb") as source:
    KEEP = set(tomllib.load(source)["tool"]["kir"]["wheel"]["keep"])


def _is_test(rel):
    parts = rel.split("/")
    return "tests" in parts or parts[-1].startswith("test_")


class PrunedBuildPy(build_py):
    def find_package_modules(self, package, package_dir):
        kept = []
        for pkg, mod, path in super().find_package_modules(package, package_dir):
            rel = os.path.relpath(path, HERE).replace(os.sep, "/")
            if _is_test(rel) and rel not in KEEP:
                continue
            kept.append((pkg, mod, path))
        return kept
