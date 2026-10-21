import test from "node:test";
import assert from "node:assert/strict";
import { cleanFormulas, expandFormula, formulaEligible, normalizeFormula, validateResult } from "../column_formulas.js";

const titles = ["Name", "Width", "Height", "Result"];

test("formula columns follow mode while retaining editability and reference restrictions", () => {
  const column = {target: "type", formulaAllowed: true, editable: true, storageType: "Double"};
  assert.equal(formulaEligible(column, "Types Mode"), true);
  assert.equal(formulaEligible(column, "Instances Mode"), false);
  assert.equal(formulaEligible({...column, target: "instance"}, "Instances Mode"), true);
  assert.equal(formulaEligible({...column, target: "instance"}, "Types Mode"), false);
  assert.equal(formulaEligible({...column, target: "typeName"}, "Types Mode"), true);
  assert.equal(formulaEligible({...column, target: "typeName"}, "Instances Mode"), false);
  for (const blocked of [
    {formulaAllowed: false}, {editable: false}, {disabled: true}, {storageType: "ElementId"},
  ]) {
    assert.equal(formulaEligible({...column, ...blocked}, "Types Mode"), false);
    assert.equal(formulaEligible({...column, target: "instance", ...blocked}, "Instances Mode"), false);
  }
});

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

test("formula bar accepts expressions with or without a leading equals sign", () => {
  for (const expression of ["B1*2", "=B1*2", " B1*2 ", " =B1*2 "]) {
    assert.equal(normalizeFormula(expression), "=B1*2");
    assert.equal(expandFormula(expression, 3, titles, titles), "=B3*2");
  }
  assert.equal(expandFormula('"Panel "&B1', 2, titles, titles), '="Panel "&B2');
  assert.equal(expandFormula("SUM(B1:C1)", 2, titles, titles), "=SUM(B2:C2)");
  for (const expression of ["", " ", "=", " = ", null, undefined]) {
    assert.throws(() => normalizeFormula(expression), /Enter a formula/);
    assert.throws(() => expandFormula(expression, 1, titles, titles), /Enter a formula/);
  }
  const stored = {Result: {expression: normalizeFormula("B1*2"), columns: titles, scope: "all"}};
  assert.equal(cleanFormulas(stored).Result.expression, "=B1*2");
});

test("preset rules are cloned", () => {
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
  assert.equal(validateResult("  Panel 1200  ", null, "typeName"), "Panel 1200");
  assert.equal(validateResult(42, null, "typeName"), "42");
  assert.throws(() => validateResult(" ", null, "typeName"), /blank/);
  assert.throws(() => validateResult("Invalid|Name", null, "typeName"), /prohibited/);
});
