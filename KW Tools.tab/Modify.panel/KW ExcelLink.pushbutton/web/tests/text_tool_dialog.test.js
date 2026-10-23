import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import vm from "node:vm";
import * as TT from "../text_tools.js";

const source = readFileSync(new URL("../app.js", import.meta.url), "utf8");
const start = source.indexOf("  function openTextTool(kind, initialCase) {");
const end = source.indexOf("  function openRangeMenu(", start);
assert.ok(start >= 0 && end > start);

function setup(kind = "replace") {
  const nodes = [];
  const staged = [];
  const sheet = {};
  let activeSheet = sheet;
  let buttons, form, resolve;
  const row = {ElementId: 1, mark: "Door one"};
  const column = {field: "mark", title: "Mark", storageType: "String", target: "instance", editable: true};
  function el(tag, className, textContent = "") {
    const node = {
      tag, className, textContent, children: [], listeners: {}, value: "", checked: false,
      appendChild(child) { this.children.push(child); },
      replaceChildren() { this.children = []; },
      setAttribute() {},
      addEventListener(name, handler) { this.listeners[name] = handler; },
      focus() {},
      closest() { return {querySelector: () => buttons.find(button => button.primary)}; }
    };
    nodes.push(node);
    return node;
  }
  const context = vm.createContext({
    TT, el, tableReady: true, clipboardBusy: false,
    currentSheet: () => activeSheet,
    blurGridInput() {},
    table: {getRanges: () => [{
      getCells: () => [[{getRow: () => ({getData: () => row}), getField: () => "mark"}]]
    }]},
    columnForField: () => column,
    fillOptions(node, options) { node.value = options[0].value; },
    CASE_OPTIONS: [{value: "upper", label: "UPPER CASE"}],
    F: {ROW_NUMBER_FIELD: "ElementId"},
    textScopeCells: (scope, selected) => TT.textScopeCells(scope, selected, [row], [column]),
    cellEditable: col => col.editable,
    rowChangeKey: (row, col) => row.ElementId + "|" + col.field,
    showModal(title, content, specs) {
      form = content;
      buttons = specs;
      return new Promise(done => { resolve = done; });
    },
    stagePlannedChanges(plan) { staged.push(plan); return Promise.resolve(); },
    reportGridError(error) { throw error; },
    showStatus(message) { assert.fail(message); }
  });
  vm.runInContext(source.slice(start, end), context);
  context.openTextTool(kind);
  return {
    row, column, staged,
    field(label) { return form.children.find(node => node.textContent === label).children[0]; },
    change(label, value) { this.field(label).value = value; form.listeners.input(); form.listeners.change(); },
    get stage() { return buttons.find(button => button.primary); },
    get error() { return nodes.find(node => node.className === "modal-error").textContent; },
    preview() { buttons[0].onClick(); },
    switchSheet() { activeSheet = {}; },
    async click(label, invalidateOnClose = false) {
      const button = buttons.find(button => button.label === label);
      if (!button.disabled && (!button.onClick || button.onClick() !== false)) {
        if (invalidateOnClose) { form.listeners.change(); }
        resolve(button.value);
      }
      await Promise.resolve();
    }
  };
}

test("find/replace stages directly and retains its accepted plan when closing invalidates the preview", async () => {
  const dialog = setup();
  assert.equal(dialog.stage.disabled, false);
  dialog.change("Find", "Door");
  dialog.change("Replace with", "Window");
  await dialog.click("Stage changes", true);
  assert.equal(dialog.staged.length, 1);
  assert.equal(dialog.staged[0].changes[0].value, "Window one");
  assert.equal(dialog.row.mark, "Door one");
});

test("staging uses current options and grid values rather than a cached preview", async () => {
  const dialog = setup();
  dialog.change("Find", "Door");
  dialog.change("Replace with", "Window");
  dialog.preview();
  dialog.change("Replace with", "Opening");
  assert.equal(dialog.stage.disabled, false);
  dialog.row.mark = "Door two";
  await dialog.click("Stage changes");
  assert.equal(dialog.staged[0].changes[0].before, "Door two");
  assert.equal(dialog.staged[0].changes[0].value, "Opening two");
});

test("invalid input blocks direct staging and can be corrected without a preview", async () => {
  const dialog = setup();
  await dialog.click("Stage changes");
  assert.match(dialog.error, /Enter text/);
  dialog.change("Find", "[");
  dialog.field("Use regular expressions (regex)").checked = true;
  await dialog.click("Stage changes");
  assert.match(dialog.error, /Invalid regular expression/);
  assert.equal(dialog.staged.length, 0);
  dialog.change("Find", "Door");
  await dialog.click("Stage changes");
  assert.equal(dialog.staged[0].changes[0].value, " one");
});

test("no matches do not stage; changing inputs enables another direct attempt", async () => {
  const dialog = setup();
  dialog.change("Find", "Missing");
  await dialog.click("Stage changes");
  assert.equal(dialog.staged.length, 0);
  assert.equal(dialog.stage.disabled, true);
  dialog.change("Find", "Door");
  assert.equal(dialog.stage.disabled, false);
  await dialog.click("Stage changes");
  assert.equal(dialog.staged.length, 1);
});

test("a different workbook sheet blocks direct staging", async () => {
  const dialog = setup();
  dialog.change("Find", "Door");
  dialog.switchSheet();
  await dialog.click("Stage changes");
  assert.match(dialog.error, /workbook changed/);
  assert.equal(dialog.staged.length, 0);
});

test("cancel never stages edits", async () => {
  const dialog = setup();
  dialog.change("Find", "Door");
  dialog.preview();
  await dialog.click("Cancel");
  assert.equal(dialog.staged.length, 0);
});

test("case conversion keeps its immediate preview and stages current values", async () => {
  const dialog = setup("case");
  assert.equal(dialog.stage.disabled, false);
  await dialog.click("Stage changes");
  assert.equal(dialog.staged[0].changes[0].value, "DOOR ONE");
});
