// src/testing/importGraph.ts
//
// THE SHARED WALKER BEHIND EVERY STATIC HONESTY ORACLE.
//
// Extracted verbatim from overviewBoundary.test.ts (map #182, #189b) when #199 needed
// the same mechanism for the workout-log submit path. Two divergent copies of an
// honesty guard is itself a defect: the copies drift, and the weaker one becomes the
// one nobody notices is vacuous.
//
// Sharing is only safe because EVERY caller keeps its own POSITIVE CONTROL — a case
// that must still be found. If this module ever stops walking, each guard's control
// goes red independently, so a silent shared failure cannot make all of them pass
// vacuously. Do not add a caller without a positive control.
//
// Resolution is done by the TypeScript compiler API against the real tsconfig, so
// path aliases (`@/*`), extensionless specifiers, `.ts`/`.tsx` selection, index
// barrels, re-exports, dynamic `import()`, and `import =`/`require` all resolve the
// way the build resolves them. The forbidden set is a set of CANONICAL RESOLVED
// PATHS — never a filename pattern like `*sim*`, which would both miss a renamed
// fixture module and falsely accuse an innocent file named `similarity.ts`.
//
// TYPE-ONLY EDGES ARE NOT EDGES. `import type { CheckinState } from "./sim"` is
// erased at build time and carries no fixture data. Counting it would make a guard
// permanently red for a reason that has nothing to do with honesty.
import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import ts from "typescript";

export const WEB_ROOT = resolve(__dirname, "../..");
export const SRC = join(WEB_ROOT, "src");

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
export function valueImportsOf(file: string): string[] {
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
export function resolveLocal(specifier: string, containingFile: string): string | null {
  const res = ts.resolveModuleName(specifier, containingFile, OPTIONS, ts.sys);
  const file = res.resolvedModule?.resolvedFileName;
  if (!file) return null;
  const canonical = resolve(file);
  if (!canonical.startsWith(SRC)) return null; // node_modules / lib
  if (canonical.includes(`${join("node_modules")}`)) return null;
  return canonical;
}

export interface Reach {
  reached: boolean;
  chain: string[];
}

/**
 * Breadth-first walk from `roots`, stopping at the first forbidden module and
 * returning the full import chain that got there.
 */
export function findForbidden(roots: string[], forbidden: Set<string>): Reach {
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

/** `src`-relative path helper. */
export const p = (...parts: string[]) => join(SRC, ...parts);
