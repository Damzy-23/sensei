// Test helper: load one dependency-free TypeScript module in plain Node.
// It is transpiled in memory with the TypeScript the project already has, so the tests
// (node --test) need no test framework and no build step. The module must import nothing.

import { readFileSync } from "node:fs";
import ts from "typescript";

export async function loadTs(url) {
  const source = readFileSync(url, "utf8");
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  });
  return import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);
}
