🇷🇺 [Русская версия](README.ru.md)

# Documentation

## Architecture

- [**KIR Architecture**](ARCHITECTURE.md) — the compiler stage by stage: the registry as
  one source of truth, the forward pipeline (typecheck → ground → plan → emit → Roslyn
  gate → live run → witness), the reverse pipeline (extract → census → lift → fold →
  materialize → rebuild verification), the five conservation laws, versioning.

## Articles

- [**A Building Is a Program**](articles/2026-07-a-building-is-a-program.md) — the
  long-form technical case: what the IR expresses, why it runs in both directions, and
  the measured number behind each claim.
- [**Five Conservation Laws of Honesty for an AI Agent in CAD**](articles/2026-07-five-laws-of-honesty.md)
  — the five laws, the measured incident behind each, and how each one is mechanically
  enforced.
- [**A Day of Measured Revit API Traps**](articles/2026-07-revit-api-traps.md) — fourteen
  Revit API behaviours as symptom → wrong hypothesis → measurement → rule. Useful even if
  you never touch KIR.
- [**One Day Inside an AI-led Compiler Team**](articles/2026-07-one-day-chronicle.md) — a
  first-person account of one working day on this project.

The revit-api-traps and five-laws-of-honesty articles now live in their own repositories — see
[Constellation](../README.md#constellation) in the root README.

## Code

- [**examples/**](../examples/README.md) — two runnable SDK demonstrations (numpy tower,
  shapely floor plate) with their measured outputs.
