import test from "node:test";
import assert from "node:assert/strict";
import {parseTSV, copyTSV, pasteValue, planPaste} from "../range_clipboard.js";

const column = {title: "Mark", field: "mark", storageType: "String", target: "instance"};
const rows = [
  {UniqueId: "b", ElementId: 2, TypeElementId: 10, mark: "B"},
  {UniqueId: "a", ElementId: 1, TypeElementId: 10, mark: "A"},
];
const key = (row, col) => [col.target, col.target === "type" ? row.TypeElementId : row.ElementId, col.field].join("|");

test("Excel TSV parses quoted tabs, newlines, quotes, Unicode and trailing row terminator", () => {
  assert.deepEqual(parseTSV('Café\t"two\tcolumns"\r\n"a\nb"\t"say ""hi"""\r\n'),
    [["Café", "two\tcolumns"], ["a\nb", 'say "hi"']]);
  assert.deepEqual(parseTSV("x\t"), [["x", ""]]);
  assert.deepEqual(parseTSV(""), [[""]]);
  assert.throws(() => parseTSV('a\tb\nc'), /rectangular/);
  assert.throws(() => parseTSV('"unclosed'), /Unclosed/);
  assert.throws(() => parseTSV('"closed"bad'), /Invalid/);
});

test("copy exports values only with escaped TSV and protects formula-like strings", () => {
  assert.equal(copyTSV([[12, null, 'a"b', "a\tb"], ["=1+2", "+SUM(A1)", "@A1", -4]]),
    '12\t\t"a""b"\t"a\tb"\r\n\'=1+2\t\'+SUM(A1)\t\'@A1\t-4');
  assert.deepEqual(parseTSV(copyTSV([["a\nb", "東京"]])), [["a\nb", "東京"]]);
});

test("formulas never enter the paste plan", () => {
  for (const formula of ["=A1", "  =1+2", "+SUM(A1)", "@SUM(A1)", "-SUM(A1)"]) {
    assert.throws(() => pasteValue(formula, column), /Formulas/);
  }
});

test("numeric and reference values are validated without silent conversion", () => {
  assert.equal(pasteValue("-1.5", {...column, storageType: "Double"}), -1.5);
  assert.equal(pasteValue("+12", {...column, storageType: "Integer"}), 12);
  for (const invalid of ["", "1,200", "12 mm", "NaN", "Infinity", "0x10", "1e999"]) {
    assert.throws(() => pasteValue(invalid, {...column, storageType: "Double"}));
  }
  for (const invalid of ["1.5", "2147483648", "-2147483649"]) {
    assert.throws(() => pasteValue(invalid, {...column, storageType: "Integer"}));
  }
  const reference = {...column, storageType: "ElementId", options: ["Level 0", "Level 1"]};
  assert.equal(pasteValue("Level 1", reference), "Level 1");
  assert.throws(() => pasteValue("level 1", reference), /reference name/);
  assert.throws(() => pasteValue("Unknown", reference), /reference name/);
  assert.throws(() => pasteValue("Level 1", {...reference, options: ["Level 1", "Level 1"]}));
  assert.throws(() => pasteValue("", {...column, target: "typeName"}), /blank/);
});

test("paste follows displayed row order, skips locked cells and does not mutate rows", () => {
  const before = JSON.stringify(rows);
  const plan = planPaste([["first"], ["second"]], rows, [column], 0, 0,
    (col, row) => row.ElementId !== 1, key);
  assert.equal(plan.skipped, 1);
  assert.equal(plan.changes.length, 1);
  assert.equal(plan.changes[0].row.ElementId, 2);
  assert.equal(plan.changes[0].value, "first");
  assert.equal(JSON.stringify(rows), before);
});

test("oversized blocks fail rather than adding rows, truncating, or wrapping", () => {
  for (const [matrix, r, c] of [[[["a"], ["b"], ["c"]], 0, 0], [[["a", "b"]], 0, 0],
    [[["a"], ["b"]], 1, 0], [[["a"]], -1, 0]]) {
    assert.throws(() => planPaste(matrix, rows, [column], r, c, () => true, key), /exceeds/);
  }
});

test("shared type conflicts abort the whole plan; identical values deduplicate", () => {
  const type = {...column, target: "type"};
  assert.throws(() => planPaste([["A"], ["B"]], rows, [type], 0, 0, () => true, key), /Conflicting/);
  const plan = planPaste([["A"], ["A"]], rows, [type], 0, 0, () => true, key);
  assert.equal(plan.changes.length, 1);
  assert.equal(plan.types, 1);
});

test("one invalid editable value rejects the entire block before staging", () => {
  const before = JSON.stringify(rows);
  assert.throws(() => planPaste([["2"], ["not numeric"]], rows,
    [{...column, storageType: "Integer"}], 0, 0, () => true, key), /Paste row 2/);
  assert.equal(JSON.stringify(rows), before);
});
