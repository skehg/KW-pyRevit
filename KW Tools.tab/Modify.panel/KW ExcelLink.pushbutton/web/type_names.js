export function nameValue(value) {
  var name = String(value == null ? "" : value).trim();
  if (!name || /[\\:{}[\]|;<>?`~\x00-\x1f]/.test(name)) {
    throw new Error("Type names cannot be blank or contain prohibited Revit name characters.");
  }
  return name;
}

export function findNameConflicts(records, proposals) {
  var groups = new Map(), conflicts = new Map();
  records.forEach(function (record) {
    var id = String(record.id);
    var name = proposals.has(id) ? proposals.get(id) : record.name;
    var key = JSON.stringify([record.scope, String(name)]);
    if (!groups.has(key)) { groups.set(key, []); }
    groups.get(key).push({...record, name: name});
  });
  groups.forEach(function (items) {
    if (items.length < 2 || !items.some(item => proposals.has(String(item.id)))) { return; }
    items.forEach(function (item) {
      var others = items.filter(other => other.id !== item.id);
      conflicts.set(String(item.id), "Type name '" + item.name + "' conflicts with " +
        others.map(other => "'" + other.name + "' in " + other.family + " (type ID " + other.id + ")").join(", ") + ".");
    });
  });
  return conflicts;
}

export function nameRecords(workbook) {
  var records = new Map();
  (workbook.sheets || []).forEach(function (sheet) {
    (sheet.typeNames || []).forEach(item => records.set(String(item.id), item));
  });
  return Array.from(records.values());
}
