"""НЕПРЕРЫВНЫЙ ИНДИКАТОР КОМПИЛИРУЕМОСТИ — и полный список того, чего он НЕ видит.

ЗАЧЕМ. Инженер сидит в чате три часа, здание живёт в графе, и в Revit уходит
РОВНО ОДНА компиляция — в самом конце. Узнать на третьем часу, что здание не
компилируется, значит потерять три часа. Значит нужна оценка, которая
обновляется на каждой программе и стоит около нуля.

ЧТО ЭТО СТОИТ (замер 10.08.2026, прод-venv, `compiler.plan_program` на
корректных программах `create_wall`):

| опов в программе | время   |
|-----------------:|--------:|
|                1 | 0.13 мс |
|                5 | 0.44 мс |
|               10 | 0.79 мс |
|               20 | 1.48 мс |
|      300 (bulk)  | 21.2 мс |
| отказ по бюджету | 0.04 мс |

То есть авторская программа проверяется за ПОЛТОРЫ МИЛЛИСЕКУНДЫ, и это
целиком питон: ни одного сетевого вызова, ни одного обращения к Roslyn, ни
одного обращения к Revit. Индикатор можно пересчитывать на каждой публикации
в журнал и не заметить его в бюджете хода.

────────────────────────────────────────────────────────────────────────────
ЧТО ИНДИКАТОР ПРОВЕРЯЕТ (замерено, не предположено)
────────────────────────────────────────────────────────────────────────────
Всё, что делает `compiler.plan_program` до эмиссии C#:

* ТИПЫ параметров по реестру (`spec.OPS`) — `KIR-T001` и родня. Замерено:
  `{"by":"name","name":"L1"}` вместо `{"by":"name","value":"L1"}` ловится
  здесь, а не в Revit;
* БЮДЖЕТЫ. `MAX_OPS_PER_PROGRAM = 20` для АВТОРСКОЙ программы и
  `MAX_BULK_OPS = 300` для чанка пересборки — `KIR-L001`. Замерено: 21 оп
  отказывается за 0.04 мс, 301 в режиме bulk — тоже;
* ССЫЛОЧНЫЙ DAG: `ref` обязан указывать на БОЛЕЕ РАННИЙ оп той же программы
  (`KIR-L003`). Это то самое правило, из-за которого дверь без стены-носителя
  не «неполная», а невалидная;
* SOLO-ОПЫ: операция, которой нужна своя транзакция (`KIR-L002`,
  `compiler.PLAN_SOLO_OP` — лестница);
* КОНВЕРТ программы: `ir_version` (`KIR-P004`), форма `ops`;
* ПОТОЛОК ПОСЛЕ МАКРОСОВ: `MAX_VALIDATED_OPS = 320`.

Плюс — ТОЛЬКО когда снимок типов документа лежит в журнале сессии
(`SessionJournal.sections`, кладёт `plan_stream.remember_sections`) —
ГРУНДИНГ СЕЛЕКТОРОВ: сводится ли `{"by":"name","value":"…"}` к реальному
уровню/типу этого документа. Без снимка грундинг НЕ ПРОВЕРЯЕТСЯ, и это
сказано полем `grounding: "not_checked"`, а не молчанием.

────────────────────────────────────────────────────────────────────────────
ЧЕГО ИНДИКАТОР НЕ ПРОВЕРЯЕТ — И ЭТО ЧАСТЬ ЕГО ОТВЕТА, А НЕ СНОСКА
────────────────────────────────────────────────────────────────────────────
Индикатор, молчащий о своей слепоте, хуже отсутствующего: зелёная лампа,
которая не знает, что она не смотрела, — ровно тот дефект «свидетель
подписывает непрочитанную ось», из-за которого 10.08 переделали шесть
проверок. Поэтому список едет в КАЖДОМ ответе, в поле `blind`, и вьюер
печатает его рядом с лампой.

1. **C# НЕ КОМПИЛИРУЕТСЯ.** Настоящий гейт идёт через живой сервис Roslyn
   против настоящих `RevitAPI.dll` шести версий. Здесь эмиссии нет вовсе.
   Класс отказов, который проходит мимо: `CS0117`, `CS0012`, `CS0136`,
   `CS0039` — и именно так умерла стадия тегов (`CS0012: ISet<>`).
2. **Шестиверсионная поверхность API не спрашивается.** Арбитр —
   `data/api_surface/api_signatures_*.json`, снятый рефлексией с DLL.
   Программа, законная по типам, может звать член, которого в целевой версии
   нет.
3. **Замыкание ссылок сборок не проверяется** (`bridge_reference_closure`):
   эмитированный C# со ссылкой на сборку, которой нет в развёрнутом плагине,
   отсюда невидим. Этот страж с 09.08 по 10.08 не был привязан ни к чему, и
   никто не заметил.
4. **Приёмка и свидетель не запускаются.** «Скомпилируется» ≠ «построится» ≠
   «построилось то, что просили». Ось, по которой никто не обещал проверять,
   считает `serving._unwitnessed_axes`, и здесь её нет.
5. **Сертификат перевода не спрашивается** (`KUKAI_IR_TRANSLATION_CERT` в
   проде не задан вовсе — замер прод-флагов 10.08).
6. **Клеши не ищутся.** 67.7 с на самом большом здании; полный поиск на
   каждое изменение невозможен по построению.
7. **`design_check` не запускается** — это суждение о ЗДАНИИ, а не о тексте
   программы.
8. **Живой документ не спрашивается.** Уровень или тип могли исчезнуть в
   Revit между публикацией и кнопкой; офлайн этого не видно.
9. **Порядок между программами не проверяется.** Каждая программа судится
   ОТДЕЛЬНО, потому что транзакция — программа. Пачка, где вторая программа
   опирается на результат первой, здесь законна, и это правильно, но
   «пачка целиком применима к текущему документу» — не то, что здесь
   сказано.
10. **Бюджет не переносится между программами.** Двадцать программ по
    двадцать опов — законны все двадцать; вопрос «а не многовато ли на один
    ход» этот индикатор не задаёт.

────────────────────────────────────────────────────────────────────────────
ТРИСТЕЙТ, А НЕ ЛАМПОЧКА
────────────────────────────────────────────────────────────────────────────
Тем же законом, что `hulls_coincide`, `Judged.proven` и
`serving._unwitnessed_axes`: `ok` — все программы прошли названные проверки;
`refused` — есть отказ, и он назван кодом и текстом; `unknown` — судить было
нечем (реестр не поднялся, журнала нет). **`unknown` — это НЕ «всё хорошо»**,
и вьюер обязан красить его серым, а не зелёным.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

__all__ = ("COMPILABILITY_SCHEMA", "BLIND", "Verdict", "check_programs",
           "check_session")

COMPILABILITY_SCHEMA = "kir-compilability/1"

#: Список слепоты как ДАННЫЕ, а не как проза: он едет в каждом ответе и
#: печатается вьюером. Порядок — от самого дорогого промаха к самому дешёвому.
BLIND: tuple[str, ...] = (
    "C# не компилируется: живой Roslyn против настоящих RevitAPI.dll шести "
    "версий здесь не вызывается (CS0117/CS0012/CS0136/CS0039 проходят мимо)",
    "поверхность API по версиям не спрашивается (api_signatures_*.json)",
    "замыкание ссылок сборок не проверяется (bridge_reference_closure)",
    "приёмка и свидетель не запускаются: «скомпилируется» ≠ «построится»",
    "сертификат перевода не спрашивается",
    "клеши не ищутся (67.7 с на самом большом здании — непрерывно невозможно)",
    "design_check не запускается: это суждение о здании, а не о тексте",
    "живой документ не спрашивается: уровень или тип могли исчезнуть в Revit",
    "программы судятся ПООДИНОЧКЕ — применимость всей пачки к документу не "
    "проверяется",
    "бюджет опов не суммируется между программами",
)


@dataclass
class Verdict:
    """Ответ индикатора. `state` — тристейт, `blind` — всегда полон."""

    state: str = "unknown"          # ok | refused | unknown
    programs: int = 0
    ops: int = 0
    checked: int = 0
    refusals: list[dict[str, Any]] = field(default_factory=list)
    grounding: str = "not_checked"  # ok | refused | not_checked
    grounding_note: str = ""
    reason: str = ""
    elapsed_ms: float = 0.0
    budgets: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": COMPILABILITY_SCHEMA,
            "state": self.state,
            "state_ru": {"ok": "компилируется (в пределах названных проверок)",
                         "refused": "НЕ компилируется: есть названный отказ",
                         "unknown": "судить нечем — это НЕ «всё хорошо»"}[self.state],
            "programs": self.programs,
            "ops": self.ops,
            "checked_programs": self.checked,
            "refusals": self.refusals[:20],
            "refusals_total": len(self.refusals),
            "grounding": self.grounding,
            "grounding_note": self.grounding_note,
            "reason": self.reason,
            "elapsed_ms": round(self.elapsed_ms, 3),
            "budgets": self.budgets,
            "blind": list(BLIND),
        }


def _budgets() -> dict[str, int]:
    from kukai.ir.compiler import (MAX_BULK_OPS, MAX_OPS_PER_PROGRAM,
                                   MAX_VALIDATED_OPS)
    return {"authored": MAX_OPS_PER_PROGRAM, "internal_bulk": MAX_BULK_OPS,
            "post_macro": MAX_VALIDATED_OPS}


def _as_program(item: Any) -> dict[str, Any] | None:
    """Программа приходит тремя видами: конверт, список опов, `ProgramRecord`.

    Конверт достраивается ЗДЕСЬ и только `ir_version`: журнал хранит уже
    раскрытые операции (`PlannedProgram.to_ops()`), а версию IR он не хранит
    вовсе — она принадлежит конверту, а не программе. Достраивать что-то
    ещё значило бы судить не то, что построится.
    """
    ops: Any
    if hasattr(item, "ops"):
        ops = list(item.ops)
    elif isinstance(item, Mapping):
        ops = list(item.get("ops") or ())
        if not ops:
            return None
        env = {k: v for k, v in item.items() if k != "ops"}
        env["ops"] = ops
        env.setdefault("ir_version", "1.0")
        return env
    elif isinstance(item, Sequence) and not isinstance(item, (str, bytes)):
        ops = list(item)
    else:
        return None
    if not ops:
        return None
    return {"ir_version": "1.0", "ops": [dict(o) for o in ops
                                         if isinstance(o, Mapping)]}


def check_programs(programs: Sequence[Any], *, bulk: bool = False,
                   snapshot: Any = None) -> Verdict:
    """Судить пачку. Никогда не поднимает исключений — индикатор не имеет
    права стоить хода, ради которого он существует."""
    started = time.perf_counter()
    verdict = Verdict()
    try:
        from kukai.ir import compiler
        from kukai.ir.diag import KirRefusal
        verdict.budgets = _budgets()
    except Exception as exc:  # noqa: BLE001 — реестр чужой
        verdict.state = "unknown"
        verdict.reason = f"компилятор не поднялся: {type(exc).__name__}"
        verdict.elapsed_ms = (time.perf_counter() - started) * 1000.0
        return verdict

    envelopes = [env for env in (_as_program(p) for p in programs)
                 if env is not None]
    verdict.programs = len(envelopes)
    verdict.ops = sum(len(env["ops"]) for env in envelopes)
    if not envelopes:
        verdict.state = "unknown"
        verdict.reason = "в журнале нет ни одной программы"
        verdict.elapsed_ms = (time.perf_counter() - started) * 1000.0
        return verdict

    planned: list[Any] = []
    for index, env in enumerate(envelopes):
        try:
            planned.append(compiler.plan_program(env, bulk=bulk))
            verdict.checked += 1
        except KirRefusal as refusal:
            verdict.refusals.append({
                "program": index,
                "ops": len(env["ops"]),
                # Диагностика КОМПИЛЯТОРА, слово в слово. Пересказывать её
                # своими словами значило бы завести второй источник правды
                # о том, почему программа не компилируется.
                "text": str(refusal)[:400],
                "codes": sorted({d.code for d in getattr(refusal, "diagnostics", ())
                                 if getattr(d, "code", None)}),
            })
        except Exception as exc:  # noqa: BLE001 — неожиданный отказ тоже отказ
            verdict.refusals.append({
                "program": index, "ops": len(env["ops"]),
                "text": f"{type(exc).__name__}: {str(exc)[:300]}",
                "codes": [], "unexpected": True})

    verdict.state = "refused" if verdict.refusals else "ok"

    # ── ГРУНДИНГ, и только если есть чем. Снимок типов документа кладёт в
    #    журнал `plan_stream.remember_sections`; без него селектор `by=name`
    #    не с чем сверять, и делать вид, что сверили, нельзя.
    if snapshot:
        try:
            from kukai.ir import ground as _ground
            bad = 0
            for plan in planned:
                ops = plan.to_ops() if hasattr(plan, "to_ops") else plan
                try:
                    _ground.ground(list(ops), snapshot)
                except Exception:  # noqa: BLE001
                    bad += 1
            verdict.grounding = "refused" if bad else "ok"
            verdict.grounding_note = (
                f"{bad} из {len(planned)} программ не заземлились на снимок "
                f"типов документа" if bad else
                f"{len(planned)} программ заземлились на снимок типов документа")
        except Exception as exc:  # noqa: BLE001
            verdict.grounding = "not_checked"
            verdict.grounding_note = (
                f"грундинг не запустился: {type(exc).__name__} — селекторы НЕ "
                "проверены")
    else:
        verdict.grounding_note = (
            "снимка типов документа в журнале нет: сводятся ли селекторы "
            "by=name к реальным уровням и типам, НЕ ПРОВЕРЕНО")

    verdict.elapsed_ms = (time.perf_counter() - started) * 1000.0
    return verdict


def check_session(device_id: str | None, doc_key: str = "") -> dict[str, Any]:
    """Индикатор для ЖИВОЙ сессии. Читает `kukai.live.journal` и ничего больше.

    Своего хранилища программ здесь нет намеренно: журнал сессии уже есть
    исходный код здания, и второй его экземпляр разъехался бы с первым молча.
    """
    try:
        from kukai.live import journal as _journal
    except Exception as exc:  # noqa: BLE001
        return Verdict(state="unknown",
                       reason=f"журнал не поднялся: {type(exc).__name__}"
                       ).to_dict()
    session = _journal.get(_journal.key_for(device_id, doc_key))
    if session is None:
        return Verdict(state="unknown",
                       reason="сессии с таким ключом в журнале нет").to_dict()
    verdict = check_programs(list(session.records),
                             snapshot=getattr(session, "sections", None))
    out = verdict.to_dict()
    out["session"] = {"programs": len(session.records),
                      "next_seq": session.next_seq,
                      "evicted": session.programs_evicted}
    # ВЫТЕСНЕНИЕ ОБЯЗАНО БЫТЬ НАЗВАНО. Журнал ограничен по числу программ;
    # индикатор, посудивший 200 программ из 500 и сказавший «ok», соврал бы
    # ровно тем же умолчанием, против которого написана перепись превью.
    if session.programs_evicted:
        out["reason"] = (
            f"судимы только программы, оставшиеся в журнале: "
            f"{session.programs_evicted} вытеснено и НЕ ПРОВЕРЕНО")
    return out
