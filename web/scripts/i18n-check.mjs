// Lists the Vietnamese strings in src/ that have no English in src/en.ts, and the English entries nothing uses.
// Strings are read the way the code writes them: tr("…") calls and tv`…` templates, where each ${…} becomes {n}.
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

const SRC = new URL("../src/", import.meta.url).pathname;
const files = readdirSync(SRC).filter((f) => /\.tsx?$/.test(f) && !["en.ts", "i18n.ts"].includes(f));

const used = new Map();
function template(s, from) {
  let key = "", n = 0, stack = [];
  for (let i = from; i < s.length; i++) {
    const c = s[i];
    if (!stack.length) {
      if (c === "`") return { key, end: i };
      if (s.startsWith("${", i)) { stack.push("}"); key += `{${n++}}`; i++; continue; }
      key += c;
    } else if (c === "`") stack[stack.length - 1] === "`" ? stack.pop() : stack.push("`");
    else if (stack[stack.length - 1] !== "`") { if (c === "{") stack.push("}"); else if (c === "}") stack.pop(); }
  }
  return { key, end: s.length };
}
for (const f of files) {
  const s = readFileSync(join(SRC, f), "utf8");
  for (const m of s.matchAll(/\btr\("((?:[^"\\]|\\.)*)"\)/g)) used.set(JSON.parse(`"${m[1]}"`), f);
  for (let i = s.indexOf("tv`"); i >= 0; i = s.indexOf("tv`", i + 3)) { const { key } = template(s, i + 3); used.set(key, f); }
}

const en = new Set();
for (const m of readFileSync(join(SRC, "en.ts"), "utf8").matchAll(/^\s*"((?:[^"\\]|\\.)*)": "/gm)) en.add(JSON.parse(`"${m[1]}"`));

const missing = [...used].filter(([k]) => !en.has(k));
const unused = [...en].filter((k) => !used.has(k));
for (const [k, f] of missing) console.log(`missing (${f}): ${JSON.stringify(k)}`);
for (const k of unused) console.log(`unused: ${JSON.stringify(k)}`);
console.log(`${used.size} strings, ${missing.length} without English, ${unused.length} English entries unused`);
process.exit(missing.length ? 1 : 0);
