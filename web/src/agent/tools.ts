// Page tools: the typed actions an agent (voice or text) may take on the UI.
//
// A screen registers handlers for the tools it can serve; an agent runtime calls `invoke`.
// Tools change React state through those handlers. They never click or scrape the DOM,
// so the agent can only do what a screen has chosen to expose.

import type { Mode } from "../api";
import type { PageId } from "../app-context";
import pageTools from "./page-tools.json";

export interface PageSnapshot {
  page: PageId;
  mode: Mode;
  problem: { id: string; title: string; pattern: string; difficulty: string } | null;
  hintLevel: number;
  failedRuns: number;
  escalated: boolean;
  lastTestRun: { passed: number; failed: number } | null;
}

/** Name -> [arguments, result]. Adding a tool here is the only way to give an agent a new ability. */
export interface ToolSignatures {
  get_page_state: [Record<string, never>, PageSnapshot];
  navigate: [{ page: PageId }, { page: PageId }];
  set_mode: [{ mode: Mode }, { mode: Mode }];
  open_problem: [{ problem_id: string }, { problem_id: string }];
  ask_coach: [{ text: string }, { reply: string; hint_level: number; escalated: boolean }];
  run_tests: [Record<string, never>, { passed: number; failed: number; total: number }];
  highlight_lines: [{ from: number; to: number; note: string }, { from: number; to: number }];
  clear_highlight: [Record<string, never>, Record<string, never>];
}
export type ToolName = keyof ToolSignatures;
export type ToolHandler<N extends ToolName> = (args: ToolSignatures[N][0]) => Promise<ToolSignatures[N][1]> | ToolSignatures[N][1];
export type ToolResult<N extends ToolName> = { ok: true; data: ToolSignatures[N][1] } | { ok: false; error: string };

/** Tool descriptions and parameters, written for the model. The same file defines the tools
 *  on the voice agent (scripts/create_voice_agent.py), so the two cannot drift apart. */
export const TOOL_SPECS = pageTools as Record<ToolName, { description: string; parameters: Record<string, unknown> }>;
export const TOOL_NAMES = Object.keys(pageTools) as ToolName[];

const handlers = new Map<ToolName, ToolHandler<ToolName>>();

/** Register a handler. Returns a function that removes it, for use as an effect cleanup. */
export function registerTool<N extends ToolName>(name: N, handler: ToolHandler<N>): () => void {
  handlers.set(name, handler as unknown as ToolHandler<ToolName>);
  return () => { if (handlers.get(name) === (handler as unknown)) handlers.delete(name); };
}

/** Call a tool. Never throws: a failure comes back as `{ ok: false, error }` for the agent to read. */
export async function invoke<N extends ToolName>(name: N, args: ToolSignatures[N][0]): Promise<ToolResult<N>> {
  const handler = handlers.get(name) as ToolHandler<N> | undefined;
  if (!handler) return { ok: false, error: `Tool ${name} is not available on this screen.` };
  try {
    return { ok: true, data: await handler(args) };
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) };
  }
}

export const availableTools = (): ToolName[] => [...handlers.keys()];
