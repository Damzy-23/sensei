// Display names for catalogue values (the data keeps short lower-case keys).
const PATTERN_NAMES: Record<string, string> = {
  dp: "Dynamic programming",
  "bit manipulation": "Bit manipulation",
  "union find": "Union-find",
  "hash map": "Hash map",
};

export function patternName(key: string): string {
  return PATTERN_NAMES[key.toLowerCase()] ?? key.charAt(0).toUpperCase() + key.slice(1);
}
