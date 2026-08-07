# TRANSLATION_VALIDATION_SPEC — само-доказывающий эмиттер (волна 2)

Волна: `wave/merkle-dag` (внутри, лид разрулит при мерже) · база обновлённый
`prod-live` (Merkle-волна `e8a63566`) · модуль
`kukai/ir/decompile/... нет` → **`kukai/ir/translation_cert.py`** (авторинг-сторона,
рядом с authoring.py/compiler.py, не в decompile/).
Статус: дизайн (этот файл) → код → property-тесты → suite → NOTES.

---

## 0. Задача одной фразой

Эмиттер (`authoring.py`) вместе с C# должен выдавать **машинно-проверяемый
сертификат**, что эмитированный код **УТОЧНЯЕТ** (refines) семантику каждого
IR-опа: корректность **by construction**, а не «доверяй голдену». Сертификат
проверяется **статически, без запуска Revit** (как emitter scope contract).

## 1. Что такое refinement здесь (и что НЕ переизобретаем)

Translation validation в общем смысле: для каждого прохода компилятора
предъявить свидетеля, что выход **уточняет** вход — сохраняет наблюдаемую
семантику. Тяжёлый вариант (Necula/TVOC) — SMT-эквивалентность source↔target.
Нам это **не нужно и невозможно**: цель компилятора — не «эквивалентный C#», а
«C#, который построит в Revit элемент, удовлетворяющий постусловиям опа».
Наблюдаемая семантика опа — это его **постусловия** (`OpSpec.post`), а Revit —
внешний интерпретатор.

**Ключевое наблюдение (уже построено, не с нуля):** эмиттеры УЖЕ несут обе
половины refinement-свидетельства, просто нигде не собранные в сертификат:

1. **Реализующий API-вызов** в блоке `create` — `Wall.Create(...)`,
   `Pipe.Create(...)`, `doc.Create.NewFamilyInstance(...)`, `Floor.Create(...)`
   и т.д. — плюс `__Refuse` на null-возврат (материализация или типизированный
   отказ, третьего нет).
2. **Рантайм-постусловие** в блоке `post`: на каждый инвариант —
   `__post.Add("<oid>: <что нарушено>")`, и `emit_program` заворачивает это в
   `if (__post.Count > 0) { RollBack | report }`. То есть эмиттер УЖЕ вставляет
   исполняемого свидетеля каждого постусловия — но срабатывает он лишь когда
   Revit исполнит код.

Сертификат — это **статическое отображение**

```
op  →  { реализующий API-вызов, для каждого клауза post: рантайм-свидетель }
```

доказуемое разбором эмиссии БЕЗ Revit. Он превращает «рантайм-свидетель
существует» в **проверяемую до отправки гарантию**, что для КАЖДОГО обещанного
постусловия свидетель эмитирован (не забыт), и что материализующий вызов —
тот самый API, что реализует op (не заглушка).

Это ровно двухчастная структура refinement: **safety** (материализация
правильным API или типизированный отказ — не тихий неверный результат) +
**liveness покрытия** (каждое обещанное наблюдаемое проверяется).

Опираемся на каркас `test_emitter_scope_contract.py`: там уже есть статический
разбор эмиссии на все 26 эмиттеров через `_EMITTERS[op](op, ver, stamp) →
(d, c, p, r)` и токенайзер C# со стрипом строк/комментов (`_STR/_CMT/_code`).
Сертификатор берёт тот же разбор и те же VERSIONS × PROGRAMS фикстуры.

## 2. Структуры

```python
class CertificateError(ValueError)          # база, fail-closed
class UnprovenRefinementError(CertificateError)   # клауз без свидетеля / нет create-вызова
class CertificateSchemaError(CertificateError)    # реестр обещает то, чего мы не умеем доказывать

@dataclass(frozen=True) Obligation:         # одно доказательное обязательство
    clause: str                             # человекочитаемый клауз из OpSpec.post
    kind: str                               # "materialize" | "geometry" | "topology"
                                            #  | "parameter" | "semantic" | "identity"
    param: str | None                       # опц. параметр, чьё присутствие включает клауз
    witness_markers: tuple[str, ...]        # C#-подстроки-свидетели (ЛЮБОЙ достаточен)
    conditional: bool                       # True → свидетель обязателен ТОЛЬКО когда param в опе

@dataclass(frozen=True) OpRefinementSpec:   # обязательства одного опа
    op: str
    materializer: tuple[str, ...]           # C#-маркеры реализующего API-вызова (ЛЮБОЙ)
    refuse_on_null: bool                     # требуется __Refuse на неуспехе материализации
    obligations: tuple[Obligation, ...]

@dataclass(frozen=True) ClauseVerdict:
    clause: str; kind: str; discharged: bool; required: bool
    matched_marker: str | None; reason: str

@dataclass(frozen=True) OpCertificate:      # результат для одного (op, version, fixture)
    op: str; version: str; program: str
    materialized: bool                       # create содержит materializer
    refusal_guarded: bool
    clauses: tuple[ClauseVerdict, ...]
    proven: bool                             # materialized ∧ refusal ∧ все required разряжены

@dataclass(frozen=True) ProgramCertificate: # весь эмитированный program
    version: str; program: str
    ops: tuple[OpCertificate, ...]
    proven: bool
```

`REFINEMENT: dict[str, OpRefinementSpec]` — таблица обязательств, ПАРАЛЛЕЛЬНАЯ
`spec.OPS`, живёт в модуле сертификатора. Она — **машинная форма** прозаического
`OpSpec.post`: каждый `;`-клауз поста получает `Obligation` со свидетелями.

## 3. API

```python
certify_op(op: dict, version: str, *, stamp="kir:cert") -> OpCertificate
    # эмитит через _EMITTERS[op["op"]], разбирает (d,c,p,r), сверяет с REFINEMENT

certify_program(grounded_ops, version, *, intent="") -> ProgramCertificate
    # per-op сертификаты; НЕ переэмитит через emit_program (сертификат — per-op,
    # оболочка program одинаковая), просто агрегирует

assert_refined(op_or_program_cert) -> None
    # fail-closed: не proven → UnprovenRefinementError с полным списком дыр

certificate_enabled() -> bool
    # env KUKAI_IR_TRANSLATION_CERT ∈ {1,true,yes,on}, default OFF

# Полнота реестра — это ОТДЕЛЬНАЯ проверка, не про конкретную эмиссию:
audit_registry_coverage() -> tuple[str, ...]
    # каждый write-op из spec.OPS (family∈WRITE_FAMILIES) имеет OpRefinementSpec;
    # каждый ';'-клауз каждого OpSpec.post имеет ≥1 Obligation (по нормализованному
    # сопоставлению) — иначе реестр обещает непроверяемое → CertificateSchemaError.
    # Возвращает список нестыковок (пусто = полно). Тест делает это hard-fail.
```

## 4. Как разряжается обязательство (статически, детерминированно)

Разбор `(d, c, p, r)` тем же токенайзером, что scope contract (`_code` стрипает
строковые литералы и комменты — свидетель `__post.Add("...: mismatch")` ищется
по **C#-коду** структуры проверки, НЕ по тексту сообщения внутри строки; см. §5
«почему не по тексту»).

- **materialize**: `any(marker in code(c))` для `spec.materializer`; при
  `refuse_on_null` — в `code(c)` есть `__Refuse` в той же зоне (грубо: `create`
  содержит и materializer, и `__Refuse`). Разряжает safety-половину.
- **обязательство с `conditional=True`**: если `param` присутствует в опе —
  свидетель ОБЯЗАН быть в `code(p)` (или `code(c)` для create-side состояний
  вроде flip); если отсутствует — свидетеля быть НЕ должно (P: отсутствие
  параметра не порождает ложного свидетеля).
- **безусловное обязательство**: свидетель обязан быть в `code(p)` всегда.
- Свидетель = `any(m in code(block) for m in witness_markers)`. Маркеры —
  структурные C#-фрагменты (`.Location as LocationCurve`,
  `WALL_BASE_CONSTRAINT`, `.Mirrored != `, `RBS_PIPE_DIAMETER_PARAM`,
  `__post.Add`), НЕ русский текст сообщения.

`proven(op) = materialized ∧ (¬refuse_on_null ∨ refusal_guarded) ∧
              ∀ required-клауз: discharged`.

## 5. Развилки и выбор с обоснованием

**Р1. SMT-эквивалентность source↔target? — НЕТ.** Наблюдаемая семантика опа
живёт в Revit, а не в C#-AST; «эквивалентный C#» — не та цель. Доказываем
уточнение **постусловий**, единственного наблюдаемого контракта. Это честнее:
сертификат провалится ровно тогда, когда эмиттер забыл проверить обещанное —
реальный класс багов (docstring `_emit_tag`: «свидетель, не поднятый в decl»;
scope-contract ловил `__hl_<s>`).

**Р2. Свидетель по тексту сообщения или по структуре кода? — по СТРУКТУРЕ.**
Токенайзер scope contract СТРИПАЕТ строковые литералы (`_STR.sub('""')`).
Значит искать `"height mismatch"` внутри строки нельзя — и не нужно: ищем
маркер С#-**проверки** (`WALL_USER_HEIGHT_PARAM` + `__post.Add`), которая живёт
в коде. Это строже: переименование сообщения не обманет сертификат, а удаление
самой проверки — обвалит. Universal: ноль зависимости от русских текстов
(и от `_MOP_RE`-класса багов — их здесь просто нет).

**Р3. Таблица REFINEMENT дублирует OpSpec.post? — она его МАШИННАЯ ФОРМА, и
это проверяется.** `audit_registry_coverage()` требует биекции клауз↔Obligation
по нормализованному сопоставлению: новый клауз в `post` без Obligation =
hard-fail (реестр обещает непроверяемое); Obligation без клауза = висячий (тоже
fail). Так таблица не расходится с реестром молча — расхождение = красный тест.
Это тот же приём, что lift_cache `_lift_source_hash` (over-invalidate в
безопасную сторону) применительно к покрытию.

**Р4. Сертификат меняет эмиссию? — НЕТ, чистое НАБЛЮДЕНИЕ (Р-3).** Модуль
только читает `(d,c,p,r)`; `authoring.py` не тронут ни байтом. Инертно, opt-in
(`certificate_enabled()` default OFF) — проводка в compiler/serving отдельным
решением с гейтом лида. Frozen L0 не при делах (это авторинг-сторона).

**Р5. Что если эмиттер материализует, но забыл ОДНУ проверку?** Именно это
сертификат и ловит: `proven=False`, `ClauseVerdict.discharged=False` с точным
клаузом и причиной. `assert_refined` → `UnprovenRefinementError` со списком
дыр. Fail-closed: недоказанное = отказ, не тихий пропуск.

**Р6. `create_stairs` (sole-op, свой шаблон `emit_stairs_program`, НЕ в
`_EMITTERS`).** Сертификатор поддержит его отдельной веткой (эмит через
`emit_stairs_program`, тот же разбор постусловий — base/top level, runs, width),
чтобы покрытие было полным. Если разбор целой программы окажется хрупким —
задокументирую и оставлю на явный TODO, но постусловия там те же
`__post.Add(...)`, так что ветка прямая.

## 6. Property-тесты (test_translation_cert.py, seeded/фикстурные —
конвенция репо, hypothesis нет)

Переиспользуем `PROGRAMS`/`VERSIONS` из scope-contract (те же корнер-кейсы,
все опциональные ветки задеты).

| # | Свойство | Что доказывает |
|---|---|---|
| C1 | каждый write-op в каждой фикстуре × 6 версий → `proven=True` | эмиттер уточняет каждый op на всех форках |
| C2 | `audit_registry_coverage()` == () | биекция клауз↔Obligation: реестр не обещает непроверяемого, таблица не висит |
| C3 | покрытие: каждый write-op из `spec.OPS` имеет `OpRefinementSpec` (как `test_fixture_covers_every_write_emitter`) | ни один эмиттер не выпал из сертификации |
| C4 | conditional-свидетель: `create_pipe` с `diameter_mm` → witness присутствует; без него → witness ОТСУТСТВУЕТ; то же для `arc`/flips/`width_mm`/`holes`/`material` | присутствие параметра ⟺ его свидетель (нет ложных и нет забытых) |
| C5 | **мутационные (negative)**: из реального `(d,c,p,r)` вырезаю одну проверку (`__post.Add` height / level-check / materializer / `__Refuse`) → `certify_op` даёт `proven=False` с точным клаузом | сертификат ЛОВИТ забытую проверку (иначе он бесполезен) |
| C6 | детерминизм: тот же (op,ver) → тот же `OpCertificate` (dataclass-равенство); порядок клауз стабилен; кросс-процесс (PYTHONHASHSEED) идентичен | воспроизводимость |
| C7 | `certify_program` = агрегат per-op; `proven` ⟺ все опы proven | композиция |
| C8 | `assert_refined` на дырявом → `UnprovenRefinementError`; на целом → тишина; `certificate_enabled()` default OFF | fail-closed + инертность |
| C9 | `create_stairs` (sole-op) сертифицируется proven=True на 6 версиях | покрытие спец-шаблона |

C5 — сердце волны: без мутационного теста сертификат недоказуемо полезен
(мог бы всё штамповать proven). Мутации — синтетическая порча РЕАЛЬНОЙ эмиссии,
не макет.

## 7. Дисциплина

- **Universal**: работа на структурных C#-маркерах и на `spec.OPS`; ноль
  хардкода под здание/LOT31; ноль зависимости от русских сообщений.
- **Fail-closed**: недоказанный refinement / реестр-расхождение = типизированное
  исключение, не тихий proven.
- **Аддитивно + opt-in + инертно**: `authoring.py`/эмиттеры не тронуты; ничто
  не импортирует сертификатор в хот-пути; флаг `KUKAI_IR_TRANSLATION_CERT`
  default OFF; проводка — отдельный гейт.
- **Детерминизм**: ни времени, ни random; разбор и вердикты сортированы;
  dataclass-равенство стабильно кросс-процессно.
- **Property-тесты обязательны** (C1–C9), включая мутационные (C5).
