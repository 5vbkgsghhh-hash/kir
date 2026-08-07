"""Живая поведенческая проверка query_model scope='table' на реальной модели.

Закрывает риск №1 из саморевью: до сих пор доказано только что код
КОМПИЛИРУЕТСЯ и содержит нужные подстроки. Здесь проверяется, что он
ДЕЛАЕТ обещанное: сортирует, ставит пустые в конец при desc, режет по limit,
и что total сходится с независимым путём (return='count', код не менялся).

Только чтение: ни одной транзакции. Устройство — из белого списка.
"""
import json, sys, urllib.request

BACKEND = "http://127.0.0.1:52411"
DEVICE = "a6d7d14340bc599817ae7e6896182ca0"
sys.path.insert(0, "/opt/kukai-rebuild1/backend")
from kukai.query.query_builder import build_query_code  # noqa: E402

TOKEN = ""
for line in open("/opt/kukai-rebuild1/backend/.env", encoding="utf-8"):
    if line.startswith("KUKAI_ADMIN_TOKEN="):
        TOKEN = line.split("=", 1)[1].strip()

def run(spec, timeout_ms=30000):
    code = build_query_code(spec)
    body = json.dumps({"code": code, "timeout_ms": timeout_ms}).encode()
    req = urllib.request.Request(f"{BACKEND}/admin/remote/exec/{DEVICE}", data=body,
                                 headers={"Content-Type": "application/json",
                                          "X-Admin-Token": TOKEN})
    with urllib.request.urlopen(req, timeout=timeout_ms/1000 + 20) as r:
        out = json.loads(r.read())
    if isinstance(out, dict) and out.get("error"):
        raise RuntimeError(f"bridge error: {str(out)[:200]}")
    res = out.get("result", out)
    if isinstance(res, str):
        res = json.loads(res)
    return res

CAT = "walls"
ok = fail = 0
def check(name, cond, detail=""):
    global ok, fail
    if cond: ok += 1; print(f"  ✓ {name}")
    else:    fail += 1; print(f"  ✗ {name}   {detail}")

print(f"устройство {DEVICE[:12]}…, категория={CAT}\n")

# ── независимая база: старый, неизменённый путь ──────────────────────────────
base = run({"category": CAT, "return": "count"})
n = base.get("count")
print(f"независимый count (старый путь): {n}\n")

# ── 1. таблица с сортировкой по площади вниз ────────────────────────────────
t = run({"category": CAT, "return": "table",
         "fields": ["id", "name", "type", "area_m2"],
         "order_by": "area_m2", "order": "desc", "limit": 20})
rows = t.get("rows") or []
print(f"таблица: rows={len(rows)} total={t.get('total')} truncated={t.get('truncated')}")
check("total сходится с независимым count", t.get("total") == n,
      f"{t.get('total')} vs {n}")
check("limit соблюдён", len(rows) <= 20, f"вернулось {len(rows)}")
check("колонки ровно те, что просили",
      all(set(r) == {"id", "name", "type", "area_m2"} for r in rows))
vals = [r.get("area_m2") for r in rows]
nums = [v for v in vals if isinstance(v, (int, float))]
check("сортировка убывающая", all(nums[i] >= nums[i+1] for i in range(len(nums)-1)),
      f"первые: {nums[:5]}")
nulls = [i for i, v in enumerate(vals) if v is None]
check("пустые значения в конце (desc)",
      (not nulls) or min(nulls) >= len(nums),
      f"позиции null={nulls[:5]}, чисел={len(nums)}")
print(f"     топ-3 площади: {nums[:3]}   пустых: {len(nulls)}")

# ── 2. мера, которой раньше не существовало вовсе ───────────────────────────
t2 = run({"category": CAT, "return": "table", "fields": ["id", "length_m"],
          "order_by": "length_m", "order": "desc", "limit": 10})
lens = [r.get("length_m") for r in (t2.get("rows") or [])]
ln = [v for v in lens if isinstance(v, (int, float))]
check("length_m возвращается числом", bool(ln), f"{lens[:3]}")
check("length_m отсортирована убыв.", all(ln[i] >= ln[i+1] for i in range(len(ln)-1)))
print(f"     самые длинные, м: {ln[:3]}")

# ── 3. без сортировки — ранний выход не ломает счётчики ─────────────────────
t3 = run({"category": CAT, "return": "table", "fields": ["id", "name"], "limit": 5})
r3 = t3.get("rows") or []
check("без сортировки limit соблюдён", len(r3) <= 5, f"{len(r3)}")
check("total не искажён ранним выходом", t3.get("total") == n,
      f"{t3.get('total')} vs {n}")
check("truncated выставлен честно",
      t3.get("truncated") == (n > len(r3)), f"{t3.get('truncated')}")

# ── 4. числовой фильтр: СЕМАНТИКА, а не только «вернулось число» ────────────
# Первая версия этой проверки требовала лишь isinstance(count, int) и потому
# пропустила молчаливый 0 от несуществующего имени параметра. Теперь монотонность.
HP = "Неприсоединенная высота"
n_any = run({"category": CAT, "return": "count",
             "param": {"name": HP, "op": "not_empty"}}).get("count")
n_1k = run({"category": CAT, "return": "count",
            "param": {"name": HP, "op": "gt", "value": "1000"}}).get("count")
n_4k = run({"category": CAT, "return": "count",
            "param": {"name": HP, "op": "gt", "value": "4000"}}).get("count")
n_99k = run({"category": CAT, "return": "count",
             "param": {"name": HP, "op": "gt", "value": "99000"}}).get("count")
check("gt монотонен по порогу", n_1k >= n_4k >= n_99k, f"{n_1k} / {n_4k} / {n_99k}")
check("gt сравнивает в мм, а не в футах", n_1k > 0 and n_99k == 0,
      f"gt1000={n_1k}, gt99000={n_99k}")
print(f"     высота задана у {n_any}; >1000мм: {n_1k}; >4000мм: {n_4k}; >99м: {n_99k}")

# ── 5. неверно угаданное имя ≠ честный ноль ─────────────────────────────────
bad = run({"category": CAT, "return": "count",
           "param": {"name": "Высота", "op": "gt", "value": "1000"}})
honest = run({"category": CAT, "return": "count",
              "param": {"name": HP, "op": "gt", "value": "99000"}})
check("несуществующее имя раскрыто", bool(bad.get("predicates_skipped")),
      str(bad.get("predicates_skipped")))
check("честный ноль НЕ помечен предупреждением",
      not honest.get("predicates_skipped"), str(honest.get("predicates_skipped")))

print(f"\nИТОГ: {ok} прошло, {fail} провалено")
sys.exit(1 if fail else 0)
