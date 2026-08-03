"""TemplateRegistry — loads .cs.j2 and .manifest.yaml pairs from disk.

Per spec Section 7.2. Each template is a (file, manifest) pair. Registry
validates args against the manifest before rendering Jinja2.
"""
from __future__ import annotations
import pathlib
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from kukai.modeling.schemas.templates import ManifestSpec


class TemplateRegistry:
    """Discovers templates in a directory and renders them with manifest validation."""

    def __init__(self, templates_dir: pathlib.Path):
        self._dir = pathlib.Path(templates_dir)
        if not self._dir.is_dir():
            raise FileNotFoundError(f"templates dir not found: {self._dir}")
        self._env = Environment(
            loader=FileSystemLoader(self._dir),
            undefined=StrictUndefined,  # raise on undefined variables (catches typos)
            keep_trailing_newline=True,
        )
        self._manifests: dict[str, ManifestSpec] = {}
        self._discover()

    def _discover(self) -> None:
        for manifest_path in self._dir.glob("*.manifest.yaml"):
            stem = manifest_path.name[: -len(".manifest.yaml")]
            raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
            self._manifests[stem] = ManifestSpec(**raw)
            # Ensure the matching .cs.j2 exists
            tmpl_path = self._dir / self._manifests[stem].template
            if not tmpl_path.exists():
                raise FileNotFoundError(
                    f"manifest {manifest_path.name} references missing template {tmpl_path.name}"
                )

    def list_template_names(self) -> list[str]:
        return sorted(self._manifests)

    def get_manifest(self, name: str) -> ManifestSpec:
        if name not in self._manifests:
            raise KeyError(f"no template named {name!r}; known: {sorted(self._manifests)}")
        return self._manifests[name]

    def render(self, name: str, args: dict[str, Any]) -> str:
        manifest = self.get_manifest(name)
        validated = manifest.validate_args(args)
        template = self._env.get_template(manifest.template)
        return template.render(**validated)
