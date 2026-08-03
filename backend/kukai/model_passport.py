"""Model Passport — structured model context formatter.

Converts raw JSON model data from C# ContextCollector into
a Markdown document optimized for LLM system prompt injection.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class ModelPassport:
    """Formats raw Revit model data into structured Markdown passport."""

    def __init__(self, data: dict[str, Any]):
        self.data = data

    # ── Tier 1: Quick context (< 1 sec collection) ──────────────

    def format_quick(self) -> str:
        """Format Tier 1 data (~5K tokens). Available immediately on connect."""
        if not self.data.get("has_document"):
            return "## Паспорт модели\n\nДокумент не открыт."

        parts: list[str] = []
        parts.append(self._header())
        parts.append(self._categories())
        parts.append(self._levels())
        parts.append(self._active_context())
        return "\n\n".join(p for p in parts if p)

    # ── Tier 2: Full passport (5-10 sec collection) ─────────────

    def format_full(self) -> str:
        """Format complete passport (~20K tokens). Available after background scan."""
        if not self.data.get("has_document"):
            return "## Паспорт модели\n\nДокумент не открыт."

        parts: list[str] = []
        parts.append(self._header())
        parts.append(self._structure())
        parts.append(self._spatial())
        parts.append(self._elements())
        parts.append(self._parameters())
        parts.append(self._views_sheets())
        parts.append(self._standards())
        parts.append(self._active_context())
        return "\n\n".join(p for p in parts if p)

    # ── Tier 1 v2: lean high-signal ALWAYS-ON core (G1 grounding) ──

    # Soft caps so a huge model can't blow the prompt, while still showing ALL
    # categories (per-family types are capped to the top-N by count).
    _V2_TYPES_MAX_CHARS = 12000
    _V2_TYPES_PER_FAMILY = 40

    def format_v2_core(self) -> str:
        """Passport v2 — lean high-signal core meant to REPLACE format_quick as
        the always-on injection (it is NOT a third passport — same data dict,
        a better Tier-1 render). Front-loads the working memory DeepSeek lacks
        (G1): a project glossary (fuzzy term -> exact type names) + ALL type
        names per category + key params, so the model writes the right filter
        first-shot instead of calling get_model_details (the wasted round).

        Reads ``family_type_hierarchy`` — the key the C# collector actually
        sends. (The legacy ``_structure`` reads ``family_types`` and so never
        renders types at all — see passport audit 2026-06-06.)
        """
        if not self.data.get("has_document"):
            return "## Паспорт модели\n\nДокумент не открыт."
        detailed = self.data.get("detailed", {}) or {}
        hier = self._v2_hier(detailed)
        has_vitals = isinstance(detailed.get("vitals"), dict) and bool(detailed.get("vitals"))
        parts = [self._header()]
        # Wave 1 — LOD-0 gestalt (Building→Levels→Zones→Systems): the "see the
        # building whole" map, right after the title. Present only when the
        # perception graph was injected (flag KUKAI_PERCEPTION) → control identical.
        _gestalt = self._v2_gestalt(detailed)
        if _gestalt:
            parts.append(_gestalt)
        # Health header — the anti-fabrication anchor, and re-weights the always-on
        # core toward the 68% analysis/normcontrol slice.
        if has_vitals:
            parts.append(self._v2_health(detailed))
        # Type tables need the pushed family_type_hierarchy; when it's absent (no
        # detailed push — typically the FIRST TURN, before the async background
        # scan lands) fall back: under KUKAI_GESTALT_V2 a compact Tier-0 digest
        # with an explicit scan-in-progress marker, else the legacy category list.
        types_section = self._v2_types(hier) or self._first_turn_fallback()
        for section in (self._v2_glossary(hier), types_section,
                        self._levels(), self._v2_params(detailed)):
            if section:
                parts.append(section)
        if has_vitals:
            for section in (self._v2_units(detailed), self._v2_views(detailed),
                            self._v2_mandatory(detailed)):
                if section:
                    parts.append(section)
        parts.append(self._active_context())
        return "\n\n".join(p for p in parts if p)

    def _v2_gestalt(self, detailed: dict[str, Any]) -> str:
        """Wave 1 — the LOD-0 building map, from the injected perception graph.

        A graph carrying the ``v2`` marker (produced by summarize_graph_v2, which
        only runs under KUKAI_GESTALT_V2) renders through the v2 spine — useful
        even with zero rooms. Data-presence gating: no flag check needed here,
        flag OFF ⇒ only v1 graphs exist ⇒ byte-identical render."""
        graph = detailed.get("graph") if isinstance(detailed, dict) else None
        if not isinstance(graph, dict) or not graph:
            return ""
        try:
            if graph.get("v3"):
                from kukai.query.model_graph_v3 import build_gestalt_v3
                return build_gestalt_v3(self.data, detailed, graph)
            if graph.get("v2"):
                from kukai.query.model_graph import build_gestalt_v2
                return build_gestalt_v2(self.data, detailed, graph)
            from kukai.query.model_graph import build_gestalt
            return build_gestalt(self.data, detailed, graph)
        except Exception:  # noqa: BLE001 — never break the passport on a render error
            return ""

    # First-turn digest caps: enough to orient, small enough for the pocket.
    _T0_TOP_CATEGORIES = 15

    def _first_turn_fallback(self) -> str:
        """Types-section fallback for the first-turn blindness window (the
        detailed_passport push arrives seconds AFTER connect; turn 1 has only the
        Tier-0 context). Flag OFF ⇒ the legacy bare category list, byte-identical.
        Flag ON (KUKAI_GESTALT_V2) ⇒ a compact structured digest + an explicit
        scan-in-progress marker, so the model prefers query tools over guessing
        type names that are not yet known."""
        try:
            from kukai.query.model_graph import gestalt_v2_enabled
            from kukai.query.model_graph_v3 import graph_v3_enabled
            if not (gestalt_v2_enabled() or graph_v3_enabled()):
                return self._categories()
        except Exception:  # noqa: BLE001 — any flag/import trouble → legacy render
            return self._categories()
        cats = [c for c in self.data.get("categories", []) if isinstance(c, dict)]
        if not cats:
            return ""
        total = sum(c.get("count", 0) for c in cats)
        top = sorted(cats, key=lambda c: c.get("count", 0), reverse=True)
        shown = top[: self._T0_TOP_CATEGORIES]
        cat_line = ", ".join(
            f"{c.get('name_ru', c.get('name', '?'))} {c.get('count', 0)}" for c in shown)
        if len(top) > len(shown):
            cat_line += f" (+{len(top) - len(shown)} категорий)"
        return "\n".join([
            "### ПЕРВИЧНЫЙ ОБЗОР "
            "(фоновое сканирование ещё идёт — детальный паспорт будет доступен "
            "через несколько секунд)",
            f"Элементы: {total} · категорий: {len(cats)}" + (f" · {cat_line}" if cat_line else ""),
            "Имена типов/семейств ещё НЕ просканированы — не угадывай их: "
            "для фактов используй query_model / get_model_details.",
        ])

    @staticmethod
    def _v2_hier(detailed: dict[str, Any]) -> dict[str, Any]:
        """Family/type hierarchy: {category: [{family_name, types:[{count,name}]}]}."""
        h = detailed.get("family_type_hierarchy") or detailed.get("family_types") or {}
        return h if isinstance(h, dict) else {}

    @staticmethod
    def _v2_cat_total(fams: Any) -> int:
        if not isinstance(fams, list):
            return 0
        return sum(
            t.get("count", 0)
            for fam in fams if isinstance(fam, dict)
            for t in (fam.get("types") or []) if isinstance(t, dict)
        )

    def _v2_wall_types(self, hier: dict[str, Any]) -> list[str]:
        names: list[str] = []
        for cat, fams in hier.items():
            cl = cat.lower()
            if cl == "walls" or "стены" in cl or cl.startswith("стен"):
                if isinstance(fams, list):
                    for fam in fams:
                        for t in (fam.get("types") or []):
                            n = t.get("name")
                            if n:
                                names.append(n)
        return names

    @staticmethod
    def _fmt_glossary(g: dict[str, list[str]]) -> str:
        if not g:
            return ""
        lines = ["### СЛОВАРЬ (термин пользователя → точные имена типов в ЭТОЙ модели; фильтруй по ним)"]
        for alias, types in g.items():
            lines.append(f"- **{alias}** → {', '.join(types)}")
        return "\n".join(lines)

    @staticmethod
    def _glossary_from_meta(meta: dict[str, Any]) -> dict[str, list[str]]:
        """A2 (model-derived): bucket structural-host types by their REAL MATERIAL
        (+ WallType.Function for walls) — not the type NAME. Works on any model's
        naming ("Железобетон" AND "Бетон" → монолит; excludes block concretes),
        catches exterior/interior by the actual Function, and (Tier1.5) covers
        floors/ceilings/roofs too — the s12-floors miss was material-by-name. Non-
        wall types are tagged with their category so the model picks the right one."""
        g: dict[str, list[str]] = {
            "монолит / ЖБ / несущие": [], "блоки (керамзито/газо/пенобетон)": [],
            "наружные": [], "внутренние / перегородки": [],
        }
        for name, info in meta.items():
            if not isinstance(info, dict):
                continue
            mat = str(info.get("material") or "").upper()
            func = str(info.get("function") or "")
            cat = str(info.get("category") or "")
            disp = name if (not cat or cat == "Стены") else f"{name} [{cat}]"
            is_block = any(b in mat for b in ("КЕРАМЗИТ", "ГАЗОБЕТОН", "ПЕНОБЕТОН", "БЛОК"))
            is_concrete = ("ЖЕЛЕЗОБЕТОН" in mat) or ("БЕТОН" in mat and not is_block)
            if is_concrete:
                g["монолит / ЖБ / несущие"].append(disp)
            if is_block:
                g["блоки (керамзито/газо/пенобетон)"].append(disp)
            if func == "Exterior":
                g["наружные"].append(disp)
            elif func == "Interior":
                g["внутренние / перегородки"].append(disp)
        return {k: v for k, v in g.items() if v}

    def _v2_glossary(self, hier: dict[str, Any]) -> str:
        # A2: prefer the model-DERIVED glossary (real material + Function) when
        # type_meta is present (injected by the backend live-query); else fall
        # back to the name-substring heuristic (works without the live data).
        detailed = self.data.get("detailed") or {}
        meta = detailed.get("type_meta") if isinstance(detailed, dict) else None
        if isinstance(meta, dict) and meta:
            g = self._glossary_from_meta(meta)
            if g:
                return self._fmt_glossary(g)

        walls = self._v2_wall_types(hier)
        if not walls:
            return ""

        def has(s: str, *subs: str) -> bool:
            up = s.upper()
            return any(x in up for x in subs)

        # Name-substring heuristic (fallback). Do NOT match bare "БЕТОН" — it
        # mis-grabs "керамзитоБЕТОН" (lightweight infill blocks, NOT monolith).
        g = {
            "монолит / ЖБ / несущие": [
                w for w in walls
                if has(w, "МОНОЛ", "ЖЕЛЕЗОБЕТОН", "ЖБ", "Ж/Б") and "КЕРАМЗИТ" not in w.upper()
            ],
            "блоки (керамзитобетон/газобетон)": [
                w for w in walls if has(w, "КЕРАМЗИТ", "ГАЗОБЕТОН", "ПЕНОБЕТОН", "БЛОК")
            ],
            "перегородки": [w for w in walls if "перегородк" in w.lower()],
            "наружные": [w for w in walls if "наружн" in w.lower()],
            "витраж": [w for w in walls if ("витраж" in w.lower() or "schueco" in w.lower())],
            "отделочные": [w for w in walls if "отделк" in w.lower()],
        }
        g = {k: v for k, v in g.items() if v}
        return self._fmt_glossary(g)

    def _v2_types(self, hier: dict[str, Any]) -> str:
        if not hier:
            return ""
        lines = ["### ТИПЫ по категориям (точные имена — фильтровать по имени типа, не угадывать enum)"]
        total_chars = 0
        truncated = False
        for cat in sorted(hier, key=lambda c: self._v2_cat_total(hier[c]), reverse=True):
            fams = hier[cat]
            tot = self._v2_cat_total(fams)
            if not tot:
                continue
            block = [f"\n**{cat} — {tot}**"]
            for fam in (fams if isinstance(fams, list) else []):
                types = fam.get("types") or []
                if not types:
                    continue
                st = sorted(types, key=lambda x: x.get("count", 0), reverse=True)
                shown = st[:self._V2_TYPES_PER_FAMILY]
                ts = ", ".join(f"{t.get('name', '?')} ({t.get('count', 0)})" for t in shown)
                if len(st) > self._V2_TYPES_PER_FAMILY:
                    ts += f", (+{len(st) - self._V2_TYPES_PER_FAMILY} ещё)"
                fn = fam.get("family_name", "")
                block.append(f"- {fn}: {ts}" if fn else f"- {ts}")
            chunk = "\n".join(block)
            if total_chars + len(chunk) > self._V2_TYPES_MAX_CHARS:
                truncated = True
                break
            lines.append(chunk)
            total_chars += len(chunk)
        if truncated:
            lines.append("\n(…остальные категории — через get_model_details)")
        return "\n".join(lines)

    def _v2_params(self, detailed: dict[str, Any]) -> str:
        names: list[str] = []
        for key in ("project_parameters", "shared_parameters"):
            for p in (detailed.get(key) or []):
                if isinstance(p, dict) and p.get("name"):
                    names.append(p["name"])
        # dedup, preserve order
        seen: set[str] = set()
        names = [n for n in names if not (n in seen or seen.add(n))]
        if not names:
            return ""
        shown = names[:60]
        tail = f" (+{len(names) - 60})" if len(names) > 60 else ""
        return "### ПАРАМЕТРЫ проекта (есть): " + ", ".join(shown) + tail

    # ── Tier-0 model-health pocket (anti-fabrication anchor) ─────
    # All of these render ONLY when detailed["vitals"] is present, which the
    # backend injects solely under the PASSPORT_VITALS flag — so control stays
    # byte-identical to today (no flag check needed here).

    def _v2_health(self, detailed: dict[str, Any]) -> str:
        v = detailed.get("vitals")
        if not isinstance(v, dict) or not v:
            return ""
        lines = ["### СОСТОЯНИЕ МОДЕЛИ (реальные данные модели — НЕ выдумывай числа; "
                 "точные элементы бери инструментами)"]
        w = v.get("warnings", {}) or {}
        wln = f"- Предупреждения Revit: {w.get('count', 0)}"
        if w.get("top"):
            wln += f" (топ: {'; '.join(w['top'][:3])})"
        lines.append(wln)
        lines.append(f"- Импорты CAD (DWG): {v.get('imports', 0)}")
        g = v.get("grids", {}) or {}
        lv = v.get("levels", {}) or {}
        lines.append(f"- Закреплено: оси {g.get('pinned', 0)}/{g.get('total', 0)}, "
                     f"уровни {lv.get('pinned', 0)}/{lv.get('total', 0)}")
        r = v.get("rooms", {}) or {}
        if r.get("total"):
            lines.append(
                f"- Помещения: {r.get('total', 0)} (размещено {r.get('placed', 0)}, "
                f"без имени/номера {r.get('unnamed', 0)}, не размещено {r.get('unplaced', 0)})"
            )
        lines.append(f"- Варианты проекта: {v.get('design_options', 0)} · "
                     f"Worksharing: {'да' if v.get('workshared') else 'нет'}")
        mep = v.get("mep", {}) or {}
        if mep.get("present"):
            lines.append(f"- MEP: воздуховоды {mep.get('ducts', 0)}, трубы {mep.get('pipes', 0)}, "
                         f"оборудование {mep.get('mech_equipment', 0)}, сантехника {mep.get('plumbing', 0)}")
        else:
            lines.append("- MEP: НЕТ (0 воздуховодов / 0 труб / 0 оборудования) — "
                         "инженерных систем в модели нет")
        return "\n".join(lines)

    def _v2_mandatory(self, detailed: dict[str, Any]) -> str:
        v = detailed.get("vitals") or {}
        md = v.get("mandatory") or []
        if not md:
            return ""
        lines = ["### ЗАПОЛНЕННОСТЬ ОБЯЗАТЕЛЬНЫХ ПАРАМЕТРОВ "
                 "(нормоконтроль; точные пустые — query_model return=coverage)"]
        for m in md:
            total = int(m.get("total", 0) or 0)
            filled = int(m.get("filled", 0) or 0)
            empty = total - filled
            pct = round(100 * filled / total) if total else 0
            ln = f"- {m.get('label', '?')}: {filled}/{total} ({pct}%)"
            if empty:
                ln += f", пустых {empty}"
            lines.append(ln)
        return "\n".join(lines)

    def _v2_units(self, detailed: dict[str, Any]) -> str:
        ud = detailed.get("units_detail") or {}
        if not isinstance(ud, dict) or not ud:
            return ""
        return (f"### ЕДИНИЦЫ: длина={ud.get('length', '?')}, "
                f"площадь={ud.get('area', '?')}, объём={ud.get('volume', '?')}")

    def _v2_views(self, detailed: dict[str, Any]) -> str:
        vs = detailed.get("view_stats") or {}
        sh = detailed.get("sheets") or []
        sc = detailed.get("schedules") or []
        if not (vs or sh or sc):
            return ""
        parts: list[str] = []
        if isinstance(vs, dict) and vs:
            nviews = sum(int(c or 0) for c in vs.values() if isinstance(c, (int, float)))
            if nviews:
                parts.append(f"видов ~{nviews}")
        if sh:
            parts.append(f"листов {len(sh)}")
        if sc:
            parts.append(f"спецификаций {len(sc)}")
        if not parts:
            return ""
        return ("### ДОКУМЕНТАЦИЯ: " + ", ".join(parts)
                + " (списки — get_model_details section=views)")

    # ── Cache fingerprint ───────────────────────────────────────

    def compute_fingerprint(self) -> str:
        """Compute hash for cache invalidation."""
        cats = self.data.get("categories", [])
        element_count = sum(c.get("count", 0) for c in cats)
        key = (
            element_count,
            len(self.data.get("levels", [])),
            self.data.get("detailed", {}).get("family_count", 0),
            self.data.get("detailed", {}).get("param_count", 0),
        )
        return hashlib.md5(str(key).encode()).hexdigest()[:12]

    # ── Formatters ──────────────────────────────────────────────

    def _header(self) -> str:
        name = self.data.get("document_name", "Unknown")
        version = self.data.get("revit_version", "?")
        units = self.data.get("units", "metric")
        cats = self.data.get("categories", [])
        total = sum(c.get("count", 0) for c in cats)
        levels = self.data.get("levels", [])

        lines = [
            f"## Паспорт модели: {name}",
            f"Revit {version} | {total} элементов | {len(levels)} уровней | "
            f"Единицы: {'мм' if units == 'metric' else 'футы'}",
        ]

        # Executive summary from detailed data if available
        summary = self.data.get("detailed", {}).get("executive_summary", "")
        if summary:
            lines.append(f"\n{summary}")

        completeness = self._detailed_completeness_notice()
        if completeness:
            lines.append(f"\n{completeness}")

        return "\n".join(lines)

    def _detailed_completeness_notice(self) -> str:
        """Render collection proof for versioned detailed passports.

        Legacy/unversioned passports remain byte-compatible.  A v2 passport is
        authoritative only when all proof fields agree; contradictions degrade
        to partial so an absent section can never be interpreted as a true zero.
        """

        detailed = self.data.get("detailed")
        if not isinstance(detailed, dict):
            return ""
        schema = detailed.get("schema_version")
        if schema is None:
            return ""  # version-tolerant read of legacy cached artifacts
        if schema != "detailed-passport/2":
            return "\n".join([
                "### ПОЛНОТА ПАСПОРТА: НЕ ПОДТВЕРЖДЕНА",
                f"Версия `{schema}` не поддерживается этим сервером. "
                "Не делай отрицательных выводов по отсутствующим секциям.",
            ])

        completed = [
            str(item) for item in (detailed.get("completed_sections") or [])
            if isinstance(item, str) and item
        ]
        pending = [
            str(item) for item in (detailed.get("pending_sections") or [])
            if isinstance(item, str) and item
        ]
        raw_errors = detailed.get("section_errors")
        errors = raw_errors if isinstance(raw_errors, dict) else {}
        status = str(detailed.get("collection_status") or "unknown")
        declared_complete = detailed.get("complete") is True
        proven_complete = (
            declared_complete
            and status == "complete"
            and not pending
            and not errors
        )

        elapsed = detailed.get("collection_time_ms")
        budget = detailed.get("budget_ms")
        timing_bits: list[str] = []
        if isinstance(elapsed, (int, float)):
            timing_bits.append(f"сбор {int(elapsed)} мс")
        if isinstance(budget, (int, float)):
            timing_bits.append(f"бюджет {int(budget)} мс")

        if proven_complete:
            suffix = f" ({', '.join(timing_bits)})" if timing_bits else ""
            return (
                "### ПОЛНОТА ПАСПОРТА: ПОДТВЕРЖДЕНА\n"
                f"Все {len(completed)} секций собраны{suffix}."
            )

        lines = [
            "### ПОЛНОТА ПАСПОРТА: ЧАСТИЧНАЯ",
            f"Статус: `{status}`"
            + (f" · {', '.join(timing_bits)}" if timing_bits else "")
            + ".",
            "**Отсутствующая секция означает «не собрано», а не «в модели ноль». "
            "Не делай отрицательных выводов без live-запроса.**",
        ]
        if completed:
            lines.append("Собрано: " + ", ".join(completed) + ".")
        if pending:
            lines.append("Не собрано: " + ", ".join(pending) + ".")
        if errors:
            names = [str(name) for name in errors.keys()]
            lines.append("Ошибки секций: " + ", ".join(names) + ".")
        return "\n".join(lines)

    def _categories(self) -> str:
        cats = self.data.get("categories", [])
        if not cats:
            return ""
        lines = ["### Категории"]
        for c in sorted(cats, key=lambda x: x.get("count", 0), reverse=True):
            lines.append(f"- {c.get('name_ru', c.get('name', '?'))}: {c.get('count', 0)}")
        return "\n".join(lines)

    def _levels(self) -> str:
        levels = self.data.get("levels", [])
        if not levels:
            return ""
        lines = ["### Уровни"]
        for lv in levels:
            lines.append(f"- {lv.get('name', '?')}: {lv.get('elevation_m', 0):+.3f} м")
        return "\n".join(lines)

    def _active_context(self) -> str:
        view = self.data.get("current_view", {})
        sel = self.data.get("selection", {})
        lines = ["### Активный контекст"]
        if view.get("name"):
            lines.append(f"Вид: {view['name']} ({view.get('type', '?')})")
        if sel.get("count", 0) > 0:
            lines.append(f"Выделено: {sel['count']} элементов ({', '.join(sel.get('categories', []))})")
        else:
            lines.append("Выделение: нет")
        return "\n".join(lines)

    def _structure(self) -> str:
        detailed = self.data.get("detailed", {})
        family_types = (
            detailed.get("family_type_hierarchy")
            or detailed.get("family_types")
            or {}
        )
        if not family_types:
            return self._categories()  # fallback to basic

        lines = ["### Структура модели — типоразмеры"]
        for cat_name, families in family_types.items():
            cat_total = sum(
                sum(t.get("count", 0) for t in fam.get("types", []))
                for fam in families
            )
            lines.append(f"\n**{cat_name}: {cat_total}**")
            for fam in families:
                types_str = ", ".join(
                    f"{t['name']} ({t['count']})" for t in fam.get("types", [])
                )
                lines.append(f"- {fam.get('family_name', '?')}: {types_str}")
        return "\n".join(lines)

    def _spatial(self) -> str:
        detailed = self.data.get("detailed", {})
        lines = ["### Пространственная организация"]

        # Levels (enhanced)
        levels = self.data.get("levels", [])
        if levels:
            lines.append("\n**Уровни:**")
            for lv in levels:
                has_plan = "\u2713" if lv.get("has_plan_view") else "\u2014"
                lines.append(f"- {lv.get('name', '?')}: {lv.get('elevation_m', 0):+.3f} м (план: {has_plan})")

        # Grids
        grids = detailed.get("grids", {})
        if grids:
            x_grids = ", ".join(grids.get("x_names", []))
            y_grids = ", ".join(grids.get("y_names", []))
            if x_grids:
                lines.append(f"\n**Оси X:** {x_grids}")
            if y_grids:
                lines.append(f"**Оси Y:** {y_grids}")

        # Phases
        phases = detailed.get("phases", [])
        active_phase = detailed.get("active_phase", "")
        if phases:
            phase_list = ", ".join(p.get("name", "?") for p in phases)
            lines.append(f"\n**Фазы:** {phase_list}")
            if active_phase:
                lines.append(f"**Активная фаза:** {active_phase}")

        # Rooms summary
        rooms = detailed.get("rooms") or detailed.get("rooms_summary", {})
        if rooms:
            lines.append(f"\n**Помещения: {rooms.get('total', 0)}**")
            for rt in rooms.get("by_type", []):
                lines.append(
                    f"- {rt['name']}: {rt['count']} шт, "
                    f"средняя площадь {rt.get('avg_area', 0):.1f} м\u00b2"
                )
            unplaced = rooms.get("unplaced_levels", [])
            if unplaced:
                lines.append(f"Нет помещений на: {', '.join(unplaced)}")

        # Bounding box
        bbox = detailed.get("bounding_box", {})
        if bbox:
            lines.append(
                f"\n**Габарит:** ~{bbox.get('length_m', 0):.0f} \u00d7 "
                f"{bbox.get('width_m', 0):.0f} \u00d7 {bbox.get('height_m', 0):.0f} м"
            )

        return "\n".join(lines)

    def _elements(self) -> str:
        detailed = self.data.get("detailed", {})
        lines = ["### Элементы"]

        # Distribution by level
        dist = detailed.get("distribution_by_level", {})
        if dist:
            lines.append("\n**Распределение по уровням:**")
            for level_name, cats in dist.items():
                cat_str = ", ".join(f"{c}: {n}" for c, n in cats.items() if n > 0)
                if cat_str:
                    lines.append(f"- {level_name}: {cat_str}")

        # Groups
        groups = detailed.get("groups", [])
        if groups:
            lines.append("\n**Группы:**")
            for g in groups:
                lines.append(f"- {g['name']}: {g['count']} экз.")

        # Links
        links = detailed.get("linked_models", [])
        if links:
            lines.append("\n**Связанные файлы:**")
            for lnk in links:
                lines.append(f"- {lnk.get('filename', '?')} ({lnk.get('link_type', '?')})")

        # Worksets
        worksets = detailed.get("worksets", [])
        if worksets:
            lines.append(f"\n**Рабочие наборы:** {', '.join(w.get('name', '?') for w in worksets)}")

        return "\n".join(lines)

    def _parameters(self) -> str:
        detailed = self.data.get("detailed", {})
        lines = ["### Параметры"]

        # Shared parameters
        shared = detailed.get("shared_parameters", [])
        if shared:
            lines.append("\n**Общие параметры:**")
            lines.append("| Имя | Тип | Категории |")
            lines.append("|-----|-----|-----------|")
            for p in shared:
                cats = ", ".join(p.get("categories", [])[:5])
                if len(p.get("categories", [])) > 5:
                    cats += f" +{len(p['categories']) - 5}"
                lines.append(f"| {p.get('name', '?')} | {p.get('storage_type', '?')} | {cats} |")

        # Project parameters
        project = detailed.get("project_parameters", [])
        if project:
            lines.append("\n**Параметры проекта:**")
            lines.append("| Имя | Тип | Instance/Type | Категории |")
            lines.append("|-----|-----|---------------|-----------|")
            for p in project:
                inst = "instance" if p.get("is_instance") else "type"
                cats = ", ".join(p.get("categories", [])[:4])
                lines.append(f"| {p.get('name', '?')} | {p.get('storage_type', '?')} | {inst} | {cats} |")

        # Value samples
        samples = detailed.get("value_samples", {})
        if samples:
            lines.append("\n**Примеры значений:**")
            for param_name, info in samples.items():
                if isinstance(info, dict) and "values" in info:
                    vals = ", ".join(f'"{v}"' for v in info["values"][:8])
                    lines.append(f"- **{param_name}**: {vals}")
                elif isinstance(info, dict) and "min" in info:
                    lines.append(
                        f"- **{param_name}**: мин={info['min']}, "
                        f"медиана={info.get('median', '?')}, макс={info['max']}"
                    )

        # Global parameters
        globals_p = detailed.get("global_parameters", [])
        if globals_p:
            lines.append("\n**Глобальные параметры:**")
            for gp in globals_p:
                lines.append(f"- {gp.get('name', '?')} = {gp.get('value', '?')}")

        return "\n".join(lines)

    def _views_sheets(self) -> str:
        detailed = self.data.get("detailed", {})
        lines = ["### Виды и листы"]

        view_stats = detailed.get("view_stats", {})
        if view_stats:
            for vtype, count in view_stats.items():
                if count > 0:
                    lines.append(f"- {vtype}: {count}")

        sheets = detailed.get("sheets", [])
        if sheets:
            lines.append(f"\n**Листы ({len(sheets)}):**")
            for s in sheets[:30]:  # limit to 30
                lines.append(f"- {s.get('number', '?')}: {s.get('name', '?')}")
            if len(sheets) > 30:
                lines.append(f"... и ещё {len(sheets) - 30}")

        schedules = detailed.get("schedules", [])
        if schedules:
            lines.append(f"\n**Спецификации ({len(schedules)}):**")
            for sc in schedules[:20]:
                lines.append(f"- {sc.get('name', '?')} \u2192 {sc.get('category', '?')}")
            if len(schedules) > 20:
                lines.append(f"... и ещё {len(schedules) - 20}")

        return "\n".join(lines)

    def _standards(self) -> str:
        detailed = self.data.get("detailed", {})
        lines = ["### Стандарты проекта"]

        lang = detailed.get("language", "")
        if lang:
            lines.append(f"**Язык:** {lang}")

        units_detail = detailed.get("units_detail", {})
        if units_detail:
            lines.append(
                f"**Единицы:** длина={units_detail.get('length', '?')}, "
                f"площадь={units_detail.get('area', '?')}, "
                f"объём={units_detail.get('volume', '?')}"
            )

        naming = detailed.get("naming_conventions", {})
        if naming:
            lines.append("\n**Конвенции именования:**")
            for cat_name, examples in naming.items():
                lines.append(f"- {cat_name}: {', '.join(examples[:5])}")

        classification = detailed.get("classification", {})
        if classification.get("system"):
            lines.append(
                f"\n**Классификация:** {classification['system']} "
                f"(заполнено {classification.get('coverage', 0)}%)"
            )

        return "\n".join(lines)


# ── Caching ─────────────────────────────────────────────────

class PassportCache:
    """Cache model passports to disk, keyed by fingerprint."""

    def __init__(self, cache_dir: Optional[Path] = None):
        if cache_dir is None:
            import os
            local = os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")
            cache_dir = Path(str(local)) / "KUKI" / ".kuki"
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, fingerprint: str) -> Path:
        return self.cache_dir / f"passport_{fingerprint}.json"

    def get(self, fingerprint: str) -> Optional[dict[str, Any]]:
        """Load cached passport data. Returns None if not found."""
        path = self._path(fingerprint)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def get_by_document(
        self,
        document_path: Optional[str],
        document_name: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """Return the most-recent cached DETAILED-passport data matching the
        document (path preferred, then name). Used to repopulate in-memory
        detailed after a restart: ``detailed_passport`` is a pure plugin push
        (sent on model-open; the server cannot request it), so it is lost on
        restart — but the on-disk cache survives. Best-effort; returns None on
        any miss/error.
        """
        try:
            files = sorted(
                self.cache_dir.glob("passport_*.json"),
                key=lambda f: f.stat().st_mtime,
                reverse=True,
            )
        except OSError:
            return None
        cands: list[dict[str, Any]] = []
        for f in files:
            try:
                obj = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            data = obj.get("data")
            if isinstance(data, dict):
                cands.append(data)
        if document_path:
            for d in cands:
                if d.get("document_path") == document_path:
                    return d
        if document_name:
            for d in cands:
                if d.get("document_name") == document_name:
                    return d
        return None

    def save(self, fingerprint: str, data: dict[str, Any], formatted: str) -> None:
        """Save passport data + formatted markdown to cache."""
        try:
            payload = {
                "fingerprint": fingerprint,
                "data": data,
                "formatted": formatted,
            }
            self._path(fingerprint).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning("Failed to save passport cache: %s", e)

    def cleanup(self, keep: int = 5) -> None:
        """Keep only the N most recent cache files."""
        try:
            files = sorted(self.cache_dir.glob("passport_*.json"), key=lambda f: f.stat().st_mtime)
            for f in files[:-keep]:
                f.unlink()
        except Exception:
            pass
