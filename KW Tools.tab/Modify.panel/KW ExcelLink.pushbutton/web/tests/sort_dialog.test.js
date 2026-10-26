import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import vm from "node:vm";
import SortModule from "../node_modules/tabulator-tables/src/js/modules/Sort/Sort.js";

const source = readFileSync(new URL("../app.js", import.meta.url), "utf8");

function functionsBetween(first, next) {
  const start = source.indexOf("  function " + first + "(");
  const end = source.indexOf("  function " + next + "(", start);
  assert.ok(start >= 0 && end > start);
  return source.slice(start, end);
}

function setup(initial = []) {
  const columns = [
    {field: "a", title: "Family"},
    {field: "b", title: "Mark"},
    {field: "c", title: "Type Name"}
  ];
  const rowNumber = {field: "_row", title: "#"};
  const sheet = {columns, layout: {sort: structuredClone(initial)}};
  let activeSheet = sheet;
  let liveSort = initial.map(item => ({
    field: columns.concat(rowNumber).find(column => column.title === item.title).field,
    dir: item.dir
  }));
  const applied = [];
  const statuses = [];
  let form, buttons, resolve;
  function el(tag, className, textContent = "") {
    return {
      tag, className, textContent, children: [], listeners: {}, value: "", disabled: false,
      appendChild(child) { this.children.push(child); },
      replaceChildren() { this.children = []; },
      setAttribute() {},
      addEventListener(name, handler) { this.listeners[name] = handler; },
      focus() {}
    };
  }
  const context = vm.createContext({
    tableReady: true, restoringFilters: false, ROW_NUMBER_COLUMN: rowNumber,
    currentSheet: () => activeSheet,
    layoutFor: target => target.layout,
    columnForField: field => columns.concat(rowNumber).find(column => column.field === field),
    columnByTitle: (target, title) => target.columns.concat(rowNumber).find(column => column.title === title),
    visibleColumns: target => target.columns,
    displayTitle: column => column.title,
    indexToLetters: index => String.fromCharCode(65 + index),
    blurGridInput() {}, syncHeaderFilters() {},
    el,
    makeButton(label, handler) {
      const button = el("button", "", label);
      button.listeners.click = handler;
      return button;
    },
    fillOptions(node, options) {
      options.forEach(item => {
        const option = el("option", "", item.label);
        option.value = item.value;
        node.appendChild(option);
      });
    },
    sortButton: {}, sortSummary: {}, sortSummaryText: {},
    table: {
      getSorters: () => liveSort,
      getColumn: () => null,
      setSort(sorters) {
        applied.push(JSON.parse(JSON.stringify(sorters)));
        liveSort = sorters.map(item => ({field: item.column, dir: item.dir}));
        context.onDataSorted();
      }
    },
    showStatus: message => statuses.push(message),
    showModal(title, content, specs) {
      form = content;
      buttons = specs;
      return new Promise(done => { resolve = done; });
    }
  });
  vm.runInContext(
    functionsBetween("captureSort", "letterToIndex") +
      functionsBetween("sortedLevels", "makeColumns"),
    context
  );
  context.openSortDialog();
  return {
    sheet, context, applied, statuses,
    get rows() { return form.children[0].children; },
    clickControl(label) {
      const button = form.children[1].children.find(node => node.textContent === label);
      if (!button.disabled) { button.listeners.click(); }
    },
    change(row, child, value) {
      const node = this.rows[row].children[child];
      node.value = value;
      node.listeners.change();
    },
    clickAction(row, index) {
      const button = this.rows[row].children[3].children[index];
      if (!button.disabled) { button.listeners.click(); }
    },
    switchSheet() { activeSheet = {}; },
    async close(label) {
      resolve(buttons.find(button => button.label === label).value);
      await Promise.resolve();
    }
  };
}

test("sort dialog applies A then C, keeps directions, and excludes duplicate columns", async () => {
  const dialog = setup();
  dialog.clickControl("Add level");
  dialog.change(1, 1, "Type Name");
  dialog.change(1, 2, "desc");
  assert.equal(dialog.rows[0].children[1].children.some(option => option.value === "Type Name"), false);
  assert.equal(dialog.rows[1].children[1].children.some(option => option.value === "Family"), false);

  await dialog.close("Apply");

  assert.deepEqual(dialog.applied, [[{column: "a", dir: "asc"}, {column: "c", dir: "desc"}]]);
  assert.deepEqual(JSON.parse(JSON.stringify(dialog.sheet.layout.sort)), [
    {title: "Family", dir: "asc"}, {title: "Type Name", dir: "desc"}
  ]);
  assert.match(dialog.context.sortSummaryText.textContent, /Family.*↑.*Type Name.*↓/);
});

test("moving and removing sort levels preserves their directions", async () => {
  const dialog = setup([{title: "Family", dir: "asc"}, {title: "Type Name", dir: "desc"}]);
  dialog.clickAction(1, 0);
  assert.equal(dialog.rows[0].children[1].value, "Type Name");
  assert.equal(dialog.rows[0].children[2].value, "desc");
  dialog.clickAction(1, 2);
  await dialog.close("Apply");
  assert.deepEqual(dialog.applied, [[{column: "c", dir: "desc"}]]);
});

test("cancel leaves the existing sort unchanged and Clear all is only applied on Apply", async () => {
  const original = [{title: "Type Name", dir: "desc"}, {title: "Family", dir: "asc"}];
  const canceled = setup(original);
  canceled.clickControl("Clear all");
  await canceled.close("Cancel");
  assert.deepEqual(canceled.applied, []);
  assert.deepEqual(JSON.parse(JSON.stringify(canceled.sheet.layout.sort)), original);

  const cleared = setup(original);
  cleared.clickControl("Clear all");
  await cleared.close("Apply");
  assert.deepEqual(cleared.applied, [[]]);
  assert.equal(cleared.context.sortSummary.hidden, true);
  assert.equal(cleared.context.sortButton.hidden, false);
});

test("capture and restore keep primary-first order without mutating the saved sort", () => {
  const original = [{title: "Type Name", dir: "desc"}, {title: "Family", dir: "asc"}];
  const dialog = setup(original);
  dialog.context.captureLayout();
  dialog.context.applySort(dialog.sheet);
  assert.deepEqual(dialog.applied, [[{column: "c", dir: "desc"}, {column: "a", dir: "asc"}]]);
  assert.deepEqual(JSON.parse(JSON.stringify(dialog.sheet.layout.sort)), original);
});

test("initial grid sorting and layout restoration cannot overwrite saved sort levels", () => {
  const original = [{title: "Type Name", dir: "desc"}, {title: "Family", dir: "asc"}];
  const dialog = setup(original);
  dialog.context.table.getSorters = () => [];
  dialog.context.tableReady = false;
  dialog.context.onDataSorted();
  dialog.context.tableReady = true;
  dialog.context.restoringFilters = true;
  dialog.context.onDataSorted();
  assert.deepEqual(JSON.parse(JSON.stringify(dialog.sheet.layout.sort)), original);
});

test("a replaced active sheet blocks applying the draft", async () => {
  const dialog = setup();
  dialog.switchSheet();
  await dialog.close("Apply");
  assert.deepEqual(dialog.applied, []);
  assert.match(dialog.statuses[0], /active sheet changed/);
});

test("Tabulator sorts A first and C second using the configured priority convention", () => {
  assert.match(source, /sortOrderReverse:\s*true/);
  const sortList = [{column: "a", dir: "asc"}, {column: "c", dir: "desc"}].map(item => ({
    dir: item.dir,
    column: {field: item.column, modules: {sort: {sorter: true, params: {}}}}
  }));
  const rows = [
    {id: 1, a: "B", c: 1},
    {id: 2, a: "A", c: 1},
    {id: 3, a: "B", c: 2},
    {id: 4, a: "A", c: 2}
  ];
  SortModule.prototype.sort.call({
    table: {options: {sortMode: "local", sortOrderReverse: true}},
    sortList,
    subscribedExternal: () => false,
    _sortItems: SortModule.prototype._sortItems,
    _sortRow(first, second, column, dir) {
      const comparison = first[column.field] < second[column.field] ? -1 :
        first[column.field] > second[column.field] ? 1 : 0;
      return dir === "desc" ? -comparison : comparison;
    }
  }, rows, true);
  assert.deepEqual(rows.map(row => row.id), [4, 2, 3, 1]);
});
