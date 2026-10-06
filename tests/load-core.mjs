import { readFileSync } from "node:fs";

const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
const m = html.match(/\/\/ @food-core-start([\s\S]*?)\/\/ @food-core-end/);
if (!m) throw new Error("food core block not found in index.html");
const body = m[1];
const names = [...body.matchAll(/^(?:async\s+function|function|const)\s+(\w+)/gm)].map(x => x[1]);
export const core = new Function(`"use strict";\n${body}\nreturn { ${names.join(", ")} };`)();
