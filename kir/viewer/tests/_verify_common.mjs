// ONE CARRIER OF THE ADDRESS AND ONE KIND OF REFUSAL FOR FOUR JS VERIFIERS.
//
// 🔴 WHY THIS WAS CREATED (29.08.2026). Four instruments
// (`verify_shown/verify_mesh/verify_partial/verify_merge`) carried a SILENT
// DEFAULT on both inputs:
//
//     const dir = process.argv[2] || "/tmp";
//     const module_path = process.argv[3] || "<product tree address>";
//
// (the product address is deliberately NOT reproduced verbatim here: a removed
//  literal left in an example is still the same literal, and the next
//  sweep will find it just the same way. The live address is known by a single carrier on the
//  Python side, `_client_asset.py`.)
//
// and both defaults are of the very kind this whole corner of the
// tree was written against.
//
// FIRST: AN ADDRESS INTO SOMEONE ELSE'S TREE. KIR is environment-agnostic; a path into KUKAI, hardcoded
// as a string, turns the instrument into a judge of SOMEONE ELSE'S copy while posing as its own — silently.
// The Python half already cured this and set up a SINGLE carrier
// (`_client_asset.py`, docstring: “A single carrier exists precisely so that
// there is no third time”). There were, in fact, FIVE carriers: it, and these four
// literals it never saw. The KIR↔product boundary guard counts IMPORTS
// and, BY CONSTRUCTION, does not see a string path (filed as `E-32`).
//
// SECOND, AND IT COSTS MORE: `|| "/tmp"`. Measured 29.08.2026 on this machine —
// `node verify_shown.mjs` WITH NO ARGUMENTS ran to completion with exit code 0 and printed
// “ok THE SIGNATURE OF WHAT WAS DRAWN EQUALS THE SIGNATURE OF WHAT WAS SHOWN”, having read
// `/tmp/d_base.bin`, `/tmp/d_delta.bin`, `/tmp/d_whole.bin` — files from 11.08,
// owner `root`, left behind by SOMEONE ELSE'S run 18 days earlier. The instrument was correct
// and was speaking ABOUT A DIFFERENT SUBJECT, and said nothing of it in any line.
//
// WHAT WAS DONE. There are no defaults: an unnamed input makes the instrument REFUSE and name
// the reason. This does not change the instrument's answer (it could not answer about
// what it was never given, even before) — SILENCE now has a REASON that can be interrogated,
// exactly as with `install_paths.install_root_refusal` and
// `viewer/scene.corpus_unreachable_reason`.
//
// 🔴 EXIT CODE 2, NOT 1, AND THIS IS NOT DECORATION. `1` already means “the check
// DID happen and the two sides diverged” — the very thing the instrument was written for, and neighboring
// tests' behavioral controls turn red on it. `2` means “the check did NOT
// happen”: the next move is different (name the directory, name the module), and merging the two
// would make the exit code useless exactly where branching depends on it.
// The same distinction as the one set up today for `snapshot_janitor --verify`.

export const СВЕРКА_НЕ_СОСТОЯЛАСЬ = 2;

export function refuse(why) {
  console.log("🔴 СВЕРКА НЕ СОСТОЯЛАСЬ: " + why);
  process.exit(СВЕРКА_НЕ_СОСТОЯЛАСЬ);
}

//: The directory with the blobs. Named — or a refusal; there is no default.
export function blobsDir(tool) {
  const dir = process.argv[2];
  if (!dir)
    refuse(`каталог с блобами не назван. СЛЕДУЮЩИЙ ХОД: `
           + `node ${tool} <каталог-с-блобами> <путь-к-scene-data.js>. `
           + `Умолчания /tmp здесь БОЛЬШЕ НЕТ намеренно: оно давало зелёный `
           + `вердикт о файлах, которые положил кто-то другой и когда-то`);
  return dir;
}

//: The path to the showroom's client module. Named — or a refusal. A fallback path into
//: someone else's tree is NOT substituted here: it is known by a single carrier on the
//: Python side (`_client_asset.scene_data_js`), and it is the one that says WHERE the
//: file came from — “its own tree” or “FALLBACK PATH — KUKAI's prod”. An instrument that
//: fails to make this distinction bears witness to someone else's copy while posing as its own.
export function clientModulePath(tool) {
  const p = process.argv[3];
  if (!p)
    refuse(`путь к клиентскому scene-data.js не назван. В дереве KIR этого `
           + `файла НЕТ ВОВСЕ — клиентская половина витрины живёт в продукте, `
           + `и подставлять её адрес молча значило бы судить чужую копию под `
           + `видом своей. СЛЕДУЮЩИЙ ХОД: назвать путь третьим аргументом; `
           + `питоновский носитель адреса — kir/viewer/tests/_client_asset.py, `
           + `он же скажет, СВОЁ это дерево или запасной путь`);
  return p;
}

//: Reading a blob. “The file is missing” is a fact ABOUT THE RIG, not about the merge, and a bare
//: node traceback does not name it: the reader sees `ERR_ENOENT` and does not know
//: whether the check did not happen or whether it diverged.
export function readBlob(readFileSync, dir, name) {
  let b;
  try {
    b = readFileSync(`${dir}/${name}`);
  } catch (e) {
    refuse(`${name} не лежит в ${dir} (${e.code || e.message}) — это факт о `
           + `СТЕНДЕ, а не о склейке. Блобы кладёт питоновский спутник прибора`);
  }
  return b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength);
}

//: Loading the client module. A missing file is again “did not happen”.
export async function importClient(path) {
  try {
    return await import(path);
  } catch (e) {
    refuse(`клиентский модуль не загрузился: ${path} — ${e.code || e.message}`);
  }
}

//: A BODY'S RANGE — UP TO THE SLOT OF THE NEXT ELEMENT IN THE SAME STREAM.
//
// 🔴 WHY (VJ-03, 29.08.2026). A capsule, a prism, and a mesh occupy a
// VARIABLE number of chunks in their buffers: a five-segment polyline has five of them.
// The server signs ALL of them (`codec._record` takes a slice up to the END of the stream and states
// outright: “signing only the first one would mean missing that half of the
// polyline vanished”), and so does the client (`scene-data.js`, the `nextSlot` table).
// A checker that takes EXACTLY ONE chunk is weaker than what it checks: for a polyline
// it would compare the first segment and declare equality while four were lost.
//
// The traversal repeats the client's VERBATIM. “To the end of the stream”, as on the server,
// cannot be used here: on the client the buffers are MERGED, and “to the end” would capture someone else's
// bodies.
export function nextSlotOf(d) {
  const n = d.header.elements;
  const K = d.header.kinds;
  const nxt = new Int32Array(n).fill(-1);
  let lastCap = -1, lastPrism = -1, lastMesh = -1;
  for (let i = 0; i < n; i++) {
    if (d.kind[i] === K.capsule) {
      if (lastCap >= 0) nxt[lastCap] = d.slot[i];
      lastCap = i;
    } else if (d.kind[i] === K.prism) {
      if (lastPrism >= 0) nxt[lastPrism] = d.slot[i];
      lastPrism = i;
    } else if (K.mesh !== undefined && d.kind[i] === K.mesh) {
      if (lastMesh >= 0) nxt[lastMesh] = d.slot[i];
      lastMesh = i;
    }
  }
  if (lastCap >= 0) nxt[lastCap] = d.capsule.length / 7;
  if (lastPrism >= 0) nxt[lastPrism] = d.prismZ.length / 2;
  if (lastMesh >= 0) nxt[lastMesh] = d.meshOfs.length - 1;
  return nxt;
}
