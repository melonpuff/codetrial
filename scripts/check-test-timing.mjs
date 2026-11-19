#!/usr/bin/env node
// Rejects the timing shapes that made browser tests fail on loaded CI runners
// while passing on a laptop, so a new one cannot land unannounced.
//
// A wall-clock bound built from `Date.now() +` and held in a variable named
// like a deadline, limit, or expiry: it measures how busy the runner is, not
// the page. Wait with `until` or `animationsFinished` from
// tests/browser/wait.js, whose timeout is only a backstop that names what
// hung.
//
// A fixed sleep, `waitForTimeout(...)` or `setTimeout(resolve, N)` with N of
// 50 ms or more, with no comment in the three lines above it or on its line.
// A fixed sleep either proves an absence by outwaiting it (so it must say what
// is being outwaited) or papers over a race (so it must not be there).
//
// A wait that bounds a property the test has just set, such as
// `scrollTop = 900` followed by a wait for `scrollTop > 0`: the bound can hold
// on the value from before, so the wait returns before what follows the value
// has caught up. Wait for the value set, `=== 900`; `=== 1` after `= 900` is
// refused too. A reset the bound cannot meet carries `timing-ok:`.
//
// A bound that is deliberate carries `timing-ok:` and a reason in a comment on
// its line or the line above. Matching runs over the code with comments and
// string contents blanked, so a call split over several lines is still seen and
// quoted text neither triggers a finding nor passes for a comment or a marker.
// The scanner does not know regular-expression literals, so one holding a quote
// or a comment marker can blank the code after it; none of the tests does.
//
// The bound rule ties a wait only to an assignment right before it that runs
// first, at its level or in an awaited call's callback, and not on another
// page the file uses. It does not see a property read into a local, brackets
// two deep on the right, a value that is not a literal, a wait kept other than
// in a `const` or `let` or wrapped in more than one call, or a change made by
// a call such as `scrollTo()`.
// It guesses whether a function body runs from how the function is written:
// one passed to a call is assumed to run, even if the call only keeps it for
// later as `setTimeout` does, and one assigned to a name or written as a
// method is assumed not to. A few shapes fool the guess. A method whose
// parameter default calls something, `reset(x = f()) {`, or whose name is
// computed, `['reset']() {`, looks like code that runs, and a function wrapped
// in parentheses, `r = (function () { ... })`, looks like one passed to a call.
//
//   check-test-timing.mjs [DIR]    DIR defaults to tests/browser

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const dir = process.argv[2] ?? path.join(root, "tests", "browser");
const problems = [];

const bound =
  /\b\w*(?:deadline|limit|until|expir\w*|giveUp|stopAt)\w*\s*=\s*Date\.now\(\)\s*\+/gi;
const sleep =
  /\bwaitForTimeout\(|\bsetTimeout\(\s*(?:\w+|\(\s*\)\s*=>\s*\w+\(\s*\))\s*,\s*(?:[5-9]\d|\d{3,})\s*,?\s*\)/g;
// `.name =` but not `==`, `===`, `=>` or a compound `+=`.
const assignment = /\.(\w+)\s*=(?![=>])/g;
const waitCall = /\b(?:waitForFunction|reaches|until)\s*\(/g;
// What may stand between an assignment and the wait tied to it: the rest of
// its statement, closing brackets and the wait's own `const x = await page.`,
// or the call it is the first argument of, `assert.equal(await reaches(`.
const follows =
  /^[\s;,]*(?:(?:const|let)\s+[\w$]+\s*=\s*)?(?:[\w$.]+\s*\(\s*)?(?:await\s+)?(?:[\w$]+\s*\.\s*)*$/;
const tied = new RegExp(String.raw`^[^;]*;${follows.source.slice(1)}`);
// A file without any of these cannot produce a finding.
const relevant =
  /Date\.now|waitForTimeout|setTimeout|waitForFunction|reaches|until/;

// The offset of the parenthesis closing the one at `open`.
function closing(code, open) {
  let depth = 0;
  for (let i = open; i < code.length; i++) {
    if (code[i] === "(") depth++;
    else if (code[i] === ")" && --depth === 0) return i;
  }
  return code.length;
}

// The argument at `index` of the call whose parenthesis opens at `open`, split
// at the commas directly inside it, or "" when the call has fewer arguments.
function argument(code, open, index) {
  const end = closing(code, open);
  let depth = 0;
  let start = open + 1;
  let at = 0;
  for (let i = start; i < end; i++) {
    if ("([{".includes(code[i])) depth++;
    else if (")]}".includes(code[i])) depth--;
    else if (code[i] === "," && depth === 0) {
      if (at === index) return code.slice(start, i);
      at++;
      start = i + 1;
    }
  }
  return at === index ? code.slice(start, end) : "";
}

// A bracketed group one level deep, and what may follow a name.
const group = String.raw`\((?:[^()]|\([^()]*\))*\)`;
const members = String.raw`(?:\s*(?:\.\s*[\w$]+|${group}|\[[^\]]*\]))*`;
const awaitedCall = new RegExp(String.raw`\bawait\s+[\w$]+${members}\s*$`);
const evaluateCall = new RegExp(
  String.raw`([\w$]+)${members}\s*\.\s*evaluate\s*$`,
);
// The start of a function whose body the next bracket opens.
const defined =
  /(?:\basync\s+)?(?:(?:\([^()]*\)|[\w$]+)\s*=>|\bfunction\b[\s\w$]*\([^()]*\))\s*$/;

// The offset of the bracket matching the one closing at `close`.
function opening(code, close) {
  let depth = 0;
  let open = close;
  for (; open > 0; open--) {
    if (")]}".includes(code[open])) depth++;
    else if ("([{".includes(code[open]) && --depth === 0) break;
  }
  return open;
}

// The statement up to the bracket matching the one closing at `close`.
function head(code, close) {
  return lead(code, opening(code, close));
}

// The statement up to the bracket at `open`.
function lead(code, open) {
  let start = open;
  for (let depth = 0; start > 0; start--) {
    const c = code[start - 1];
    if (")]".includes(c) || (c === "}" && depth > 0)) depth++;
    else if ("([{".includes(c) && depth > 0) depth--;
    else if (depth === 0 && ";{}".includes(c)) break;
  }
  return code.slice(start, open);
}

// A method (`reset() {`), which defining never runs, and not a block such as
// `if (on) {` or a named function handed to a call.
const method =
  /(?<![\w$.]|\bfunction\s+)(?!(?:if|for|while|switch|catch|function|await)\b)[\w$]+\s*\([^()]*\)\s*$/;

// Whether the bracket after `before` opens a function body that is stored
// rather than handed to a call, and so does not run here.
function stored(before) {
  if (method.test(before)) return true;
  const fn = defined.exec(before);
  return Boolean(fn) && !/[(,]\s*$/.test(before.slice(0, fn.index));
}

// The brackets that opened after `from` and are still open at `at`.
function enclosing(code, from, at) {
  const open = [];
  let depth = 0;
  for (let i = at - 1; i >= from; i--) {
    if (")]}".includes(code[i])) depth++;
    else if ("([{".includes(code[i])) {
      if (depth) depth--;
      else open.push(i);
    }
  }
  return open;
}

// Where the assignment ending at `after` runs, if it runs before the wait at
// `end`: `page`, the `.evaluate` receiver or "", and `from`, where the awaited
// call opens; else null. A function body runs only when handed to a call.
function setOn(code, after, end) {
  const around = [];
  let depth = 0;
  for (let i = after; i < end; i++) {
    if ("([{".includes(code[i])) depth++;
    else if (")]}".includes(code[i]) && --depth < -around.length)
      around.push(i);
  }
  if (!around.length)
    return tied.test(code.slice(after, end)) ? { page: "" } : null;
  if (!/^[^;]*;?\s*$/.test(code.slice(after, around[0]))) return null;
  for (let k = 1; k < around.length; k++)
    if (code[around[k]] === "}")
      if (!/^[\s;]*$/.test(code.slice(around[k - 1] + 1, around[k])))
        return null;
  const outer = around.at(-1);
  if (!follows.test(code.slice(outer + 1, end))) return null;
  if (!awaitedCall.test(head(code, outer))) return null;
  if (around.some((close) => stored(head(code, close)))) return null;
  const from = opening(code, outer);
  for (const close of around) {
    const call = evaluateCall.exec(head(code, close));
    if (call) return { page: call[1], from };
  }
  return { page: "", from };
}

// A value written out in the code; a string's contents are blanked.
const literal = String.raw`-?\d+(?:\.\d+)?|true|false|null`;
// The literal an assignment sets, and the start of a chained one.
const assigned = new RegExp(String.raw`\s*(${literal})\s*[;,)}\]]`, "y");
const chained = /\s*[\w$]+(?:\s*\.\s*[\w$]+)*\s*=(?![=>])/y;

// The literals the assignments to `.property` in `from`..`end` set, leaving
// out one in a stored function, or undefined when one sets something else.
function setValues(code, from, end, property) {
  const values = [];
  for (const set of code.slice(from, end).matchAll(assignment)) {
    if (set[1] !== property) continue;
    const opened = enclosing(code, from, from + set.index);
    if (opened.some((open) => stored(lead(code, open)))) continue;
    const at = from + set.index + set[0].length;
    chained.lastIndex = at;
    if (chained.test(code)) continue;
    assigned.lastIndex = at;
    const value = assigned.exec(code)?.[1];
    if (value === undefined) return undefined;
    values.push(value);
  }
  return values.length ? values : undefined;
}

// Why `predicate` can hold on `.property` before it was set to one of
// `values`: a bound, or `===`/`==` with another literal. A literal in a larger
// expression on either side is not compared.
function stale(predicate, property, values) {
  const operator = "(?<op>===|==|!==|!=|>=|<=|(?<![=>])>(?!>)|(?<!<)<(?!<))";
  const before = String.raw`(?:(?<![\w$.)\]]|[-+*/%]\s*)(?<left>${literal})\s*)?`;
  const after = String.raw`(?:\s*(?<right>${literal})(?![\w$.(]|\s*[-+*/%]))?`;
  const chain = String.raw`(?:[\w$]+|${group})${members}?`;
  // An operator binding tighter than `===` makes the operand more than it.
  const leading = new RegExp(String.raw`${chain}\s*$`);
  const alone = (side, found) =>
    side === 0
      ? !/(?:[-+*/%!~]|(?<!=)[<>])\s*$/.test(
          predicate.slice(0, found.index).replace(leading, ""),
        )
      : !/^\s*(?:[-+*/%<>.([]|\?\.)/.test(
          predicate.slice(found.index + found[0].length),
        );
  const written = [
    new RegExp(String.raw`\.${property}\b\s*${operator}${after}`, "g"),
    new RegExp(
      String.raw`${before}${operator}\s*${chain}\s*\.\s*${property}\b`,
      "g",
    ),
  ];
  for (const [side, pattern] of written.entries())
    for (const found of predicate.matchAll(pattern)) {
      const { groups } = found;
      if (groups.op !== "===" && groups.op !== "==")
        return `bounds .${property}, which the test just set`;
      const other = alone(side, found)
        ? (groups.left ?? groups.right)
        : undefined;
      // `900.0` is the 900 set; `true` and `null` match only as written.
      const same = (value) =>
        other === value || Number(other) === Number(value);
      if (values && other !== undefined && !values.some(same))
        return `compares .${property} with ${other}, but the test just set ${values.join(", ")}`;
    }
  return null;
}

// The names a file uses as a page, so a locator kept in a variable is not
// taken for one.
const pageUse =
  /\b([\w$]+)\s*\.\s*(?:waitForFunction|goto)\s*\(|\breaches\s*\(\s*([\w$]+)\s*,/g;

// The waits that can hold on a property the statement before them set.
function boundWaits(code) {
  const found = new Map();
  const pages = new Set(
    [...code.matchAll(pageUse)].map((used) => used[1] ?? used[2]),
  );
  for (const set of code.matchAll(assignment)) {
    const after = set.index + set[0].length;
    waitCall.lastIndex = after;
    const call = waitCall.exec(code);
    if (!call) break;
    const between = code.slice(after, call.index);
    const tie = setOn(code, after, call.index);
    if (!tie) continue;
    // Only the polled argument: the second for `reaches(page, predicate)`.
    const open = call.index + call[0].length - 1;
    const reaching = call[0].startsWith("reaches");
    const polled = reaching
      ? /^\s*([\w$]+)\s*$/.exec(argument(code, open, 0))
      : /([\w$]+)\s*\.[\s\w$.]*$/.exec(between);
    if (pages.has(tie.page) && polled && polled[1] !== tie.page) continue;
    const predicate = argument(code, open, reaching ? 1 : 0);
    const values = setValues(code, tie.from ?? set.index, call.index, set[1]);
    const reason = stale(predicate, set[1], values);
    if (reason && !found.has(call.index)) found.set(call.index, reason);
  }
  return [...found].map(([offset, reason]) => ({ offset, reason }));
}

// One global pattern for every comment and string token, so plain code is
// skipped by the regex engine instead of examined a character at a time.
const token =
  /\/\/[^\n]*|\/\*[\s\S]*?\*\/|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'|`(?:\\.|[^`\\])*`/g;

// Returns `code`, the source with comments and string contents replaced by
// spaces (newlines kept, so offsets and lines still line up), and the sets of
// lines that carry a comment and that carry a `timing-ok:` marker.
function scan(source) {
  const commented = new Set();
  const marked = new Set();
  const blank = (text) => text.replace(/[^\n]/g, " ");
  let code = "";
  let last = 0;
  let line = 0;
  let counted = 0;
  for (const found of source.matchAll(token)) {
    const [text] = found;
    line += source.slice(counted, found.index).split("\n").length - 1;
    counted = found.index;
    code += source.slice(last, found.index);
    if (text[0] === "/") {
      const span = text.split("\n").length;
      for (let k = 0; k < span; k++) {
        commented.add(line + k);
        if (text.includes("timing-ok:")) marked.add(line + k);
      }
      code += blank(text);
    } else {
      code += text[0] + blank(text.slice(1, -1)) + text.at(-1);
    }
    last = found.index + text.length;
  }
  return { code: code + source.slice(last), commented, marked };
}

for (const name of fs.readdirSync(dir).sort()) {
  // wait.js is where the one sanctioned deadline lives.
  if (!name.endsWith(".js") || name === "wait.js") continue;
  const source = fs.readFileSync(path.join(dir, name), "utf8");
  if (!relevant.test(source)) continue;
  const { code, commented, marked } = scan(source);
  const lineOf = (offset) => code.slice(0, offset).split("\n").length - 1;
  const within = (lines, line, before) => {
    for (let k = Math.max(0, line - before); k <= line; k++) {
      if (lines.has(k)) return true;
    }
    return false;
  };
  for (const [pattern, report, needsComment] of [
    [bound, "wall-clock bound; use until() from wait.js", false],
    [sleep, "fixed sleep without a comment saying what it outwaits", true],
  ]) {
    for (const found of code.matchAll(pattern)) {
      const line = lineOf(found.index);
      if (within(marked, line, 1)) continue;
      if (needsComment && within(commented, line, 3)) continue;
      problems.push(`${name}:${line + 1}: ${report}`);
    }
  }
  for (const { offset, reason } of boundWaits(code)) {
    const line = lineOf(offset);
    if (within(marked, line, 1)) continue;
    problems.push(
      `${name}:${line + 1}: wait ${reason}; wait for the value set`,
    );
  }
}

if (problems.length) {
  console.error(problems.join("\n"));
  process.exit(1);
}
