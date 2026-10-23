// Reference choices can differ between rows even when parameter identity matches.
export function cellColumn(column, row) {
  var metadata = row && row[column.field + "__metadata"];
  return metadata ? Object.assign({}, column, metadata) : column;
}

export function typeLabel(column) {
  var label = column.dataType || "";
  return column.unit ? label + (label ? " " : "") + "[" + column.unit + "]" : label;
}
