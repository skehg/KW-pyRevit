import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import vm from "node:vm";

const appSource = readFileSync(new URL("../app.js", import.meta.url), "utf8");
const htmlSource = readFileSync(new URL("../index.html", import.meta.url), "utf8");
const highlightedStart = appSource.indexOf("  function highlightedRows() {");
const highlightedEnd = appSource.indexOf("  function updateHighlightedRevitButtons()", highlightedStart);
const sendStart = appSource.indexOf("  function sendRevitView(mode, scope) {");
const sendEnd = appSource.indexOf("  // ------------------------------------------------------------ apply/save", sendStart);
assert.ok(highlightedStart >= 0 && highlightedEnd > highlightedStart);
assert.ok(sendStart >= 0 && sendEnd > sendStart);

function setup(selected, active) {
  const posts = [];
  const statuses = [];
  const busyStates = [];
  const context = vm.createContext({
    tableReady: true,
    table: {
      getRanges: () => selected ? [{
        getCells: () => selected.map(row => row.map(data => ({
          getRow: () => ({getData: () => data})
        })))
      }] : [],
      getData: () => active
    },
    currentSheet: () => ({}),
    setRevitButtons: busy => busyStates.push(busy),
    showStatus: message => statuses.push(message),
    post: message => posts.push(message)
  });
  vm.runInContext(
    appSource.slice(highlightedStart, highlightedEnd) +
      appSource.slice(sendStart, sendEnd),
    context
  );
  return {context, posts, statuses, busyStates};
}

test("highlightedRows deduplicates highlighted cells and excludes rows hidden by filters", () => {
  const first = {UniqueId: "one", ElementId: 1};
  const second = {UniqueId: "two", IsTypeRow: true, TypeElementId: 22};
  const hidden = {UniqueId: "hidden", ElementId: 3};
  const harness = setup([[first, first], [second], [hidden]], [first, second]);

  assert.deepEqual(Array.from(harness.context.highlightedRows()), [first, second]);
  assert.equal(harness.context.highlightedRows().some(row => row === hidden), false);
});

test("highlighted Revit actions dispatch only rows intersecting the highlighted range", () => {
  const first = {UniqueId: "one", ElementId: 1};
  const second = {UniqueId: "two", IsTypeRow: true, TypeElementId: 22};
  const other = {UniqueId: "other", ElementId: 3};
  const harness = setup([[first], [second]], [first, second, other]);

  harness.context.sendRevitView("select", "highlighted");

  assert.deepEqual(JSON.parse(JSON.stringify(harness.posts[0])), {
    type: "revitView",
    mode: "select",
    elementIds: [1],
    typeIds: [22]
  });
  assert.match(harness.statuses[0], /2 highlighted row/);
});

test("highlighted Revit actions do not fall back to visible rows when no range exists", () => {
  const active = [{UniqueId: "visible", ElementId: 1}];
  const harness = setup(null, active);

  harness.context.sendRevitView("isolate", "highlighted");

  assert.equal(harness.posts.length, 0);
  assert.match(harness.statuses[0], /No highlighted rows/);
  assert.deepEqual(harness.busyStates, []);
});

test("existing Revit actions still target visible rows and reset stays last in the menu", () => {
  const first = {UniqueId: "one", ElementId: 1};
  const second = {UniqueId: "two", IsTypeRow: true, TypeElementId: 22};
  const harness = setup(null, [first, second]);

  harness.context.sendRevitView("select");

  assert.deepEqual(JSON.parse(JSON.stringify(harness.posts[0])), {
    type: "revitView",
    mode: "select",
    elementIds: [1],
    typeIds: [22]
  });
  const menuOrder = [
    "id=\"selectButton\"",
    "id=\"isolateButton\"",
    "id=\"selectHighlightedButton\"",
    "id=\"isolateHighlightedButton\"",
    "id=\"resetViewButton\""
  ].map(value => htmlSource.indexOf(value));
  assert.ok(menuOrder.every(index => index >= 0));
  assert.deepEqual(menuOrder, menuOrder.slice().sort((a, b) => a - b));
});
