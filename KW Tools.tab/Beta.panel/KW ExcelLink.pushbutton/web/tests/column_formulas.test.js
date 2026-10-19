import test from "node:test";
import assert from "node:assert/strict";
import { cleanFormulas, expandFormula, validateResult } from "../column_formulas.js";

const titles = ["Name", "Width", "Height", "Result"];

test("relative rows use original row numbers, including ranges", () => {
  assert.equal(expandFormula("=SUM(B1:C1)+B2", 7, titles, titles), "=SUM(B7:C7)+B8");
});

test("absolute rows and quoted references stay fixed", () => {
  assert.equal(expandFormula('=$B$1+B$2+$C1&"B1""C1"', 5, titles, titles),
    '=$B$1+B$2+$C5&"B1""C1"');
});

test("saved column titles remap references after a layout change", () => {
  assert.equal(expandFormula("=B1*C1", 3, titles, ["Height", "Result", "Width", "Name"]), "=C3*A3");
  assert.throws(() => expandFormula("=B1", 1, titles, ["Name"]), /missing: Width/);
  assert.throws(() => expandFormula("=Z1", 1, titles, titles), /missing/);
});

test("function names containing digits are not references", () => {
  assert.equal(expandFormula("=LOG10(B1)+ATAN2(B1,C1)", 2, titles, titles), "=LOG10(B2)+ATAN2(B2,C2)");
});

test("malformed templates are rejected and preset rules are cloned", () => {
  assert.throws(() => expandFormula("B1", 1, titles, titles), /Start/);
  const source = { Result: { expression: " =B1 ", columns: titles, scope: "all" }, Bad: { expression: "x" } };
  const clean = cleanFormulas(source);
  assert.deepEqual(Object.keys(clean), ["Result"]);
  assert.equal(clean.Result.expression, "=B1");
  assert.notEqual(clean.Result.columns, titles);
  assert.equal(cleanFormulas(null).Result, undefined);
});

test("formula results must be finite scalars valid for their parameter", () => {
  assert.equal(validateResult("42", "Double"), 42);
  assert.equal(validateResult(42, "String"), "42");
  assert.equal(validateResult(42, "Integer"), 42);
  for (const value of [NaN, Infinity, "", "   ", "oops", true]) {
    assert.throws(() => validateResult(value, "Double"), /finite/);
  }
  assert.throws(() => validateResult(1.5, "Integer"), /integer/);
  for (const value of [null, undefined, [], {}]) {
    assert.throws(() => validateResult(value, "String"), /single value/);
  }
  assert.throws(() => validateResult(new Error("#VALUE!"), "Double"), /#VALUE!/);
});
