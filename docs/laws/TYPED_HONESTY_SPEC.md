# TYPED_HONESTY_SPEC — Verified<T> непостроимый без доказательства (волна 7)

Волна: `wave/merkle-dag` · база `prod-live` (`1b2ce5b7`) · модуль
**`kukai/ir/decompile/verified.py`** (decompile-сторона, рядом с honesty).
Статус: дизайн → код → property-тесты → suite → NOTES.

---

## 0. Задача одной фразой

Вердикты честности/fidelity как ТИП `Verified[T]`, который **нельзя
сконструировать без доказательства** → «verified» неподделываемо **by
construction**. Не «поле state=VERIFIED, которое любой может выставить» (текущий
`EquivalenceClaim` — forgeable value), а тип, чей единственный конструктор
требует объект доказательства (`Proof`), а `Proof` мятятся ТОЛЬКО настоящими
верификаторами (оффлайн-доказуемые проверки волн 1/5/6/9/10 + translation-cert).

## 1. Что уже построено — НЕ с нуля

- **`honesty.py`**: `FidelityVerdict`, `EquivalenceClaim(scope, state, detail)`,
  `EquivalenceState.{NOT_VERIFIED,VERIFIED,FAILED}` — типизированные вердикты, НО
  `state` — обычное поле (можно выставить VERIFIED без проверки → подделываемо).
  Волна 7 НАДСТРАИВАЕТ: оборачивает вердикт в `Verified[T]`, который требует Proof.
- **Оффлайн-доказательства всех волн** — уже СУЩЕСТВУЮТ как функции, кидающие при
  провале: `assert_preservation`/P7 (волна 1), `assert_round_trip` (волна 5),
  `assert_transition` (волна 6), `verify` (журнал волны 9), merge T-MERGE
  (волна 10), `assert_refined`/translation-cert (волна 2). Каждая — потенциальный
  «монетный двор» Proof: если она НЕ кинула, доказательство состоялось.
- Дисциплина: вердикт = данные, а не мнение (константа проекта «truth=witnesses,
  не opining judge»). `Verified[T]` — типовое воплощение этого: witness обязателен.

## 2. Механика неподделываемости (Python-аналог witness/phantom-типа)

Python не даёт статически запретить конструктор. Запрещаем В РАНТАЙМЕ через
**sealed-конструктор + capability-токен**:

- `_ProofToken` — приватный маркер; его нельзя создать снаружи модуля (конструктор
  проверяет вызывающего через приватный sentinel, недоступный извне).
- `Proof` — несёт `(kind, subject_hash, evidence)` + `_ProofToken`. Конструктор
  `Proof` требует токен ⇒ создать `Proof` может ТОЛЬКО код этого модуля.
- **Верификаторы** (`prove_*`) — единственные, кто мятит `Proof`: они ЗАПУСКАЮТ
  реальную оффлайн-проверку (assert_round_trip/assert_transition/…); если проверка
  НЕ кинула — мятят `Proof`, иначе пробрасывают исключение (нет Proof без проверки).
- `Verified[T]` — обёртка `(value: T, proof: Proof)`; конструктор ТРЕБУЕТ `Proof`
  с совпадающим `subject_hash` (иначе `ForgeryError`). ⇒ `Verified` существует
  ⟺ прошла реальная проверка. Подделка (сконструировать `Verified` с чужим/
  фейковым proof) → типизированное исключение.

Инвариант **UNFORGEABLE**: не существует пути создать `Verified[T]`, минуя
верификатор. Тестируется адверсариально (попытки подделки → исключение).

## 3. Структуры

```python
class HonestyTypeError(ValueError)           # база
class ForgeryError(HonestyTypeError)         # попытка подделать Verified/Proof
class ProofMismatchError(HonestyTypeError)   # proof не про этот subject

@dataclass(frozen=True) Proof:               # неподделываемое доказательство
    kind: str                                # "round_trip"|"transition"|"merge"|
                                             #  "preservation"|"refinement"|"journal"
    subject_hash: str                        # контент-адрес доказанного (merkle/canon)
    evidence: tuple[str,...]                  # что именно проверено (аудит)
    # конструктор требует _ProofToken (sealed)

@dataclass(frozen=True) Verified(Generic[T]):
    value: T
    proof: Proof
    # конструктор требует Proof с proof.subject_hash == subject_of(value)
    def unwrap() -> T                         # достать значение (proof остаётся)
    @property proven_by -> str                # proof.kind

# верификаторы — ЕДИНСТВЕННЫЙ источник Proof:
prove_round_trip(lib, tree) -> Proof         # запускает assert_round_trip (волна 5)
prove_transition(program, a, b) -> Proof     # assert_transition (волна 6)
prove_preservation(tree, nodes) -> Proof     # assert_preservation (волна 1/fold)
prove_merge_clean(result) -> Proof           # merge clean (волна 10)
prove_journal_integrity(journal) -> Proof    # verify (волна 9)
prove_refinement(op_cert) -> Proof           # translation-cert proven (волна 2)

verify_equivalence(claim, proof) -> Verified[EquivalenceClaim]
    # поднимает EquivalenceClaim до Verified ТОЛЬКО с валидным Proof того же subject;
    # state форсится VERIFIED внутри (нельзя Verified с state=FAILED — противоречие).
```

## 4. Развилки/выбор с обоснованием

**Р1. Runtime sealed-конструктор вместо статического типа.** Python не enforce'ит
приватность конструктора статически. Используем capability-sentinel: `_ProofToken`
берёт приватный объект-ключ, недоступный из-за пределов модуля; любой внешний
`Proof(...)` без ключа → ForgeryError. Это САМАЯ сильная гарантия, доступная в
Python — эквивалент «конструктор private, доступен только фабрике». Тестируется
адверсариально.

**Р2. Proof привязан к subject_hash (контент-адрес).** Доказательство round-trip
здания X не годится для здания Y: `Verified` требует `proof.subject_hash ==
subject_of(value)`. ⇒ нельзя переклеить старое доказательство на новое значение
(replay-атака). subject_hash = merkle_hash дерева / canon состояния / hash claim'а —
уже построенные контент-адреса (волна 1). Универсально, детерминированно.

**Р3. Верификатор ЗАПУСКАЕТ проверку, не верит на слово.** `prove_round_trip`
внутри ВЫЗЫВАЕТ `assert_round_trip` — если та кинула, Proof НЕ мятится (исключение
пробрасывается). Нет пути «сказать что проверил» — только «проверить». Это и есть
by-construction: Proof — свидетельство ЗАПУСКА, не декларация.

**Р4. Verified не может нести FAILED.** `Verified[EquivalenceClaim]` с
state=FAILED — противоречие (verified ⟹ не failed). Конструктор форсит
VERIFIED и отвергает FAILED-вход (ForgeryError). Честно: тип означает ровно
«доказано истинным».

**Р5. Инертно/аддитивно (Р-3).** Новый модуль; honesty/merkle/… не тронуты; frozen
L0 не при делах; `verified_enabled()` default OFF; проводка (заменить forgeable
`EquivalenceClaim.state` на `Verified` в passport) — отдельный гейт (МОЖЕТ усилить
существующий контракт, но осторожно — отдельное решение). Меняет КАК гарантируется
честность (тип vs поле), не ЧТО.

**Р6. Детерминизм.** Proof.subject_hash/evidence детерминированы (из контент-хешей);
ни времени, ни random. Verified round-trip'ится (to_dict хранит proof — но
from_dict ПЕРЕПРОВЕРЯЕТ, а не доверяет сериализованному «verified»: загруженный
Verified без повторной проверки — НЕ Verified, а сырой claim; см. Р7).

**Р7. Сериализация НЕ переносит доверие.** `Verified.to_dict()` пишет value+proof
для аудита, но `Verified.from_dict()` ТРЕБУЕТ повторного `prove_*` (или отдаёт
сырой value без Verified-обёртки). Иначе сериализованный «verified:true» стал бы
подделываемым (как исходная проблема!). Загрузка = недоверенная граница →
перепроверка. Fail-closed.

## 5. Property-тесты (test_verified.py, seeded/фикстурные)

| # | Свойство | Что доказывает |
|---|---|---|
| V1 | **непостроимость**: прямой `Verified(value, fake_proof)` / `Proof(...)` без токена → ForgeryError | нельзя подделать |
| V2 | **честный путь**: `prove_round_trip(корректная lib, tree)` → Proof; `verify_equivalence(claim, proof)` → Verified; unwrap==claim | верификатор работает |
| V3 | **проверка реально запускается**: `prove_round_trip(СЛОМАННАЯ lib, tree)` → пробрасывает ComponentRoundTripError, Proof НЕ выдан | нет Proof без проверки |
| V4 | **subject-привязка**: Proof здания X + claim здания Y → ProofMismatchError | нельзя переклеить (Р2) |
| V5 | все верификаторы: prove_transition/preservation/merge/journal/refinement на корректном → Proof; на сломанном → пробрасывают, Proof нет | каждый мост честен |
| V6 | Verified не несёт FAILED: verify_equivalence с FAILED-claim → ForgeryError | verified⟹не failed (Р4) |
| V7 | сериализация не переносит доверие: to_dict→from_dict БЕЗ перепроверки не даёт Verified (даёт raw / требует prove) | Р7 |
| V8 | детерминизм: тот же subject → тот же Proof.subject_hash; кросс-процесс идентичен | воспроизводимость |
| V9 | `verified_enabled()` default OFF | инертность |

V1/V3/V4 — сердце: подделка невозможна, проверка реально гоняется, subject привязан.

## 6. Дисциплина + зависимость
Universal (subject_hash — контент-адрес); fail-closed (подделка/mismatch/сломанная
проверка кидают); аддитивно+opt-in+инертно (flag OFF, honesty не тронут); детерминизм
(хеши, без random/time); property-тесты обязательны (V1–V9, включая адверсариальные
попытки подделки).
Зависимости: волны 1/5/6/9/10/2 как ИСТОЧНИКИ проверок (импортируются верификаторами),
но каждый мост опционален (импорт ленивый). Волна 7 — «шляпа» над всеми
доказательствами; не ломается без любого моста (просто нет того prove_*).
