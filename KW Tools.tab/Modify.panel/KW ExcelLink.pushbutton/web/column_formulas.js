// Templates are written for row #1; quoted strings and absolute rows stay fixed.
export function expandFormula(expression, rowNumber, savedTitles, currentTitles) {
  if (typeof expression !== "string" || !expression.trim().startsWith("=")) {
    throw new Error("Start the column formula with =.");
  }
  function index(letters) {
    return letters.toUpperCase().split("").reduce((n, c) => n * 26 + c.charCodeAt(0) - 64, 0) - 1;
  }
  function letters(n) {
    var text = "";
    for (n += 1; n > 0; n = Math.floor((n - 1) / 26)) {
      text = String.fromCharCode(65 + (n - 1) % 26) + text;
    }
    return text;
  }
  return expression.trim().split(/("(?:[^"]|"")*")/g).map(function (part, i) {
    if (i % 2) { return part; }
    return part.replace(/(\$?)([A-Za-z]+)(\$?)([1-9][0-9]*)\b(?!\s*\()/g,
      function (match, fixedColumn, column, fixedRow, row, offset, source) {
        if (offset && /[A-Za-z0-9_.]/.test(source[offset - 1])) { return match; }
        var title = savedTitles[index(column)];
        var next = currentTitles.indexOf(title);
        if (!title || next < 0) { throw new Error("Referenced column is missing: " + (title || column)); }
        return fixedColumn + letters(next) + fixedRow + (Number(row) + (fixedRow ? 0 : rowNumber - 1));
      });
  }).join("");
}

export function cleanFormulas(value) {
  var result = {};
  if (!value || typeof value !== "object" || Array.isArray(value)) { return result; }
  Object.keys(value).forEach(function (title) {
    var rule = value[title];
    if (!rule || typeof rule.expression !== "string" || !rule.expression.trim().startsWith("=") ||
        !Array.isArray(rule.columns) || !rule.columns.every(t => typeof t === "string")) { return; }
    result[title] = {
      expression: rule.expression.trim(),
      columns: rule.columns.slice(),
      scope: rule.scope === "all" ? "all" : "visible"
    };
  });
  return result;
}

export function validateResult(value, storageType) {
  if (value instanceof Error || value === undefined || value === null ||
      (typeof value !== "number" && typeof value !== "string" && typeof value !== "boolean")) {
    throw new Error(value instanceof Error ? value.message : "Formula must return a single value.");
  }
  if (storageType === "Double" || storageType === "Integer") {
    if ((typeof value === "string" && !value.trim()) || typeof value === "boolean" ||
        !Number.isFinite(Number(value)) ||
        (storageType === "Integer" && !Number.isInteger(Number(value)))) {
      throw new Error("Formula must return a finite " + (storageType === "Integer" ? "integer." : "number."));
    }
    return Number(value);
  }
  return String(value);
}
