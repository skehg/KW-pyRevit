import test from "node:test";
import assert from "node:assert/strict";
import {cellColumn, typeLabel} from "../cell_metadata.js";
import {planPaste, planFillDown} from "../range_clipboard.js";
import {readFileSync} from "node:fs";
import vm from "node:vm";

const source = readFileSync(new URL("../app.js", import.meta.url), "utf8");

function appFunction(name, next, context) {
  const start = source.indexOf("  function " + name + "(");
  const end = source.indexOf("  function " + next + "(", start);
  assert.ok(start >= 0 && end > start);
  vm.runInContext(source.slice(start, end), context);
  return context[name];
}

test("header type labels place units alongside semantic data types", () => {
  assert.equal(typeLabel({dataType: "Length", unit: "mm"}), "Length [mm]");
  assert.equal(typeLabel({dataType: "Yes/No"}), "Yes/No");
  assert.equal(typeLabel({dataType: "Text"}), "Text");
});

test("cell metadata overrides reference choices without mutating a shared column", () => {
  const column = {field: "p0", storageType: "ElementId", options: ["Door type"]};
  const row = {p0__metadata: {options: ["Window type"], referenceKind: {key: "windows"}}};
  assert.deepEqual(cellColumn(column, row).options, ["Window type"]);
  assert.deepEqual(column.options, ["Door type"]);
  assert.equal(cellColumn(column, {}).options, column.options);
});

test("paste validates reference choices for each target category, not the first row's choices", () => {
  const column = {field: "p0", title: "Family and Type", target: "instance",
    storageType: "ElementId", options: ["Door type"]};
  const rows = [
    {id: 1, p0__metadata: {options: ["Door type"]}},
    {id: 2, p0__metadata: {options: ["Window type"]}}
  ];
  const key = row => row.id;
  assert.equal(planPaste([["Door type"], ["Window type"]], rows, [column], 0, 0, () => true, key).changes.length, 2);
  assert.throws(() => planPaste([["Door type"], ["Door type"]], rows, [column], 0, 0, () => true, key),
    /unambiguous reference/);
});

test("fill down rejects incompatible reference choices before any values change", () => {
  const column = {field: "p0", title: "Family and Type", target: "instance",
    storageType: "ElementId", options: ["Door type"]};
  const data = [
    {id: 1, p0: "Door type", p0__metadata: {options: ["Door type"]}},
    {id: 2, p0: "Window type", p0__metadata: {options: ["Window type"]}}
  ];
  const cells = data.map(row => [{
    getField: () => "p0", getValue: () => row.p0, getRow: () => ({getData: () => row})
  }]);
  assert.throws(() => planFillDown(cells, () => column, () => true, row => row.id), /unambiguous reference/);
  assert.equal(data[1].p0, "Window type");
});

test("staged changes carry stable parameter identity and the target row's reference kind", () => {
  const buildChange = appFunction("buildChange", "recalculateFormulas", vm.createContext({cellColumn}));
  const column = {field: "p0", target: "instance", parameterName: "Type", parameterKey: "stable-key",
    parameterIdentity: "builtin:-1", specTypeId: "reference", storageType: "ElementId",
    referenceKind: {key: "doors"}};
  const row = {ElementId: 1, p0__metadata: {referenceKind: {key: "windows"}, parameterBuiltin: -1}};
  const change = buildChange(row, column, "Window type");
  assert.equal(change.parameterIdentity, "builtin:-1");
  assert.equal(change.parameterKey, "stable-key");
  assert.equal(change.specTypeId, "reference");
  assert.equal(change.referenceKind.key, "windows");
});

test("grid header places semantic type and units above the parameter label", () => {
  const column = {dataType: "Length", unit: "mm"};
  const context = vm.createContext({
    typeLabel, columnForField: () => column,
    document: {createElement: () => ({
      children: [], appendChild(child) { this.children.push(child); }
    })}
  });
  const formatter = appFunction("headerTitleFormatter", "headerFilterEditor", context);
  const header = formatter("width", "A")({getValue: () => "Width (Type)"});
  assert.deepEqual(Array.from(header.children, node => node.textContent),
    ["A", "Length [mm]", "Width (Type)"]);
});
