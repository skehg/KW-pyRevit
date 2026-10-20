import test from "node:test";
import assert from "node:assert/strict";
import {changeCase, textReplacement, textScopeCells, planTextChanges} from "../text_tools.js";

test("case transforms preserve punctuation and handle Unicode and apostrophes", () => {
  assert.equal(changeCase("Café 東京", "upper"), "CAFÉ 東京");
  assert.equal(changeCase("CAFÉ DOOR", "lower"), "café door");
  assert.equal(changeCase("JOHN'S DOOR-TYPE and l’été", "title"), "John's Door-Type And L’été");
  assert.equal(changeCase("\u{10428}WORD", "title"), "\u{10400}word");
  assert.equal(changeCase('  hELLO! "HOW ARE YOU?" fine. NEXT\nLINE', "sentence"),
    '  Hello! "How are you?" Fine. Next\nline');
  assert.equal(changeCase("", "sentence"), "");
  assert.throws(() => changeCase("test", "unknown"), /supported/);
});

test("find replace is literal, supports whole cell, match case and deletion", () => {
  assert.equal(textReplacement("d.", "$&", false, false)("D. d. door"), "$& $& door");
  assert.equal(textReplacement("Door", "Window", true, false)("door Door"), "door Window");
  assert.equal(textReplacement("Door", "Window", false, true)("DOOR"), "Window");
  assert.equal(textReplacement("Door", "Window", false, true)("Door 1"), "Door 1");
  assert.equal(textReplacement("Door", "Window", false, true)("Door\n"), "Door\n");
  assert.equal(textReplacement("[x]", "", true, false)("a[x][x]b"), "ab");
  assert.equal(textReplacement("café", "Room", false, false)("CAFÉ"), "Room");
  assert.throws(() => textReplacement("", "x", false, false), /Enter text/);
});

test("regex supports captures, named groups, case options, deletion and literal formula results", () => {
  assert.equal(textReplacement("(door)-(\\d+)", "$2:$1", false, false, true)("DOOR-12 door-34"),
    "12:DOOR 34:door");
  assert.equal(textReplacement("(?<prefix>Door) (?<id>\\d+)", "$<id> $<prefix>", true, true, true)("Door 12"),
    "12 Door");
  assert.equal(textReplacement("door", "Window", true, false, true)("door Door"), "Window Door");
  assert.equal(textReplacement("\\d+", "", false, false, true)("A12B34"), "AB");
  assert.equal(textReplacement("^Door", "=1+2", false, false, true)("Door"), "=1+2");
  assert.equal(textReplacement("(Door)", "$1", false, false, false)("(Door)"), "$1");
});

test("regex whole-cell matching handles alternatives, newlines and repeated calls", () => {
  const replace = textReplacement("Door|Window", "Opening", false, true, true);
  assert.equal(replace("Door"), "Opening");
  assert.equal(replace("WINDOW"), "Opening");
  assert.equal(replace("Door 1"), "Door 1");
  assert.equal(replace("Door\n"), "Door\n");
  assert.equal(textReplacement("[\\s\\S]+", "x", true, true, true)("Door\n"), "x");
  assert.equal(textReplacement("^|$", "_", true, false, true)("Door"), "_Door_");
  assert.throws(() => textReplacement("[", "x", false, false, true), /Invalid regular expression/);
  assert.throws(() => textReplacement("", "x", false, false, true), /Enter text/);
});

const mark = {field: "mark", title: "Mark (Instance)", storageType: "String", target: "instance", editable: true};
const key = (row, col) => [col.target, col.target === "instance" ? row.ElementId : row.TypeElementId, col.field].join("|");
const editable = (col, row) => col.editable && !row[col.field + "__disabled"];
const row = {ElementId: 1, TypeElementId: 10, mark: "Door one"};

test("column scope expands one or several selected columns across visible rows only", () => {
  const columns = [mark, {...mark, field: "other"}, {...mark, field: "third"}, {...mark, field: "fourth"}];
  const hidden = {...row, ElementId: 3, mark: "filtered out"};
  const rows = [row, {...row, ElementId: 2}];
  const selected = [{row, column: mark}];
  assert.deepEqual(textScopeCells("columns", selected, rows, columns),
    rows.map(row => ({row, column: mark})));
  selected.push({row, column: columns[1]}, {row, column: columns[2]}, {row: rows[1], column: mark});
  const expanded = textScopeCells("columns", selected, rows, columns);
  assert.equal(expanded.length, 6);
  assert.deepEqual(expanded.map(cell => cell.column.field), ["mark", "other", "third", "mark", "other", "third"]);
  assert.ok(expanded.every(cell => cell.row !== hidden));
  assert.equal(textScopeCells("selected", selected, rows, columns), selected);
  assert.equal(textScopeCells("visible", [], rows, columns).length, 8);
  assert.throws(() => textScopeCells("columns", [], rows, columns), /Select a cell/);
  assert.throws(() => textScopeCells("columns", [{row}], rows, columns), /Select a cell/);
  assert.throws(() => textScopeCells("selected", [], rows, columns), /Select a range/);
  assert.throws(() => textScopeCells("unknown", [], rows, columns), /supported text scope/);
});

test("text plans skip locked, numeric, references and null cells; do not mutate input", () => {
  const cells = [
    {row, column: mark},
    {row: {...row, mark__disabled: true}, column: mark},
    {row, column: {...mark, storageType: "ElementId"}},
    {row, column: {...mark, storageType: "Integer"}},
    {row: {...row, mark: null}, column: mark},
    {row, column: undefined},
  ];
  const before = JSON.stringify(cells);
  const plan = planTextChanges(cells, text => changeCase(text, "upper"), editable, key);
  assert.equal(plan.changes.length, 1);
  assert.equal(plan.changes[0].value, "DOOR ONE");
  assert.equal(plan.changes[0].before, "Door one");
  assert.equal(plan.skipped, 5);
  assert.equal(plan.types, 0);
  assert.equal(JSON.stringify(cells), before);
});

test("unchanged values are not staged; shared type changes deduplicate", () => {
  const column = {...mark, target: "type"};
  const cells = [{row, column}, {row: {...row, ElementId: 2}, column}];
  const plan = planTextChanges(cells, text => changeCase(text, "upper"), editable, key);
  assert.equal(plan.changes.length, 1);
  assert.equal(plan.types, 1);
  const unchanged = planTextChanges(cells, text => text, editable, key);
  assert.equal(unchanged.changes.length, 0);
  assert.equal(unchanged.unchanged, 2);
  assert.equal(unchanged.types, 0);
});

test("conflicting shared type results reject the entire plan, including unchanged candidates", () => {
  const column = {...mark, target: "type"};
  const cells = [{row, column}, {row: {...row, ElementId: 2, mark: "DOOR TWO"}, column}];
  assert.throws(() => planTextChanges(cells, text => text.toUpperCase(), editable, key), /Conflicting/);
});

test("type names may be transformed but cannot become blank", () => {
  const column = {...mark, target: "typeName", storageType: undefined};
  const cells = [{row, column}];
  assert.equal(planTextChanges(cells, text => text.toUpperCase(), editable, key).types, 1);
  assert.throws(() => planTextChanges(cells, () => "", editable, key), /blank type name/);
});

test("replacement results are literal values, not evaluated as formulas", () => {
  const plan = planTextChanges([{row, column: mark}],
    textReplacement("Door", "=1+2", false, false), editable, key);
  assert.equal(plan.changes[0].value, "=1+2 one");
});
