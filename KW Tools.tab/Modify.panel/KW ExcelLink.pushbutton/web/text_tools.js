// Pure text transforms and validation, shared by the range menu and Edit menu.
export function changeCase(value, mode) {
  switch (mode) {
    case "upper": return value.toUpperCase();
    case "lower": return value.toLowerCase();
    case "title":
      return value.toLowerCase().replace(/\p{L}[\p{L}\p{M}\p{N}'\u2019]*/gu,
        function (word) { return word.replace(/^\p{L}/u, function (letter) { return letter.toUpperCase(); }); });
    case "sentence": {
      var capitalize = true;
      return Array.from(value.toLowerCase()).map(function (letter) {
        if (/[.!?]/.test(letter)) { capitalize = true; }
        if (/\p{L}/u.test(letter) && capitalize) {
          capitalize = false;
          return letter.toUpperCase();
        }
        return letter;
      }).join("");
    }
    default: throw new Error("Choose a supported case conversion.");
  }
}

export function textReplacement(find, replacement, matchCase, wholeCell, useRegex) {
  if (!find) { throw new Error("Enter text to find."); }
  var source = useRegex ? find : find.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  var pattern;
  try {
    pattern = new RegExp(wholeCell ? "^(?:" + source + ")(?![\\s\\S])" : source, matchCase ? "gu" : "giu");
  } catch (exc) {
    throw new Error("Invalid regular expression: " + exc.message);
  }
  return function (value) {
    // Only regex mode expands capture groups and other replacement tokens.
    return value.replace(pattern, useRegex ? replacement : function () { return replacement; });
  };
}

export function textScopeCells(scope, selected, rows, columns) {
  if (scope === "selected") {
    if (!selected.length) { throw new Error("Select a range, or choose All visible cells."); }
    return selected;
  }
  if (scope === "columns") {
    var fields = new Set(selected.filter(function (cell) { return !!cell.column; }).map(function (cell) {
      return cell.column.field;
    }));
    if (!fields.size) { throw new Error("Select a cell or range to choose the current column(s)."); }
    columns = columns.filter(function (column) { return fields.has(column.field); });
  } else if (scope !== "visible") {
    throw new Error("Choose a supported text scope.");
  }
  var cells = [];
  rows.forEach(function (row) {
    columns.forEach(function (column) { cells.push({row: row, column: column}); });
  });
  return cells;
}

export function planTextChanges(cells, transform, editable, changeKey) {
  var changes = new Map(), types = new Set(), skipped = 0, unchanged = 0;
  cells.forEach(function (cell) {
    var row = cell.row, column = cell.column;
    if (!column || !editable(column, row) ||
        (column.storageType !== "String" && column.target !== "typeName") ||
        typeof row[column.field] !== "string") {
      skipped += 1;
      return;
    }
    var before = row[column.field], value = transform(before);
    if (column.target === "typeName" && !value.trim()) {
      throw new Error("The operation would create a blank type name. No changes were staged.");
    }
    var key = changeKey(row, column);
    // Include unchanged candidates in conflict checks: one type cannot have two results.
    if (changes.has(key) && changes.get(key).value !== value) {
      throw new Error("Conflicting results for shared type parameter " + column.title +
        ". No changes were staged.");
    }
    changes.set(key, {row: row, column: column, value: value, before: before});
    if (value === before) { unchanged += 1; }
  });
  var edited = Array.from(changes.values()).filter(function (change) {
    return change.value !== change.before;
  });
  edited.forEach(function (change) {
    if (change.column.target === "type" || change.column.target === "typeName") {
      types.add(String(change.row.TypeElementId));
    }
  });
  return {changes: edited, skipped: skipped, unchanged: unchanged, types: types.size};
}
