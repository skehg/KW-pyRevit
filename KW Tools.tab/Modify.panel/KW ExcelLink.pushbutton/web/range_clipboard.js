// Values-only clipboard parsing and paste planning; no grid mutations here.
export function parseTSV(text) {
  var rows = [[]], value = "", quoted = false, closed = false;
  text = String(text).replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  for (var i = 0; i < text.length; i += 1) {
    var ch = text[i];
    if (quoted) {
      if (ch === '"' && text[i + 1] === '"') { value += '"'; i += 1; }
      else if (ch === '"') { quoted = false; closed = true; }
      else { value += ch; }
    } else if (ch === '"' && !value && !closed) {
      quoted = true;
    } else if (ch === "\t" || ch === "\n") {
      rows[rows.length - 1].push(value);
      value = ""; closed = false;
      if (ch === "\n") { rows.push([]); }
    } else {
      if (closed) { throw new Error("Invalid quoted clipboard value."); }
      value += ch;
    }
  }
  if (quoted) { throw new Error("Unclosed quoted clipboard value."); }
  rows[rows.length - 1].push(value);
  if (text.endsWith("\n")) { rows.pop(); }
  if (!rows.length || !rows[0].length ||
      rows.some(function (row) { return row.length !== rows[0].length; })) {
    throw new Error("Paste a rectangular block of cells.");
  }
  return rows;
}

export function formulaLike(value) {
  var text = String(value).trim();
  return /^[=+@-]/.test(text) && !/^[+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?$/i.test(text);
}

export function copyTSV(values) {
  return values.map(function (row) {
    return row.map(function (value) {
      var text = value == null ? "" : String(value);
      // Excel must not interpret literal text as a formula.
      if (formulaLike(text)) { text = "'" + text; }
      return /[\t\n\r"]/.test(text) ? '"' + text.replace(/"/g, '""') + '"' : text;
    }).join("\t");
  }).join("\r\n");
}

export function pasteValue(raw, column) {
  if (formulaLike(raw)) {
    throw new Error("Formulas are not accepted. Copy calculated values from Excel.");
  }
  if (column.storageType === "Double" || column.storageType === "Integer") {
    var text = raw.trim();
    if (!/^[+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?$/i.test(text)) {
      throw new Error("Enter a number in project display units (no unit suffix or thousands separator).");
    }
    var value = Number(text);
    if (!Number.isFinite(value) ||
        (column.storageType === "Integer" && (!Number.isInteger(value) ||
         value < -2147483648 || value > 2147483647))) {
      throw new Error("Number is outside the parameter's supported range.");
    }
    return value;
  }
  if (column.storageType === "ElementId") {
    var matches = (column.options || []).filter(function (value) { return value === raw; });
    if (matches.length !== 1) { throw new Error("Choose an exact, unambiguous reference name from this column's dropdown."); }
  }
  if (column.target === "typeName" && !raw.trim()) { throw new Error("Type names cannot be blank."); }
  return raw;
}

export function planPaste(matrix, rows, columns, startRow, startColumn, editable, changeKey) {
  if (startRow < 0 || startColumn < 0 ||
      startRow + matrix.length > rows.length ||
      startColumn + matrix[0].length > columns.length) {
    throw new Error("The pasted block exceeds the visible grid. No cells were changed.");
  }
  var changes = new Map(), skipped = 0, typeRows = new Set();
  matrix.forEach(function (values, r) {
    values.forEach(function (raw, c) {
      var row = rows[startRow + r], column = columns[startColumn + c];
      if (!editable(column, row)) { skipped += 1; return; }
      var value;
      try { value = pasteValue(raw, column); }
      catch (error) { throw new Error("Paste row " + (r + 1) + ", column " + (c + 1) +
        " (" + column.title + "): " + error.message); }
      var key = changeKey(row, column);
      if (changes.has(key) && changes.get(key).value !== value) {
        throw new Error("Conflicting pasted values for shared type parameter " + column.title +
          ". No cells were changed.");
      }
      changes.set(key, {row: row, column: column, value: value});
      if (column.target === "type" || column.target === "typeName") { typeRows.add(row.TypeElementId); }
    });
  });
  return {changes: Array.from(changes.values()), skipped: skipped, types: typeRows.size};
}
