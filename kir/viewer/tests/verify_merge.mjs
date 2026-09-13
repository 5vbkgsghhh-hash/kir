// CHECKING THE DELTA MERGE AGAINST THE WHOLE SCENE — something that cannot be checked in Python.
//
// The merge lives ON THE CLIENT (`assets/viewer/scene-data.js`) and is
// the only place where an error drops nothing, and quietly shows
// an element SOMEONE ELSE'S body: shift the slots by one — and the building stays
// plausible. That is why the merge is checked not by properties, but by element-by-element
// equality against the whole scene: geometry via the slot (exactly as it will be taken by the
// renderer), both honesty axes, the graph axes, and the row tables.
//
// Run it (the blobs are dropped by `test_delta_merge.py`):
//     node verify_merge.mjs <blobs-directory> <path-to-scene-data.js>   (BOTH required)
// Exit code 0 — the merge equals the whole; 1 — discrepancies are named line by line.

import { readFileSync } from "node:fs";
// 🔴 ONE CARRIER OF THE ADDRESS AND ONE KIND OF REFUSAL FOR FOUR VERIFIERS.
// There used to be TWO silent defaults here — `|| "/tmp"` and a hardcoded
// path into the product tree; both are removed, the full argument lives in
// `_verify_common.mjs`. In short: KIR is environment-agnostic, and a green
// verdict about someone else's files is worse than no verdict at all.
import { blobsDir, clientModulePath, readBlob, importClient, nextSlotOf }
  from "./_verify_common.mjs";

const dir = blobsDir("verify_merge.mjs");
const module_path = clientModulePath("verify_merge.mjs");
const { parseScene, mergeScenes } = await importClient(module_path);

const ab = (name) => readBlob(readFileSync, dir, name);

const base = parseScene(ab("d_base.bin"));
const delta = parseScene(ab("d_delta.bin"));
const whole = parseScene(ab("d_whole.bin"));
const merged = mergeScenes(base, delta);

let bad = 0;
const fail = (m) => { console.log("  x " + m); bad++; };

if (merged.header.elements !== whole.header.elements)
  fail(`элементов ${merged.header.elements} против ${whole.header.elements}`);
else console.log(`  ok элементов ${merged.header.elements}`);

// Geometry is taken VIA THE SLOT, that is exactly as it will be taken by the
// renderer. Matching addresses without matching bodies is the quietest of
// possible merge errors, and this is the only way to catch it.
// 🔴 TWO DEFECTS IN THIS FUNCTION, FOUND ON 29.08.2026 (VJ-03), AND BOTH SILENT.
//
// (1) A MESH WAS PARSED AS A PRISM. There was no `mesh` branch at all, and anything that was not
//     a box or a capsule was read via `prismOfs[s]` — SOMEONE ELSE'S index into SOMEONE ELSE'S
//     stream. On a scene made from `create_directshape`, the prism buffers are EMPTY,
//     so the checker compared `undefined` to `undefined` and declared
//     equality ALWAYS. Verified by execution: swapping the slots of two bodies in
//     `mergeScenes`, on a scene made of PIPES, gives exit code 1 and names both elements, while on a
//     scene made of MESHES — code 0 and “ok THE MERGE IS ELEMENT-BY-ELEMENT EQUAL TO THE WHOLE SCENE”.
//     The same defect, two scenes, opposite verdicts.
//
// (2) EXACTLY ONE CHUNK WAS TAKEN. `capsule.slice(s*7, s*7+7)` and
//     `prismOfs[s]..prismOfs[s+1]` are the FIRST segment, whereas the server
//     (`codec._record`) signs EVERYTHING up to the end of the stream. For a five-segment
//     polyline, the checker would compare the first one and declare equality while four are
//     lost. The range is now taken up to the slot of the NEXT element in the
//     same stream — using the same traversal as the client (`nextSlotOf`).
//
// The signature (`verify_shown`) is deliberately NOT reused here: this instrument
// checks GEOMETRY BY SLOT, “exactly as the renderer will take it”, and
// repeating its neighbor would mean running two instruments about the same thing.
const geomOf = (d, i, nxt) => {
  const k = d.kind[i], s = d.slot[i], nx = nxt[i];
  if (k === d.header.kinds.box) return ["box", ...d.box.slice(s * 6, s * 6 + 6)];
  if (k === d.header.kinds.capsule)
    return ["cap", ...d.capsule.slice(s * 7, nx * 7)];
  if (d.header.kinds.mesh !== undefined && k === d.header.kinds.mesh) {
    // Indices are rebased TO THEIR OWN ORIGIN: the merge rebases them LEGITIMATELY, and
    // without the rebasing the instrument would turn red on a healthy merge.
    return ["mesh",
            ...Array.from(d.meshTri.slice(d.meshOfs[s] * 3, d.meshOfs[nx] * 3),
                          (t) => t - d.meshVofs[s]),
            ...d.meshVtx.slice(d.meshVofs[s] * 3, d.meshVofs[nx] * 3)];
  }
  const v0 = d.prismOfs[s], v1 = d.prismOfs[nx];
  return ["prism", ...d.prismZ.slice(s * 2, nx * 2),
          ...d.prismXY.slice(v0 * 2, v1 * 2)];
};
const byId = (d) => {
  const m = new Map();
  for (let i = 0; i < d.header.elements; i++) m.set(d.ids[i], i);
  return m;
};
const mi = byId(merged), wi = byId(whole);
const mNext = nextSlotOf(merged), wNext = nextSlotOf(whole);
for (const [id, wIdx] of wi) {
  if (!mi.has(id)) { fail(`склейка потеряла ${id}`); continue; }
  const m = mi.get(id);
  const a = JSON.stringify(geomOf(merged, m, mNext));
  const b = JSON.stringify(geomOf(whole, wIdx, wNext));
  if (a !== b) fail(`ГЕОМЕТРИЯ ${id}: ${a.slice(0, 70)} != ${b.slice(0, 70)}`);
  for (const f of ["trust", "fidelity", "axes", "authority", "existence",
                   "flagbits"]) {
    // 🔴 A MISSING AXIS IS A DISCREPANCY, NOT A REASON TO SKIP THE COMPARISON (VJ-04,
    // 29.08.2026). The condition `merged[f] && whole[f] && ...` SKIPPED
    // the comparison exactly when an axis DISAPPEARED during the merge: losing a WHOLE honesty
    // axis read as equality. Axes are how a scene says “I did not check
    // this”; a silently lost axis turns gray into green,
    // that is, the unchecked into the confirmed.
    //
    // Axes cannot be required UNCONDITIONALLY: a scene is entitled not to carry them at all
    // (the header declares which buffers exist), and such a check would turn red
    // on a legitimate scene. What is compared is PRESENCE — `!a !== !b` — and this
    // is the only form that catches a disappearance.
    const a = merged[f], b = whole[f];
    if (!a !== !b) {
      fail(`ось ${f} у ${id}: у склейки ${!!a}, у целого ${!!b} — пропала `
           + `целая ось честности, а не значение`);
      continue;
    }
    if (a && b && a[m] !== b[wIdx])
      fail(`${f} у ${id}: ${a[m]} != ${b[wIdx]}`);
  }
  // 🔴 THE LABEL IS CHECKED ON EQUAL FOOTING WITH THE CATEGORY AND THE LEVEL (VJ-04). It is exactly what
  // a person reads under an element (“create_wall”), and it had never once been checked:
  // a shift in the label table would show a wall labeled as a pipe, without
  // dropping anything in the process. It is compared AS A STRING, not by number: the merge's
  // table numbers are its own — the same argument recorded in `codec._record` (“NUMBERS IN
  // TABLES ARE DELIBERATELY NOT INCLUDED”).
  if (merged.labels[m] !== whole.labels[wIdx])
    fail(`ярлык у ${id}: ${merged.labels[m]} != ${whole.labels[wIdx]}`);
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
