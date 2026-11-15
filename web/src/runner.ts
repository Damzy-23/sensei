// Runs the student's Python in the browser with Pyodide and checks it against the visible tests.
// Nothing is sent to a server; only the pass/fail summary is reported to the API.

import type { VisibleTest } from "./api";

const PYODIDE_URL = "https://cdn.jsdelivr.net/pyodide/v0.27.1/full/pyodide.js";

interface Pyodide {
  runPythonAsync(code: string): Promise<unknown>;
  globals: { set(name: string, value: unknown): void };
}
declare global {
  interface Window { loadPyodide?: () => Promise<Pyodide> }
}

export interface TestResult { name: string; passed: boolean; message: string }
export interface RunResult { results: TestResult[]; runtimeMs: number }

let pyodide: Promise<Pyodide> | null = null;

function load(): Promise<Pyodide> {
  pyodide ??= new Promise<Pyodide>((resolve, reject) => {
    const script = document.createElement("script");
    script.src = PYODIDE_URL;
    script.onload = () => window.loadPyodide!().then(resolve, reject);
    script.onerror = () => reject(new Error("Could not load the Python runtime."));
    document.head.appendChild(script);
  });
  pyodide.catch(() => { pyodide = null; });
  return pyodide;
}

// Each test's `input` is keyword arguments ("nums=[2,7,11,15], target=9"); `expected` is a Python literal.
// A list answer is accepted in any order, as the problem statements allow.
const HARNESS = `
import ast, json, traceback

def _same(got, want):
    if got == want:
        return True
    if isinstance(got, (list, tuple)) and isinstance(want, (list, tuple)):
        try:
            return sorted(got) == sorted(want)
        except TypeError:
            return False
    return False

def _run(source, entry, tests):
    scope = {}
    try:
        exec(source, scope)
    except Exception:
        message = traceback.format_exc(limit=1).strip().splitlines()[-1]
        return [{"name": t["name"], "passed": False, "message": message} for t in tests]
    fn = scope.get(entry)
    if not callable(fn):
        return [{"name": t["name"], "passed": False, "message": f"function {entry} is not defined"} for t in tests]
    out = []
    for t in tests:
        try:
            got = fn(**eval("dict(" + t["input"] + ")", {}))
            want = ast.literal_eval(t["expected"])
            ok = _same(got, want)
            out.append({"name": t["name"], "passed": ok, "message": "" if ok else f"expected {t['expected']}, got {got!r}"})
        except Exception as exc:
            out.append({"name": t["name"], "passed": False, "message": f"{type(exc).__name__}: {exc}"})
    return out

json.dumps(_run(_source, _entry, json.loads(_tests)))
`;

export function entryPoint(starterCode: string): string | null {
  return /def\s+(\w+)\s*\(/.exec(starterCode)?.[1] ?? null;
}

export async function runTests(source: string, entry: string, tests: VisibleTest[]): Promise<RunResult> {
  const py = await load();
  py.globals.set("_source", source);
  py.globals.set("_entry", entry);
  py.globals.set("_tests", JSON.stringify(tests));
  const started = performance.now();
  const raw = await py.runPythonAsync(HARNESS);
  return { results: JSON.parse(String(raw)) as TestResult[], runtimeMs: Math.round(performance.now() - started) };
}

const MAX_OUTPUT = 2000;

// Runs the code as written and captures what it prints. The code is not changed or sent anywhere.
const CAPTURE = `
import io, json, traceback
from contextlib import redirect_stdout

def _capture(source):
    out = io.StringIO()
    error = None
    try:
        with redirect_stdout(out):
            exec(source, {"__name__": "__main__"})
    except Exception:
        error = traceback.format_exc(limit=2).strip().splitlines()[-1]
    return {"stdout": out.getvalue(), "error": error}

json.dumps(_capture(_source))
`;

export interface CodeOutput { stdout: string; error: string | null; truncated: boolean }

export async function runCode(source: string): Promise<CodeOutput> {
  const py = await load();
  py.globals.set("_source", source);
  const { stdout, error } = JSON.parse(String(await py.runPythonAsync(CAPTURE))) as { stdout: string; error: string | null };
  return { stdout: stdout.slice(0, MAX_OUTPUT), error, truncated: stdout.length > MAX_OUTPUT };
}
