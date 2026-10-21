import test from "node:test";
import assert from "node:assert/strict";
import {editValue, navigationTarget, scalarEditor} from "../spreadsheet.js";
import {planFillDown} from "../range_clipboard.js";

const text = {field: "mark", title: "Mark", storageType: "String", target: "instance", editable: true};
const numeric = {...text, field: "length", title: "Length", storageType: "Double"};
const reference = {...text, field: "level", storageType: "ElementId", options: ["Ground", "First"]};
const key = (row, col) => [col.target, col.target === "type" ? row.TypeElementId : row.UniqueId, col.field].join("|");
const editable = (column, row) => column.editable && !row[column.field + "__disabled"];
function cell(data, field) {
  return {getField: () => field, getValue: () => data[field], getRow: () => ({getData: () => data})};
}
function plan(rows, columns = [text]) {
  return planFillDown(rows.map(row => columns.map(col => cell(row, col.field))),
    field => columns.find(col => col.field === field), editable, key);
}

test("scalar editing preserves text, validates numbers/references and gates formulas", () => {
  assert.equal(editValue("hello", text), "hello");
  assert.equal(editValue("+literal", text), "+literal");
  assert.equal(editValue("+Type name", {...text, target: "typeName"}), "+Type name");
  assert.equal(editValue("-12.5", numeric), -12.5);
  for (const raw of ["", "-", ".", "NaN", "Infinity", "1,000", "2 mm"]) {
    assert.throws(() => editValue(raw, numeric));
  }
  assert.equal(editValue("First", reference), "First");
  assert.throws(() => editValue("unknown", reference));
  assert.throws(() => editValue("=1+2", text), /disabled/);
  assert.equal(editValue("=1+2", {...text, formulaAllowed: true}), "=1+2");
  assert.throws(() => editValue("2147483648", {...numeric, storageType: "Integer"}));
});

test("navigation follows displayed rows, wraps Tab, reverses Shift, and stops at grid edges", () => {
  const rows = ["c", "a", "b"].map(id => ({
    getData: () => ({UniqueId: id}), getCell: field => id + ":" + field
  }));
  const fields = ["mark", "length"];
  assert.equal(navigationTarget(rows, fields, "c", "mark", "Enter", false), "a:mark");
  assert.equal(navigationTarget(rows, fields, "a", "mark", "Enter", true), "c:mark");
  assert.equal(navigationTarget(rows, fields, "c", "mark", "Tab", false), "c:length");
  assert.equal(navigationTarget(rows, fields, "c", "length", "Tab", false), "a:mark");
  assert.equal(navigationTarget(rows, fields, "a", "mark", "Tab", true), "c:length");
  assert.equal(navigationTarget(rows, fields, "b", "length", "Tab", false), null);
  assert.equal(navigationTarget(rows, fields, "c", "mark", "Enter", true), null);
  assert.equal(navigationTarget(rows, fields, "missing", "mark", "Tab", false), null);
});

test("fill down copies each top-row value, skips locks/unchanged cells and never mutates input", () => {
  const rows = [
    {UniqueId: "c", mark: "Top", length: 12},
    {UniqueId: "b", mark: "Old", length: 1, length__disabled: true},
    {UniqueId: "a", mark: "Top", length: 2},
  ];
  const before = JSON.stringify(rows);
  const result = plan(rows, [text, numeric]);
  assert.deepEqual(result.changes.map(change => [change.row.UniqueId, change.column.field, change.value]),
    [["b", "mark", "Top"], ["a", "length", 12]]);
  assert.equal(result.skipped, 1);
  assert.equal(result.types, 0);
  assert.equal(JSON.stringify(rows), before);
});

test("fill down validates the whole plan and requires at least two rows", () => {
  assert.throws(() => plan([{mark: "a"}]), /at least one row/);
  assert.throws(() => plan([{mark: "a", length: null}, {mark: "b", length: 2}], [text, numeric]),
    /Enter a number/);
  assert.throws(() => plan([{level: "Unknown"}, {level: "Ground"}], [reference]), /reference name/);
});

test("fill down copies formula-like literal text unchanged, handles blanks and shared types", () => {
  assert.equal(plan([{mark: "=literal"}, {mark: "old"}]).changes[0].value, "=literal");
  assert.equal(plan([{mark: null}, {mark: "old"}]).changes[0].value, "");
  const type = {...text, target: "type"};
  const result = plan([
    {UniqueId: "a", TypeElementId: 1, mark: "source"},
    {UniqueId: "b", TypeElementId: 2, mark: "old"},
    {UniqueId: "c", TypeElementId: 2, mark: "old"},
  ], [type]);
  assert.equal(result.changes.length, 1);
  assert.equal(result.types, 1);
  assert.equal(result.changes[0].value, "source");
});

test("fill replaces equal-valued target formulas and keeps literal type names", () => {
  const rows = [{UniqueId: "a", mark: "same"}, {UniqueId: "b", mark: "same"}];
  const result = planFillDown(rows.map(row => [cell(row, "mark")]), () => text,
    editable, key, row => row.UniqueId === "b");
  assert.equal(result.changes.length, 1);
  const typeName = {...text, target: "typeName"};
  assert.equal(plan([{mark: "=literal"}, {mark: "old"}], [typeName]).changes[0].value,
    "=literal");
});

test("scalar editor validates before success, keeps invalid input open and cancels with Escape", () => {
  const previous = globalThis.document;
  const handlers = {}, attributes = {}, errors = [], commits = [];
  let focused = 0, selected = 0, cancelled = 0, render;
  const input = {
    style: {}, value: "",
    setAttribute: (key, value) => { attributes[key] = value; },
    addEventListener: (name, callback) => { handlers[name] = callback; },
    focus: () => { focused += 1; }, select: () => { selected += 1; },
  };
  globalThis.document = {createElement: () => input};
  try {
    const editor = scalarEditor(numeric, message => errors.push(message));
    assert.equal(editor({getValue: () => 42}, callback => { render = callback; },
      value => commits.push(value), () => { cancelled += 1; }), input);
    assert.equal(input.value, "42");
    render();
    assert.equal(selected, 1);
    input.value = "-";
    handlers.keydown({key: "Enter"});
    assert.equal(commits.length, 0);
    assert.equal(attributes["aria-invalid"], "true");
    assert.equal(focused, 2);
    assert.equal(errors.length, 1);
    input.value = "-12.5";
    handlers.keydown({key: "Enter", isComposing: true});
    assert.equal(commits.length, 0);
    handlers.keydown({key: "Enter"});
    assert.deepEqual(commits, [-12.5]);
    handlers.blur();
    assert.equal(commits.length, 1);

    editor({getValue: () => 42}, () => {}, value => commits.push(value),
      () => { cancelled += 1; });
    input.value = "replacement";
    handlers.keydown({key: "Escape"});
    handlers.blur();
    assert.equal(cancelled, 1);
    assert.equal(commits.length, 1);
  } finally {
    if (previous === undefined) { delete globalThis.document; }
    else { globalThis.document = previous; }
  }
});
