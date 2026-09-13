// THE FOURTH KIND OF CHECK: THE CLIENT READS THE MESH THE SAME WAY THE SERVER WROTE IT.
//
// THREE things are checked, and all three are about the equality of TWO INDEPENDENT computations,
// not about the client repeating the server's number:
//
//   1. SIGNATURE, ELEMENT BY ELEMENT. The client's `shownRecords` must give byte-for-byte the
//      same thing as the server's `SceneBuilder.records`. This is the easiest place to break:
//      a mesh's signature carries BOTH the triangles AND the vertices, and any slip in the
//      ranges shows up immediately.
//   2. THE MERGE REBASES INDICES. Triangle indices are global; after
//      the merge they must point into the MERGED vertex array. Forgetting this
//      means getting someone else's triangles on your own vertices — a body that
//      nobody built.
//   3. GEOMETRY AFTER THE MERGE EQUALS THE GEOMETRY OF THE WHOLE. The path has no right
//      to affect what the person sees.
//
//     node verify_mesh.mjs <blobs-directory> <path-to-scene-data.js>   (BOTH required)

import { readFileSync } from "node:fs";
// 🔴 ONE CARRIER OF THE ADDRESS AND ONE KIND OF REFUSAL FOR FOUR VERIFIERS.
// There used to be TWO silent defaults here — `|| "/tmp"` and a hardcoded
// path into the product tree; both are removed, the full argument lives in
// `_verify_common.mjs`. In short: KIR is environment-agnostic, and a green
// verdict about someone else's files is worse than no verdict at all.
import { blobsDir, clientModulePath, readBlob, importClient }
  from "./_verify_common.mjs";

const dir = blobsDir("verify_mesh.mjs");
const module_path = clientModulePath("verify_mesh.mjs");
const { parseScene, mergeScenes, shownRecords } = await importClient(module_path);

const ab = (name) => readBlob(readFileSync, dir, name);
const hex = (u8) => Array.from(u8, (b) => b.toString(16).padStart(2, "0")).join("");

let bad = 0;
const fail = (msg) => { console.log(`  x ${msg}`); bad++; };

// ── 1. signature, element by element ──────────────────────────────────────────────────
const whole = parseScene(ab("m_whole.bin"));
const server = JSON.parse(readFileSync(`${dir}/m_records.json`, "utf8"));
const client = shownRecords(whole).map(hex);
if (client.length !== server.length)
  fail(`записей: клиент ${client.length}, сервер ${server.length}`);
else {
  let diff = 0;
  for (let i = 0; i < client.length; i++) if (client[i] !== server[i]) diff++;
  if (diff) fail(`подписи разошлись у ${diff} из ${client.length} элементов`);
  else console.log(`  ok подпись поэлементно: ${client.length} записей байт в байт`);
}

// ── 2 and 3. the merge ──────────────────────────────────────────────────────────
const base = parseScene(ab("m_base.bin"));
const tail = parseScene(ab("m_tail.bin"));
const merged = mergeScenes(base, tail);

const KM = whole.header.kinds.mesh;
const triCount = merged.meshOfs[merged.meshOfs.length - 1];
if (triCount * 3 !== merged.meshTri.length)
  fail(`после склейки треугольников ${merged.meshTri.length / 3}, `
       + `а префиксная сумма обещает ${triCount}`);
else console.log(`  ok склейка: ${triCount} треугольников, сумма сходится`);

let outOfRange = 0;
for (let i = 0; i < merged.meshTri.length; i++)
  if (merged.meshTri[i] * 3 >= merged.meshVtx.length) outOfRange++;
if (outOfRange) fail(`${outOfRange} индексов после склейки смотрят за массив вершин`);
else console.log("  ok склейка: все индексы внутри склеенных вершин");

// GEOMETRY: unroll the triangles into points and check against the whole.
const soup = (d) => {
  const out = [];
  for (let i = 0; i < d.meshTri.length; i++) {
    const v = d.meshTri[i];
    out.push(d.meshVtx[v * 3], d.meshVtx[v * 3 + 1], d.meshVtx[v * 3 + 2]);
  }
  return out;
};
const a = soup(merged), b = soup(whole);
if (a.length !== b.length) fail(`точек: склейка ${a.length}, целое ${b.length}`);
else {
  let off = 0, unusable = 0;
  for (let i = 0; i < a.length; i++) {
    const d = a[i] - b[i];
    // 🔴 INCOMPARABLE IS NOT EQUAL (VJ-06, 29.08.2026). Every comparison with NaN
    // is false under IEEE-754, so `Math.abs(NaN) > 1e-4` gave `false`, and
    // a coordinate that CANNOT be compared fell into the same bucket as one that
    // matched. Where the NaN comes from: READING PAST THE END of a `Float32Array`
    // yields `undefined`, and `undefined - x` yields NaN — meaning an index slip
    // during the merge, exactly the error this instrument is meant to guard against, WAS SILENCING
    // ITSELF. Verified: `Math.abs(new Float32Array([1,2,3])[9] - 1.0)
    // > 1e-4` -> false, discrepancies counted as 0 where it must be 1.
    //
    // NaN honestly does NOT COME from the server (`codec._f32_safe` turns
    // non-finite values into 0.0, and `struct.pack('<f', 1e40)` raises OverflowError) —
    // it is born ON THE CLIENT, and this is stated outright so the path is not taken
    // for unreachable.
    //
    // A SEPARATE counter, not `off++`: “did not match” gets fixed in the merge,
    // “nothing to compare” — in the indices, and their next move differs. Merging them
    // would send the reader the wrong way. `Number.isFinite` covers
    // all three kinds at once: NaN, ±Infinity, and `undefined` past the end of the buffer.
    if (!Number.isFinite(d)) { unusable++; continue; }
    if (Math.abs(d) > 1e-4) off++;
  }
  if (unusable)
    fail(`${unusable} координат НЕСРАВНИМЫ (NaN/бесконечность/чтение за концом `
         + `буфера) — это не равенство, это невозможность сравнить`);
  if (off) fail(`${off} координат склейки не равны целому`);
  if (!off && !unusable)
    console.log(`  ok склейка == целое: ${a.length / 3} точек совпали`);
}
if (KM === undefined) fail("заголовок не называет рода mesh");

// ── 4. WHOSE BODY IS THIS ─────────────────────────────────────────────────────────
// 🔴 THE THREE PREVIOUS CHECKS DO NOT ASK ABOUT THE OWNER (VJ-05, 29.08.2026).
// The sum, the ranges, and the “soup” are all three global: the soup unrolls the ENTIRE buffer
// and is not tied to elements. So a slot shift in the mesh during the merge left
// them green and quietly showed an element SOMEONE ELSE'S BODY — exactly the error that
// its neighbor (`verify_merge.mjs`) calls “the quietest one possible”: it drops
// nothing, and the building stays plausible.
//
// The signature (check 1) ALREADY carries ownership — it is assembled element by element. But
// it checks the SERVER against the CLIENT on the WHOLE scene, not the MERGE against the WHOLE, and
// a slot swap DURING THE MERGE does not fall within it.
//
// `nextMeshSlot` repeats the client's algorithm (`scene-data.js`, `nextSlot`)
// deliberately and verbatim: a body's boundaries are taken exactly as the
// renderer would take them, otherwise the instrument would be checking a DIFFERENT subject.
const nextMeshSlot = (d) => {
  const n = d.header.elements;
  const nxt = new Int32Array(n).fill(-1);
  let last = -1;
  for (let i = 0; i < n; i++) {
    if (d.kind[i] !== KM) continue;
    if (last >= 0) nxt[last] = d.slot[i];
    last = i;
  }
  if (last >= 0) nxt[last] = d.meshOfs.length - 1;
  return nxt;
};
const byId = (d) => {
  const m = new Map();
  for (let i = 0; i < d.header.elements; i++) m.set(d.ids[i], i);
  return m;
};
// 🔴 INDICES ARE REBASED TO THEIR OWN ORIGIN (`- d.meshVofs[s]`): this check's
// question is “did the element get THE SAME BODY”, not “does it sit in the same place”, and
// without the rebasing it would duplicate check 3's sensitivity to the buffer's
// layout.
//
// 🔴 BUT HONESTLY: TODAY'S FIXTURE DOES NOT CHECK THIS. The package promised that
// removing `- d.meshVofs[s]` would turn red on a HEALTHY merge; verified on 29.08 —
// IT DOES NOT TURN RED, the instrument stays green across all five rows. The reason: the merge
// places the vertices in the same order the whole scene lists them, and
// `meshVofs[s]` matches on both sides — the rebasing on this data is an
// IDENTITY. This is written down here rather than left unsaid: a control that cannot
// turn red guards nothing, and passing it off as verified would be the very
// lie this whole instrument was written against.
const meshOf = (d, i, nxt) => {
  const s = d.slot[i], e = nxt[i];
  const tri = Array.from(d.meshTri.slice(d.meshOfs[s] * 3, d.meshOfs[e] * 3),
                         (t) => t - d.meshVofs[s]);
  const vtx = Array.from(d.meshVtx.slice(d.meshVofs[s] * 3, d.meshVofs[e] * 3));
  return JSON.stringify([tri, vtx]);
};
if (KM !== undefined) {
  const mNext = nextMeshSlot(merged), wNext = nextMeshSlot(whole);
  const mi = byId(merged), wi = byId(whole);
  let owned = 0;
  for (const [id, wIdx] of wi) {
    if (whole.kind[wIdx] !== KM) continue;
    if (!mi.has(id)) { fail(`склейка потеряла ${id}`); continue; }
    const m = mi.get(id);
    if (merged.kind[m] !== KM) { fail(`РОД ${id}: склейка отдала не сетку`); continue; }
    if (meshOf(merged, m, mNext) !== meshOf(whole, wIdx, wNext))
      fail(`ТЕЛО ${id}: склейка отдала ему чужую сетку`);
    else owned++;
  }
  for (const id of mi.keys()) if (!wi.has(id)) fail(`склейка ВЫДУМАЛА ${id}`);
  if (owned) console.log(`  ok владение: ${owned} элемента получили свои тела`);
}

console.log(bad === 0
  ? "  ok ЧЕТВЁРТЫЙ РОД ЧИТАЕТСЯ КЛИЕНТОМ ТАК ЖЕ, КАК ЗАПИСАН СЕРВЕРОМ"
  : `  x расхождений: ${bad}`);
process.exit(bad ? 1 : 0);
