// «ХВОСТ» ПОСЛЕ СКЛЕЙКИ — СВОЙСТВО НАКОПЛЕННОГО, А НЕ ПОСЛЕДНЕГО ОТВЕТА.
//
// НАЙДЕНО 16.08.2026 НА ЖИВОМ ХОДЕ ВЛАДЕЛЬЦА, И ЦЕНА БЫЛА — ВЕСЬ ПРОДУКТ.
// Сервер честно ставит `partial = since > 0` (`live_scene.py:243`): в ЭТИХ
// байтах лежит хвост журнала. Склейка брала заголовок целиком от дельты, и
// правда об ОТВЕТЕ становилась ложью о СЦЕНЕ: клиент, начавший с `since=0` и
// применивший все дельты, держит здание ЦЕЛИКОМ, а говорил о себе «я хвост».
// Кнопку «Отправить в Revit» это убивало ПО ПОСТРОЕНИЮ: живая сессия начинает
// кадром `since=0`, дальше идут дельты, и ПЕРВАЯ ЖЕ — даже пустая — ставила
// признак навсегда. Отказ `PARTIAL_SCENE` (`transfer.py:610`) на человеке
// читался как «на экране ХВОСТ журнала… запросите сцену целиком», и запросить
// её было некому.
//
// ЧЕГО ЭТОТ ПРИБОР НЕ ДЕЛАЕТ. Он не проверяет геометрию склейки — это работа
// `verify_merge.mjs`, и повторять её здесь значило бы завести второе место, где
// живёт один ответ. Здесь ровно один вопрос: ЧЕСТНОСТЬ О ПОЛНОТЕ.
//
// Запуск (блобы кладёт `test_delta.py`):
//     node verify_partial.mjs <каталог-с-блобами> <путь-к-scene-data.js>
// Код возврата 0 — признак выводится верно; 1 — расхождения названы построчно.

import { readFileSync } from "node:fs";

const dir = process.argv[2] || "/tmp";
const module_path = process.argv[3]
  || "/opt/kukai-rebuild1/assets/viewer/scene-data.js";
const { parseScene, mergeScenes } = await import(module_path);

const ab = (name) => {
  const b = readFileSync(`${dir}/${name}`);
  return b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength);
};

let bad = 0;
const fail = (m) => { console.log("  x " + m); bad++; };
const ok = (m) => console.log("  ok " + m);

const base = parseScene(ab("d_base.bin"));
const delta = parseScene(ab("d_delta.bin"));

// ── ПРЕДПОСЫЛКИ. Прибор обязан доказать, что мерит ТОТ предмет: если сервер
// перестанет помечать дельту хвостом, тест ниже позеленеет ни о чём.
if (base.header.partial !== false)
  fail(`база (since=0) обязана быть НЕ хвостом, а пришла partial=${base.header.partial}`);
else ok("база честно не хвост");
if (delta.header.partial !== true)
  fail(`дельта обязана быть хвостом, а пришла partial=${delta.header.partial}`);
else ok("дельта честно хвост");

// ── ГЛАВНОЕ. Целое + хвост = целое.
const merged = mergeScenes(base, delta);
if (merged.header.partial !== false)
  fail("склейка ЦЕЛОГО с хвостом объявила себя хвостом: "
     + `partial=${merged.header.partial}. Кнопка переноса мертва по построению`);
else ok("склейка целого с хвостом — не хвост");

if (merged.header.partial === false && merged.header.partial_ru)
  fail(`не хвост, но объяснение хвоста осталось: «${merged.header.partial_ru}»`);
else ok("объяснение согласовано с признаком");

// ── ВТОРАЯ ДЕЛЬТА ПОДРЯД ничего не меняет: полнота не «изнашивается».
const twice = mergeScenes(merged, delta);
if (twice.header.partial !== false)
  fail("вторая дельта подряд сделала целое хвостом");
else ok("вторая дельта подряд полноту не портит");

// ── ОБРАТНЫЙ ПОЛЮС, БЕЗ КОТОРОГО ПОЧИНКА СВЕЛАСЬ БЫ К «ВСЕГДА ЦЕЛОЕ».
// Вытеснение — единственная причина, по которой честный курсор всё-таки даёт
// неполное: этих программ клиенту уже не пришлёт никто.
const evicted = parseScene(ab("d_delta.bin"));
evicted.header = Object.assign({}, evicted.header, {
  journal: Object.assign({}, evicted.header.journal, { evicted: 7 }),
});
const lost = mergeScenes(base, evicted);
if (lost.header.partial !== true)
  fail("программы ВЫТЕСНЕНЫ из журнала, а склейка объявила себя целой — "
     + "это молчаливо-неполное здание, ровно то, что запрещено");
else ok("вытеснение делает склейку неполной");
if (lost.header.partial === true && !/ВЫТЕСНЕН/.test(lost.header.partial_ru || ""))
  fail(`неполнота от вытеснения не НАЗЫВАЕТ себя: «${lost.header.partial_ru}»`);
else ok("вытеснение названо словами");

// ── И БАЗА-ХВОСТ ОСТАЁТСЯ ХВОСТОМ. Клиент, начавший не с нуля, целого не имеет.
const fromTail = mergeScenes(delta, delta);
if (fromTail.header.partial !== true)
  fail("склейка, начатая ОТ ХВОСТА, объявила себя целой");
else ok("начатое от хвоста остаётся хвостом");

console.log(bad ? `РАСХОЖДЕНИЙ: ${bad}` : "признак полноты выводится верно");
process.exit(bad ? 1 : 0);
