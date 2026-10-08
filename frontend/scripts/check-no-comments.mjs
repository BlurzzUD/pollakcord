import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

import ts from "typescript";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const SKIP = new Set(["node_modules", "dist", "coverage"]);

function walk(directory, files = []) {
  for (const name of readdirSync(directory)) {
    if (SKIP.has(name)) {
      continue;
    }
    const path = join(directory, name);
    if (statSync(path).isDirectory()) {
      walk(path, files);
    } else {
      files.push(path);
    }
  }
  return files;
}

function scriptKind(path) {
  return path.endsWith(".tsx") ? ts.ScriptKind.TSX : path.endsWith(".mjs") || path.endsWith(".js") ? ts.ScriptKind.JS : ts.ScriptKind.TS;
}

function lineOf(text, position) {
  return text.slice(0, position).split("\n").length;
}

function commentsInScript(path, text) {
  const source = ts.createSourceFile(path, text, ts.ScriptTarget.Latest, true, scriptKind(path));
  const found = new Set();
  const visit = (node) => {
    for (const range of ts.getLeadingCommentRanges(text, node.pos) ?? []) {
      found.add(lineOf(text, range.pos));
    }
    for (const range of ts.getTrailingCommentRanges(text, node.end) ?? []) {
      found.add(lineOf(text, range.pos));
    }
    node.getChildren(source).forEach(visit);
  };
  visit(source);
  return [...found];
}

export function findComments() {
  const offenders = [];
  for (const path of walk(root)) {
    const shown = relative(root, path);
    const text = readFileSync(path, "utf8");
    if (/\.(ts|tsx|mjs|js)$/.test(path)) {
      commentsInScript(path, text).forEach((line) => offenders.push(`${shown}:${line}`));
    } else if (path.endsWith(".css")) {
      text.split("\n").forEach((line, index) => /\/\*/.test(line) && offenders.push(`${shown}:${index + 1}`));
    } else if (path.endsWith(".html") || path.endsWith(".svg")) {
      text.split("\n").forEach((line, index) => /<!--/.test(line) && offenders.push(`${shown}:${index + 1}`));
    }
  }
  return offenders;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const offenders = findComments();
  if (offenders.length > 0) {
    console.error(`Comments are not allowed:\n${offenders.join("\n")}`);
    process.exit(1);
  }
  console.log("No comments found.");
}
