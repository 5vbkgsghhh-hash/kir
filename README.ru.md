🇬🇧 [English version](README.md)

<p align="center">
  <img src="assets/logo.png" width="96" alt="KIR logo"/>
</p>

<h1 align="center">KIR</h1>

<p align="center">
  <b>Здание — это программа.</b><br/>
  Типизированное, верифицируемое IR для Autodesk Revit — мозги на Python, проверенные руки.
</p>

<p align="center">
  <img alt="License Apache-2.0" src="https://img.shields.io/badge/license-Apache--2.0-blue">
  <img alt="Revit 2021-2026" src="https://img.shields.io/badge/Revit-2021%E2%80%932026-005386">
  <img alt="Compile gate 1056 checks" src="https://img.shields.io/badge/compile%20gate-1056%20checks%20PASS-brightgreen">
  <img alt="Live-proven 31 of 31 writing ops" src="https://img.shields.io/badge/live--proven-31%2F31%20writing%20ops-success">
  <img alt="Open source August 9 2026" src="https://img.shields.io/badge/open--source-Aug%209%2C%202026-orange">
</p>

<p align="center">
  <a href="#why">Зачем</a> ·
  <a href="#the-idea-in-one-picture">Идея одной картинкой</a> ·
  <a href="#show-me-code">Код</a> ·
  <a href="#measured-not-promised">Измеренные факты</a> ·
  <a href="#the-five-laws">Пять законов</a> ·
  <a href="docs/ARCHITECTURE.ru.md">Архитектура</a> ·
  <a href="examples/README.ru.md">Примеры</a> ·
  <a href="#constellation">Созвездие</a>
</p>

---


<p align="center">
  <img src="assets/tower-side-by-side.png" alt="Одна и та же башня дважды в Revit" width="720"/>
</p>

Одно и то же здание, удержанное двумя способами. Как проверенный C#, который KIR эмитирует для
одной версии Revit, 60-этажная башня из [`examples/tower_numpy.py`](examples/tower_numpy.py)
весит **3 616 130 символов — порядка 0.9 млн токенов, это не влезает ни в один контекст**. Как
типизированная KIR-программа, которую модель и правит, — **15 508 символов, порядка 4 тыс.
токенов: в 233 раза меньше**. Это разница между моделью, которая может перекроить планировку
или изогнуть фасад — и каждое изменение будет проверено, — и моделью, которая не способна даже
прочитать здание, которое её просят изменить. *(Размеры замерены 2026-07-28 запуском примера из
этого репо; рендер — визуальное сопровождение, не сам замер.)*

<a id="why"></a>
## Зачем

Языковые модели хорошо пишут код. Здания они пишут плохо, и причина здесь структурная, а не
вопрос масштаба обучения. Здание не помещается в контекстное окно — одна из моделей, на которых мы
сверяемся, держит **90 758 элементов**. Работа стейтфул: стена должна существовать раньше, чем в ней
можно разместить дверь, а это состояние живёт внутри приложения, а не в файле, который можно
сравнить diff'ом. Она реентерабельна: одна и та же инструкция, поданная дважды, не должна породить
две двери. И она версионирована на шесть ладов: один и тот же замысел компилируется по-разному для
Revit 2021 и Revit 2026.

Поэтому сегодняшняя практика — заставить модель писать Revit C# напрямую, и арифметика этой
практики у нас перед глазами. Из **85 374 боевых ошибок компиляции**, залогированных за семь недель,
два кода дают **48.4%** — `CS1061` (32.3%) и `CS0117` (16.1%) — и оба это один и тот же отказ:
*обращение к члену Revit API, которого не существует*. Ещё ~10% (`CS0104`/`CS0012`) — проблемы с
namespace и ссылками на сборки. Грубо говоря, **около 60% всех боевых ошибок компиляции тратятся на
борьбу с поверхностью API**, а не на описание здания.

**KIR — попытка его построить**: модель концентрируется на 3D,
геометрии и композиции, а единицы измерения, транзакции, версии API, хосты, свидетели и откаты
отдаются компилятору.

<a id="the-idea-in-one-picture"></a>
## Идея одной картинкой

```mermaid
flowchart TB
    subgraph FWD["FORWARD — intent becomes a building"]
        direction LR
        SDK["Python SDK<br/>numpy · shapely · the model"]
        PROG["Typed program<br/>KIR JSON, ops + refs"]
        REG["Registry<br/>one source of truth:<br/>schema · grammar · docs · emitters"]
        GRND["ground<br/>symbolic selectors to ElementIds"]
        PLAN["typecheck + plan<br/>mm only · DAG · txn partitions"]
        EMIT["emit<br/>per-version C#"]
        GATE["Roslyn gate<br/>2021–2026 · 1056 checks PASS"]
        RUN["live Revit<br/>one TransactionGroup"]
        SDK --> PROG --> REG --> GRND --> PLAN --> EMIT --> GATE --> RUN
    end

    RUN --> WIT["witness<br/>read the RESULT back, not the call"]
    WIT --> OUT{"exactly two<br/>typed outcomes"}
    OUT -->|ok| OKN["geometry_ok · semantic_ok · topology_ok"]
    OUT -->|refused| REFN["diagnostics + candidates + route<br/>KIR-G/T/L/E/C/X/W codes"]
    REFN -.->|"IR-level repair, max 3 rounds"| PROG

    subgraph REV["REVERSE — a building becomes a program"]
        direction LR
        DOC["live model"]
        L0["extract to L0<br/>48 categories · full-model census"]
        L1["lift to typed ops<br/>or a typed ATOM with a reason"]
        FOLD["fold to canon<br/>template-canon/4 · fidelity-canon/1"]
        MAT["materialize<br/>chunked programs, host-atomic"]
        DOC --> L0 --> L1 --> FOLD --> MAT
    end

    RUN -.-> DOC
    MAT -.->|"rebuild · edit · diff"| PROG
```

Важнее самих блоков — два свойства.

**Каждый вызов заканчивается ровно одним из двух типизированных исходов** — либо `ok` с
доказательством, полученным обратным чтением, либо машиночитаемый `refused` с кандидатами и
маршрутом к запасному пути. Единственное запрещённое состояние — молча неверный ответ; `ok:true`,
оборачивающий вложенную ошибку, — постоянный регрессионный кейс со своим собственным тестом.

**IR работает в обе стороны.** Всё, что лифтер не может выразить, становится *типизированным
атомом с кодом причины*, а не молча пропадает. Именно обратное направление превращает «мы умеем
строить» в «мы умеем редактировать то, что уже существует».

Пошаговый разбор обоих конвейеров — реестр как единый источник истины, режимы изоляции, перепись,
фолд, проверка пересборкой — живёт в [**docs/ARCHITECTURE.ru.md**](docs/ARCHITECTURE.ru.md).

<a id="show-me-code"></a>
## Покажи код

Вот настоящая программа — напечатана дословно из SDK:

```json
{
  "ir_version": "1.0",
  "intent": "one bay: wall + door + window",
  "ops": [
    {"op": "create_wall", "id": "wall1",
     "p0_mm": [0, 0], "p1_mm": [6000, 0],
     "level": {"by": "name", "value": "Level 1"}, "height_mm": 3300},
    {"op": "create_door", "id": "door1",
     "host": {"by": "ref", "value": "wall1"},
     "offset_mm": 1200, "sill_mm": -100,
     "symbol": {"by": "name", "value": "0915 x 2134mm"},
     "mirrored": false, "hand_flipped": false, "facing_flipped": false}
  ]
}
```

Обратите внимание, что именно *невыразимо*. У двери нет `xyz`: она — это `host` + `offset_mm`
вдоль хоста + `sill_mm`. «Окно, парящее в воздухе» — это не случай, который мы валидируем, это
предложение, которое язык не может сформулировать. Любая длина — в миллиметрах; футов в IR не
существует.

Поверхность на Python не написана, а сгенерирована: **35 билдеров рождаются из реестра в момент
импорта, по одному на оп реестра** (2026-07-28), так что сигнатура не может разойтись со спекой.
SDK не добавляет собственной семантики — он не может выразить ничего, чего нет в реестре, и не
может спрятать отказ.

```python
import numpy as np
from kukai.ir import sdk

p = sdk.program(intent="tower with a waist")
with p.stack(levels=20, h_mm=3600,
             transform=sdk.transform(scale_xy_top=[0.8, 0.8],
                                     twist_deg_total=24)) as floor:
    for a in np.linspace(0, 2 * np.pi, 12, endpoint=False):
        floor.add(sdk.create_column(xy=[20000 * np.cos(a), 20000 * np.sin(a)],
                                    level=sdk.BY_MACRO, symbol="К 300x300"))

p.stats()   # {'ops_written': 1, 'ops_expanded': 260, 'elements': 240}
out = p.compile(version="2023", snapshot=snap)
```

Пример из поставки идёт дальше. В `tower_numpy.py` numpy вычисляет синусоидальную талию и
закрутку, а KIR повторяет этаж — запуск от 2026-07-28:

```text
100 lines of Python -> 6 authored ops -> 840 after expansion -> 780 elements (3 KIR programs)
60 storeys, 30% waist, 120 deg total twist
piecewise vs. true sine: 217 mm along the radius
compilation: 6/6 versions ['2021','2022','2023','2024','2025','2026']
```

Смысл — в третьей строке. `stack.transform` интерполирует линейно; запрошенная кривая — синус.
Сказать «синус» и построить ломаную, **не назвав расхождение**, было бы молча неверным ответом,
поэтому пример печатает ошибку в миллиметрах.

Обе демонстрации — башня на numpy и вырезанная shapely криволинейная плита перекрытия — идут в
поставке в [**examples/**](examples/README.ru.md) вместе с измеренными результатами.

### Что происходит с одним опом

```mermaid
sequenceDiagram
    autonumber
    participant M as Model — the LLM
    participant K as KIR compiler
    participant R as Revit — live document

    M->>K: create_wall — p0, p1, level by name, height 3300 mm
    K->>K: parse · typecheck · mm to feet · plan the DAG
    K->>R: snapshot query — resolve selectors
    R-->>K: level id, wall type pool

    alt selector missing or ambiguous
        K-->>M: refused KIR-G102 + candidates + route
    else grounded
        K->>K: emit C# for THIS Revit version
        K->>R: TransactionGroup — Wall.Create, op_id stamped
        R-->>K: new element id
        K->>R: read the element BACK
        R-->>K: LocationCurve, height param, level id
        alt postconditions hold
            K-->>M: ok + witness — geometry_ok, semantic_ok, topology_ok
        else violated
            K->>R: RollBack
            K-->>M: refused KIR-X004 + which axis failed
        end
    end
```

Именно этот штамп делает повтор идемпотентным: id опа записывается в модель внутри той же
транзакции, так что повторный запуск программы пропускает уже проштампованное, а «возобновить с
опа K» — это просто «пропустить всё, что несёт штамп».

<a id="measured-not-promised"></a>
## Измерено, а не обещано

Всё ниже получено инструментом на указанную дату, а не по памяти.

| Факт | Значение | Дата / источник |
|---|---|---|
| Пишущих опов в реестре | **31** (+4 запросных) | 2026-07-28, `spec.OPS` |
| Пишущих опов минимум с одним успешным живым запуском + свидетелем | **31 из 31** | объединение `data/telemetry/kir_witness.jsonl` (строки с `ok` + `family=write` + `duration_ms>0`; включает прогоны 2026-07-28 P8/P10v2/P11 и ночной P9) и артефакта живой матрицы от 2026-07-27 (добавляет `create_floor`, `create_room`) |
| Последний закрытый оп | `move_elements` — ночь 2026-07-28, Revit 2026: *связанная* пара кабельных лотков сдвинута на +500 мм по Z, свидетель 3/3, связь подтверждена независимым чтением | там же |
| Компиляционный гейт на шести версиях | **1 056 компиляций Roslyn, PASS** (101 атомарная + 69 per-op × 6 версий) | 2026-07-28 |
| Тестовый набор | **1 692 пройдено / 2 767 подтестов** | 2026-07-28, полный набор в чистом окне |
| Категорий, которые читает обратное направление | **48** | 2026-07-28 |
| Покрытие — модель R2023, 1 383 элемента | **93.28%** (сырое 77.30%) | 2026-07-27 |
| Покрытие — модель R2026, 90 758 элементов | **92.83%** (сырое 56.94%) | 2026-07-27 |
| Боевые ошибки компиляции, структурно невыразимые в KIR | **≈60%** из 85 374 за семь недель | с оговорками исходного отчёта о полноте логов |

<a id="the-five-laws"></a>
## Пять законов

Инвариант легко написать и трудно удержать: **ноль молча неверных исходов**. 2026-07-28 аудит
обнаружил, что наша собственная спека формулировала это прозой — а реализация разошлась именно там,
где проза не компилировалась. Поэтому честность стала арифметикой: пять законов сохранения, у
каждого свой механизм принуждения. Нарушение одного из них — это отказ сборки или прогона, а не
заметка ревьюеру.

```mermaid
flowchart LR
    subgraph LAWS["§18 — five conservation laws"]
        direction TB
        L1["1 · CENSUS<br/>lifted + atoms + not_read<br/>= the whole document"]
        L2["2 · RECEIPT<br/>every cut emits<br/>element_id + typed_reason"]
        L3["3 · WITNESS AXIS<br/>sign only the axis<br/>you actually read"]
        L4["4 · CONTAMINATION<br/>a partial read marks<br/>everything derived from it"]
        L5["5 · NEUTRALITY<br/>no device ids, install paths,<br/>or locale-only keys"]
    end

    subgraph CORE["what they enclose"]
        direction TB
        C1["compile"] --> C2["execute in Revit"] --> C3["read back"] --> C4["publish a number"]
    end

    L1 -->|"run-fatal identity check + CI fixture"| CORE
    L2 -->|"rows + failures contract on every side stage"| CORE
    L3 -->|"certificate lint: kind to legal reader"| CORE
    L4 -->|"header round-trip test + A5 gate on partial data"| CORE
    L5 -->|"CI pattern lint"| CORE

    CORE --> R1["built, with a witness"]
    CORE --> R2["typed refusal, with a route"]
    CORE -.->|forbidden by construction| R3["silently wrong"]
```

Полный разбор: [**Пять законов сохранения честности для AI-агента в САПР**](docs/articles/2026-07-five-laws-of-honesty.ru.md).

## Читать дальше

- [**Здание — это программа**](docs/articles/2026-07-a-building-is-a-program.ru.md) — развёрнутое
  техническое обоснование: что выражает IR, почему он работает в обе стороны, и измеренное число за
  каждым утверждением.
- [**Пять законов сохранения честности для AI-агента в САПР**](docs/articles/2026-07-five-laws-of-honesty.ru.md)
  — пять законов, ловушка за каждым из них и то, как каждый механически принуждается.
- [**День измеренных ловушек Revit API**](docs/articles/2026-07-revit-api-traps.ru.md) — четырнадцать
  особенностей поведения Revit API в формате симптом, неверная гипотеза, измерение, правило. Полезно,
  даже если вы никогда не тронете KIR.
- [**Один день внутри команды компилятора под руководством ИИ**](docs/articles/2026-07-one-day-chronicle.ru.md)
  — рассказ от первого лица об одном рабочем дне на этом проекте.

## Созвездие

Две статьи выше теперь живут в собственных репозиториях и развиваются независимо, а не как
разделы этого репо:

- [**revit-api-traps**](https://github.com/BigDick2014/revit-api-traps) — живой каталог
  измеренных ловушек Autodesk Revit API. Каждая запись: документировано | наблюдение | наш баг.
- [**five-laws-of-honesty**](https://github.com/BigDick2014/five-laws-of-honesty) — пять законов
  сохранения, отдельно.

Манифест чисел для всего созвездия остаётся здесь:
[`docs/articles/publication_manifest.json`](docs/articles/publication_manifest.json).

## Дорожная карта до 9 августа

Дата — это обязательство, а не уже достигнутый результат. В поставку идёт ядро компилятора: реестр,
генераторы схемы и грамматики, поэтапный конвейер, эмиттеры по версиям, механика свидетеля, хребет
декомпиляции и спеки, которые всем этим управляют.

| Веха | Состояние |
|---|---|
| Спеки канонизированы внутри репозитория (`SPEC_V1.md`, `KIR_DECOMPILE_SPEC.md`) | готово, 2026-07-28 |
| Нейтральность поставки — allow-list устройств, без абсолютных путей, без ключей только на локали | готово, 2026-07-28 |
| Каждый модуль подписан `live` / `incubating` / `deleted` в `WIRING.md` | готово, 2026-07-28 |
| Сертификат перевода подключён в компиляционный гейт | план |
| Предполётная проверка `open_model` — один живой прогон RollBack, затем включение по умолчанию | план |
| Стенд-миссия, полный прогон на отложенном корпусе | план |
| Подключён хребет инкрементальной пересборки (сперва merkle — это краеугольный камень) | план, после стенда |
| Код появляется в этом репозитории | **9 августа 2026** |

---

<p align="center">
  <sub>Apache License 2.0 — см. <a href="LICENSE">LICENSE</a>.</sub>
</p>
