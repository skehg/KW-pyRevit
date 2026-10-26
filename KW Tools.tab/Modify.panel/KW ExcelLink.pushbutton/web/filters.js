// Filter logic for the ExcelLink grid. Kept free of DOM and Tabulator code so
// the same rules drive header filters, the master filter and hidden-row checks.

export var BLANK_KEY = "(Blanks)";
export var ROW_NUMBER_FIELD = "__rowNo";
export var ROW_NUMBER_TITLE = "#";

export var OPERATORS = [
  { op: "contains", label: "contains" },
  { op: "notContains", label: "does not contain" },
  { op: "equals", label: "equals" },
  { op: "notEquals", label: "does not equal" },
  { op: "startsWith", label: "starts with" },
  { op: "notStartsWith", label: "does not start with" },
  { op: "endsWith", label: "ends with" },
  { op: "notEndsWith", label: "does not end with" },
  { op: "gt", label: ">" },
  { op: "gte", label: "≥" },
  { op: "lt", label: "<" },
  { op: "lte", label: "≤" },
  { op: "between", label: "between", needsSecond: true },
  { op: "empty", label: "is empty", noValue: true },
  { op: "notEmpty", label: "is not empty", noValue: true },
  { op: "wildcard", label: "matches wildcard (* ?)" },
  { op: "regex", label: "matches regex" }
];

export var SHOW_OPTIONS = [
  { value: "all", label: "All rows" },
  {
    value: "topLevelInstances",
    label: "Top-level instances",
    tooltip: "Hides instances nested inside another family"
  },
  { value: "pending", label: "Rows with pending changes" },
  { value: "notPending", label: "Rows without pending changes" },
  { value: "editable", label: "Rows with editable cells" },
  { value: "readOnly", label: "Read-only rows" },
  { value: "typeRows", label: "Type rows" },
  { value: "instanceRows", label: "Instance rows" }
];

export function emptyFilters() {
  return {
    search: "",
    show: "all",
    headers: {},
    values: {},
    advanced: { join: "and", rules: [] }
  };
}

export function cloneFilters(source) {
  var base = emptyFilters();
  if (!source || typeof source !== "object") { return base; }
  base.search = typeof source.search === "string" ? source.search : "";
  base.show = SHOW_OPTIONS.some(function (item) { return item.value === source.show; })
    ? source.show : "all";
  Object.keys(source.headers || {}).forEach(function (title) {
    var value = source.headers[title];
    if (typeof value === "string" && value.trim()) { base.headers[title] = value; }
  });
  Object.keys(source.values || {}).forEach(function (title) {
    if (Array.isArray(source.values[title])) {
      base.values[title] = source.values[title].map(String);
    }
  });
  base.advanced = cloneGroup(source.advanced);
  return base;
}

function cloneGroup(group) {
  var result = { join: group && group.join === "or" ? "or" : "and", rules: [] };
  ((group && group.rules) || []).forEach(function (rule) {
    if (!rule || typeof rule !== "object") { return; }
    if (Array.isArray(rule.rules)) {
      result.rules.push(cloneGroup(rule));
    } else if (rule.title && OPERATORS.some(function (item) { return item.op === rule.op; })) {
      result.rules.push({
        title: String(rule.title),
        op: rule.op,
        value: rule.value == null ? "" : String(rule.value),
        value2: rule.value2 == null ? "" : String(rule.value2)
      });
    }
  });
  return result;
}

export function countRules(group) {
  return ((group && group.rules) || []).reduce(function (total, rule) {
    return total + (Array.isArray(rule.rules) ? countRules(rule) : 1);
  }, 0);
}

export function hasActiveFilters(state) {
  if (!state) { return false; }
  return !!(state.search && state.search.trim()) ||
    state.show !== "all" ||
    Object.keys(state.headers).some(function (title) { return state.headers[title].trim(); }) ||
    Object.keys(state.values).length > 0 ||
    countRules(state.advanced) > 0;
}

export function valueKey(value) {
  return value === null || value === undefined || value === "" ? BLANK_KEY : String(value);
}

function isBlank(value) {
  return value === null || value === undefined || String(value).trim() === "";
}

function toNumber(value) {
  if (typeof value === "number") { return Number.isFinite(value) ? value : null; }
  if (typeof value === "boolean") { return value ? 1 : 0; }
  if (value === null || value === undefined) { return null; }
  var text = String(value).trim().replace(/,/g, "");
  if (!text || !/^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/.test(text)) { return null; }
  return Number(text);
}

function text(value) {
  return isBlank(value) ? "" : String(value).toLowerCase();
}

function compare(cell, operand) {
  var a = toNumber(cell);
  var b = toNumber(operand);
  if (a !== null && b !== null) { return a === b ? 0 : (a < b ? -1 : 1); }
  return String(cell == null ? "" : cell).localeCompare(String(operand), undefined, {
    numeric: true,
    sensitivity: "base"
  });
}

function equalValues(cell, operand) {
  var a = toNumber(cell);
  var b = toNumber(operand);
  if (a !== null && b !== null) {
    return Math.abs(a - b) <= 1e-9 * Math.max(1, Math.abs(a), Math.abs(b));
  }
  return text(cell) === String(operand).toLowerCase();
}

var regexCache = new Map();

function cachedRegex(source, flags) {
  var key = flags + "/" + source;
  if (!regexCache.has(key)) {
    var compiled;
    try { compiled = new RegExp(source, flags); } catch (error) { compiled = null; }
    if (regexCache.size > 500) { regexCache.clear(); }
    regexCache.set(key, compiled);
  }
  return regexCache.get(key);
}

function wildcardRegex(pattern) {
  var source = pattern.replace(/[.+^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*").replace(/\?/g, ".");
  return cachedRegex("^" + source + "$", "i");
}

// Tests one cell value against an operator. Unknown or invalid input passes so a
// half-typed filter never hides everything.
export function testValue(op, cell, operand, operand2) {
  operand = operand == null ? "" : String(operand);
  switch (op) {
    case "empty": return isBlank(cell);
    case "notEmpty": return !isBlank(cell);
    case "contains": return !operand || text(cell).indexOf(operand.toLowerCase()) >= 0;
    case "notContains": return !operand || text(cell).indexOf(operand.toLowerCase()) < 0;
    case "equals": return equalValues(cell, operand);
    case "notEquals": return !equalValues(cell, operand);
    case "startsWith": return text(cell).indexOf(operand.toLowerCase()) === 0;
    case "notStartsWith": return !testValue("startsWith", cell, operand);
    case "endsWith":
      return text(cell).slice(-operand.length) === operand.toLowerCase();
    case "notEndsWith": return !testValue("endsWith", cell, operand);
    case "gt": return operand === "" || (!isBlank(cell) && compare(cell, operand) > 0);
    case "gte": return operand === "" || (!isBlank(cell) && compare(cell, operand) >= 0);
    case "lt": return operand === "" || (!isBlank(cell) && compare(cell, operand) < 0);
    case "lte": return operand === "" || (!isBlank(cell) && compare(cell, operand) <= 0);
    case "between": {
      if (isBlank(cell)) { return false; }
      var low = operand;
      var high = operand2 == null ? "" : String(operand2);
      if (low !== "" && high !== "" && compare(low, high) > 0) {
        var swap = low; low = high; high = swap;
      }
      return (low === "" || compare(cell, low) >= 0) && (high === "" || compare(cell, high) <= 0);
    }
    case "wildcard": {
      var wildcard = wildcardRegex(operand);
      return !operand || !wildcard || wildcard.test(isBlank(cell) ? "" : String(cell));
    }
    case "regex": {
      var regex = cachedRegex(operand, "i");
      return !operand || !regex || regex.test(isBlank(cell) ? "" : String(cell));
    }
    default: return true;
  }
}

// Header filter syntax (Excel-like, case-insensitive):
//   text contains · =x equals · = empty · != not empty · !=x / <>x not equal ·
//   !x does not contain · >x >=x <x <=x · a..b between · ^x starts · x$ ends ·
//   * ? wildcards · /regex/ · a|b either · 'text literal contains.
export function parseTerm(term) {
  var trimmed = term.trim();
  var match;
  if (!trimmed) { return null; }
  if (trimmed === "=") { return { op: "empty" }; }
  if (trimmed === "!=" || trimmed === "<>") { return { op: "notEmpty" }; }
  if ((match = /^(>=|<=|<>|!=|>|<|=)\s*(.*)$/.exec(trimmed))) {
    var ops = { ">=": "gte", "<=": "lte", "<>": "notEquals", "!=": "notEquals", ">": "gt", "<": "lt", "=": "equals" };
    return { op: ops[match[1]], value: match[2] };
  }
  if (trimmed.charAt(0) === "!") { return { op: "notContains", value: trimmed.slice(1).trim() }; }
  if ((match = /^(.*?)\s*\.\.\s*(.*)$/.exec(trimmed)) && (match[1] || match[2])) {
    return { op: "between", value: match[1], value2: match[2] };
  }
  var starts = trimmed.charAt(0) === "^";
  var ends = trimmed.length > 1 && trimmed.charAt(trimmed.length - 1) === "$";
  if (starts && ends) { return { op: "equals", value: trimmed.slice(1, -1) }; }
  if (starts) { return { op: "startsWith", value: trimmed.slice(1) }; }
  if (ends) { return { op: "endsWith", value: trimmed.slice(0, -1) }; }
  if (/[*?]/.test(trimmed)) { return { op: "wildcard", value: trimmed }; }
  return { op: "contains", value: trimmed };
}

var expressionCache = new Map();

// Returns a predicate for a header expression, or null when it filters nothing.
export function compileExpression(expression) {
  var source = expression == null ? "" : String(expression);
  if (expressionCache.has(source)) { return expressionCache.get(source); }
  var trimmed = source.trim();
  var predicate = null;
  var regexMatch = /^\/(.+)\/([a-z]*)$/.exec(trimmed);
  if (regexMatch) {
    var flags = Array.from(new Set((regexMatch[2] + "i").replace(/[^imsu]/g, "").split(""))).join("");
    var regex = cachedRegex(regexMatch[1], flags);
    predicate = regex ? function (value) { return regex.test(isBlank(value) ? "" : String(value)); } : null;
  } else if (trimmed.charAt(0) === "'") {
    var literal = trimmed.slice(1);
    predicate = literal ? function (value) { return testValue("contains", value, literal); } : null;
  } else if (trimmed) {
    var terms = trimmed.split("|").map(parseTerm).filter(Boolean);
    if (terms.length) {
      predicate = function (value) {
        return terms.some(function (term) {
          return testValue(term.op, value, term.value, term.value2);
        });
      };
    }
  }
  if (expressionCache.size > 500) { expressionCache.clear(); }
  expressionCache.set(source, predicate);
  return predicate;
}

// Turns a builder condition into header filter text that parses back the same way.
export function expressionFor(op, value, value2) {
  value = value == null ? "" : String(value);
  value2 = value2 == null ? "" : String(value2);
  switch (op) {
    case "empty": return "=";
    case "notEmpty": return "!=";
    case "equals": return value ? "=" + value : "=";
    case "notEquals": return value ? "!=" + value : "!=";
    case "gt": return ">" + value;
    case "gte": return ">=" + value;
    case "lt": return "<" + value;
    case "lte": return "<=" + value;
    case "between": return value + ".." + value2;
    case "startsWith": return "^" + value;
    case "endsWith": return value + "$";
    case "notContains": return "!" + value;
    case "wildcard": return value;
    case "regex": return "/" + value.replace(/\//g, "\\/") + "/";
    default:
      return /^[=!<>^'/]|[|*?$]|\.\./.test(value) ? "'" + value : value;
  }
}

export function describeExpression(expression) {
  var compact = String(expression).trim();
  return compact.length > 28 ? compact.slice(0, 27) + "…" : compact;
}

function evaluateGroup(group, row, columnByTitle) {
  var rules = (group.rules || []).filter(function (rule) {
    return Array.isArray(rule.rules) ? countRules(rule) > 0 : !!columnByTitle(rule.title);
  });
  if (!rules.length) { return true; }
  var test = function (rule) {
    if (Array.isArray(rule.rules)) { return evaluateGroup(rule, row, columnByTitle); }
    var column = columnByTitle(rule.title);
    return testValue(rule.op, row[column.field], rule.value, rule.value2);
  };
  return group.join === "or" ? rules.some(test) : rules.every(test);
}

// Full row test against a sheet's filter state. `context` supplies helpers that
// depend on grid state: columnByTitle, visibleColumns, isPending, isEditable.
// `options.skipHeaders` lets Tabulator evaluate header filters itself;
// `options.excludeTitle` ignores one column's filters (for the value checklist).
export function rowPasses(row, state, context, options) {
  options = options || {};
  if (!state) { return true; }
  var search = (state.search || "").trim().toLowerCase();
  if (search) {
    var haystack = context.visibleColumns().map(function (column) {
      return text(row[column.field]);
    }).join("\u0001");
    var words = search.split(/\s+/);
    for (var w = 0; w < words.length; w += 1) {
      if (haystack.indexOf(words[w]) < 0) { return false; }
    }
  }
  switch (state.show) {
    case "pending": if (!context.isPending(row)) { return false; } break;
    case "notPending": if (context.isPending(row)) { return false; } break;
    case "editable": if (!context.isEditable(row)) { return false; } break;
    case "readOnly": if (context.isEditable(row)) { return false; } break;
    case "typeRows": if (!row.IsTypeRow) { return false; } break;
    case "instanceRows": if (row.IsTypeRow) { return false; } break;
    case "topLevelInstances": if (row.IsNested) { return false; } break;
    default: break;
  }
  var titles = Object.keys(state.values);
  for (var v = 0; v < titles.length; v += 1) {
    if (titles[v] === options.excludeTitle) { continue; }
    var valueColumn = context.columnByTitle(titles[v]);
    if (valueColumn && state.values[titles[v]].indexOf(valueKey(row[valueColumn.field])) < 0) {
      return false;
    }
  }
  if (!options.skipHeaders) {
    var headerTitles = Object.keys(state.headers);
    for (var h = 0; h < headerTitles.length; h += 1) {
      if (headerTitles[h] === options.excludeTitle) { continue; }
      var headerColumn = context.columnByTitle(headerTitles[h]);
      var predicate = headerColumn && compileExpression(state.headers[headerTitles[h]]);
      if (predicate && !predicate(row[headerColumn.field])) { return false; }
    }
  }
  return evaluateGroup(state.advanced, row, context.columnByTitle);
}
