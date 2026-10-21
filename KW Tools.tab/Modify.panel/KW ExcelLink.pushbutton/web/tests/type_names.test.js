import test from "node:test";
import assert from "node:assert/strict";
import {findNameConflicts, nameRecords, nameValue} from "../type_names.js";

const records = [
  {id: 1, scope: "family:10", family: "Door A", name: "Small"},
  {id: 2, scope: "family:10", family: "Door A", name: "Large"},
  {id: 3, scope: "family:10", family: "Door A", name: "Outside workbook"},
  {id: 4, scope: "family:20", family: "Door B", name: "Small"},
];

test("duplicate proposed names flag both types and identify existing names outside the workbook", () => {
  const duplicates = findNameConflicts(records, new Map([["1", "New"], ["2", "New"]]));
  assert.deepEqual([...duplicates.keys()], ["1", "2"]);
  assert.match(duplicates.get("1"), /type ID 2/);
  const outside = findNameConflicts(records, new Map([["1", "Outside workbook"]]));
  assert.match(outside.get("1"), /Outside workbook.*Door A.*type ID 3/);
  assert.equal(outside.size, 2);
});

test("names compare within family scope, not globally, with Revit's distinct name casing", () => {
  assert.equal(findNameConflicts(records, new Map([["1", "Large"]])).size, 2);
  assert.equal(findNameConflicts(records, new Map([["1", "large"]])).size, 0);
  assert.equal(findNameConflicts(records, new Map([["1", "Small"]])).size, 0);
  assert.equal(findNameConflicts(records, new Map()).size, 0);
  assert.equal(findNameConflicts(records, new Map([["4", "Large"]])).size, 0);
});

test("corrections, swaps and chains are validated against the final names", () => {
  assert.equal(findNameConflicts(records, new Map([["1", "Large"], ["2", "Small"]])).size, 0);
  assert.equal(findNameConflicts(records, new Map([["1", "Large"], ["2", "New"]])).size, 0);
  assert.equal(findNameConflicts(records, new Map([["1", "Large"]])).size, 2);
});

test("workbook inventory deduplicates shared types across sheets", () => {
  assert.equal(nameRecords({sheets: [{typeNames: records}, {typeNames: [records[0]]}]}).length, 4);
  assert.deepEqual(nameRecords({sheets: [{}]}), []);
});

test("names are trimmed and blank/prohibited names are rejected", () => {
  assert.equal(nameValue("  Panel 1200 x 2400  "), "Panel 1200 x 2400");
  for (const invalid of ["", " ", null, "Bad|Name", "Bad[Name]", "Bad\\Name", "Bad\nName"]) {
    assert.throws(() => nameValue(invalid), /blank|prohibited/);
  }
});
