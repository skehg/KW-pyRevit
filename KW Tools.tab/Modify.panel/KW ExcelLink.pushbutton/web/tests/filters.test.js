import test from "node:test";
import assert from "node:assert/strict";
import {rowPasses, SHOW_OPTIONS} from "../filters.js";

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
