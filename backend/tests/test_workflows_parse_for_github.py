"""ВОРОТА, КОТОРЫЕ НЕ ЗАПУСКАЮТСЯ, ВОРОТАМИ НЕ ЯВЛЯЮТСЯ.

ЗАМЕР, КУПИВШИЙ ЭТОТ ФАЙЛ (16.08.2026). `.github/workflows/kir-evidence.yml` —
главные ворота доказательства продового пути компилятора — дали **175 прогонов
и НИ ОДНОГО зелёного**. Из них **171 умер до запуска единого задания**:
`/actions/runs/<id>/jobs` отвечал `total_count: 0`, `/logs` — 404, у прогона
`created_at == updated_at`, а поле `name` было ПУТЁМ ФАЙЛА вместо объявленного
`CI — KIR compiler evidence`. Последнее и есть подпись отказа на старте: GitHub
не смог прочитать `name:`, потому что не смог разобрать файл.

Причину назвал сам GitHub, дословно, через `POST /actions/workflows/<wf>/dispatches`
с ВАЛИДНЫМ реф'ом:

    failed to parse workflow: (Line: 169, Col: 23):
    Unrecognized named-value: 'runner'. Located at position 1
    within expression: runner.temp

`${{ runner.temp }}` стоял в `env:` НА УРОВНЕ ДЖОБА. Контекст `runner` там
недоступен — он появляется только внутри шагов. Дефект приехал ПЕРВЫМ ЖЕ
коммитом файла (`7900353c`, 23.07.2026, «ci: enforce six-version KIR evidence
gate»), то есть ворота были мертвы с рождения и не охраняли ни одного пуша.
Тот же файл байт-в-байт лежит на `prod-live` — ветке, которую он и обязан
охранять.

ПОЧЕМУ ЛОКАЛЬНЫЙ РАЗБОР ЭТОГО НЕ ЛОВИЛ. PyYAML разбирает файл ЧИСТО: 3 джоба,
`name` читается, дублей ключей нет, табуляций нет. Синтаксис YAML исправен —
неверен КОНТЕКСТ ВЫРАЖЕНИЯ, а это правило GitHub Actions, о котором YAML не
знает. Прибор обязан проверять то же, что проверяет GitHub, иначе он зелен на
предмете, который GitHub отвергает.

🔴 И ОДИН ВАКУУМНЫЙ КОНТРОЛЬ, КУПЛЕННЫЙ ПО ДОРОГЕ. Первая попытка проверить все
воркфлоу разом слала `dispatches` с НЕСУЩЕСТВУЮЩИМ реф'ом, чтобы «проверить
разбор, ничего не запуская». Восемь файлов из восьми ответили «разбирается» —
включая заведомо сломанный. GitHub проверяет реф ПЕРВЫМ и до разбора не
доходит: прибор был зелен по построению. Поэтому проверка здесь СТАТИЧЕСКАЯ и
не зависит от сети.

ЧТО ИМЕННО ЗАПРЕЩЕНО. Контексты `runner`, `steps`, `job`, `jobs` существуют
только внутри шага. Всякое их упоминание в ключах УРОВНЯ ДЖОБА (`env`,
`defaults`, `strategy`, `container`, `services`, `runs-on`, `timeout-minutes`,
`continue-on-error`, `if`) делает файл неразбираемым для GitHub целиком — не
джоб, не шаг, а ВЕСЬ файл, включая исправные джобы.
"""
from __future__ import annotations

import pathlib
import re

import pytest
import yaml

_HERE = pathlib.Path(__file__).resolve()
_ROOT = _HERE.parents[2]
_WORKFLOWS = _ROOT / ".github" / "workflows"

# Контексты, существующие ТОЛЬКО внутри шага.
_STEP_ONLY = ("runner", "steps", "job", "jobs")

# Ключи джоба, которые GitHub вычисляет ДО того, как появится раннер.
_JOB_LEVEL_KEYS = (
    "env", "defaults", "strategy", "container", "services",
    "runs-on", "timeout-minutes", "continue-on-error", "if", "concurrency",
)

_EXPR = re.compile(r"\$\{\{([^}]*)\}\}")


def _workflow_files() -> list[pathlib.Path]:
    if not _WORKFLOWS.is_dir():
        pytest.fail(
            f"НЕ ПРОЧЁЛ каталог воркфлоу {_WORKFLOWS} — это отказ, а не «чисто». "
            "Прибор, объявляющий чистоту на непрочитанном дереве, и есть тот "
            "дефект, ради которого написан этот файл."
        )
    files = sorted(p for p in _WORKFLOWS.glob("*.yml"))
    files += sorted(p for p in _WORKFLOWS.glob("*.yaml"))
    if not files:
        pytest.fail(f"в {_WORKFLOWS} нет ни одного воркфлоу — проверять нечего, это отказ")
    return files


def _step_only_contexts(node) -> list[str]:
    """Все упоминания шаговых контекстов внутри произвольного поддерева."""
    found: list[str] = []
    if isinstance(node, dict):
        for v in node.values():
            found += _step_only_contexts(v)
    elif isinstance(node, list):
        for v in node:
            found += _step_only_contexts(v)
    elif isinstance(node, str):
        for expr in _EXPR.findall(node):
            for ctx in _STEP_ONLY:
                if re.search(rf"(?<![\w.]){ctx}\s*\.", expr):
                    found.append(f"{ctx}.* в «{expr.strip()}»")
    return found


def _jobs_of(doc) -> dict:
    return (doc or {}).get("jobs") or {}


def test_the_control_reads_real_workflow_files():
    """Контроль обязан доказать, что предмет прочитан.

    Без этого «нарушений нет» неотличимо от «файлов не нашёл» — ровно та
    подмена, из-за которой 171 мёртвый прогон никто не читал.
    """
    files = _workflow_files()
    assert len(files) >= 5, f"воркфлоу подозрительно мало: {[f.name for f in files]}"
    parsed = 0
    for path in files:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert isinstance(doc, dict), f"{path.name}: не разобрался в отображение"
        parsed += 1
    assert parsed == len(files)


def test_no_step_only_context_at_job_level():
    """ГЛАВНОЕ: шаговый контекст на уровне джоба убивает ВЕСЬ файл.

    Отказ GitHub не локален: неразбираемый файл не запускает ни одного джоба,
    и в API это выглядит как обычный `failure`, а не как «файл неверен».
    """
    offenders: list[str] = []
    for path in _workflow_files():
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job_id, job in _jobs_of(doc).items():
            if not isinstance(job, dict):
                continue
            for key in _JOB_LEVEL_KEYS:
                if key not in job:
                    continue
                for hit in _step_only_contexts(job[key]):
                    offenders.append(f"{path.name}: джоб «{job_id}», ключ «{key}» -> {hit}")

    assert not offenders, (
        "шаговый контекст на уровне джоба — GitHub ОТКАЖЕТСЯ разбирать файл "
        "целиком, и все прогоны умрут до запуска заданий:\n  "
        + "\n  ".join(offenders)
        + "\nПочинка: перенести величину в шаг и объявить её через "
          "$GITHUB_ENV, либо взять переменную окружения раннера ($RUNNER_TEMP)."
    )


def test_step_level_runner_context_stays_allowed():
    """ОБРАТНЫЙ ПОЛЮС: внутри шага `runner.*` законен и запрещать его нельзя.

    Без этой проверки «починка» свелась бы к «выкинуть runner отовсюду», что
    сломало бы рабочие шаги. Предмет выбран не наугад: в `kir-evidence.yml`
    те же `${{ runner.temp }}` стоят в `with.path` шага выгрузки артефактов и
    обязаны там остаться.
    """
    seen_step_level = 0
    for path in _workflow_files():
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job in _jobs_of(doc).values():
            if not isinstance(job, dict):
                continue
            for step in job.get("steps") or []:
                seen_step_level += len(_step_only_contexts(step))
    assert seen_step_level > 0, (
        "ни одного шагового контекста внутри шагов не найдено — предмет "
        "подозрительно пуст, и тогда основная проверка зелена ни о чём"
    )
