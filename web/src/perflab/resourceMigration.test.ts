// Migration ratchet for the B3 resource-state sweep.
//
// `useLegacyAuthedResource` is condemned infrastructure: it exists only so the
// files not yet migrated to the canonical AuthedResource contract keep building.
// This test is the mechanism that stops it becoming a permanent compatibility
// path — it fails when a new consumer appears, when a migrated file reintroduces
// it, and when the adapter itself outlives the last consumer.
//
// To migrate a file: convert it, then DELETE its line from UNMIGRATED below.
// When the list is empty, this test fails until the adapter is deleted too.
import { readdirSync, readFileSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = join(__dirname, "..");
const HOOK_FILE = join(__dirname, "useAuthedResource.ts");

/**
 * The exact set of files still on the legacy adapter. Shrinks, never grows.
 *
 * IT IS NOW EMPTY, and that is the terminal state: the sweep is complete and the
 * adapter has been deleted from useAuthedResource.ts. The second test below
 * enforces that deletion, so this list can never be repopulated to bring the
 * adapter back — a new legacy consumer fails the first test, and restoring the
 * adapter to satisfy it fails the second.
 */
const UNMIGRATED: string[] = [];

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) return sourceFiles(full);
    return /\.tsx?$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name) ? [full] : [];
  });
}

function importsLegacyAdapter(file: string): boolean {
  return /useLegacyAuthedResource/.test(readFileSync(file, "utf8"));
}

/**
 * Code only — a migrated file may legitimately name the retired idiom in a
 * comment explaining why it is gone. Truncates at `//` inside string literals
 * too, which can only make this guard less strict, never falsely accusing.
 */
function code(file: string): string {
  return readFileSync(file, "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/\/\/.*$/gm, "");
}

const consumers = sourceFiles(SRC)
  .filter((f) => f !== HOOK_FILE)
  .filter(importsLegacyAdapter)
  .map((f) => relative(SRC, f).split(sep).join("/"))
  .sort();

describe("legacy resource adapter is condemned, not load-bearing", () => {
  it("has no consumers beyond the enumerated unmigrated files", () => {
    // A new import here means a file skipped the canonical contract.
    expect(consumers).toEqual([...UNMIGRATED].sort());
  });

  it("is deleted once the last consumer migrates", () => {
    if (UNMIGRATED.length > 0) return;
    const hook = readFileSync(HOOK_FILE, "utf8");
    expect(hook).not.toMatch(/useLegacyAuthedResource|toLegacyResource|interface Resource</);
  });
});

describe("migrated files do not reconstruct the state machine", () => {
  const migrated = sourceFiles(SRC)
    .filter((f) => f !== HOOK_FILE)
    .filter((f) => !importsLegacyAdapter(f))
    .filter((f) => /useAuthedResource/.test(readFileSync(f, "utf8")));

  it("contains no `loading || data === null` dance", () => {
    const offenders = migrated.filter((f) => {
      const src = code(f);
      return /\bloading\s*\|\|\s*\w+\s*===\s*null/.test(src) || /\w+\s*===\s*null\s*\|\|\s*\bloading\b/.test(src);
    });
    expect(offenders.map((f) => relative(SRC, f))).toEqual([]);
  });

  it("reads resource state through the union, never a `.data ?? fallback` chain", () => {
    const offenders = migrated.filter((f) => /\.data\s*\?\?/.test(code(f)));
    expect(offenders.map((f) => relative(SRC, f))).toEqual([]);
  });
});
