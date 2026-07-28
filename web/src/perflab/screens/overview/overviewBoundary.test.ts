// src/perflab/screens/overview/overviewBoundary.test.ts
//
// THE STATIC HALF OF THE OVERVIEW HONESTY ORACLE (map #182, #189b).
//
// Claim under test: starting from the authenticated Overview roots and following
// every value-carrying import edge transitively, no fixture module is reachable.
//
// Why this and not the alternatives, both of which were ruled out in #189:
//   - ESLint cannot enforce it. `.github/workflows/ci.yml:207-209` runs lint with
//     `continue-on-error: true`, and lint already exits 1 on three pre-existing
//     errors, so an ESLint rule would be a suggestion, not a gate.
//   - The B3 migration ratchet cannot enforce it. It matches `/\.data\s*\?\?/`,
//     which does not match Overview's actual fixture fallbacks (`.data?.score ??
//     null`), so migrating the file would have turned every check green while all
//     five leaks survived.
//
// Resolution is done by the TypeScript compiler API against the real tsconfig, so
// path aliases (`@/*`), extensionless specifiers, `.ts`/`.tsx` selection, index
// barrels, re-exports, dynamic `import()`, and `import =`/`require` all resolve the
// way the build resolves them. The forbidden set is a set of CANONICAL RESOLVED
// PATHS — never a filename pattern like `*sim*`, which would both miss a renamed
// fixture module and falsely accuse an innocent file named `similarity.ts`.
//
// TYPE-ONLY EDGES ARE NOT EDGES. `import type { CheckinState } from "./sim"` is
// erased at build time and carries no fixture data. Counting it would make the
// guard permanently red for a reason that has nothing to do with honesty.
import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import ts from "typescript";
import { describe, expect, it } from "vitest";

const WEB_ROOT = resolve(__dirname, "../../../..");
const SRC = join(WEB_ROOT, "src");

/** Compiler options from the real tsconfig, so alias resolution matches the build. */
function compilerOptions(): ts.CompilerOptions {
  const configPath = join(WEB_ROOT, "tsconfig.json");
  const read = ts.readConfigFile(configPath, ts.sys.readFile);
  if (read.error) throw new Error(`Cannot read tsconfig.json: ${read.error.messageText}`);
  const parsed = ts.parseJsonConfigFileContent(read.config, ts.sys, WEB_ROOT, undefined, configPath);
  return parsed.options;
}

const OPTIONS = compilerOptions();

/**
 * Every module specifier in `file` that survives to runtime.
 *
 * Uses the real parser rather than a regex, because the distinction that matters
 * here — type-only versus value — is a syntactic property a regex cannot see.
 */
function valueImportsOf(file: string): string[] {
  const text = readFileSync(file, "utf8");
  const sf = ts.createSourceFile(file, text, ts.ScriptTarget.ESNext, true,
    file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  const out: string[] = [];

  const literal = (node: ts.Expression | undefined): string | null =>
    node && ts.isStringLiteral(node) ? node.text : null;

  const visit = (node: ts.Node): void => {
    // import ... from "x"  /  import "x"
    if (ts.isImportDeclaration(node)) {
      const clause = node.importClause;
      const typeOnly =
        clause?.isTypeOnly === true ||
        (clause?.namedBindings !== undefined &&
          ts.isNamedImports(clause.namedBindings) &&
          clause.namedBindings.elements.length > 0 &&
          clause.namedBindings.elements.every((e) => e.isTypeOnly));
      if (!typeOnly) {
        const s = literal(node.moduleSpecifier);
        if (s) out.push(s);
      }
    }
    // export ... from "x"
    else if (ts.isExportDeclaration(node) && node.moduleSpecifier) {
      const typeOnly =
        node.isTypeOnly ||
        (node.exportClause !== undefined &&
          ts.isNamedExports(node.exportClause) &&
          node.exportClause.elements.length > 0 &&
          node.exportClause.elements.every((e) => e.isTypeOnly));
      if (!typeOnly) {
        const s = literal(node.moduleSpecifier);
        if (s) out.push(s);
      }
    }
    // import x = require("y")
    else if (ts.isImportEqualsDeclaration(node) && ts.isExternalModuleReference(node.moduleReference)) {
      const s = literal(node.moduleReference.expression);
      if (s) out.push(s);
    }
    // import("x")  /  require("x")
    else if (ts.isCallExpression(node)) {
      const isDynamicImport = node.expression.kind === ts.SyntaxKind.ImportKeyword;
      const isRequire = ts.isIdentifier(node.expression) && node.expression.text === "require";
      if (isDynamicImport || isRequire) {
        const s = literal(node.arguments[0]);
        if (s) out.push(s);
      }
    }
    ts.forEachChild(node, visit);
  };

  visit(sf);
  return out;
}

/** Resolve a specifier to a canonical path inside src/, or null if external. */
function resolveLocal(specifier: string, containingFile: string): string | null {
  const res = ts.resolveModuleName(specifier, containingFile, OPTIONS, ts.sys);
  const file = res.resolvedModule?.resolvedFileName;
  if (!file) return null;
  const canonical = resolve(file);
  if (!canonical.startsWith(SRC)) return null; // node_modules / lib
  if (canonical.includes(`${join("node_modules")}`)) return null;
  return canonical;
}

interface Reach {
  reached: boolean;
  chain: string[];
}

/**
 * Breadth-first walk from `roots`, stopping at the first forbidden module and
 * returning the full import chain that got there.
 */
function findForbidden(roots: string[], forbidden: Set<string>): Reach {
  const parent = new Map<string, string | null>();
  const queue: string[] = [];
  for (const r of roots) {
    const c = resolve(r);
    if (!parent.has(c)) {
      parent.set(c, null);
      queue.push(c);
    }
  }

  while (queue.length) {
    const file = queue.shift() as string;
    for (const spec of valueImportsOf(file)) {
      const next = resolveLocal(spec, file);
      if (next === null || parent.has(next)) continue;
      parent.set(next, file);
      if (forbidden.has(next)) {
        // Rebuild the chain so the failure names every hop, not just the endpoint —
        // a laundering module in the middle is exactly what this must expose.
        const chain: string[] = [];
        let cur: string | null = next;
        while (cur) {
          chain.unshift(cur.slice(SRC.length + 1).split("\\").join("/"));
          cur = parent.get(cur) ?? null;
        }
        return { reached: true, chain };
      }
      queue.push(next);
    }
  }
  return { reached: false, chain: [] };
}

const p = (...parts: string[]) => join(SRC, ...parts);

// Every authenticated authority-bearing surface, not just the Overview screen.
//
// The Overview-only root set is exactly why the sidebar's block card shipped
// three hardcoded literals ("Mid-base", 42%, "Week 3 of 7 · build phase") to
// signed-in athletes with no macrocycle at all: the card is always-visible
// chrome, so the walk starting at AuthedOverview.tsx could never reach it.
// A surface belongs here if an authenticated athlete can see it and it can
// assert anything about their own data.
const AUTHED_ROOTS = [
  // Overview screen
  p("perflab", "screens", "overview", "AuthedOverview.tsx"),
  p("perflab", "screens", "overview", "overviewModel.ts"),
  p("perflab", "screens", "overview", "overviewLeaves.tsx"),
  // Always-visible chrome
  p("perflab", "sidebar", "AuthedSidebarBlock.tsx"),
  p("perflab", "sidebar", "sidebarBlockModel.ts"),
];

// DELIBERATELY NOT A ROOT: overlays/SessionPlayer.tsx.
//
// It imports PHASES from sim.ts (SessionPlayer.tsx:5) and that import is
// legitimate, because the player is a GUEST-ONLY surface: SessionPlayer.tsx:28
// is `if (token != null) return null`, so an authenticated athlete never sees
// it. Listing it here would fail this guard for a component that bears no
// authenticated authority, and the only way to "fix" that failure would be to
// break the guest preview. Its authenticated behaviour is proved by the
// rejection test over that boundary, not by import reachability.

const FIXTURE_MODULES = new Set([
  p("perflab", "sim.ts"),
  p("perflab", "screens", "overview", "GuestOverviewPreview.tsx"),
  p("perflab", "screens", "twin", "GuestTwinPreview.tsx"),
]);

describe("authenticated Overview cannot reach fixture data", () => {
  it("resolves the alias table from the real tsconfig", () => {
    // If alias resolution silently broke, every `@/...` edge would resolve to null
    // and the guard would pass by seeing almost no graph at all.
    const resolved = resolveLocal("@/types", AUTHED_ROOTS[0]);
    expect(resolved).toBe(p("types.ts"));
  });

  it("POSITIVE CONTROL: the walker does find a fixture module that IS reachable", () => {
    // The guest preview imports sim.ts directly and legitimately. If this stops
    // failing, the walker has stopped walking and the real assertion below is
    // passing vacuously.
    const guest = [p("perflab", "screens", "overview", "GuestOverviewPreview.tsx")];
    const hit = findForbidden(guest, new Set([p("perflab", "sim.ts")]));
    expect(hit.reached).toBe(true);
    expect(hit.chain[hit.chain.length - 1]).toBe("perflab/sim.ts");
  });

  it("reaches no fixture module from any authenticated Overview root", () => {
    const hit = findForbidden(AUTHED_ROOTS, FIXTURE_MODULES);
    const detail = hit.reached
      ? `\n\nForbidden module reachable from authenticated Overview.\nImport chain:\n  ${hit.chain.join("\n    -> ")}\n`
      : "";
    expect(hit.reached, detail).toBe(false);
  });
});
