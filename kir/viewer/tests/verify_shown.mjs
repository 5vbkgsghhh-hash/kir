// COMPARING THE SIGNATURE OF WHAT WAS DRAWN AGAINST THE SIGNATURE OF WHAT WAS SHOWN.
//
// The panel computes the signature from ITS OWN merged buffers, the server — from what it
// sent. The match is meaningful only because the two computations are INDEPENDENT:
// if the panel repeated the server's value, the signature would mean politeness, not
// equality. This script checks exactly that independence: it computes the signature from the
// client code and checks it against the value from the scene header.
//
//     node verify_shown.mjs <blobs-directory> <path-to-scene-data.js>   (BOTH required)

import { readFileSync } from "node:fs";
// 🔴 ONE CARRIER OF THE ADDRESS AND ONE KIND OF REFUSAL FOR FOUR VERIFIERS.
// There used to be TWO silent defaults here — `|| "/tmp"` and a hardcoded
// path into the product tree; both are removed, the full argument lives in
// `_verify_common.mjs`. In short: KIR is environment-agnostic, and a green
// verdict about someone else's files is worse than no verdict at all.
import { blobsDir, clientModulePath, readBlob, importClient }
  from "./_verify_common.mjs";

const dir = blobsDir("verify_shown.mjs");
const module_path = clientModulePath("verify_shown.mjs");
const { parseScene, mergeScenes, shownDigest } = await importClient(module_path);

const ab = (name) => readBlob(readFileSync, dir, name);

let bad = 0;
const check = async (label, data, expected) => {
  const got = await shownDigest(data);
  if (got === expected) console.log(`  ok ${label}: ${got.slice(0, 16)}…`);
  else { console.log(`  x ${label}: панель ${got.slice(0, 16)}… != сервер `
                     + `${String(expected).slice(0, 16)}…`); bad++; }
};

const base = parseScene(ab("d_base.bin"));
const delta = parseScene(ab("d_delta.bin"));
const whole = parseScene(ab("d_whole.bin"));

await check("целое (база)", base, base.header.shown_digest);
// THE MAIN CHECK: the MERGE's signature must equal the signature accumulated
// by the showroom after the base and the tail. If the merge reordered things, dropped a field,
// or took the wrong geometry for a slot, there would be nothing to match.
await check("склейка база+хвост", mergeScenes(base, delta),
            delta.header.shown_digest);
// And it must also equal the signature of the WHOLE scene in the same state: the path
// must not affect the signature, or “what was seen” would depend on how it
// arrived.
await check("склейка == целое-после", mergeScenes(base, delta),
            whole.header.shown_digest);

console.log(bad === 0
  ? "  ok ПОДПИСЬ НАРИСОВАННОГО РАВНА ПОДПИСИ ПОКАЗАННОГО"
  : `  x расхождений: ${bad}`);
process.exit(bad ? 1 : 0);
