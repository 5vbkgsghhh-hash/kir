// СВЕРКА ПОДПИСИ НАРИСОВАННОГО С ПОДПИСЬЮ ПОКАЗАННОГО.
//
// Панель считает подпись из СВОИХ склеенных буферов, сервер — из того, что
// отправил. Совпадение имеет смысл только потому, что вычисления НЕЗАВИСИМЫ:
// повтори панель серверное значение — и подпись означала бы вежливость, а не
// равенство. Этот скрипт проверяет ровно независимость: он считает подпись по
// клиентскому коду и сверяет со значением из заголовка сцены.
//
//     node verify_shown.mjs <каталог-с-блобами> [<путь-к-scene-data.js>]

import { readFileSync } from "node:fs";

const dir = process.argv[2] || "/tmp";
const module_path = process.argv[3]
  || "/opt/kukai-rebuild1/assets/viewer/scene-data.js";
const { parseScene, mergeScenes, shownDigest } = await import(module_path);

const ab = (name) => {
  const b = readFileSync(`${dir}/${name}`);
  return b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength);
};

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
// ГЛАВНАЯ ПРОВЕРКА: подпись СКЛЕЙКИ обязана равняться подписи, накопленной
// витриной после базы и хвоста. Если бы склейка меняла порядок, теряла поле
// или брала чужую геометрию по слоту — совпасть было бы нечему.
await check("склейка база+хвост", mergeScenes(base, delta),
            delta.header.shown_digest);
// И она же обязана равняться подписи ЦЕЛОЙ сцены того же состояния: путь не
// должен влиять на подпись, иначе «что видел» зависело бы от того, как оно
// доехало.
await check("склейка == целое-после", mergeScenes(base, delta),
            whole.header.shown_digest);

console.log(bad === 0
  ? "  ok ПОДПИСЬ НАРИСОВАННОГО РАВНА ПОДПИСИ ПОКАЗАННОГО"
  : `  x расхождений: ${bad}`);
process.exit(bad ? 1 : 0);
