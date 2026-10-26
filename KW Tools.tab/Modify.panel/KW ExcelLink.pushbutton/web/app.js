import { TabulatorFull as Tabulator } from "tabulator-tables";
import * as formulajs from "@formulajs/formulajs";
import "tabulator-tables/dist/css/tabulator.min.css";
import * as F from "./filters.js";
import * as CF from "./column_formulas.js";
import * as RC from "./range_clipboard.js";
import * as TT from "./text_tools.js";
import * as SS from "./spreadsheet.js";
import * as TN from "./type_names.js";
import {cellColumn, typeLabel} from "./cell_metadata.js";

(function () {
  "use strict";

  var workbook = null;
  var table = null;
  var tableReady = false;
  var pendingChanges = new Map();
  var originalValues = new Map();
  var importNotice = "";
  var formulaValues = new Map();
  var formulaTexts = new Map();
  var formulaEvaluationStack = new Set();
  var undoHistory = [];
  var redoHistory = [];
  var HISTORY_LIMIT = 75;
  var activeSheetIndex = 0;
  var typeNameConflicts = new Map();
  var applyingChanges = false;
  // Per-category column widths (only user-resized ones) and sorting, keyed by column title.
  var layoutState = new Map();
  // Header filter events fire while columns are rebuilt; ignore them until restored.
  var restoringFilters = false;
  // Pending changes held back because their rows were filtered out at Apply time.
  var carryOver = [];
  var columnMenu = null;
  var ROW_NUMBER_COLUMN = {
    title: F.ROW_NUMBER_TITLE,
    field: F.ROW_NUMBER_FIELD,
    storageType: "Integer",
    columnType: "rowNumber"
  };
  var statusNode = document.getElementById("status");
  var sheetSelect = document.getElementById("sheetSelect");
  var startupTimer = null;

  function reportGridError(error) {
    var message = error && error.message ? error.message : String(error);
    showStatus("ExcelLink grid failed: " + message, true);
    console.error(error);
    post({ type: "clientError", message: message });
  }

  window.addEventListener("error", function (event) {
    reportGridError(event.error || event.message);
  });
  window.addEventListener("unhandledrejection", function (event) {
    reportGridError(event.reason);
  });

  function post(message) {
    if (window.chrome && window.chrome.webview) {
      window.chrome.webview.postMessage(message);
    } else {
      showStatus("This workbook grid must be opened inside Revit's WebView2 host.", true);
    }
  }

  function handleZoomReset(event) {
    if (!event.ctrlKey || event.altKey || event.shiftKey || event.metaKey ||
        (event.key !== "0" && event.code !== "Numpad0")) { return; }
    event.preventDefault();
    event.stopPropagation();
    post({ type: "resetZoom" });
  }
  document.addEventListener("keydown", handleZoomReset, true);

  function showStatus(message, isError) {
    if (typeNameConflicts.size) {
      message = typeNameConflicts.size + " type(s) have conflicting names — resolve before applying." +
        (message ? " " + message : "");
      isError = true;
    }
    statusNode.textContent = message || "";
    statusNode.className = isError ? "error" : (message ? "success" : "");
  }

  function currentSheet() {
    return workbook && workbook.sheets[activeSheetIndex];
  }

  function rowChangeKey(row, column) {
    var id = column.target === "type"
      ? row.TypeElementId
      : (column.target === "typeName" ? row.TypeElementId : row.ElementId);
    return [column.target, id, column.parameterKey || column.parameterName || "__TYPE_NAME__"].join("|");
  }

  function reportChangeCount() {
    refreshTypeNameConflicts();
    var count = pendingChanges.size;
    document.getElementById("changeCount").textContent =
      count ? count + " pending change" + (count === 1 ? "" : "s") : "No pending changes";
    document.getElementById("applyButton").disabled = count === 0 || typeNameConflicts.size > 0 || applyingChanges;
    updateHistoryButtons();
    if (tableReady) { scheduleFilterBar(); }
  }

  function proposedTypeNames(changes) {
    var names = new Map();
    changes.forEach(function (change) {
      if (change.target === "typeName") { names.set(String(change.typeElementId), String(change.value).trim()); }
    });
    return names;
  }

  function refreshTypeNameConflicts() {
    var previous = typeNameConflicts.size;
    typeNameConflicts = workbook
      ? TN.findNameConflicts(TN.nameRecords(workbook), proposedTypeNames(pendingChanges)) : new Map();
    if (tableReady) {
      table.getRows().forEach(function (row) {
        row.getCells().forEach(function (cell) {
          var column = findColumn(cell.getField());
          var conflict = column && column.target === "typeName"
            ? typeNameConflicts.get(String(row.getData().TypeElementId)) : null;
          cell.getElement().classList.toggle("name-conflict-cell", !!conflict);
          if (conflict) { cell.getElement().setAttribute("aria-invalid", "true"); }
          else { cell.getElement().removeAttribute("aria-invalid"); }
        });
      });
    }
    if (typeNameConflicts.size || previous) { showStatus(""); }
  }

  function cloneMap(map) {
    return new Map(map);
  }

  function captureEditState(targetWorkbook) {
    var source = targetWorkbook || workbook;
    if (source === workbook && tableReady && currentSheet()) {
      currentSheet().rows = table.getData();
    }
    var state = {
      pending: cloneMap(pendingChanges),
      original: cloneMap(originalValues),
      formulaTexts: cloneMap(formulaTexts),
      formulaValues: cloneMap(formulaValues),
      cells: new Map(),
      refs: new Map()
    };
    if (!source) { return state; }

    function addRowCell(sheetIndex, row, field, baselineKey) {
      var key = row.UniqueId + "|" + field;
      if (!state.refs.has(key)) {
        state.refs.set(key, { sheetIndex: sheetIndex, uniqueId: row.UniqueId,
          field: field, baselineKey: baselineKey });
      }
      state.cells.set(key, row[field]);
    }

    var formulaFieldsById = new Map();
    [state.formulaTexts, state.formulaValues].forEach(function (map) {
      map.forEach(function (value, formulaKey) {
        var separator = formulaKey.lastIndexOf("|");
        var uniqueId = formulaKey.slice(0, separator);
        var field = formulaKey.slice(separator + 1);
        if (!formulaFieldsById.has(uniqueId)) {
          formulaFieldsById.set(uniqueId, new Set());
        }
        formulaFieldsById.get(uniqueId).add(field);
      });
    });

    source.sheets.forEach(function (sheet, sheetIndex) {
      var changesByElementId = new Map();
      var changesByTypeId = new Map();
      state.pending.forEach(function (change, changeKey) {
        var column = sheetColumn(sheet, change.field);
        if (!column || column.target !== change.target) { return; }
        var shared = change.target === "type" || change.target === "typeName";
        var id = String(shared ? change.typeElementId : change.elementId);
        var index = shared ? changesByTypeId : changesByElementId;
        if (!index.has(id)) { index.set(id, []); }
        index.get(id).push({ field: change.field, changeKey: changeKey });
      });
      (sheet.rows || []).forEach(function (row) {
        (changesByElementId.get(String(row.ElementId)) || []).forEach(function (item) {
          addRowCell(sheetIndex, row, item.field, item.changeKey);
        });
        (changesByTypeId.get(String(row.TypeElementId)) || []).forEach(function (item) {
          addRowCell(sheetIndex, row, item.field, item.changeKey);
        });
        (formulaFieldsById.get(row.UniqueId) || []).forEach(function (field) {
          var column = sheetColumn(sheet, field);
          if (column) {
            addRowCell(sheetIndex, row, field, rowChangeKey(row, column));
          }
        });
      });
    });
    return state;
  }

  function completeHistoryPair(before, after) {
    var refs = new Map(before.refs);
    after.refs.forEach(function (ref, key) {
      if (!refs.has(key)) { refs.set(key, ref); }
    });
    refs.forEach(function (ref, key) {
      var baseline;
      if (before.original.has(ref.baselineKey)) {
        baseline = before.original.get(ref.baselineKey);
      } else if (after.original.has(ref.baselineKey)) {
        baseline = after.original.get(ref.baselineKey);
      } else if (before.cells.has(key)) {
        baseline = before.cells.get(key);
      } else {
        baseline = after.cells.get(key);
      }
      if (!before.cells.has(key)) { before.cells.set(key, baseline); }
      if (!after.cells.has(key)) { after.cells.set(key, baseline); }
      before.refs.set(key, ref);
      after.refs.set(key, ref);
    });
  }

  function mapDelta(before, after) {
    var delta = new Map();
    var keys = new Set(Array.from(before.keys()).concat(Array.from(after.keys())));
    keys.forEach(function (key) {
      var beforeHas = before.has(key);
      var afterHas = after.has(key);
      var beforeValue = before.get(key);
      var afterValue = after.get(key);
      if (beforeHas !== afterHas ||
          beforeValue !== afterValue) {
        delta.set(key, {
          before: { present: beforeHas, value: beforeValue },
          after: { present: afterHas, value: afterValue }
        });
      }
    });
    return delta;
  }

  function updateHistoryButtons() {
    var undoButton = document.getElementById("undoButton");
    var redoButton = document.getElementById("redoButton");
    if (!undoButton || !redoButton) { return; }
    undoButton.disabled = undoHistory.length === 0;
    redoButton.disabled = redoHistory.length === 0;
    undoButton.title = undoHistory.length
      ? "Undo: " + undoHistory[undoHistory.length - 1].label + " (Ctrl+Z)"
      : "Undo the last staged grid edit (Ctrl+Z)";
    redoButton.title = redoHistory.length
      ? "Redo: " + redoHistory[redoHistory.length - 1].label + " (Ctrl+Y)"
      : "Redo the last undone grid edit (Ctrl+Y)";
  }

  function clearEditHistory() {
    undoHistory = [];
    redoHistory = [];
    updateHistoryButtons();
  }

  function recordHistory(before, label, targetWorkbook) {
    var after = captureEditState(targetWorkbook);
    completeHistoryPair(before, after);
    var changes = {
      pending: mapDelta(before.pending, after.pending),
      original: mapDelta(before.original, after.original),
      formulaTexts: mapDelta(before.formulaTexts, after.formulaTexts),
      formulaValues: mapDelta(before.formulaValues, after.formulaValues),
      cells: mapDelta(before.cells, after.cells)
    };
    if (Object.keys(changes).every(function (key) {
      return changes[key].size === 0;
    })) { return; }
    var refs = new Map();
    changes.cells.forEach(function (change, key) {
      var ref = before.refs.get(key) || after.refs.get(key);
      if (ref) { refs.set(key, ref); }
    });
    undoHistory.push({ label: label, changes: changes, refs: refs });
    if (undoHistory.length > HISTORY_LIMIT) { undoHistory.shift(); }
    redoHistory = [];
    updateHistoryButtons();
  }

  function applyHistoryMap(map, changes, direction) {
    changes.forEach(function (change, key) {
      var state = change[direction];
      if (state.present) { map.set(key, state.value); }
      else { map.delete(key); }
    });
  }

  function applyHistoryEntry(entry, direction) {
    applyHistoryMap(pendingChanges, entry.changes.pending, direction);
    applyHistoryMap(originalValues, entry.changes.original, direction);
    applyHistoryMap(formulaTexts, entry.changes.formulaTexts, direction);
    applyHistoryMap(formulaValues, entry.changes.formulaValues, direction);
    formulaEvaluationStack.clear();
    entry.changes.cells.forEach(function (change, key) {
      var ref = entry.refs.get(key);
      var sheet = ref && workbook && workbook.sheets[ref.sheetIndex];
      if (!sheet) { return; }
      var row = (sheet.rows || []).find(function (item) {
        return item.UniqueId === ref.uniqueId;
      });
      if (row) { row[ref.field] = change[direction].value; }
    });
    reportChangeCount();
    if (tableReady && currentSheet()) {
      table.replaceData(currentSheet().rows).then(function () {
        table.refreshFilter();
        updateFilterBar();
      }).catch(reportGridError);
    }
  }

  function undoEdit() {
    var entry = undoHistory.pop();
    if (!entry) { return; }
    applyHistoryEntry(entry, "before");
    redoHistory.push(entry);
    updateHistoryButtons();
    showStatus("Undid " + entry.label + ". Changes remain staged; Apply Changes writes them to Revit.");
  }

  function redoEdit() {
    var entry = redoHistory.pop();
    if (!entry) { return; }
    applyHistoryEntry(entry, "after");
    undoHistory.push(entry);
    updateHistoryButtons();
    showStatus("Redid " + entry.label + ". Changes remain staged; Apply Changes writes them to Revit.");
  }

  function findColumn(field) {
    var columns = (currentSheet() || {}).columns || [];
    return columns.find(function (column) { return column.field === field; });
  }

  function layoutFor(sheet) {
    var key = String(sheet.categoryKey || sheet.categoryId || sheet.name);
    if (!layoutState.has(key)) {
      var saved = sheet.layout || {};
      layoutState.set(key, {
        widths: Object.assign({}, saved.widths || {}),
        sort: (saved.sort || []).slice(),
        formulas: CF.cleanFormulas(saved.formulas),
        filters: F.cloneFilters(saved.filters)
      });
    }
    return layoutState.get(key);
  }

  function filtersFor(sheet) {
    return layoutFor(sheet).filters;
  }

  // Filters and layouts are keyed by column title so they survive projects and presets.
  function columnByTitle(sheet, title) {
    if (title === F.ROW_NUMBER_TITLE) { return ROW_NUMBER_COLUMN; }
    return (sheet.columns || []).find(function (column) {
      return column.title === title && column.visible !== false;
    }) || null;
  }

  function columnForField(field) {
    return field === F.ROW_NUMBER_FIELD ? ROW_NUMBER_COLUMN : findColumn(field);
  }

  function visibleColumns(sheet) {
    return (sheet.columns || []).filter(function (column) { return column.visible !== false; });
  }

  function cellEditable(column, data) {
    return !!column.editable && !column.disabled &&
      !data[column.field + "__disabled"] &&
      (column.target !== "typeName" || data.TypeNameEditable !== false);
  }

  function isTrackedColumn(column) {
    return column.columnType === "parameter" || column.columnType === "typeName";
  }

  function filterContext(sheet) {
    var columns = visibleColumns(sheet);
    return {
      columnByTitle: function (title) { return columnByTitle(sheet, title); },
      visibleColumns: function () { return columns; },
      isPending: function (row) {
        return pendingChanges.size > 0 && columns.some(function (column) {
          return isTrackedColumn(column) && pendingChanges.has(rowChangeKey(row, column));
        });
      },
      isEditable: function (row) {
        return columns.some(function (column) { return cellEditable(column, row); });
      }
    };
  }

  // Copies the live Tabulator header filter text into the sheet's filter state.
  function syncHeaderFilters() {
    var sheet = currentSheet();
    if (!tableReady || !sheet || restoringFilters) { return; }
    var headers = {};
    table.getHeaderFilters().forEach(function (item) {
      var column = columnForField(item.field);
      var value = item.value == null ? "" : String(item.value);
      if (column && value.trim()) { headers[column.title] = value; }
    });
    filtersFor(sheet).headers = headers;
  }

  function captureSort(sheet) {
    if (!tableReady || !sheet || !sheet.columns) { return; }
    layoutFor(sheet).sort = table.getSorters().map(function (sorter) {
      var column = columnForField(sorter.field);
      return column ? { title: column.title, dir: sorter.dir } : null;
    }).filter(Boolean);
  }

  function captureLayout() {
    var sheet = currentSheet();
    if (!tableReady || !sheet || !sheet.columns) { return; }
    captureSort(sheet);
    syncHeaderFilters();
  }

  function applySort(sheet) {
    var sorters = sortedLevels(sheet).map(function (item) {
      var column = columnByTitle(sheet, item.title);
      return column ? { column: column.field, dir: item.dir } : null;
    }).filter(Boolean);
    table.setSort(sorters);
  }

  function letterToIndex(letters) {
    var value = 0;
    for (var i = 0; i < letters.length; i += 1) {
      value = value * 26 + letters.charCodeAt(i) - 64;
    }
    return value - 1;
  }

  function indexToLetters(index) {
    var value = index + 1;
    var result = "";
    while (value > 0) {
      var remainder = (value - 1) % 26;
      result = String.fromCharCode(65 + remainder) + result;
      value = Math.floor((value - 1) / 26);
    }
    return result;
  }

  function cellValue(address, rangeEnd) {
    address = address.replace(/\$/g, "");
    if (rangeEnd) { rangeEnd = rangeEnd.replace(/\$/g, ""); }
    var match = /^([A-Z]+)([1-9][0-9]*)$/i.exec(address);
    if (!match) { throw new Error("Invalid cell reference: " + address); }
    var columnIndex = letterToIndex(match[1].toUpperCase());
    var rowIndex = parseInt(match[2], 10) - 1;
    var rows = table.getData();
    var columns = currentSheet().columns.filter(function (column) {
      return column.visible !== false;
    });

    if (!rangeEnd) {
      var column = columns[columnIndex];
      // Formula rows follow the frozen "#" column, whatever the current sort or filter.
      var row = rows[rowIndex];
      if (row && row[F.ROW_NUMBER_FIELD] !== rowIndex + 1) {
        row = rows.find(function (item) { return item[F.ROW_NUMBER_FIELD] === rowIndex + 1; });
      }
      if (!column || !row) { return 0; }
      var key = row.UniqueId + "|" + column.field;
      if (formulaTexts.has(key)) {
        if (formulaEvaluationStack.has(key)) {
          throw new Error("Circular formula reference.");
        }
        formulaEvaluationStack.add(key);
        try {
          var formulaResult = evaluateFormula(
            formulaTexts.get(key),
            rowIndex,
            column.field
          );
          formulaValues.set(key, formulaResult);
          return formulaResult;
        } finally {
          formulaEvaluationStack.delete(key);
        }
      }
      if (formulaValues.has(key)) { return formulaValues.get(key); }
      var value = row[column.field];
      return value == null || value === "" ? 0 : value;
    }

    var endMatch = /^([A-Z]+)([1-9][0-9]*)$/i.exec(rangeEnd);
    if (!endMatch) { throw new Error("Invalid range reference: " + rangeEnd); }
    var endColumn = letterToIndex(endMatch[1].toUpperCase());
    var endRow = parseInt(endMatch[2], 10) - 1;
    var values = [];
    for (var r = Math.min(rowIndex, endRow); r <= Math.max(rowIndex, endRow); r += 1) {
      for (var c = Math.min(columnIndex, endColumn); c <= Math.max(columnIndex, endColumn); c += 1) {
        values.push(cellValue(indexToLetters(c) + (r + 1), null));
      }
    }
    return values;
  }

  function tokenize(source) {
    var pattern = /\s*(?:(\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)|("(?:[^"]|"")*")|(\$?[A-Za-z_][A-Za-z0-9_.$]*)|(<=|>=|<>|[+\-*/^&%=<>(),:]))/gy;
    var tokens = [];
    var offset = 0;
    while (offset < source.length) {
      pattern.lastIndex = offset;
      var match = pattern.exec(source);
      if (!match) { throw new Error("Unsupported formula near: " + source.slice(offset)); }
      offset = pattern.lastIndex;
      tokens.push(match[1] || match[2] || match[3] || match[4]);
    }
    return tokens;
  }

  function evaluateFormula(source, rowIndex, field) {
    var tokens = tokenize(source.replace(/^=/, ""));
    var cursor = 0;
    var depth = 0;

    function peek() { return tokens[cursor]; }
    function take() { return tokens[cursor++]; }
    function parseExpression() { return parseComparison(); }

    function parseComparison() {
      var left = parseConcat();
      while (["=", "<>", "<", ">", "<=", ">="].indexOf(peek()) >= 0) {
        var operator = take();
        var right = parseConcat();
        if (operator === "=") { left = left === right; }
        else if (operator === "<>") { left = left !== right; }
        else if (operator === "<") { left = left < right; }
        else if (operator === ">") { left = left > right; }
        else if (operator === "<=") { left = left <= right; }
        else { left = left >= right; }
      }
      return left;
    }

    function parseConcat() {
      var left = parseSum();
      while (peek() === "&") {
        take();
        left = String(left) + String(parseSum());
      }
      return left;
    }

    function parseSum() {
      var left = parseProduct();
      while (peek() === "+" || peek() === "-") {
        var operator = take();
        var right = parseProduct();
        left = operator === "+" ? Number(left) + Number(right) : Number(left) - Number(right);
      }
      return left;
    }

    function parseProduct() {
      var left = parsePower();
      while (peek() === "*" || peek() === "/" || peek() === "%") {
        var operator = take();
        var right = parsePower();
        if (operator === "*") { left = Number(left) * Number(right); }
        else if (operator === "/") { left = Number(left) / Number(right); }
        else { left = Number(left) % Number(right); }
      }
      return left;
    }

    function parsePower() {
      var left = parseUnary();
      if (peek() === "^") {
        take();
        left = Math.pow(Number(left), Number(parsePower()));
      }
      return left;
    }

    function parseUnary() {
      if (peek() === "+") { take(); return Number(parseUnary()); }
      if (peek() === "-") { take(); return -Number(parseUnary()); }
      return parsePrimary();
    }

    function parsePrimary() {
      var token = take();
      if (token === undefined) { throw new Error("Formula ended unexpectedly."); }
      if (token === "(") {
        depth += 1;
        if (depth > 40) { throw new Error("Formula nesting is too deep."); }
        var value = parseExpression();
        if (take() !== ")") { throw new Error("Expected a closing parenthesis."); }
        depth -= 1;
        return value;
      }
      if (token.charAt(0) === '"') { return token.slice(1, -1).replace(/""/g, '"'); }
      if (/^\d/.test(token)) { return Number(token); }
      if (/^\$?[A-Za-z]+\$?[1-9][0-9]*$/.test(token)) {
        var end = null;
        if (peek() === ":") { take(); end = take(); }
        return cellValue(token, end);
      }
      if (/^[A-Za-z_]/.test(token) && peek() === "(") {
        take();
        var args = [];
        if (peek() !== ")") {
          do {
            args.push(parseExpression());
            if (peek() !== ",") { break; }
            take();
          } while (true);
        }
        if (take() !== ")") { throw new Error("Expected a function closing parenthesis."); }
        var library = formulajs;
        var functionName = token.toUpperCase();
        if (!library || typeof library[functionName] !== "function") {
          throw new Error("Formula function is unavailable: " + functionName);
        }
        var functionResult = library[functionName].apply(null, args);
        if (functionResult instanceof Error) { throw functionResult; }
        return functionResult;
      }
      throw new Error("Unsupported formula token: " + token);
    }

    var result = parseExpression();
    if (cursor !== tokens.length) { throw new Error("Unexpected formula input."); }
    if (result instanceof Error) { throw result; }
    if (typeof result === "number" && !Number.isFinite(result)) {
      throw new Error("Formula result is not finite.");
    }
    return result;
  }

  function buildChange(row, column, value) {
    column = cellColumn(column, row);
    var change = {
      target: column.target,
      elementId: row.ElementId,
      typeElementId: row.TypeElementId,
      parameterName: column.parameterName,
      parameterKey: column.parameterKey,
      parameterIdentity: column.parameterIdentity,
      specTypeId: column.specTypeId,
      parameterGuid: column.parameterGuid || null,
      parameterBuiltin: column.parameterBuiltin,
      storageType: column.storageType,
      referenceKind: column.referenceKind || null,
      field: column.field,
      value: value
    };
    return change;
  }

  function recalculateFormulas() {
    var rows = table.getRows();
    var data = table.getData();
    formulaTexts.forEach(function (expression, key) {
      var separator = key.lastIndexOf("|");
      var uniqueId = key.slice(0, separator);
      var field = key.slice(separator + 1);
      var rowIndex = data.findIndex(function (item) {
        return item.UniqueId === uniqueId;
      });
      if (rowIndex < 0) { return; }
      try {
        var column = findColumn(field);
        var value = CF.validateResult(evaluateFormula(expression, rowIndex, field), column.storageType, column.target);
        formulaValues.set(key, value);
        var gridRow = rows.find(function (item) {
          return item.getData().UniqueId === uniqueId;
        });
        if (!gridRow) { return; }
        var row = gridRow.getData();
        var changeKey = rowChangeKey(row, column);
        if (!originalValues.has(changeKey)) { originalValues.set(changeKey, row[field]); }
        row[field] = value;
        gridRow.update(row);
        if (column) {
          pendingChanges.set(rowChangeKey(row, column), buildChange(row, column, value));
        }
      } catch (error) {
        showStatus(error.message, true);
      }
    });
    reportChangeCount();
  }

  function onCellEdited(cell) {
    var row = cell.getRow().getData();
    var column = findColumn(cell.getField());
    if (!column || column.disabled || !column.editable ||
        row[cell.getField() + "__disabled"]) { return; }

    var historyBefore = captureEditState();
    var editedCellKey = row.UniqueId + "|" + cell.getField();
    historyBefore.cells.set(editedCellKey, cell.getOldValue());
    historyBefore.refs.set(editedCellKey, {
      sheetIndex: activeSheetIndex,
      uniqueId: row.UniqueId,
      field: cell.getField(),
      baselineKey: rowChangeKey(row, column)
    });
    var raw = cell.getValue();
    var value = raw;
    var rowIndex = cell.getRow().getPosition(true) - 1;
    var formulaKey = row.UniqueId + "|" + cell.getField();
    if (typeof raw === "string" && raw.trim().charAt(0) === "=") {
      if (!column.formulaAllowed || column.storageType === "ElementId") {
        showStatus("Formulas are disabled for this column.", true);
        cell.restoreOldValue();
        return;
      }
      try {
        formulaTexts.set(formulaKey, raw.trim());
        value = CF.validateResult(evaluateFormula(raw.trim(), rowIndex, cell.getField()), column.storageType, column.target);
        formulaValues.set(formulaKey, value);
        cell.setValue(value, true);
      } catch (error) {
        formulaTexts.delete(formulaKey);
        formulaValues.delete(formulaKey);
        showStatus(error.message, true);
        cell.restoreOldValue();
        return;
      }
    } else {
      formulaTexts.delete(formulaKey);
      formulaValues.delete(formulaKey);
    }

    if (column.target === "type" || column.target === "typeName") {
      table.getRows().forEach(function (gridRow) {
        var data = gridRow.getData();
        if (String(data.TypeElementId) === String(row.TypeElementId)) {
          data[column.field] = value;
          gridRow.update(data);
        }
      });
    }
    var key = rowChangeKey(row, column);
    if (!originalValues.has(key)) { originalValues.set(key, cell.getOldValue()); }
    pendingChanges.set(key, buildChange(row, column, value));
    recalculateFormulas();
    reportChangeCount();
    cell.getRow().reformat();
    recordHistory(historyBefore, "cell edit");
    showStatus("");
  }

  function isSharedByType(column) {
    return column.target === "type" || column.target === "typeName";
  }

  // Sets one value on every visible row where the column is editable. Shared type
  // values are recorded once per type and copied to all of that type's rows.
  function bulkSetValue(column, value) {
    table.getData("active").forEach(function (row) {
      if (cellEditable(column, row)) {
        RC.literalValue(value == null ? "" : String(value), cellColumn(column, row));
      }
    });
    var historyBefore = captureEditState();
    var edited = new Set();
    var typeValues = new Set();
    var skipped = 0;
    table.getData("active").forEach(function (row) {
      if (!cellEditable(column, row)) { skipped += 1; return; }
      var key = rowChangeKey(row, column);
      if (isSharedByType(column)) {
        if (typeValues.has(String(row.TypeElementId))) { return; }
        typeValues.add(String(row.TypeElementId));
      } else {
        edited.add(row.UniqueId);
      }
      var formulaKey = row.UniqueId + "|" + column.field;
      formulaTexts.delete(formulaKey);
      formulaValues.delete(formulaKey);
      if (!originalValues.has(key)) { originalValues.set(key, row[column.field]); }
      pendingChanges.set(key, buildChange(row, column, value));
    });
    var updates = table.getData().filter(function (row) {
      return isSharedByType(column)
        ? typeValues.has(String(row.TypeElementId))
        : edited.has(row.UniqueId);
    }).map(function (row) {
      var update = { UniqueId: row.UniqueId };
      update[column.field] = value;
      return update;
    });
    var count = isSharedByType(column) ? typeValues.size : edited.size;
    return table.updateData(updates).then(function () {
      recalculateFormulas();
      reportChangeCount();
      updateFilterBar();
      recordHistory(historyBefore, "Set value");
      return { count: count, rows: updates.length, skipped: skipped };
    });
  }

  function sheetColumn(sheet, field) {
    return (sheet.columns || []).find(function (column) { return column.field === field; });
  }

  var clipboardBusy = false;
  var forwardingEditorKey = false;
  var gridElement = document.getElementById("grid");

  function rangeClipboardTarget(event) {
    return tableReady && !clipboardBusy && !event.target.closest("input, textarea, select, [contenteditable=true]") &&
      table.getRanges().length === 1;
  }

  function selectedRangeCells() {
    if (!tableReady || table.getRanges().length !== 1) {
      throw new Error("Select one range in the grid first.");
    }
    return table.getRanges()[0].getCells();
  }

  function copiedRangeText() {
    return RC.copyTSV(selectedRangeCells().map(function (row) {
      return row.map(function (cell) { return cell.getValue(); });
    }));
  }

  function stagePlannedChanges(plan, label) {
    if (clipboardBusy) { throw new Error("A grid edit is already in progress."); }
    if (!plan.changes.length) {
      showStatus("No values changed; skipped " + plan.skipped + " locked or unsupported cell(s).");
      return Promise.resolve();
    }
    if (plan.types && !window.confirm(label + " changes " + plan.types +
        " shared type(s), including instances outside the selected range or hidden by filters. Continue?")) {
      return Promise.resolve();
    }
    var historyBefore = captureEditState();
    var updates = new Map();
    var rowsByType = new Map();
    table.getData().forEach(function (row) {
      var typeId = String(row.TypeElementId);
      if (!rowsByType.has(typeId)) { rowsByType.set(typeId, []); }
      rowsByType.get(typeId).push(row);
    });
    plan.changes.forEach(function (change) {
      var column = change.column, row = change.row;
      var key = rowChangeKey(row, column);
      if (!originalValues.has(key)) { originalValues.set(key, row[column.field]); }
      pendingChanges.set(key, buildChange(row, column, change.value));
      var targets = isSharedByType(column)
        ? rowsByType.get(String(row.TypeElementId)) : [row];
      targets.forEach(function (item) {
        var update = updates.get(item.UniqueId) || {UniqueId: item.UniqueId};
        update[column.field] = change.value;
        updates.set(item.UniqueId, update);
        var formulaKey = item.UniqueId + "|" + column.field;
        formulaTexts.delete(formulaKey);
        formulaValues.delete(formulaKey);
      });
    });
    clipboardBusy = true;
    return table.updateData(Array.from(updates.values())).then(function () {
      recalculateFormulas();
      reportChangeCount();
      updateFilterBar();
      recordHistory(historyBefore, label);
      showStatus(label + ": " + plan.changes.length + " value(s) staged; skipped " + plan.skipped +
        " locked or unsupported cell(s). Review pending changes, then Apply Changes.");
    }).finally(function () { clipboardBusy = false; });
  }

  function pasteRangeText(text) {
    var first = selectedRangeCells()[0][0];
    var rows = table.getRows("active").map(function (row) { return row.getData(); });
    var columns = [ROW_NUMBER_COLUMN].concat(visibleColumns(currentSheet()));
    var plan = RC.planPaste(RC.parseTSV(text),
      rows, columns, rows.indexOf(first.getRow().getData()),
      columns.findIndex(function (column) { return column.field === first.getField(); }),
      cellEditable, rowChangeKey);
    return stagePlannedChanges(plan, "Paste");
  }

  function fillDown() {
    try {
      var plan = RC.planFillDown(selectedRangeCells(), columnForField, cellEditable, rowChangeKey,
        function (row, column) { return formulaTexts.has(row.UniqueId + "|" + column.field); });
      return stagePlannedChanges(plan, "Fill down").catch(reportGridError);
    } catch (error) { showStatus("Fill down not applied: " + error.message, true); }
  }

  function selectGridCell(cell) {
    if (!cell) { return; }
    table.getRanges().forEach(function (range) { range.remove(); });
    table.addRange(cell, cell);
    Promise.all([
      cell.getRow().scrollTo("nearest", false),
      cell.getColumn().scrollTo("nearest", false)
    ]).then(function () {
      cell.getElement().focus({preventScroll: true});
    }).catch(reportGridError);
  }

  gridElement.addEventListener("keydown", function (event) {
    if (forwardingEditorKey || !tableReady || clipboardBusy || document.body.inert ||
        document.querySelector(".modal-backdrop") || event.isComposing || event.keyCode === 229) { return; }
    var editingElement = event.target.closest(".tabulator-cell.tabulator-editing");
    var control = event.target.closest("input, textarea, select, [contenteditable=true]");
    if (control && !editingElement) { return; }
    if (editingElement) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "d") {
        event.preventDefault();
        event.stopImmediatePropagation();
        showStatus("Finish or cancel the cell edit before filling down.", true);
        return;
      }
      if ((event.key !== "Enter" && event.key !== "Tab") || event.ctrlKey || event.altKey || event.metaKey) { return; }
      event.preventDefault();
      event.stopImmediatePropagation();
      var editingCell = table.getRanges()[0] && table.getRanges()[0].getCells()[0][0];
      if (!editingCell) { return; }
      var rowId = editingCell.getRow().getData().UniqueId;
      var field = editingCell.getField();
      // Let the editor validate/commit; do not bypass dropdown selection.
      forwardingEditorKey = true;
      try {
        event.target.dispatchEvent(new KeyboardEvent("keydown", {key: "Enter", bubbles: false}));
      } finally { forwardingEditorKey = false; }
      if (editingElement.classList.contains("tabulator-editing")) { return; }
      var fields = visibleColumns(currentSheet()).map(function (column) { return column.field; });
      var next = SS.navigationTarget(table.getRows("active"), fields, rowId, field, event.key, event.shiftKey);
      selectGridCell(next || table.getRow(rowId).getCell(field));
      return;
    }
    if (!event.target.closest(".tabulator-tableholder, .tabulator-cell")) { return; }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "d") {
      event.preventDefault();
      event.stopImmediatePropagation();
      fillDown();
      return;
    }
    if (event.ctrlKey || event.metaKey || event.altKey) { return; }
    var replace = event.key.length === 1;
    if (event.key !== "F2" && event.key !== "Enter" && !replace) { return; }
    var range = table.getRanges()[0];
    var cell = range && range.getCells()[0][0];
    if (!cell) { return; }
    event.preventDefault();
    event.stopImmediatePropagation();
    var column = findColumn(cell.getField());
    if (!column || !cellEditable(column, cell.getRow().getData())) {
      showStatus("This cell is read-only.", true);
      return;
    }
    cell.edit();
    var input = cell.getElement().querySelector("input");
    if (input) {
      if (replace) {
        input.value = event.key;
        input.dispatchEvent(new Event("input", {bubbles: true}));
        input.dispatchEvent(new KeyboardEvent("keyup", {key: event.key, bubbles: true}));
      } else if (input.type === "text") {
        input.setSelectionRange(input.value.length, input.value.length);
      }
    }
  }, true);

  gridElement.addEventListener("copy", function (event) {
    if (!rangeClipboardTarget(event)) { return; }
    event.preventDefault();
    try {
      event.clipboardData.setData("text/plain", copiedRangeText());
      showStatus("Copied highlighted values (no formulas).");
    } catch (error) { showStatus("Copy failed: " + error.message, true); }
  });

  gridElement.addEventListener("paste", function (event) {
    if (event.target.closest(".tabulator-cell") &&
        event.target.closest("input, textarea, [contenteditable=true]")) {
      if (RC.formulaLike(event.clipboardData.getData("text/plain"))) {
        event.preventDefault();
        showStatus("Paste not applied: formulas are not accepted. Copy calculated values from Excel.", true);
      }
      return;
    }
    if (!rangeClipboardTarget(event)) { return; }
    event.preventDefault();
    try {
      pasteRangeText(event.clipboardData.getData("text/plain")).catch(function (error) {
        reportGridError(error);
      });
    } catch (error) { showStatus("Paste not applied: " + error.message, true); }
  });

  function applyImportUpdates(nextWorkbook, updates) {
    var historyBefore = captureEditState(nextWorkbook);
    var applied = 0;
    var perSheet = {};
    (updates || []).forEach(function (update) {
      var sheet = nextWorkbook.sheets[update.sheetIndex];
      var column = sheet && sheetColumn(sheet, update.field);
      if (!column) { return; }
      var sharedByType = column.target === "type" || column.target === "typeName";
      var targets = sheet.rows.filter(function (row) {
        return sharedByType
          ? String(row.TypeElementId) === String(update.typeElementId)
          : row.UniqueId === update.uniqueId;
      });
      if (!targets.length) { return; }
      targets.forEach(function (row) { row[column.field] = update.value; });
      var key = rowChangeKey(targets[0], column);
      if (!originalValues.has(key)) { originalValues.set(key, update.oldValue); }
      pendingChanges.set(key, buildChange(targets[0], column, update.value));
      perSheet[update.sheetIndex] = (perSheet[update.sheetIndex] || 0) + 1;
      applied += 1;
    });
    nextWorkbook.sheets.forEach(function (sheet, index) {
      sheet.pendingLabel = perSheet[index] ? " (" + perSheet[index] + " to import)" : "";
    });
    if (applied) { recordHistory(historyBefore, "Import XLSX", nextWorkbook); }
    return applied;
  }

  function formatValue(value) {
    return value === null || value === undefined || value === "" ? "(empty)" : String(value);
  }

  function columnEditor(column) {
    if (column.storageType === "ElementId" && column.options) {
      return {
        editor: "list",
        editorParams: function (cell) {
          return {
            values: cellColumn(column, cell.getRow().getData()).options || [],
            autocomplete: true,
            listOnEmpty: true,
            allowEmpty: true,
            clearable: false
          };
        }
      };
    }
    return {
      editor: SS.scalarEditor(column, function (message) { showStatus(message, true); }),
      editorParams: {}
    };
  }

  function displayTitle(column) {
    return column.title;
  }

  function isPending(cell, column) {
    if (column.columnType !== "parameter" && column.columnType !== "typeName") {
      return false;
    }
    return pendingChanges.has(rowChangeKey(cell.getRow().getData(), column));
  }

  var FILTER_HELP = "Filter: text = contains · =x equals · = empty · != not empty · " +
    "!x excludes · >5 >=5 <5 <=5 · 2..8 between · ^start · end$ · * ? wildcards · " +
    "/regex/ · a|b either";

  function headerFilterFunc(headerValue, rowValue) {
    var predicate = F.compileExpression(headerValue);
    return !predicate || predicate(rowValue);
  }

  function headerTitleFormatter(field, letter) {
    return function (cell) {
      var wrapper = document.createElement("span");
      wrapper.className = "col-title";
      if (letter) {
        var badge = document.createElement("span");
        badge.className = "col-letter";
        badge.textContent = letter;
        badge.title = "Formula column " + letter;
        wrapper.appendChild(badge);
      }
      var column = columnForField(field);
      var details = document.createElement("span");
      details.className = "col-data-type";
      details.textContent = column ? typeLabel(column) : "";
      details.title = details.textContent;
      wrapper.appendChild(details);
      var label = document.createElement("span");
      label.className = "col-label";
      label.textContent = cell.getValue();
      wrapper.appendChild(label);
      return wrapper;
    };
  }

  function headerFilterEditor(cell, onRendered, success) {
    var input = document.createElement("input");
    input.type = "text";
    input.value = cell.getValue() == null ? "" : cell.getValue();
    input.addEventListener("change", function () { success(input.value); });
    onRendered(function () {
      var field = cell.getField();
      var button = document.createElement("button");
      button.type = "button";
      button.className = "col-menu-button";
      button.dataset.field = field;
      button.title = "Sort and filter this column";
      button.textContent = "▾";
      button.addEventListener("mousedown", function (event) { event.stopPropagation(); });
      button.addEventListener("click", function (event) {
        event.stopPropagation();
        event.preventDefault();
        openColumnMenu(field, button);
      });
      input.parentNode.appendChild(button);
    });
    return input;
  }

  function rowNumberDefinition() {
    return {
      title: F.ROW_NUMBER_TITLE,
      field: F.ROW_NUMBER_FIELD,
      frozen: true,
      width: 64,
      hozAlign: "right",
      headerSort: false,
      sorter: "number",
      headerTooltip: "Row number used by formulas (A1 = first row). " + FILTER_HELP,
      titleFormatter: headerTitleFormatter(F.ROW_NUMBER_FIELD, ""),
      headerFilter: headerFilterEditor,
      headerFilterFunc: headerFilterFunc,
      headerFilterPlaceholder: "…",
      cssClass: "row-number"
    };
  }

  function sortedLevels(sheet) {
    if (!sheet) { return []; }
    var seen = new Set();
    return layoutFor(sheet).sort.filter(function (item) {
      if (!columnByTitle(sheet, item.title) || seen.has(item.title) ||
          (item.dir !== "asc" && item.dir !== "desc")) { return false; }
      seen.add(item.title);
      return true;
    });
  }

  function sortColumnLabel(sheet, column) {
    return column === ROW_NUMBER_COLUMN ? "# — Row number" :
      indexToLetters(visibleColumns(sheet).indexOf(column)) + " — " + displayTitle(column);
  }

  function updateSortIndicators(levels) {
    if (!tableReady || !currentSheet()) { return; }
    var priorityByTitle = new Map();
    levels.forEach(function (item, index) { priorityByTitle.set(item.title, index + 1); });
    [ROW_NUMBER_COLUMN].concat(visibleColumns(currentSheet())).forEach(function (column) {
      var component = table.getColumn(column.field);
      var element = component && component.getElement();
      var sorter = element && (element.querySelector(".tabulator-col-sorter") ||
        element.querySelector(".col-title"));
      if (!sorter) { return; }
      var indicator = sorter.querySelector(".sort-priority");
      var priority = priorityByTitle.get(column.title);
      element.classList.toggle("has-sort-priority", !!priority);
      if (!priority) {
        if (indicator) { indicator.remove(); }
        return;
      }
      if (!indicator) {
        indicator = el("span", "sort-priority");
        sorter.appendChild(indicator);
      }
      indicator.textContent = String(priority);
      indicator.title = "Sort priority " + priority;
      indicator.setAttribute("aria-label", indicator.title);
    });
  }

  function updateSortSummary() {
    var sheet = currentSheet();
    var levels = sortedLevels(sheet);
    sortButton.disabled = !tableReady || !sheet;
    sortButton.hidden = !!levels.length;
    sortSummary.hidden = !levels.length;
    sortSummaryText.textContent = levels.length ? "Sort: " + levels.map(function (item) {
      return sortColumnLabel(sheet, columnByTitle(sheet, item.title)) +
        (item.dir === "asc" ? " ↑" : " ↓");
    }).join(" → ") : "";
    updateSortIndicators(levels);
  }

  function onDataSorted() {
    if (!tableReady || restoringFilters || !currentSheet()) { return; }
    captureSort(currentSheet());
    updateSortSummary();
  }

  function openSortDialog() {
    var sheet = currentSheet();
    if (!sheet || !tableReady) { return; }
    blurGridInput();
    captureSort(sheet);
    var columns = visibleColumns(sheet).concat([ROW_NUMBER_COLUMN]);
    var levels = sortedLevels(sheet).map(function (item) {
      return { title: item.title, dir: item.dir };
    });
    if (!levels.length) { levels.push({ title: columns[0].title, dir: "asc" }); }
    var content = el("div", "sort-dialog");
    var levelList = el("div", "sort-level-list");
    var addLevel = makeButton("Add level", function () {
      var used = new Set(levels.map(function (item) { return item.title; }));
      var available = columns.find(function (column) { return !used.has(column.title); });
      if (!available) { return; }
      levels.push({ title: available.title, dir: "asc" });
      renderLevels(levels.length - 1);
    });
    var clearLevels = makeButton("Clear all", function () {
      levels = [];
      renderLevels();
      addLevel.focus();
    });

    function renderLevels(focusIndex) {
      levelList.replaceChildren();
      var used = new Set(levels.map(function (item) { return item.title; }));
      var columnSelects = [];
      levels.forEach(function (level, index) {
        var row = el("div", "sort-level");
        row.appendChild(el("span", "sort-level-label",
          (index + 1) + (index === 0 ? " Sort by" : " Then by")));
        var columnSelect = el("select", "sort-column-select");
        columnSelect.setAttribute("aria-label", "Sort level " + (index + 1) + " column");
        columns.forEach(function (column) {
          if (column.title !== level.title && used.has(column.title)) { return; }
          var option = el("option", null, sortColumnLabel(sheet, column));
          option.value = column.title;
          columnSelect.appendChild(option);
        });
        columnSelect.value = level.title;
        columnSelect.addEventListener("change", function () {
          level.title = columnSelect.value;
          renderLevels(index);
        });
        columnSelects.push(columnSelect);
        row.appendChild(columnSelect);

        var directionSelect = el("select", "sort-direction-select");
        directionSelect.setAttribute("aria-label", "Sort level " + (index + 1) + " direction");
        fillOptions(directionSelect, [
          { value: "asc", label: "Ascending" },
          { value: "desc", label: "Descending" }
        ]);
        directionSelect.value = level.dir;
        directionSelect.addEventListener("change", function () { level.dir = directionSelect.value; });
        row.appendChild(directionSelect);

        var actions = el("div", "sort-level-actions");
        var moveUp = makeButton("↑", function () {
          if (index === 0) { return; }
          levels.splice(index - 1, 0, levels.splice(index, 1)[0]);
          renderLevels(index - 1);
        });
        moveUp.title = "Move sort level up";
        moveUp.setAttribute("aria-label", "Move sort level " + (index + 1) + " up");
        moveUp.disabled = index === 0;
        actions.appendChild(moveUp);
        var moveDown = makeButton("↓", function () {
          if (index >= levels.length - 1) { return; }
          levels.splice(index + 1, 0, levels.splice(index, 1)[0]);
          renderLevels(index + 1);
        });
        moveDown.title = "Move sort level down";
        moveDown.setAttribute("aria-label", "Move sort level " + (index + 1) + " down");
        moveDown.disabled = index >= levels.length - 1;
        actions.appendChild(moveDown);
        var remove = makeButton("×", function () {
          levels.splice(index, 1);
          renderLevels(Math.min(index, levels.length - 1));
        });
        remove.title = "Remove sort level";
        remove.setAttribute("aria-label", "Remove sort level " + (index + 1));
        actions.appendChild(remove);
        row.appendChild(actions);
        levelList.appendChild(row);
      });
      addLevel.disabled = levels.length >= columns.length;
      clearLevels.disabled = !levels.length;
      if (focusIndex != null && columnSelects[focusIndex]) { columnSelects[focusIndex].focus(); }
    }

    content.appendChild(levelList);
    var controls = el("div", "sort-level-actions");
    controls.appendChild(addLevel);
    controls.appendChild(clearLevels);
    content.appendChild(controls);
    content.appendChild(el("div", "sort-hint",
      "Sort priority runs from top to bottom. A column can appear only once. Sort order is saved with presets."));
    renderLevels();
    showModal("Sort", content, [
      { label: "Apply", value: "apply", primary: true },
      { label: "Cancel", value: null }
    ]).then(function (choice) {
      if (choice !== "apply") { return; }
      if (currentSheet() !== sheet) {
        showStatus("The active sheet changed. Reopen Sort to change its sorting.", true);
        return;
      }
      layoutFor(sheet).sort = levels;
      applySort(sheet);
    });
  }

  function makeColumns(sheet) {
    var widths = layoutFor(sheet).widths;
    var letterIndex = 0;
    return [rowNumberDefinition()].concat(sheet.columns.map(function (column) {
      if (column.visible === false) {
        return { title: column.title, field: column.field, visible: false };
      }
      var letter = indexToLetters(letterIndex);
      letterIndex += 1;
      var editorSetup = columnEditor(column);
      var definition = {
        title: displayTitle(column),
        headerWordWrap: true,
        field: column.field,
        headerSort: true,
        headerTooltip: displayTitle(column) + " (column " + letter + ")\n" + FILTER_HELP,
        titleFormatter: headerTitleFormatter(column.field, letter),
        headerFilter: headerFilterEditor,
        headerFilterFunc: headerFilterFunc,
        headerFilterPlaceholder: "Filter…",
          editable: function (cell) {
          return cellEditable(column, cell.getRow().getData());
        },
        editor: editorSetup.editor,
        editorParams: editorSetup.editorParams,
        formatter: function (cell) {
          var element = cell.getElement();
          if (column.typeHighlight) { element.classList.add("type-column"); }
          if (column.disabled || cell.getRow().getData()[column.field + "__disabled"]) {
            element.classList.add("disabled-cell");
          }
          element.classList.toggle("pending-cell", isPending(cell, column));
          element.classList.toggle("name-conflict-cell", column.target === "typeName" &&
            typeNameConflicts.has(String(cell.getRow().getData().TypeElementId)));
          return cell.getValue() == null ? "" : cell.getValue();
        },
        tooltip: function (event, cell) {
          var data = cell.getRow().getData();
          if (column.target === "typeName" && typeNameConflicts.has(String(data.TypeElementId))) {
            return typeNameConflicts.get(String(data.TypeElementId));
          }
          if (!isPending(cell, column)) {
            return data[column.field + "__disabled"] ? (data[column.field + "__note"] || "") : "";
          }
          var key = rowChangeKey(data, column);
          return "Revit: " + formatValue(originalValues.get(key)) +
            "\nNew: " + formatValue(cell.getValue());
        },
        cellEdited: onCellEdited,
        cssClass: column.typeHighlight ? "type-column" : ""
      };
      if (widths[column.title]) { definition.width = widths[column.title]; }
      else if (letterIndex > 1) { definition.width = 180; }
      return definition;
    }));
  }

  function sheetStatus(sheet) {
    return "Step 5 of 5 — " + sheet.name +
      (workbook.presetName ? " · Preset: " + workbook.presetName : "") +
      (importNotice ? " · " + importNotice : "");
  }

  // ---------------------------------------------------------------- helpers

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) { node.className = className; }
    if (text !== undefined && text !== null) { node.textContent = text; }
    return node;
  }

  function makeButton(label, onClick, className) {
    var node = el("button", className, label);
    node.type = "button";
    node.addEventListener("click", onClick);
    return node;
  }

  function fillOptions(select, items) {
    items.forEach(function (item) {
      var option = el("option", null, item.label);
      option.value = item.value;
      if (item.tooltip) { option.title = item.tooltip; }
      select.appendChild(option);
    });
  }

  function operatorItems() {
    return F.OPERATORS.map(function (item) { return { value: item.op, label: item.label }; });
  }

  function operatorInfo(op) {
    return F.OPERATORS.find(function (item) { return item.op === op; }) || F.OPERATORS[0];
  }

  // Resolves with the clicked button's value, or null for Escape. A button's
  // onClick may return false to keep the dialog open (validation).
  function showModal(title, content, buttons) {
    closeColumnMenu();
    return new Promise(function (resolve) {
      var previousFocus = document.activeElement;
      var backdrop = el("div", "modal-backdrop");
      var dialog = el("div", "modal");
      dialog.setAttribute("role", "dialog");
      dialog.setAttribute("aria-modal", "true");
      dialog.setAttribute("aria-label", title);
      dialog.appendChild(el("h2", null, title));
      var body = el("div", "modal-body");
      if (typeof content === "string") { body.textContent = content; } else { body.appendChild(content); }
      dialog.appendChild(body);
      var footer = el("div", "modal-footer");
      function onKey(event) {
        if (event.key === "Escape") { event.stopPropagation(); close(null); }
        if (event.key === "Tab") {
          var focusable = Array.from(dialog.querySelectorAll("input, select, button, textarea"))
            .filter(function (node) { return !node.disabled && node.getClientRects().length; });
          var first = focusable[0], last = focusable[focusable.length - 1];
          if (event.shiftKey && document.activeElement === first) {
            event.preventDefault(); last.focus();
          } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault(); first.focus();
          }
        }
      }
      function close(value) {
        document.removeEventListener("keydown", onKey, true);
        backdrop.remove();
        if (previousFocus && previousFocus.isConnected) { previousFocus.focus(); }
        resolve(value);
      }
      buttons.forEach(function (spec) {
        var button = makeButton(spec.label, function () {
          if (spec.onClick && spec.onClick() === false) { return; }
          close(spec.value);
        }, spec.primary ? "primary" : "");
        button.disabled = !!spec.disabled;
        footer.appendChild(button);
      });
      dialog.appendChild(footer);
      backdrop.appendChild(dialog);
      document.body.appendChild(backdrop);
      document.addEventListener("keydown", onKey, true);
      var focus = dialog.querySelector("input, select, button.primary");
      if (focus) { focus.focus(); }
    });
  }

  // ------------------------------------------------------------- text tools

  var CASE_OPTIONS = [
    {value: "upper", label: "UPPER CASE"},
    {value: "lower", label: "lower case"},
    {value: "title", label: "Title Case"},
    {value: "sentence", label: "Sentence case"}
  ];

  function textScopeCells(scope, selected) {
    return TT.textScopeCells(scope, selected,
      scope === "selected" ? [] : table.getRows("active").map(function (row) { return row.getData(); }),
      visibleColumns(currentSheet()));
  }

  function openTextTool(kind, initialCase) {
    if (!tableReady || !currentSheet() || clipboardBusy) { return; }
    blurGridInput();
    var sourceSheet = currentSheet();
    var selected = [];
    if (table.getRanges().length === 1) {
      table.getRanges()[0].getCells().forEach(function (row) {
        row.forEach(function (cell) {
          selected.push({row: cell.getRow().getData(), column: columnForField(cell.getField())});
        });
      });
    }
    var form = el("div", "bulk");
    function inputField(label, node) {
      var holder = el("label", "field", label);
      holder.appendChild(node);
      form.appendChild(holder);
      return node;
    }
    var scope = el("select");
    fillOptions(scope, [
      {value: "selected", label: "Selected range"},
      {value: "columns", label: "Current column(s) (visible rows)"}
    ].concat(
      kind === "replace" ? [{value: "visible", label: "All visible cells (this sheet)"}] : []
    ));
    inputField("Scope", scope);
    var find = el("input"); find.type = "text";
    var replace = el("input"); replace.type = "text";
    var match = el("input"); match.type = "checkbox";
    var whole = el("input"); whole.type = "checkbox";
    var regex = el("input"); regex.type = "checkbox";
    var caseMode = el("select");
    if (kind === "replace") {
      inputField("Find", find);
      inputField("Replace with", replace);
      inputField("Match case", match);
      inputField("Whole cell", whole);
      inputField("Use regular expressions (regex)", regex);
    } else {
      fillOptions(caseMode, CASE_OPTIONS);
      caseMode.value = initialCase || "upper";
      inputField("Case", caseMode);
    }
    form.appendChild(el("div", "modal-hint",
      "Only editable text cells are changed. Locked, numeric and reference cells are skipped. " +
      "Existing cell formulas become literal values. Shared types affect every instance. " +
      "Current column(s) includes each selected column, respecting current row filters. " +
      (kind === "replace" ? "Find/Replace is literal unless regex is checked. Regex uses JavaScript syntax " +
        "(without / delimiters); replacement supports $1, $2 and $<name>. Results are never evaluated as formulas." :
        "Sentence case capitalizes after . ! or ? and lowercases the other letters.")));
    var summary = el("div", "modal-hint");
    summary.setAttribute("aria-live", "polite");
    var samples = el("div");
    var error = el("div", "modal-error");
    error.setAttribute("role", "alert");
    form.appendChild(summary);
    form.appendChild(samples);
    form.appendChild(error);
    var plan = null;
    // Restoring focus on close can emit a final change event and invalidate the preview.
    var acceptedPlan = null;
    var apply = null;
    function invalidate() {
      plan = null;
      if (apply) { apply.disabled = false; }
      samples.replaceChildren();
      summary.textContent = "Stage changes directly, or Preview to see the change count and sample results.";
      error.textContent = "";
    }
    function preview() {
      invalidate();
      try {
        if (currentSheet() !== sourceSheet) { throw new Error("The workbook changed. Reopen this dialog."); }
        var transform = kind === "replace"
          ? TT.textReplacement(find.value, replace.value, match.checked, whole.checked, regex.checked)
          : function (value) { return TT.changeCase(value, caseMode.value); };
        plan = TT.planTextChanges(textScopeCells(scope.value, selected), transform, cellEditable, rowChangeKey);
        summary.textContent = plan.changes.length + " value(s) will change; " + plan.skipped +
          " locked/non-text cell(s) skipped; " + plan.unchanged + " unchanged cell(s)." +
          (plan.types ? " Affects " + plan.types + " shared type(s)." : "");
        var previewTable = el("table", "text-preview");
        var headings = el("tr");
        ["Row / Column", "Before", "After"].forEach(function (title) {
          headings.appendChild(el("th", null, title));
        });
        previewTable.appendChild(headings);
        plan.changes.slice(0, 8).forEach(function (change) {
          var row = el("tr");
          row.appendChild(el("td", null, "#" + change.row[F.ROW_NUMBER_FIELD] + " / " + change.column.title));
          row.appendChild(el("td", null, change.before));
          row.appendChild(el("td", null, change.value));
          previewTable.appendChild(row);
        });
        if (plan.changes.length) {
          samples.appendChild(previewTable);
          if (plan.changes.length > 8) { samples.appendChild(el("div", "modal-hint", "Showing the first 8 changes.")); }
        }
        apply.disabled = !plan.changes.length;
      } catch (exc) { error.textContent = exc.message; }
      return false;
    }
    form.addEventListener("input", invalidate);
    form.addEventListener("change", invalidate);
    var title = kind === "replace" ? "Find / Replace" : "Change case";
    var result = showModal(title, form, [
      {label: "Preview", value: null, onClick: preview},
      {label: "Stage changes", value: "apply", primary: true, onClick: function () {
        preview();
        if (!plan || !plan.changes.length) { return false; }
        acceptedPlan = plan;
      }},
      {label: "Cancel", value: null}
    ]);
    apply = form.closest(".modal").querySelector(".modal-footer button.primary");
    invalidate();
    if (kind === "case") { preview(); }
    else { find.focus(); }
    result.then(function (choice) {
      if (choice !== "apply") { return; }
      try { stagePlannedChanges(acceptedPlan, title).catch(reportGridError); }
      catch (exc) { showStatus(title + " not applied: " + exc.message, true); }
    });
  }

  function openRangeMenu(event, cell) {
    if (event.target.closest("input, textarea, select, [contenteditable=true]")) { return; }
    event.preventDefault();
    if (clipboardBusy) { showStatus("A grid edit is already in progress.", true); return; }
    closeColumnMenu();
    var selected = table.getRanges();
    var contains = selected.length === 1 && selected[0].getCells().some(function (row) {
      return row.some(function (item) {
        return item.getRow().getData() === cell.getRow().getData() && item.getField() === cell.getField();
      });
    });
    if (!contains) {
      selected.forEach(function (range) { range.remove(); });
      table.addRange(cell, cell);
    }
    var menu = el("div", "col-menu range-menu");
    menu.setAttribute("aria-label", "Highlighted range actions");
    menu.appendChild(el("div", "col-menu-title", "Highlighted range"));
    function action(label, callback, parent) {
      var button = makeButton(label, function () {
        closeColumnMenu();
        cell.getElement().focus();
        callback();
      });
      (parent || menu).appendChild(button);
    }
    action("Copy values", function () {
      if (!navigator.clipboard || !navigator.clipboard.writeText) {
        showStatus("Clipboard access is unavailable. Use Ctrl+C in the grid.", true); return;
      }
      navigator.clipboard.writeText(copiedRangeText()).then(function () {
        showStatus("Copied highlighted values (no formulas).");
      }).catch(function (exc) { showStatus("Copy failed: " + exc.message + ". Use Ctrl+C in the grid.", true); });
    });
    action("Paste values", function () {
      if (!navigator.clipboard || !navigator.clipboard.readText) {
        showStatus("Clipboard access is unavailable. Use Ctrl+V in the grid.", true); return;
      }
      navigator.clipboard.readText().then(pasteRangeText).catch(function (exc) {
        showStatus("Paste not applied: " + exc.message + ". You can use Ctrl+V in the grid.", true);
      });
    });
    action("Fill down — Ctrl+D", fillDown);
    action("Find / Replace...", function () { openTextTool("replace"); });
    var cases = el("details");
    cases.appendChild(el("summary", null, "Change case"));
    CASE_OPTIONS.forEach(function (option) {
      action(option.label, function () { openTextTool("case", option.value); }, cases);
    });
    menu.appendChild(cases);
    var revit = el("details");
    revit.appendChild(el("summary", null, "Revit"));
    action("Select highlighted rows in Revit", function () {
      sendRevitView("select", "highlighted");
    }, revit);
    action("Isolate highlighted rows in view", function () {
      sendRevitView("isolate", "highlighted");
    }, revit);
    action("Reset view", function () { sendRevitView("reset"); }, revit);
    menu.appendChild(revit);
    document.body.appendChild(menu);
    menu.style.left = Math.max(8, Math.min(event.clientX, window.innerWidth - menu.offsetWidth - 8)) + "px";
    menu.style.top = Math.max(8, Math.min(event.clientY, window.innerHeight - menu.offsetHeight - 8)) + "px";
    cases.addEventListener("toggle", function () {
      menu.style.top = Math.max(8, Math.min(event.clientY, window.innerHeight - menu.offsetHeight - 8)) + "px";
    });
    columnMenu = menu;
    document.addEventListener("mousedown", onMenuOutside, true);
    document.addEventListener("keydown", onMenuKey, true);
    menu.querySelector("button").focus();
  }

  // ------------------------------------------------------------- filter bar

  var searchBox = document.getElementById("searchBox");
  var showSelect = document.getElementById("showSelect");
  var filterChips = document.getElementById("filterChips");
  var filterCount = document.getElementById("filterCount");
  var clearFiltersButton = document.getElementById("clearFiltersButton");
  var sortButton = document.getElementById("sortButton");
  var sortSummary = document.getElementById("sortSummary");
  var sortSummaryText = document.getElementById("sortSummaryText");
  var sortEditButton = document.getElementById("sortEditButton");
  var sortClearButton = document.getElementById("sortClearButton");
  var applyButton = document.getElementById("applyButton");
  var revitButtons = ["selectButton", "isolateButton", "resetViewButton"].map(function (id) {
    return document.getElementById(id);
  });
  var highlightedRevitButtons = ["selectHighlightedButton", "isolateHighlightedButton"].map(function (id) {
    return document.getElementById(id);
  });
  var revitBusy = false;
  var filterBarTimer = null;
  var contextCache = { sheet: null, context: null };
  fillOptions(showSelect, F.SHOW_OPTIONS);

  function cachedContext(sheet) {
    if (contextCache.sheet !== sheet) {
      contextCache = { sheet: sheet, context: filterContext(sheet) };
    }
    return contextCache.context;
  }

  function masterFilter(data) {
    var sheet = currentSheet();
    if (!sheet) { return true; }
    return F.rowPasses(data, filtersFor(sheet), cachedContext(sheet), { skipHeaders: true });
  }

  function refreshFilters() {
    if (!tableReady) { return; }
    table.refreshFilter();
    scheduleFilterBar();
  }

  function scheduleFilterBar() {
    if (filterBarTimer) { clearTimeout(filterBarTimer); }
    filterBarTimer = setTimeout(function () {
      filterBarTimer = null;
      updateFilterBar();
    }, 30);
  }

  function setHeaderExpression(column, expression) {
    table.setHeaderFilterValue(column.field, expression || "");
    scheduleFilterBar();
  }

  // Rows the filters let through. The open sheet asks Tabulator (it includes
  // header filters); other sheets are evaluated from their saved filter state.
  function visibleRowsFor(sheet, index) {
    if (index === activeSheetIndex && tableReady) { return table.getData("active"); }
    var state = filtersFor(sheet);
    if (!F.hasActiveFilters(state)) { return sheet.rows || []; }
    var context = filterContext(sheet);
    return (sheet.rows || []).filter(function (row) { return F.rowPasses(row, state, context); });
  }

  function hiddenChangeKeys() {
    if (!workbook || !pendingChanges.size) { return []; }
    var elementIds = new Set();
    var typeIds = new Set();
    workbook.sheets.forEach(function (sheet, index) {
      visibleRowsFor(sheet, index).forEach(function (row) {
        elementIds.add(String(row.ElementId));
        typeIds.add(String(row.TypeElementId));
      });
    });
    var hidden = [];
    pendingChanges.forEach(function (change, key) {
      var visible = isSharedByType(change)
        ? typeIds.has(String(change.typeElementId || change.elementId))
        : elementIds.has(String(change.elementId));
      if (!visible) { hidden.push(key); }
    });
    return hidden;
  }

  function refreshSheetOptions() {
    if (!workbook) { return; }
    Array.prototype.forEach.call(sheetSelect.options, function (option, index) {
      var sheet = workbook.sheets[index];
      if (!sheet) { return; }
      option.textContent = sheet.name + (sheet.pendingLabel || "") +
        (F.hasActiveFilters(filtersFor(sheet)) ? " (filtered)" : "");
    });
  }

  function refreshHeaderIndicators(state) {
    document.querySelectorAll("#grid .col-menu-button").forEach(function (node) {
      var column = columnForField(node.dataset.field);
      var active = column && (state.headers[column.title] || state.values[column.title]);
      node.classList.toggle("active", !!active);
    });
  }

  function chip(label, onClear) {
    var node = el("span", "chip");
    node.appendChild(el("span", "chip-label", label));
    node.title = label;
    var close = makeButton("✕", onClear, "chip-clear");
    close.title = "Remove this filter";
    node.appendChild(close);
    return node;
  }

  function updateFilterBar() {
    var sheet = currentSheet();
    if (!tableReady || !sheet) { return; }
    syncHeaderFilters();
    var state = filtersFor(sheet);
    var chips = [];
    if (state.search.trim()) {
      chips.push(chip("Search: " + state.search.trim(), function () {
        state.search = "";
        searchBox.value = "";
        refreshFilters();
      }));
    }
    if (state.show !== "all") {
      var show = F.SHOW_OPTIONS.find(function (item) { return item.value === state.show; });
      chips.push(chip("Show: " + (show ? show.label : state.show), function () {
        state.show = "all";
        showSelect.value = "all";
        refreshFilters();
      }));
    }
    Object.keys(state.headers).forEach(function (title) {
      var column = columnByTitle(sheet, title);
      if (!column) { return; }
      chips.push(chip(title + ": " + F.describeExpression(state.headers[title]), function () {
        setHeaderExpression(column, "");
      }));
    });
    Object.keys(state.values).forEach(function (title) {
      if (!columnByTitle(sheet, title)) { return; }
      var values = state.values[title];
      var label = values.length === 0 ? "(nothing)" :
        (values.length <= 2 ? values.join(", ") : values.length + " values");
      chips.push(chip(title + " in " + label, function () {
        delete state.values[title];
        refreshFilters();
      }));
    });
    var ruleCount = F.countRules(state.advanced);
    if (ruleCount) {
      chips.push(chip("Advanced: " + ruleCount + " rule" + (ruleCount === 1 ? "" : "s"), function () {
        state.advanced = { join: "and", rules: [] };
        refreshFilters();
      }));
    }
    filterChips.replaceChildren.apply(filterChips, chips);
    var shown = table.getDataCount("active");
    var total = table.getDataCount();
    var text = shown === total ? total + " rows" : "Showing " + shown + " of " + total + " rows";
    var hidden = hiddenChangeKeys().length;
    if (hidden) {
      text += " · " + hidden + " pending change" + (hidden === 1 ? "" : "s") + " hidden by filters";
    }
    filterCount.textContent = text;
    filterCount.classList.toggle("warn", hidden > 0);
    clearFiltersButton.disabled = !chips.length;
    refreshHeaderIndicators(state);
    refreshSheetOptions();
  }

  // Tabulator commits a header filter input on blur. Removing a focused input
  // (setColumns, clearHeaderFilter) would otherwise re-apply its old text.
  function blurGridInput() {
    var active = document.activeElement;
    if (active && active.blur && document.getElementById("grid").contains(active)) {
      active.blur();
    }
  }

  function clearAllFilters() {
    var sheet = currentSheet();
    if (!sheet || !tableReady) { return; }
    blurGridInput();
    var state = filtersFor(sheet);
    state.search = "";
    state.show = "all";
    state.values = {};
    state.advanced = { join: "and", rules: [] };
    state.headers = {};
    searchBox.value = "";
    showSelect.value = "all";
    table.clearHeaderFilter();
    refreshFilters();
  }

  function configureShowOptions(sheet) {
    var rows = sheet.rows || [];
    var mixed = rows.some(function (row) { return row.IsTypeRow; }) &&
      rows.some(function (row) { return !row.IsTypeRow; });
    var instancesMode = workbook && workbook.parameterMode === "Instances Mode";
    var state = filtersFor(sheet);
    if (!instancesMode && state.show === "topLevelInstances") {
      state.show = "all";
    }
    Array.prototype.forEach.call(showSelect.options, function (option) {
      if (option.value === "topLevelInstances") {
        option.hidden = !instancesMode;
      } else {
        option.hidden = !mixed &&
          (option.value === "typeRows" || option.value === "instanceRows");
      }
    });
  }

  // ------------------------------------------------------------ column menu

  function onMenuOutside(event) {
    if (columnMenu && !columnMenu.contains(event.target)) { closeColumnMenu(); }
  }

  function onMenuKey(event) {
    if (event.key === "Escape") { closeColumnMenu(); }
  }

  function closeColumnMenu() {
    if (!columnMenu) { return; }
    columnMenu.remove();
    columnMenu = null;
    document.removeEventListener("mousedown", onMenuOutside, true);
    document.removeEventListener("keydown", onMenuKey, true);
  }

  // Distinct values of the rows that pass every other filter (Excel behaviour).
  function distinctValues(sheet, column) {
    var state = filtersFor(sheet);
    var context = filterContext(sheet);
    var counts = new Map();
    table.getData().forEach(function (row) {
      if (!F.rowPasses(row, state, context, { excludeTitle: column.title })) { return; }
      var key = F.valueKey(row[column.field]);
      counts.set(key, (counts.get(key) || 0) + 1);
    });
    return Array.from(counts.keys()).sort(function (a, b) {
      if (a === F.BLANK_KEY) { return -1; }
      if (b === F.BLANK_KEY) { return 1; }
      var numberA = Number(a);
      var numberB = Number(b);
      if (a.trim() && b.trim() && Number.isFinite(numberA) && Number.isFinite(numberB)) {
        return numberA - numberB;
      }
      return a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" });
    }).map(function (key) { return { key: key, count: counts.get(key) }; });
  }

  function conditionEditor(initial) {
    var opSelect = el("select");
    fillOptions(opSelect, operatorItems());
    var value1 = el("input");
    value1.type = "text";
    value1.placeholder = "Value";
    var value2 = el("input");
    value2.type = "text";
    value2.placeholder = "and";
    opSelect.value = initial.op || "contains";
    value1.value = initial.value || "";
    value2.value = initial.value2 || "";
    function sync() {
      var info = operatorInfo(opSelect.value);
      value1.hidden = !!info.noValue;
      value2.hidden = !info.needsSecond;
    }
    opSelect.addEventListener("change", sync);
    sync();
    return { opSelect: opSelect, value1: value1, value2: value2, sync: sync };
  }

  function currentCondition(expression) {
    if (!expression) { return {}; }
    if (expression.charAt(0) === "'") { return { op: "contains", value: expression.slice(1) }; }
    var regex = /^\/(.+)\/[a-z]*$/.exec(expression.trim());
    if (regex) { return { op: "regex", value: regex[1] }; }
    if (expression.indexOf("|") >= 0) { return {}; }
    return F.parseTerm(expression) || {};
  }

  function openColumnMenu(field, anchor) {
    closeColumnMenu();
    var sheet = currentSheet();
    var column = columnForField(field);
    if (!sheet || !column || !tableReady) { return; }
    syncHeaderFilters();
    var state = filtersFor(sheet);
    var menu = el("div", "col-menu");
    menu.setAttribute("role", "dialog");
    menu.appendChild(el("div", "col-menu-title",
      column === ROW_NUMBER_COLUMN ? "Row number (#)" : displayTitle(column)));

    var sortRow = el("div", "col-menu-row");
    sortRow.appendChild(makeButton("Sort A → Z", function () {
      table.setSort(field, "asc");
      closeColumnMenu();
    }));
    sortRow.appendChild(makeButton("Sort Z → A", function () {
      table.setSort(field, "desc");
      closeColumnMenu();
    }));
    sortRow.appendChild(makeButton("Clear all sorting", function () {
      table.clearSort();
      closeColumnMenu();
    }));
    menu.appendChild(sortRow);
    menu.appendChild(makeButton("Custom sort…", function () {
      closeColumnMenu();
      openSortDialog();
    }));

    menu.appendChild(el("div", "col-menu-heading", "Condition"));
    var expression = state.headers[column.title] || "";
    var editor = conditionEditor(currentCondition(expression));
    function applyCondition() {
      setHeaderExpression(column,
        F.expressionFor(editor.opSelect.value, editor.value1.value, editor.value2.value));
      closeColumnMenu();
    }
    [editor.value1, editor.value2].forEach(function (input) {
      input.addEventListener("keydown", function (event) {
        if (event.key === "Enter") { applyCondition(); }
      });
    });
    var conditionRow = el("div", "col-menu-row");
    conditionRow.appendChild(editor.opSelect);
    conditionRow.appendChild(editor.value1);
    conditionRow.appendChild(editor.value2);
    conditionRow.appendChild(makeButton("Apply", applyCondition, "primary"));
    menu.appendChild(conditionRow);
    if (expression) {
      menu.appendChild(el("div", "col-menu-hint", "Header filter: " + expression));
    }

    var entries = distinctValues(sheet, column);
    var saved = state.values[column.title];
    var selected = new Set(saved ? saved : entries.map(function (entry) { return entry.key; }));
    menu.appendChild(el("div", "col-menu-heading", "Values (" + entries.length + ")"));
    var valueSearch = el("input");
    valueSearch.type = "search";
    valueSearch.placeholder = "Search values…";
    var selectAll = el("input");
    selectAll.type = "checkbox";
    var selectAllLabel = el("label", "col-menu-check col-menu-all");
    selectAllLabel.appendChild(selectAll);
    selectAllLabel.appendChild(el("span", null, "Select all shown"));
    var list = el("div", "col-menu-values");
    var LIMIT = 500;

    function shownEntries() {
      var query = valueSearch.value.trim().toLowerCase();
      return query ? entries.filter(function (entry) {
        return entry.key.toLowerCase().indexOf(query) >= 0;
      }) : entries;
    }
    function syncSelectAll() {
      var shown = shownEntries();
      var count = shown.filter(function (entry) { return selected.has(entry.key); }).length;
      selectAll.checked = shown.length > 0 && count === shown.length;
      selectAll.indeterminate = count > 0 && count < shown.length;
    }
    function renderValues() {
      var shown = shownEntries();
      list.replaceChildren();
      shown.slice(0, LIMIT).forEach(function (entry) {
        var label = el("label", "col-menu-check");
        var box = el("input");
        box.type = "checkbox";
        box.checked = selected.has(entry.key);
        box.addEventListener("change", function () {
          if (box.checked) { selected.add(entry.key); } else { selected.delete(entry.key); }
          syncSelectAll();
        });
        label.appendChild(box);
        label.appendChild(el("span", "col-menu-value", entry.key));
        label.appendChild(el("span", "col-menu-count", String(entry.count)));
        list.appendChild(label);
      });
      if (shown.length > LIMIT) {
        list.appendChild(el("div", "col-menu-hint",
          (shown.length - LIMIT) + " more values. Type to narrow the list."));
      }
      if (!shown.length) { list.appendChild(el("div", "col-menu-hint", "No values")); }
      syncSelectAll();
    }
    selectAll.addEventListener("change", function () {
      shownEntries().forEach(function (entry) {
        if (selectAll.checked) { selected.add(entry.key); } else { selected.delete(entry.key); }
      });
      renderValues();
    });
    valueSearch.addEventListener("input", renderValues);
    menu.appendChild(valueSearch);
    menu.appendChild(selectAllLabel);
    menu.appendChild(list);

    var footer = el("div", "col-menu-row col-menu-footer");
    footer.appendChild(makeButton("Apply values", function () {
      if (entries.every(function (entry) { return selected.has(entry.key); })) {
        delete state.values[column.title];
      } else {
        state.values[column.title] = entries.filter(function (entry) {
          return selected.has(entry.key);
        }).map(function (entry) { return entry.key; });
      }
      closeColumnMenu();
      refreshFilters();
    }, "primary"));
    footer.appendChild(makeButton("Clear column filter", function () {
      delete state.values[column.title];
      closeColumnMenu();
      setHeaderExpression(column, "");
      refreshFilters();
    }));
    footer.appendChild(makeButton("Close", closeColumnMenu));
    menu.appendChild(footer);
    renderValues();

    document.body.appendChild(menu);
    var rect = anchor.getBoundingClientRect();
    var left = Math.min(rect.left, window.innerWidth - menu.offsetWidth - 8);
    var top = rect.bottom + 4;
    if (top + menu.offsetHeight > window.innerHeight - 8) {
      top = Math.max(8, window.innerHeight - menu.offsetHeight - 8);
    }
    menu.style.left = Math.max(8, left) + "px";
    menu.style.top = top + "px";
    columnMenu = menu;
    document.addEventListener("mousedown", onMenuOutside, true);
    document.addEventListener("keydown", onMenuKey, true);
    valueSearch.focus();
  }

  // -------------------------------------------------------- advanced filter

  function blankRule(titles) {
    return { title: titles[1] || titles[0], op: "contains", value: "", value2: "" };
  }

  // Drops rules that cannot filter anything (no value typed) and empty groups.
  function pruneGroup(group) {
    return {
      join: group.join,
      rules: group.rules.map(function (rule) {
        return Array.isArray(rule.rules) ? pruneGroup(rule) : rule;
      }).filter(function (rule) {
        if (Array.isArray(rule.rules)) { return rule.rules.length > 0; }
        var info = operatorInfo(rule.op);
        return info.noValue || rule.value !== "" || (info.needsSecond && rule.value2 !== "");
      })
    };
  }

  function openAdvancedFilter() {
    var sheet = currentSheet();
    if (!sheet || !tableReady) { return; }
    var state = filtersFor(sheet);
    var draft = F.cloneFilters({ advanced: state.advanced }).advanced;
    var titles = [F.ROW_NUMBER_TITLE].concat(visibleColumns(sheet).map(function (column) {
      return column.title;
    }));
    if (!draft.rules.length) { draft.rules.push(blankRule(titles)); }
    var container = el("div", "advanced");

    function renderRule(rule, rules) {
      var row = el("div", "adv-row adv-rule");
      var columnSelect = el("select");
      fillOptions(columnSelect, titles.map(function (title) { return { value: title, label: title }; }));
      if (titles.indexOf(rule.title) < 0) {
        fillOptions(columnSelect, [{ value: rule.title, label: rule.title + " (not in this sheet)" }]);
      }
      columnSelect.value = rule.title;
      columnSelect.addEventListener("change", function () { rule.title = columnSelect.value; });
      var editor = conditionEditor(rule);
      editor.opSelect.addEventListener("change", function () { rule.op = editor.opSelect.value; });
      editor.value1.addEventListener("input", function () { rule.value = editor.value1.value; });
      editor.value2.addEventListener("input", function () { rule.value2 = editor.value2.value; });
      row.appendChild(columnSelect);
      row.appendChild(editor.opSelect);
      row.appendChild(editor.value1);
      row.appendChild(editor.value2);
      var remove = makeButton("✕", function () {
        rules.splice(rules.indexOf(rule), 1);
        render();
      }, "icon-button");
      remove.title = "Remove rule";
      row.appendChild(remove);
      return row;
    }

    function renderGroup(group, depth, parentRules) {
      var box = el("div", depth ? "adv-group nested" : "adv-group");
      var head = el("div", "adv-row");
      head.appendChild(el("span", "adv-label", depth ? "Group: match" : "Show rows matching"));
      var join = el("select");
      fillOptions(join, [
        { value: "and", label: "all of these (AND)" },
        { value: "or", label: "any of these (OR)" }
      ]);
      join.value = group.join;
      join.addEventListener("change", function () { group.join = join.value; });
      head.appendChild(join);
      if (depth) {
        head.appendChild(makeButton("Remove group", function () {
          parentRules.splice(parentRules.indexOf(group), 1);
          render();
        }));
      }
      box.appendChild(head);
      group.rules.forEach(function (rule) {
        box.appendChild(Array.isArray(rule.rules)
          ? renderGroup(rule, depth + 1, group.rules)
          : renderRule(rule, group.rules));
      });
      var add = el("div", "adv-row");
      add.appendChild(makeButton("+ Rule", function () {
        group.rules.push(blankRule(titles));
        render();
      }));
      if (!depth) {
        add.appendChild(makeButton("+ Group", function () {
          group.rules.push({ join: "or", rules: [blankRule(titles)] });
          render();
        }));
      }
      box.appendChild(add);
      return box;
    }

    var hint = el("div", "modal-hint",
      "Rules combine with the search box, Show filter and column filters. " +
      "Numbers compare numerically; text comparisons ignore case.");
    function render() {
      container.replaceChildren(renderGroup(draft, 0, null), hint);
    }
    render();

    showModal("Advanced filter — " + sheet.name, container, [
      { label: "Apply", value: "apply", primary: true },
      { label: "Clear rules", value: "clear" },
      { label: "Cancel", value: null }
    ]).then(function (choice) {
      if (choice === "apply") {
        state.advanced = pruneGroup(F.cloneFilters({ advanced: draft }).advanced);
      } else if (choice === "clear") {
        state.advanced = { join: "and", rules: [] };
      } else {
        return;
      }
      refreshFilters();
    });
  }

  // --------------------------------------------------------------- bulk fill

  var formulaColumn = document.getElementById("formulaColumn");
  var columnFormula = document.getElementById("columnFormula");
  var formulaScope = document.getElementById("formulaScope");
  var formulaApply = document.getElementById("formulaApply");
  var formulaRemove = document.getElementById("formulaRemove");

  function formulaEligible(column) {
    return CF.formulaEligible(column, workbook && workbook.parameterMode);
  }

  function loadFormulaDraft() {
    var sheet = currentSheet();
    var rule = sheet && layoutFor(sheet).formulas[formulaColumn.value];
    columnFormula.value = rule ? rule.expression : "";
    formulaScope.value = rule ? rule.scope : "visible";
    if (rule) {
      try {
        var titles = visibleColumns(sheet).map(c => c.title);
        columnFormula.value = CF.expandFormula(rule.expression, 1, rule.columns, titles);
        rule.expression = columnFormula.value;
        rule.columns = titles;
      } catch (error) {
        showStatus("Saved column formula needs attention: " + error.message, true);
      }
    }
  }

  function configureFormulaBar() {
    var selected = formulaColumn.value;
    formulaColumn.replaceChildren();
    var sheet = currentSheet();
    document.getElementById("formulaHint").textContent =
      (workbook && workbook.parameterMode === "Types Mode"
        ? "Type formulas affect all instances of each type, including those outside this workbook. "
        : "Instance parameters only. ") +
      "The leading = is optional. Formulas are saved with presets; Apply Changes writes to Revit.";
    var columns = sheet ? visibleColumns(sheet).filter(formulaEligible) : [];
    columns.forEach(function (column) {
      var option = document.createElement("option");
      option.value = column.title;
      var index = visibleColumns(sheet).indexOf(column);
      option.textContent = indexToLetters(index) + " - " + displayTitle(column);
      formulaColumn.appendChild(option);
    });
    if (columns.some(c => c.title === selected)) { formulaColumn.value = selected; }
    [formulaColumn, columnFormula, formulaScope, formulaApply, formulaRemove].forEach(function (node) {
      node.disabled = !columns.length;
    });
    loadFormulaDraft();
  }

  function saveFormulaDraft() {
    var sheet = currentSheet();
    if (!sheet || !formulaColumn.value || !columnFormula.value.trim()) { return; }
    var titles = visibleColumns(sheet).map(c => c.title);
    var expression = CF.normalizeFormula(columnFormula.value);
    // A restored expression retains its title bindings until the user edits it.
    var previous = layoutFor(sheet).formulas[formulaColumn.value];
    var bindings = previous && previous.expression === expression
      ? previous.columns : titles;
    CF.expandFormula(expression, 1, bindings, titles);
    layoutFor(sheet).formulas[formulaColumn.value] = {
      expression: expression,
      columns: bindings.slice(),
      scope: formulaScope.value
    };
  }

  formulaColumn.addEventListener("change", loadFormulaDraft);
  [columnFormula, formulaScope].forEach(function (node) {
    node.addEventListener("change", function () {
      try {
        saveFormulaDraft();
      } catch (error) {
        showStatus("Column formula not saved: " + error.message, true);
      }
    });
  });
  formulaApply.addEventListener("click", function () {
    var sheet = currentSheet();
    var column = sheet && columnByTitle(sheet, formulaColumn.value);
    if (!column || !formulaEligible(column)) { return; }
    var historyBefore = captureEditState();
    var oldTexts = new Map(formulaTexts);
    var oldValues = new Map(formulaValues);
    try {
      var expression = CF.normalizeFormula(columnFormula.value);
      var titles = visibleColumns(sheet).map(c => c.title);
      var previous = layoutFor(sheet).formulas[column.title];
      var bindings = previous && previous.expression === expression
        ? previous.columns : titles;
      var rows = table.getData(formulaScope.value === "all" ? undefined : "active");
      var targets = rows.filter(row => cellEditable(column, row));
      if (!targets.length) { throw new Error("No editable rows in the selected scope."); }
      targets.forEach(function (row) {
        var key = row.UniqueId + "|" + column.field;
        formulaTexts.set(key, CF.expandFormula(expression, row.__rowNo, bindings, titles));
        formulaValues.delete(key);
      });
      // Evaluate everything before changing any row or pending change. This
      // includes existing dependent formulas, and makes invalid batches atomic.
      var updates = [];
      table.getData().forEach(function (row) {
        visibleColumns(sheet).forEach(function (item) {
          var key = row.UniqueId + "|" + item.field;
          if (!formulaTexts.has(key)) { return; }
          formulaEvaluationStack.add(key);
          var value;
          try {
            value = CF.validateResult(
              evaluateFormula(formulaTexts.get(key), row.__rowNo - 1, item.field), item.storageType, item.target
            );
          } finally {
            formulaEvaluationStack.delete(key);
          }
          formulaValues.set(key, value);
          updates.push({ row: row, column: item, value: value });
        });
      });
      saveFormulaDraft();
      var byRow = new Map();
      updates.forEach(function (item) {
        var key = rowChangeKey(item.row, item.column);
        if (!originalValues.has(key)) { originalValues.set(key, item.row[item.column.field]); }
        if (String(originalValues.get(key) == null ? "" : originalValues.get(key)) === String(item.value)) {
          pendingChanges.delete(key);
        } else {
          pendingChanges.set(key, buildChange(item.row, item.column, item.value));
        }
        if (!byRow.has(item.row.UniqueId)) { byRow.set(item.row.UniqueId, { UniqueId: item.row.UniqueId }); }
        byRow.get(item.row.UniqueId)[item.column.field] = item.value;
      });
      table.updateData(Array.from(byRow.values())).then(function () {
        reportChangeCount();
        table.refreshFilter();
        recordHistory(historyBefore, "Apply formula");
        showStatus("Formula applied to " + targets.length + " row(s); " +
          (rows.length - targets.length) + " read-only row(s) skipped. Review pending changes, then Apply Changes.");
      }).catch(function (error) { showStatus("Could not update the grid: " + error.message, true); });
    } catch (error) {
      formulaTexts = oldTexts;
      formulaValues = oldValues;
      formulaEvaluationStack.clear();
      showStatus("Column formula not applied: " + error.message, true);
    }
  });
  formulaRemove.addEventListener("click", function () {
    var sheet = currentSheet();
    var column = sheet && columnByTitle(sheet, formulaColumn.value);
    if (!column) { return; }
    delete layoutFor(sheet).formulas[column.title];
    table.getData().forEach(function (row) {
      var key = row.UniqueId + "|" + column.field;
      formulaTexts.delete(key);
      formulaValues.delete(key);
    });
    loadFormulaDraft();
    showStatus("Column formula removed. Current values and pending changes are kept.");
  });

  function openBulkFill() {
    var sheet = currentSheet();
    if (!sheet || !tableReady) { return; }
    var columns = visibleColumns(sheet).filter(function (column) {
      return column.columnType === "parameter" && column.editable && !column.disabled;
    });
    if (!columns.length) {
      showStatus("This sheet has no editable parameter columns.", true);
      return;
    }
    var visibleRows = table.getData("active");
    if (!visibleRows.length) {
      showStatus("No rows are visible. Change the filters first.", true);
      return;
    }
    var form = el("div", "bulk");
    var columnLabel = el("label", "field", "Column");
    var columnSelect = el("select");
    fillOptions(columnSelect, columns.map(function (column, index) {
      return { value: String(index), label: displayTitle(column) };
    }));
    columnLabel.appendChild(columnSelect);
    var valueLabel = el("label", "field", "New value");
    var valueHolder = el("span");
    valueLabel.appendChild(valueHolder);
    var info = el("div", "modal-hint");
    var error = el("div", "modal-error");
    form.appendChild(columnLabel);
    form.appendChild(valueLabel);
    form.appendChild(info);
    form.appendChild(error);
    var input = null;
    var result = null;

    function selectedColumn() { return columns[parseInt(columnSelect.value, 10)]; }
    function rebuild() {
      var column = selectedColumn();
      if (column.storageType === "ElementId" && column.options) {
        input = el("select");
        var choices = new Set();
        visibleRows.forEach(function (row) {
          if (cellEditable(column, row)) {
            (cellColumn(column, row).options || []).forEach(function (option) { choices.add(option); });
          }
        });
        fillOptions(input, Array.from(choices).map(function (option) {
          return { value: option, label: option };
        }));
      } else {
        input = el("input");
        input.type = "text";
        input.placeholder = column.storageType === "Double" || column.storageType === "Integer"
          ? "Number" + (column.unit ? " in " + column.unit : "")
          : "Text (leave empty to clear)";
      }
      valueHolder.replaceChildren(input);
      var editable = visibleRows.filter(function (row) { return cellEditable(column, row); }).length;
      info.textContent = "Applies to " + editable + " of " + visibleRows.length + " visible row(s)." +
        (editable < visibleRows.length ? " Locked cells are skipped." : "") +
        (isSharedByType(column) ? " This is a type parameter, so every row of each affected type changes." : "");
      error.textContent = "";
    }
    columnSelect.addEventListener("change", rebuild);
    rebuild();

    function validate() {
      var column = selectedColumn();
      var raw = input.value;
      var value = raw;
      if (typeof raw === "string" && raw.trim().charAt(0) === "=") {
        error.textContent = "Formulas are not supported here; enter a plain value.";
        return false;
      }
      if (column.storageType === "Double" || column.storageType === "Integer") {
        value = Number(String(raw).trim());
        if (!String(raw).trim() || !Number.isFinite(value)) {
          error.textContent = "Enter a number.";
          return false;
        }
        if (column.storageType === "Integer" && !Number.isInteger(value)) {
          error.textContent = "This parameter only accepts whole numbers.";
          return false;
        }
      }
      try {
        visibleRows.forEach(function (row) {
          if (cellEditable(column, row)) {
            RC.literalValue(String(value), cellColumn(column, row));
          }
        });
      } catch (exc) { error.textContent = exc.message; return false; }
      result = { column: column, value: value };
      return true;
    }

    showModal("Set value for visible rows", form, [
      { label: "Set value", value: "ok", primary: true, onClick: validate },
      { label: "Cancel", value: null }
    ]).then(function (choice) {
      if (choice !== "ok" || !result) { return; }
      try {
        bulkSetValue(result.column, result.value).then(function (summary) {
          showStatus("Set " + displayTitle(result.column) + " on " + summary.rows + " row(s)" +
            (summary.skipped ? "; skipped " + summary.skipped + " locked cell(s)" : "") +
            ". Review the highlighted cells, then Apply Changes.");
        }).catch(reportGridError);
      } catch (exc) { reportGridError(exc); }
    });
  }

  // ------------------------------------------------------------ revit views

  function highlightedRows() {
    if (!tableReady || !table || table.getRanges().length !== 1) { return []; }
    var highlightedIds = new Set();
    table.getRanges()[0].getCells().forEach(function (row) {
      row.forEach(function (cell) {
        var data = cell.getRow().getData();
        if (data && data.UniqueId != null) { highlightedIds.add(String(data.UniqueId)); }
      });
    });
    return table.getData("active").filter(function (row) {
      return row.UniqueId != null && highlightedIds.has(String(row.UniqueId));
    });
  }

  function updateHighlightedRevitButtons() {
    var disabled = revitBusy || !highlightedRows().length;
    highlightedRevitButtons.forEach(function (node) { node.disabled = disabled; });
  }

  function setRevitButtons(busy) {
    revitBusy = busy;
    revitButtons.concat(highlightedRevitButtons).forEach(function (node) {
      node.disabled = busy;
    });
    if (!busy) { updateHighlightedRevitButtons(); }
  }

  function sendRevitView(mode, scope) {
    if (!currentSheet() || !tableReady) { return; }
    var rows = mode === "reset" ? [] :
      scope === "highlighted" ? highlightedRows() : table.getData("active");
    if (mode !== "reset" && !rows.length) {
      showStatus(scope === "highlighted"
        ? "No highlighted rows in the active sheet to send to Revit."
        : "No visible rows to send to Revit.", true);
      return;
    }
    setRevitButtons(true);
    showStatus(mode === "reset" ? "Resetting the active view…" :
      "Sending " + rows.length + " " + (scope === "highlighted" ? "highlighted" : "visible") +
      " row(s) to Revit…");
    post({
      type: "revitView",
      mode: mode,
      elementIds: rows.filter(function (row) { return !row.IsTypeRow; }).map(function (row) {
        return row.ElementId;
      }),
      typeIds: rows.filter(function (row) { return row.IsTypeRow; }).map(function (row) {
        return row.TypeElementId;
      })
    });
  }

  // ------------------------------------------------------------ apply/save

  function sendApply(hiddenKeys) {
    if (typeNameConflicts.size) { showStatus(""); return; }
    var hiddenSet = new Set(hiddenKeys);
    carryOver = hiddenKeys.map(function (key) {
      return { change: pendingChanges.get(key), oldValue: originalValues.get(key) };
    });
    var changes = [];
    pendingChanges.forEach(function (change, key) {
      if (!hiddenSet.has(key)) { changes.push(change); }
    });
    var partialConflicts = TN.findNameConflicts(TN.nameRecords(workbook), proposedTypeNames(changes));
    if (partialConflicts.size) {
      carryOver = [];
      showStatus("The visible rename batch conflicts with names held by filtered-out types. " +
        "Clear the filters and apply the complete rename batch.", true);
      return;
    }
    applyingChanges = true;
    post({ type: "apply", changes: changes });
    applyButton.disabled = true;
    showStatus("Applying " + changes.length + " change(s) in Revit…");
  }

  // Re-adds changes that were held back at Apply onto the refreshed workbook.
  function restoreCarryOver(nextWorkbook) {
    var historyBefore = captureEditState(nextWorkbook);
    var restored = 0;
    carryOver.forEach(function (item) {
      var change = item.change;
      nextWorkbook.sheets.some(function (sheet) {
        var column = sheetColumn(sheet, change.field);
        if (!column || column.target !== change.target) { return false; }
        var shared = isSharedByType(column);
        var targets = (sheet.rows || []).filter(function (row) {
          return shared
            ? String(row.TypeElementId) === String(change.typeElementId)
            : String(row.ElementId) === String(change.elementId);
        });
        if (!targets.length) { return false; }
        targets.forEach(function (row) { row[column.field] = change.value; });
        var key = rowChangeKey(targets[0], column);
        originalValues.set(key, item.oldValue);
        pendingChanges.set(key, buildChange(targets[0], column, change.value));
        restored += 1;
        return true;
      });
    });
    carryOver = [];
    if (restored) { recordHistory(historyBefore, "Restore filtered changes", nextWorkbook); }
    return restored;
  }

  function visibleWorkbook() {
    return Object.assign({}, workbook, {
      sheets: workbook.sheets.map(function (sheet, index) {
        return Object.assign({}, sheet, { rows: visibleRowsFor(sheet, index) });
      })
    });
  }

  // ------------------------------------------------------------ sheets

  function openSheet(index, persistCurrent) {
    closeColumnMenu();
    blurGridInput();
    if (tableReady) {
      table.getRanges().forEach(function (range) { range.remove(); });
    }
    if (tableReady && currentSheet() && persistCurrent !== false) {
      currentSheet().rows = table.getData();
      captureLayout();
    }
    activeSheetIndex = index;
    sheetSelect.value = String(index);
    reportChangeCount();
    var sheet = currentSheet();
    if (!sheet || !tableReady) { return; }
    var state = filtersFor(sheet);
    searchBox.value = state.search;
    configureShowOptions(sheet);
    showSelect.value = state.show;
    restoringFilters = true;
    contextCache = { sheet: null, context: null };
    // Sheets share field names (p0_type…), and Tabulator keeps header filter
    // values for matching fields across setColumns.
    table.clearHeaderFilter();
    table.setColumns(makeColumns(sheet));
    Object.keys(state.headers).forEach(function (title) {
      var column = columnByTitle(sheet, title);
      if (!column) { return; }
      try {
        table.setHeaderFilterValue(column.field, state.headers[title]);
      } catch (error) {
        console.warn("Could not restore the filter for " + title, error);
      }
    });
    table.replaceData(sheet.rows).then(function () {
      restoringFilters = false;
      if (currentSheet() === sheet) {
        applySort(sheet);
        updateSortSummary();
        table.refreshFilter();
        updateFilterBar();
        configureFormulaBar();
      }
    }, function (error) {
      restoringFilters = false;
      reportGridError(error);
    });
    showStatus(sheetStatus(sheet));
  }

  function renderWorkbook(nextWorkbook, resetLayouts) {
    closeColumnMenu();
    blurGridInput();
    if (tableReady && workbook && currentSheet()) {
      currentSheet().rows = table.getData();
      captureLayout();
    }
    if (resetLayouts) { layoutState.clear(); }
    workbook = nextWorkbook;
    workbook.sheets.forEach(function (sheet) {
      (sheet.rows || []).forEach(function (row, rowIndex) {
        row[F.ROW_NUMBER_FIELD] = rowIndex + 1;
      });
    });
    sheetSelect.replaceChildren();
    workbook.sheets.forEach(function (sheet, index) {
      var option = document.createElement("option");
      option.value = String(index);
      option.textContent = sheet.name + (sheet.pendingLabel || "");
      sheetSelect.appendChild(option);
    });
    refreshSheetOptions();
    if (!table) {
      if (typeof Tabulator !== "function") {
        showStatus("Tabulator is missing. Place tabulator.min.js and tabulator.min.css in the libs folder.", true);
        return;
      }
      table = new Tabulator("#grid", {
        height: "100%",
        layout: "fitDataFill",
        data: [],
        columns: [],
        index: "UniqueId",
        movableColumns: false,
        clipboard: false,
        selectableRange: 1,
        selectableRangeColumns: false,
        selectableRangeRows: true,
        selectableRangeClearCells: false,
        selectableRangeFill: false,
        editTriggerEvent: "dblclick",
        headerSortClickElement: "icon",
        columnHeaderSortMulti: false,
        // Layouts and presets store sort levels in primary-first order.
        sortOrderReverse: true,
        headerFilterLiveFilterDelay: 400,
        placeholder: "No rows match. Check the filters above."
      });
      // Tabulator builds asynchronously; setColumns/replaceData are ignored until then.
      table.on("tableBuilt", function () {
        tableReady = true;
        restoringFilters = true;
        table.setFilter(masterFilter);
        openSheet(activeSheetIndex, false);
        updateHighlightedRevitButtons();
      });
      table.on("dataFiltered", function () {
        if (!restoringFilters) { scheduleFilterBar(); }
        updateHighlightedRevitButtons();
      });
      table.on("dataSorted", onDataSorted);
      table.on("rangeAdded", updateHighlightedRevitButtons);
      table.on("rangeChanged", updateHighlightedRevitButtons);
      table.on("rangeRemoved", updateHighlightedRevitButtons);
      table.on("columnResized", function (gridColumn) {
        var column = findColumn(gridColumn.getField());
        if (column && currentSheet()) {
          layoutFor(currentSheet()).widths[column.title] = Math.round(gridColumn.getWidth());
        }
      });
      table.on("cellContext", openRangeMenu);
    }
    openSheet(0, false);
  }

  // ------------------------------------------------------------ toolbar

  var toolbarMenus = Array.from(document.querySelectorAll(".toolbar-menu"));
  toolbarMenus.forEach(function (menu) {
    menu.querySelector("summary").addEventListener("click", function () {
      closeColumnMenu();
      toolbarMenus.forEach(function (other) { if (other !== menu) { other.open = false; } });
    });
    menu.addEventListener("click", function (event) {
      if (event.target.closest("button")) { menu.open = false; }
    });
  });
  document.addEventListener("mousedown", function (event) {
    toolbarMenus.forEach(function (menu) {
      if (!menu.contains(event.target)) { menu.open = false; }
    });
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") {
      toolbarMenus.forEach(function (menu) {
        if (menu.open) { menu.open = false; menu.querySelector("summary").focus(); }
      });
    }
  });
  document.getElementById("formulaToggle").addEventListener("click", function () {
    var panel = document.getElementById("formulaPanel");
    if (!panel.hidden) { blurGridInput(); }
    panel.hidden = !panel.hidden;
    this.setAttribute("aria-expanded", String(!panel.hidden));
    if (tableReady) { table.redraw(); }
  });
  document.getElementById("findReplaceButton").addEventListener("click", function () {
    openTextTool("replace");
  });
  document.getElementById("changeCaseButton").addEventListener("click", function () {
    openTextTool("case");
  });
  var searchTimer = null;
  searchBox.addEventListener("input", function () {
    if (searchTimer) { clearTimeout(searchTimer); }
    searchTimer = setTimeout(function () {
      var sheet = currentSheet();
      if (!sheet) { return; }
      filtersFor(sheet).search = searchBox.value;
      refreshFilters();
    }, 250);
  });
  showSelect.addEventListener("change", function () {
    var sheet = currentSheet();
    if (!sheet) { return; }
    filtersFor(sheet).show = showSelect.value;
    refreshFilters();
  });
  clearFiltersButton.addEventListener("click", clearAllFilters);
  document.getElementById("advancedButton").addEventListener("click", openAdvancedFilter);
  sortButton.addEventListener("click", openSortDialog);
  sortEditButton.addEventListener("click", openSortDialog);
  sortClearButton.addEventListener("click", function () {
    if (tableReady) { table.clearSort(); }
  });
  document.getElementById("bulkButton").addEventListener("click", openBulkFill);
  document.getElementById("selectButton").addEventListener("click", function () {
    sendRevitView("select");
  });
  document.getElementById("isolateButton").addEventListener("click", function () {
    sendRevitView("isolate");
  });
  document.getElementById("selectHighlightedButton").addEventListener("click", function () {
    sendRevitView("select", "highlighted");
  });
  document.getElementById("isolateHighlightedButton").addEventListener("click", function () {
    sendRevitView("isolate", "highlighted");
  });
  document.getElementById("resetViewButton").addEventListener("click", function () {
    sendRevitView("reset");
  });
  document.addEventListener("keydown", function (event) {
    if (document.querySelector(".modal-backdrop") || document.body.inert) { return; }
    var editingControl = event.target.closest && event.target.closest(
      "input, textarea, select, [contenteditable=true]"
    );
    if ((event.ctrlKey || event.metaKey) && !editingControl &&
        event.key.toLowerCase() === "z") {
      event.preventDefault();
      if (event.shiftKey) { redoEdit(); } else { undoEdit(); }
      return;
    }
    if ((event.ctrlKey || event.metaKey) && !editingControl &&
        event.key.toLowerCase() === "y") {
      event.preventDefault();
      redoEdit();
      return;
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "h") {
      event.preventDefault();
      openTextTool("replace");
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "f") {
      event.preventDefault();
      searchBox.focus();
      searchBox.select();
    }
  });

  sheetSelect.addEventListener("change", function () {
    openSheet(parseInt(sheetSelect.value, 10));
  });
  document.getElementById("undoButton").addEventListener("click", undoEdit);
  document.getElementById("redoButton").addEventListener("click", redoEdit);
  applyButton.addEventListener("click", function () {
    if (typeNameConflicts.size) { showStatus(""); return; }
    if (!pendingChanges.size) { return; }
    var hidden = hiddenChangeKeys();
    if (!hidden.length) {
      sendApply([]);
      return;
    }
    var visibleCount = pendingChanges.size - hidden.length;
    var message = hidden.length + " of " + pendingChanges.size +
      " pending change(s) are in rows hidden by the current filters.\n\n" +
      (visibleCount
        ? "Apply only the " + visibleCount + " visible change(s)? The hidden changes stay " +
          "pending, so you can review and apply them later."
        : "None of the pending changes are visible. Change the filters to review them first.");
    var buttons = visibleCount
      ? [
        { label: "Apply " + visibleCount + " visible change(s)", value: "apply", primary: true },
        { label: "Go back to filters", value: null }
      ]
      : [{ label: "Go back to filters", value: null, primary: true }];
    showModal("Pending changes hidden by filters", message, buttons).then(function (choice) {
      if (choice === "apply") { sendApply(hidden); }
    });
  });
  document.getElementById("reloadButton").addEventListener("click", function () {
    if (pendingChanges.size &&
        !window.confirm("Reloading will discard pending changes. Continue?")) {
      return;
    }
    post({ type: "reload" });
  });
  document.getElementById("saveButton").addEventListener("click", function () {
    if (!workbook) { return; }
    if (tableReady && currentSheet()) {
      currentSheet().rows = table.getData();
      captureLayout();
    }
    var filtered = workbook.sheets.some(function (sheet) {
      return F.hasActiveFilters(filtersFor(sheet));
    });
    if (!filtered) {
      post({ type: "save", workbook: workbook });
      return;
    }
    showModal("Export XLSX",
      "Filters are active. Save every row, or only the rows the filters show?\n\n" +
      "Importing a visible-rows file later only updates the rows it contains.",
      [
        { label: "Visible rows only", value: "visible", primary: true },
        { label: "All rows", value: "all" },
        { label: "Cancel", value: null }
      ]).then(function (choice) {
      if (choice) {
        post({ type: "save", workbook: choice === "visible" ? visibleWorkbook() : workbook });
      }
    });
  });
  var importButton = document.getElementById("importButton");
  var presetButton = document.getElementById("presetButton");
  document.getElementById("closeButton").addEventListener("click", function () {
    if (clipboardBusy || importButton.disabled || presetButton.disabled ||
        applyingChanges) {
      showStatus("Wait for the current operation to finish before closing ExcelLink.", true);
      return;
    }
    blurGridInput();
    if (pendingChanges.size && !window.confirm(
      "Closing ExcelLink will discard " + pendingChanges.size + " unapplied change(s). Close anyway?"
    )) { return; }
    post({ type: "close" });
  });
  document.getElementById("backButton").addEventListener("click", function () {
    if (!workbook || !tableReady) { return; }
    if (importButton.disabled || presetButton.disabled ||
        applyingChanges) {
      showStatus("Wait for the current operation to finish before going Back.", true);
      return;
    }
    blurGridInput();
    if (pendingChanges.size && !window.confirm(
      "Returning to the wizard will replace " + pendingChanges.size +
      " unapplied change(s) when you reopen the grid. Canceling the wizard keeps them. Continue?"
    )) { return; }
    try {
      saveFormulaDraft();
    } catch (error) {
      showStatus("Cannot keep the column formula: " + error.message, true);
      return;
    }
    captureLayout();
    post({
      type: "back", sheetIndex: activeSheetIndex,
      layouts: workbook.sheets.map(layoutFor)
    });
    document.body.inert = true;
    showStatus("Returning to parameter selection...");
  });
  presetButton.addEventListener("click", function () {
    if (!workbook) { return; }
    try {
      saveFormulaDraft();
    } catch (error) {
      showStatus("Cannot save the column formula: " + error.message, true);
      return;
    }
    captureLayout();
    presetButton.disabled = true;
    showStatus("Saving preset…");
    post({ type: "savePreset", layouts: workbook.sheets.map(layoutFor) });
  });
  importButton.addEventListener("click", function () {
    if (pendingChanges.size &&
        !window.confirm("Importing replaces your " + pendingChanges.size +
          " unapplied change(s) with the changes from the file. Continue?")) {
      return;
    }
    importButton.disabled = true;
    showStatus("Choose the edited workbook (save it in Excel first)…");
    post({ type: "import" });
  });

  if (window.chrome && window.chrome.webview) {
    window.chrome.webview.addEventListener("message", function (event) {
      var message = event.data;
      if (message.type === "workbook" || message.type === "error") {
        clearTimeout(startupTimer);
      }
      if (message.type === "workbook" || message.type === "wizardCancelled" || message.type === "error") {
        document.body.inert = false;
      }
      if (message.type === "workbook" || message.type === "applied") {
        applyingChanges = false;
        importButton.disabled = false;
        applyButton.disabled = false;
        clearEditHistory();
        pendingChanges.clear();
        originalValues.clear();
        formulaValues.clear();
        formulaTexts.clear();
        formulaEvaluationStack.clear();
        message.workbook.sheets.forEach(function (sheet) { sheet.pendingLabel = ""; });
        var imported = message.importUpdates
          ? applyImportUpdates(message.workbook, message.importUpdates) : 0;
        var carried = message.type === "applied" ? restoreCarryOver(message.workbook) : 0;
        carryOver = [];
        importNotice = "";
        if (message.importUpdates) {
          var summary = message.importSummary || {};
          importNotice =
            "Imported " + (message.workbook.importFile || "workbook") + ": " +
            imported + " change(s) highlighted for review" +
            (summary.skipped ? ", " + summary.skipped + " skipped (see pyRevit output)" : "") +
            (summary.rowsUnmatched ? ", " + summary.rowsUnmatched + " row(s) not found" : "") +
            (message.layoutReplaced ? ", grid rebuilt to match the file's sheets and columns" : "") +
            (message.removedElements
              ? ", " + message.removedElements + " deleted element(s) removed from the grid"
              : "") +
            ". Hover a highlighted cell to compare with Revit, then Apply Changes.";
        }
        reportChangeCount();
        renderWorkbook(message.workbook, message.wizardRebuilt);
        if (message.type === "applied") {
          showStatus("Applied " + message.result.applied + " change(s)." +
            (carried ? " " + carried + " change(s) in filtered-out rows are still pending." : "") +
            (message.removedElements
              ? " " + message.removedElements + " deleted element(s) were removed from the grid."
              : ""));
        } else if (message.importUpdates) {
          var firstSheet = message.workbook.sheets.findIndex(function (sheet) {
            return !!sheet.pendingLabel;
          });
          if (firstSheet > 0) { openSheet(firstSheet, false); }
        } else if (message.removedElements) {
          showStatus("Reloaded from Revit. " + message.removedElements +
            " deleted element(s) were removed from the grid.");
        }
      } else if (message.type === "wizardCancelled") {
        showStatus("Wizard canceled. The grid and unapplied changes are unchanged.");
      } else if (message.type === "error") {
        applyingChanges = false;
        carryOver = [];
        if (message.typeNames && workbook) {
          workbook.sheets.forEach(function (sheet) { sheet.typeNames = message.typeNames; });
        }
        reportChangeCount();
        importButton.disabled = false;
        presetButton.disabled = false;
        setRevitButtons(false);
        showStatus(message.message + (message.details ? "\n" + message.details : ""), true);
      } else if (message.type === "revitViewDone") {
        setRevitButtons(false);
        showStatus(message.message);
      } else if (message.type === "importCancelled") {
        importButton.disabled = false;
        openSheet(activeSheetIndex, false);
      } else if (message.type === "saved") {
        showStatus("Workbook saved" + (message.path ? " to " + message.path : "") +
          (message.opened ? " and opened in Excel" : "") +
          ". Edit and save it in Excel, then use Import XLSX to bring the changes back.");
      } else if (message.type === "presetSaved") {
        presetButton.disabled = false;
        workbook.presetName = message.name;
        showStatus("Preset '" + message.name + "' saved to " + message.path +
          ". Load it from the first wizard step in any project.");
      } else if (message.type === "presetCancelled") {
        presetButton.disabled = false;
        if (currentSheet()) { showStatus(sheetStatus(currentSheet())); }
      }
    });
    showStatus("Loading workbook from Revit...");
    startupTimer = setTimeout(function () {
      reportGridError(new Error(
        "No workbook was received from Revit. Close this window, reload pyRevit " +
        "to activate ExcelLink's persistent engine, and reopen the tool."
      ));
    }, 10000);
    window.chrome.webview.postMessage({ type: "ready" });
  } else {
    showStatus("Open this page from the KW ExcelLink Revit command.", true);
  }
}());
