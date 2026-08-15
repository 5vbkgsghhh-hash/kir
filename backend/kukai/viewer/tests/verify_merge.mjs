// СВЕРКА СКЛЕЙКИ ДЕЛЬТЫ С ЦЕЛОЙ СЦЕНОЙ — то, что нельзя проверить питоном.
//
// Склейка живёт у КЛИЕНТА (`assets/viewer/scene-data.js`) и является
// единственным местом, где ошибка не роняет ничего, а тихо показывает
// элементу ЧУЖОЕ тело: сдвинь слоты на единицу — и здание останется
// правдоподобным. Поэтому склейка сверяется не свойствами, а поэлементным
// равенством целой сцене: геометрия через слот (ровно так, как её возьмёт
// рисовальщик), обе оси честности, оси графа и таблицы строк.
//
// Запуск (блобы кладёт `test_delta_merge.py`):
//     node verify_merge.mjs <каталог-с-блобами> <путь-к-scene-data.js>
// Код возврата 0 — склейка равна целому; 1 — расхождения названы построчно.

import { readFileSync } from "node:fs";

const dir = process.argv[2] || "/tmp";
const module_path = process.argv[3]
  || "/opt/kukai-rebuild1/assets/viewer/scene-data.js";
const { parseScene, mergeScenes } = await import(module_path);

const ab = (name) => {
  const b = readFileSync(`${dir}/${name}`);
  return b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength);
};

const base = parseScene(ab("d_base.bin"));
const delta = parseScene(ab("d_delta.bin"));
const whole = parseScene(ab("d_whole.bin"));
const merged = mergeScenes(base, delta);

let bad = 0;
const fail = (m) => { console.log("  x " + m); bad++; };

if (merged.header.elements !== whole.header.elements)
  fail(`элементов ${merged.header.elements} против ${whole.header.elements}`);
else console.log(`  ok элементов ${merged.header.elements}`);

// Геометрия берётся ЧЕРЕЗ СЛОТ, то есть ровно так, как её возьмёт
// рисовальщик. Совпадение адресов без совпадения тел — самая тихая из
// возможных ошибок склейки, и ловится только так.
const geomOf = (d, i) => {
  const k = d.kind[i], s = d.slot[i];
  if (k === d.header.kinds.box) return ["box", ...d.box.slice(s * 6, s * 6 + 6)];
  if (k === d.header.kinds.capsule)
    return ["cap", ...d.capsule.slice(s * 7, s * 7 + 7)];
  const v0 = d.prismOfs[s], v1 = d.prismOfs[s + 1];
  return ["prism", d.prismZ[s * 2], d.prismZ[s * 2 + 1],
          ...d.prismXY.slice(v0 * 2, v1 * 2)];
};
const byId = (d) => {
  const m = new Map();
  for (let i = 0; i < d.header.elements; i++) m.set(d.ids[i], i);
  return m;
};
const mi = byId(merged), wi = byId(whole);
for (const [id, wIdx] of wi) {
  if (!mi.has(id)) { fail(`склейка потеряла ${id}`); continue; }
  const m = mi.get(id);
  const a = JSON.stringify(geomOf(merged, m));
  const b = JSON.stringify(geomOf(whole, wIdx));
  if (a !== b) fail(`ГЕОМЕТРИЯ ${id}: ${a.slice(0, 70)} != ${b.slice(0, 70)}`);
  for (const f of ["trust", "fidelity", "axes", "authority", "existence",
                   "flagbits"]) {
    if (merged[f] && whole[f] && merged[f][m] !== whole[f][wIdx])
      fail(`${f} у ${id}: ${merged[f][m]} != ${whole[f][wIdx]}`);
  }
  if (merged.header.categories[merged.cat[m]]
      !== whole.header.categories[whole.cat[wIdx]])
    fail(`категория у ${id}`);
  if (merged.header.levels[merged.level[m]]
      !== whole.header.levels[whole.level[wIdx]])
    fail(`уровень у ${id}`);
}
for (const id of mi.keys()) if (!wi.has(id)) fail(`склейка ВЫДУМАЛА ${id}`);

console.log(bad === 0
  ? "  ok СКЛЕЙКА ПОЭЛЕМЕНТНО РАВНА ЦЕЛОЙ СЦЕНЕ"
  : `  x расхождений: ${bad}`);
process.exit(bad ? 1 : 0);
