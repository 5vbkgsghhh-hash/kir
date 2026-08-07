# KUKAI Prod Operation Distribution — for Revit-IR opcode prioritization

Generated 2026-07-16 from prod log analysis (SSH root@155.254.35.192, read-only). Sources: fresh journald (post-migration, ~2 days) + old-server filesystem snapshot at `/root/migration/dima-root/` (May 12 – Jun 30, 2026).

## 1. Tool-call distribution (top-level action shape)

This is the most reliable structural signal — the LLM's actual tool choice, combined across all sources that log `TOOL CALL: <name>` (fresh journalctl Jul14-16, `kukai_lastweek.log` Jun23, `kukai_24h.log` May12-13). **`kuki_revit_bridge`-style whole-payload logs (kukai_signals.txt) could not be parsed for a clean tool name and are excluded from this table** (see §4).

| Tool call | Count | % | Source(s) |
|---|---|---|---|
| `execute_revit_code` (generic C# exec — action encoded *inside* the code, not the tool name) | 301 | 74.0% | fresh journald, kukai_lastweek.log, kukai_24h.log |
| `query_model` (read: category/filter/aggregate/return) | 35 | 8.6% | fresh journald, kukai_lastweek.log |
| `get_model_info` (whole-model summary) | 19 | 4.7% | fresh journald, kukai_lastweek.log, kukai_24h.log |
| `inspect` (single element_id lookup) | 15 | 3.7% | kukai_lastweek.log |
| `get_model_details` (sectioned model info) | 12 | 2.9% | kukai_lastweek.log |
| `apply_revit_write` (structured write: schedules, view actions) | 10 | 2.5% | kukai_lastweek.log |
| `excel_script` (filename+script → Excel export) | 6 | 1.5% | kukai_lastweek.log |
| `generate_report` | 5 | 1.2% | kukai_lastweek.log, kukai_24h.log |
| `select_elements` | 2 | 0.5% | kukai_24h.log |
| `lookup_norm` (нормоконтроль reference lookup) | 1 | 0.2% | kukai_lastweek.log |
| `add_user_note` | 1 | 0.2% | kukai_lastweek.log |
| **Total** | **407** | 100% | |

**Key structural finding:** ~74% of all tool calls are the generic `execute_revit_code` bridge — the LLM writes free-form C# rather than calling a typed action. This is *exactly* the gap Revit-IR is meant to close: today there is no opcode boundary at the tool-call layer, so the real action distribution is invisible to the orchestrator and only recoverable by parsing generated C# or user text (§2, §4).

### 1a. `apply_revit_write` argument shapes (proxy for write-side sub-actions), n=10
| args_keys shape | count | inferred action |
|---|---|---|
| `['operation','category','schedule_name','schedule_fields']` (both orderings) | 9 | create_schedule_report |
| `['element_ids','operation','view_action']` | 1 | view/visibility op on element set |

### 1b. `query_model` argument shapes (proxy for read-side sub-actions), n=~23 sampled from lastweek.log
| args_keys shape | count | inferred action |
|---|---|---|
| `['category','return']` | 13 | list/filter by category |
| `['category','return','group_by']` | 3 | count/group by category |
| `['action','category','type_contains','return']` | 3 | filter by type |
| `['action','category','limit','return']` | 3 | filter with limit |
| `['action','aggregate','category','layer_material_contains','return']` | 3 | aggregate by material (e.g. wall area by material) |
| `['selected','return']` | 1 | query current selection |
| `[]` | 1 | bare query |

Note: actual `action=`/`operation=` **values** are not present in any log — only `args_keys` (key names) are logged, never the argument values. This caps how finely §1a/§1b can be broken down; see §4.

## 2. User-intent classification (from raw user messages, `messages_2wk.tsv`, May 18–29 2026, n=588 non-greeting user turns)

This is the ground-truth "what does the user actually ask for" signal, classified by keyword/regex on the message text. **No raw user text is reproduced below beyond short (<100 char), delexicalized examples.**

| Action × object category | Count | % | Example (truncated, anonymized) |
|---|---|---|---|
| unclassified/other | 274 | 46.6% | (see §4 — largest bucket, mostly follow-up/conversational turns) |
| create_element | 70 | 11.9% | "Как создать стену программно в Revit?" |
| filter_select_category | 39 | 6.6% | "Выдели мне все оси" |
| check_element_normcontrol | 36 | 6.1% | "запусти проверку" |
| count_element | 35 | 6.0% | "Посчитай объём и площадь стен с именем материала…" |
| explain_howto_capability | 26 | 4.4% | "Что ты умеешь?" |
| conversational_filler (не операция) | 24 | 4.1% | "да" / "хорошо" / "продолжай" |
| create_schedule_report | 22 | 3.7% | "выгрузи отчёт в формат excel" |
| set_param_replace_rename | 17 | 2.9% | "замени все трубы 16 на 20" |
| list_element | 12 | 2.0% | "Покажи все стены" |
| delete_element | 11 | 1.9% | "убери из отчёта помещения с именем…" |
| isolate_visibility_view | 11 | 1.9% | "Изолируй монолит" |
| get_param_query | 5 | 0.9% | "какая длина труб 16х2,2 в выделенном диапазоне?" |
| compare_elements_views | 3 | 0.5% | "Сравни два вида…" |
| move_element | 3 | 0.5% | "Скопируй … и перемести в рабочий набор…" |

## 3. Top CS compile-error codes (cs_codes) — knowledge-gap map for the code generator

Aggregated across 4 old-server log files with raw compiler diagnostics (`bridge_errs.txt` May12-19, `tail200.log` ~Jun3-5, `kukai_24h.log` May12-13, `kukai_lastweek.log` Jun23) — **85,374 total CS-code occurrences**. Fresh journald (Jul14-16, n=14 occurrences: 11×CS0117, 2×CS1061, 1×CS0103) shows the *same top-2 codes still dominant* after migration — consistent signal across a ~2-month span.

| Rank | Code | Meaning | Count | % |
|---|---|---|---|---|
| 1 | CS1061 | Type does not contain a definition for member (wrong/hallucinated Revit API member) | 27,618 | 32.3% |
| 2 | CS0117 | Type does not contain a definition for member (static/type-level variant) | 13,747 | 16.1% |
| 3 | CS0104 | Ambiguous reference between namespaces (e.g. `Line`, `Color`, `Parameter` collide between `Autodesk.Revit.DB` and other usings) | 5,610 | 6.6% |
| 4 | CS1001 | Identifier expected (malformed generated code) | 5,589 | 6.5% |
| 5 | CS0161 | Not all code paths return a value | 5,448 | 6.4% |
| 6 | CS0103 | Name does not exist in current context (undeclared variable/method) | 4,745 | 5.6% |
| 7 | CS0012 | Type defined in an assembly not referenced (missing `using`/reference) | 3,303 | 3.9% |
| 8 | CS0246 | Type or namespace not found | 3,224 | 3.8% |
| 9 | CS1513 | `}` expected (malformed/truncated code) | 2,761 | 3.2% |
| 10 | CS1503 | Argument type mismatch | 2,543 | 3.0% |

**CS1061 + CS0117 alone = 48.4% of all compile errors.** Both are "hallucinated Revit API member" errors — the single largest, most consistent pain point of the current C# code generator, and the strongest argument for Revit-IR: a typed IR with a deterministic compiler cannot hallucinate a nonexistent `.Member` because the compiler — not the LLM — resolves API surface.

CS0104 (ambiguous namespace) and CS0012 (missing assembly reference) are the next-largest *mechanical* (non-hallucination) categories — both are exactly the class of error a deterministic IR-to-C# compiler eliminates by construction (it owns imports/usings/references, per the IR-spine design already agreed — see prior program notes).

## 4. ok / repair / fail split (pipeline health)

Two independent signals, **not directly comparable** (different eras, different instrumentation):

**A. Fresh journald `EXEC_PIPELINE_RECORD` (exact, but tiny sample — Jul14-16, n=5):**
| state | count | % |
|---|---|---|
| ok | 4 | 80% |
| fail | 1 | 20% |
| had ≥1 repair attempt (preflight_fixer or llm_repair) before settling | 3 | 60% |

**B. Old-server `bridge_errs.txt` approximate `"success": true/false` field occurrences (May 12–19, n=4930 — NOT a 1:1 proxy for pipeline runs, may double-count per-request):**
| status | count | % |
|---|---|---|
| success: true | 4,862 | 98.6% |
| success: false | 68 | 1.4% |

These two numbers are **not reconcilable** — (A) is a precise per-pipeline-run verdict from the current instrumented pipeline; (B) is a much coarser textual field from raw request/response dumps in an older code path, likely counting successful *sub-steps* rather than full user-turn outcomes, which is why its "success" rate reads far higher than the fresh sample's failure-inclusive 80%. Treat (B) only as "the old system was not in a persistent crash state," not as a calibrated success-rate estimate. The `repairs` mechanism (preflight_fixer / llm_repair auto-fixing bad codegen before it reaches the user) visible in (A) is itself indirect evidence for the CS1061/CS0117 story in §3 — the pipeline already spends real latency (one record showed `total_ms: 38195` due to an `llm_repair` retry) papering over exactly the hallucinated-API-member class of error that a typed IR would prevent at the source.

## 5. Honest data limitations

- **EXEC_PIPELINE_RECORD and WIKI_ROUTER do not exist anywhere in the old-server snapshot** (`/root/migration/dima-root/`, ~2GB+ searched) — confirmed via full recursive grep across the snapshot. That structured-logging format was introduced after the last old-server log dump (Jun 30, 2026). Only the fresh ~2-day journald window has these markers, and it is small: 5 EXEC_PIPELINE_RECORD, 23 WIKI_ROUTER, 19 TOOL CALL lines total. All CS-error and tool-call volume analysis above therefore leans on older, differently-shaped log formats (`TOOL CALL: <name>, args_keys=[...]`, raw LiteLLM request/response dumps, and bare `CS####` diagnostic text) — cross-source consistency (same top codes, same tool-name shape) is the main confidence check available, not a single authoritative log.
- **`op` field is always `null`** in every EXEC_PIPELINE_RECORD found (fresh journald, n=5/5). `tool` is always `"execute_revit_code"` in all 5. This confirms the pipeline currently has *no* action-type tagging at all at the point of logging — 100% of the pipeline-record sample required tool-name/args-shape heuristics, not a direct `op` read.
- **Tool-call argument *values* are never logged**, only `args_keys` (key names) — e.g. `apply_revit_write, args_keys=['operation','category',...]` never shows what `operation` actually equals. §1a/§1b sub-action labels are therefore inferred from key-shape + tool name, not read directly. This is the single biggest ceiling on classification precision in this report.
- **46.6% of user messages (§2) fell into `unclassified_other`.** Manually sampled: this bucket is dominated by (a) multi-turn follow-ups/clarifications with no new action verb ("хорошо, вот для...", "продолжай"), (b) highly domain-specific one-off phrasing not caught by the keyword list (marking/tagging workflows — "проставь марки", "расставь марки" — were partially recovered into set_param_replace_rename but likely under-counted), (c) non-Russian/non-English text (Uzbek observed in a few samples) that the keyword classifier does not cover, and (d) genuinely ambiguous short queries. This is a keyword-regex classifier, not an LLM classifier — a follow-up pass with an LLM-based intent labeler would likely resolve a large fraction of this bucket and is the natural next step if finer-grained priors are needed.
- **`kuki_revit_bridge`-tagged calls in `kukai_signals.txt`** (99,695 lines, Apr26–Jun17) could not be cleanly parsed into a tool-call table — each line embeds the full request payload (system prompt + generated C# + prior turns) rather than a clean `TOOL CALL: <name>` marker, and grepping structured fields out of it reliably was not attempted given the size/noise tradeoff; this file was used only for its 1,453 raw `TOOL CALL` occurrence count (not broken out by name) and as a secondary confirmation source for Revit API surface patterns (`FilteredElementCollector`: 385,729 occurrences, `Transaction(`: 130,979, `FamilyInstance`: 114,671, `.Create(`: 92,099, `LookupParameter`: 87,681, `Wall.Create`: 10,613 — raw grep counts across the whole file, **not** deduplicated per distinct pipeline run, so these are directional "API surface touched" signals only, not call-frequency counts, and are not included as a primary table above to avoid conflating them with actual op frequency).
- **Coverage window:** old-server data spans **May 12 – Jun 30, 2026** (~7 weeks, several distinct log files, not one continuous stream — some days may be gap-covered by one file but not another). Fresh-server data spans **Jul 14 – Jul 16, 2026** (~2 days, thin sample post-migration). There is a **gap between Jun 30 and Jul 14** with no logs examined (not searched — out of scope per the two named sources; may exist in journald rotation on old box but that box is being decommissioned per prior program notes).
- **`messages_2wk.tsv`** (588 user turns used in §2) is itself a curated 2-week extract (dated internally May 18–29 per file content, despite the "2wk" filename and a `du`/`ls` mtime of May 30) — it is a sample, not the full message volume for that window; total raw user-message count in the underlying system for that period is unknown from this file alone.
- No user identifiers, model/project names, or verbatim long text are included in this report; all examples above are ≤100 characters and stripped of any project-specific naming beyond what was already generic in the source (e.g. material codes were left in one count_element example as they are not identifying).
