import {literalValue} from "./range_clipboard.js";

export function editValue(raw, column) {
  if (raw.trim().startsWith("=")) {
    if (!column.formulaAllowed || column.storageType === "ElementId") {
      throw new Error("Formulas are disabled for this column.");
    }
    return raw;
  }
  return literalValue(raw, column);
}

export function navigationTarget(rows, fields, rowId, field, key, backwards) {
  var r = rows.findIndex(row => row.getData().UniqueId === rowId);
  var c = fields.indexOf(field);
  if (r < 0 || c < 0) { return null; }
  var direction = backwards ? -1 : 1;
  if (key === "Enter") { r += direction; }
  else {
    c += direction;
    if (c === fields.length) { c = 0; r += 1; }
    if (c < 0) { c = fields.length - 1; r -= 1; }
  }
  return r >= 0 && r < rows.length ? rows[r].getCell(fields[c]) : null;
}

export function scalarEditor(column, showError) {
  return function (cell, onRendered, success, cancel) {
    var input = document.createElement("input");
    input.type = "text";
    input.setAttribute("aria-label", column.title);
    input.style.cssText = "padding:4px;width:100%;height:100%;box-sizing:border-box";
    var original = cell.getValue();
    input.value = original == null ? "" : String(original);
    var finished = false;
    function commit() {
      if (finished) { return; }
      var value;
      try { value = editValue(input.value, column); }
      catch (error) {
        input.setAttribute("aria-invalid", "true");
        showError(error.message);
        input.focus({preventScroll: true});
        return;
      }
      finished = true;
      if (value === original) { cancel(); }
      else { success(value); }
    }
    onRendered(function () {
      input.focus({preventScroll: true});
      input.select();
    });
    input.addEventListener("blur", commit);
    input.addEventListener("keydown", function (event) {
      if (event.isComposing || event.keyCode === 229) { return; }
      if (event.key === "Enter") { commit(); }
      if (event.key === "Escape") { finished = true; cancel(); }
    });
    return input;
  };
}
