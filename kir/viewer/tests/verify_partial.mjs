// “TAIL” AFTER THE MERGE IS A PROPERTY OF THE ACCUMULATED STATE, NOT OF THE LAST RESPONSE.
//
// FOUND 16.08.2026 ON THE OWNER'S LIVE TURN, AND THE PRICE WAS — THE WHOLE PRODUCT.
// The server honestly sets `partial = since > 0` (`live_scene.py:243`): the tail of the
// journal lives in THESE bytes. The merge took the header wholesale from the delta, and
// the truth about the RESPONSE turned into a lie about the SCENE: a client that started with `since=0` and
// applied every delta holds the WHOLE building, yet said of itself “I am a tail”.
// This killed the “Send to Revit” button BY CONSTRUCTION: a live session starts
// with a `since=0` frame, deltas follow, and the VERY FIRST one — even an empty one — set
// the flag forever. To a human, the `PARTIAL_SCENE` refusal (`transfer.py:610`)
// read as “the screen shows a journal TAIL… request the whole scene”, and there was
// no one to make that request.
//
// WHAT THIS INSTRUMENT DOES NOT DO. It does not check the merge's geometry — that is the job of
// `verify_merge.mjs`, and repeating it here would mean setting up a second place where
// one answer lives. There is exactly one question here: HONESTY ABOUT COMPLETENESS.
//
// Run it (the blobs are dropped by `test_delta.py`):
//     node verify_partial.mjs <blobs-directory> <path-to-scene-data.js>   (BOTH required)
// Exit code 0 — the flag comes out correct; 1 — discrepancies are named line by line.

import { readFileSync } from "node:fs";
// 🔴 ONE CARRIER OF THE ADDRESS AND ONE KIND OF REFUSAL FOR FOUR VERIFIERS.
// There used to be TWO silent defaults here — `|| "/tmp"` and a hardcoded
// path into the product tree; both are removed, the full argument lives in
// `_verify_common.mjs`. In short: KIR is environment-agnostic, and a green
// verdict about someone else's files is worse than no verdict at all.
import { blobsDir, clientModulePath, readBlob, importClient }
  from "./_verify_common.mjs";

const dir = blobsDir("verify_partial.mjs");
const module_path = clientModulePath("verify_partial.mjs");
const { parseScene, mergeScenes } = await importClient(module_path);

const ab = (name) => readBlob(readFileSync, dir, name);

let bad = 0;
const fail = (m) => { console.log("  x " + m); bad++; };
const ok = (m) => console.log("  ok " + m);

const base = parseScene(ab("d_base.bin"));
const delta = parseScene(ab("d_delta.bin"));

// ── PRECONDITIONS. The instrument must prove it is measuring THE right subject: if the server
// stops flagging a delta as a tail, the test below would turn green about nothing.
if (base.header.partial !== false)
  fail(`база (since=0) обязана быть НЕ хвостом, а пришла partial=${base.header.partial}`);
else ok("база честно не хвост");
if (delta.header.partial !== true)
  fail(`дельта обязана быть хвостом, а пришла partial=${delta.header.partial}`);
else ok("дельта честно хвост");

// ── THE MAIN POINT. Whole + tail = whole.
const merged = mergeScenes(base, delta);
if (merged.header.partial !== false)
  fail("склейка ЦЕЛОГО с хвостом объявила себя хвостом: "
     + `partial=${merged.header.partial}. Кнопка переноса мертва по построению`);
else ok("склейка целого с хвостом — не хвост");

if (merged.header.partial === false && merged.header.partial_ru)
  fail(`не хвост, но объяснение хвоста осталось: «${merged.header.partial_ru}»`);
else ok("объяснение согласовано с признаком");

// ── A SECOND DELTA IN A ROW changes nothing: completeness does not “wear out”.
const twice = mergeScenes(merged, delta);
if (twice.header.partial !== false)
  fail("вторая дельта подряд сделала целое хвостом");
else ok("вторая дельта подряд полноту не портит");

// ── THE OPPOSITE POLE, WITHOUT WHICH THE FIX WOULD REDUCE TO “ALWAYS WHOLE”.
// Eviction is the only reason an honest cursor can still yield
// something incomplete: no one will ever send the client those programs again.
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

// ── AND A BASE-PLUS-TAIL STAYS A TAIL. A client that did not start from zero does not have the whole.
const fromTail = mergeScenes(delta, delta);
if (fromTail.header.partial !== true)
  fail("склейка, начатая ОТ ХВОСТА, объявила себя целой");
else ok("начатое от хвоста остаётся хвостом");

console.log(bad ? `РАСХОЖДЕНИЙ: ${bad}` : "признак полноты выводится верно");
process.exit(bad ? 1 : 0);
