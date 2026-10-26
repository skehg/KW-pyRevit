import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import vm from "node:vm";

const source = readFileSync(new URL("../app.js", import.meta.url), "utf8");
const start = source.indexOf("  function stagePlannedChanges(");
const end = source.indexOf("  function selectGridCell(", start);
assert.ok(start >= 0 && end > start);

function setup(confirm = () => assert.fail("Paste and fill down must not open a confirmation")) {
  const column = {field: "mark", target: "type"};
  const rows = [
    {UniqueId: "one", TypeElementId: 10, mark: "old"},
    {UniqueId: "hidden", TypeElementId: 10, mark: "old"},
    {UniqueId: "other", TypeElementId: 20, mark: "unchanged"}
  ];
  const plan = {changes: [{row: rows[0], column, value: "new"}], types: 1, skipped: 0};
  const history = [];
  const updates = [];
  const context = vm.createContext({
    clipboardBusy: false,
    window: {confirm},
    RC: {parseTSV: text => text, planPaste: () => plan, planFillDown: () => plan},
    ROW_NUMBER_COLUMN: {field: "_row"},
    selectedRangeCells: () => [[{
      getRow: () => ({getData: () => rows[0]}),
      getField: () => column.field
    }]],
    currentSheet: () => ({}),
    visibleColumns: () => [column],
    columnForField: () => column,
    cellEditable: () => true,
    rowChangeKey: row => row.TypeElementId + "|mark",
    isSharedByType: () => true,
    captureEditState: () => structuredClone(rows),
    originalValues: new Map(),
    pendingChanges: new Map(),
    formulaTexts: new Map([["one|mark", "=1"], ["hidden|mark", "=1"]]),
    formulaValues: new Map([["one|mark", "old"], ["hidden|mark", "old"]]),
    buildChange: (row, col, value) => ({typeElementId: row.TypeElementId, field: col.field, value}),
    table: {
      getData: () => rows,
      getRows: () => [{getData: () => rows[0]}],
      updateData(changes) {
        updates.push(...changes);
        changes.forEach(change => Object.assign(rows.find(row => row.UniqueId === change.UniqueId), change));
        return Promise.resolve();
      }
    },
    recalculateFormulas() {},
    reportChangeCount() {},
    updateFilterBar() {},
    recordHistory: (before, label) => history.push({before, label}),
    showStatus() {},
    reportGridError(error) { throw error; }
  });
  vm.runInContext(source.slice(start, end), context);
  return {context, plan, rows, history, updates};
}

for (const label of ["Paste", "Fill down"]) {
  test(label + " stages shared-type changes without confirmation and retains Undo history", async () => {
    const harness = setup();
    if (label === "Paste") { await harness.context.pasteRangeText("new"); }
    else { await harness.context.fillDown(); }

    assert.equal(harness.rows[0].mark, "new");
    assert.equal(harness.rows[1].mark, "new");
    assert.equal(harness.rows[2].mark, "unchanged");
    assert.equal(harness.context.pendingChanges.size, 1);
    assert.equal(harness.context.originalValues.get("10|mark"), "old");
    assert.equal(harness.history.length, 1);
    assert.equal(harness.history[0].label, label);
    assert.equal(harness.history[0].before[0].mark, "old");
    assert.equal(harness.context.formulaTexts.size, 0);
    assert.equal(harness.context.clipboardBusy, false);
  });
}

test("other shared-type staging operations retain their confirmation", async () => {
  let confirmations = 0;
  const harness = setup(() => { confirmations += 1; return false; });
  await harness.context.stagePlannedChanges(harness.plan, "Find / Replace");
  assert.equal(confirmations, 1);
  assert.equal(harness.updates.length, 0);
  assert.equal(harness.context.pendingChanges.size, 0);
});
