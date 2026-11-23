import test from "node:test";
import assert from "node:assert/strict";
import {
  OPERATORS,
  expressionFor,
  parseTerm,
  rowPasses,
  SHOW_OPTIONS,
  testValue
} from "../filters.js";

const context = {
  visibleColumns: () => [],
  isPending: () => false,
  isEditable: () => true,
  columnByTitle: () => null
};

test("Top-level instances hides nested rows while preserving top-level rows", () => {
  const state = {show: "topLevelInstances", values: {}, headers: {}, advanced: {rules: []}};
  assert.equal(rowPasses({IsNested: false}, state, context), true);
  assert.equal(rowPasses({IsNested: true}, state, context), false);
  assert.equal(rowPasses({}, state, context), true);
});

test("Top-level instances option has the requested label and tooltip", () => {
  const option = SHOW_OPTIONS.find(item => item.value === "topLevelInstances");
  assert.equal(SHOW_OPTIONS[1], option);
  assert.equal(option.label, "Top-level instances");
  assert.equal(option.tooltip, "Hides instances nested inside another family");
});

test("negative prefix and suffix operators are available and match case-insensitively", () => {
  assert.ok(OPERATORS.some(item => item.op === "notStartsWith" && item.label === "does not start with"));
  assert.ok(OPERATORS.some(item => item.op === "notEndsWith" && item.label === "does not end with"));
  assert.equal(testValue("notStartsWith", "Door 101", "door"), false);
  assert.equal(testValue("notStartsWith", "Room 101", "door"), true);
  assert.equal(testValue("notEndsWith", "Room 101", "101"), false);
  assert.equal(testValue("notEndsWith", "Room 101", "102"), true);
  assert.equal(testValue("notStartsWith", "Door 101", ""), true);
  assert.equal(testValue("notEndsWith", "Room 101", ""), true);
});

test("negative prefix and suffix builder conditions round-trip without wildcard conversion", () => {
  assert.deepEqual(parseTerm(expressionFor("notStartsWith", "*")), {
    op: "notStartsWith",
    value: "*"
  });
  assert.deepEqual(parseTerm(expressionFor("notEndsWith", "*")), {
    op: "notEndsWith",
    value: "*"
  });
  assert.equal(testValue("notStartsWith", "*Name", "*"), false);
  assert.equal(testValue("notStartsWith", "Name", "*"), true);
  assert.equal(testValue("notEndsWith", "Name*", "*"), false);
  assert.equal(testValue("notEndsWith", "Name", "*"), true);
});
