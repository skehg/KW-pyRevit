import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import vm from "node:vm";

const source = readFileSync(new URL("../app.js", import.meta.url), "utf8");
const start = source.indexOf("  function handleZoomReset(event) {");
const end = source.indexOf('  document.addEventListener("keydown", handleZoomReset, true);', start);
assert.ok(start >= 0 && end > start);

function setup() {
  const messages = [];
  const registrations = [];
  const context = vm.createContext({
    post: message => messages.push(message.type),
    document: {addEventListener: (...args) => registrations.push(args)}
  });
  vm.runInContext(source.slice(start, end) +
    'document.addEventListener("keydown", handleZoomReset, true);', context);
  return {messages, registrations, handler: context.handleZoomReset};
}

function keyEvent(overrides = {}) {
  return {
    ctrlKey: true, altKey: false, shiftKey: false, metaKey: false,
    key: "0", code: "Digit0", prevented: false, stopped: false,
    preventDefault() { this.prevented = true; },
    stopPropagation() { this.stopped = true; },
    ...overrides
  };
}

test("Ctrl+0 and numpad zero reset zoom from grid, editor or modal focus", () => {
  const {handler, messages, registrations} = setup();
  assert.equal(registrations[0][0], "keydown");
  assert.equal(registrations[0][2], true);
  for (const target of [{tagName: "DIV"}, {tagName: "INPUT"}, {tagName: "TEXTAREA"}]) {
    for (const keys of [{}, {key: "Insert", code: "Numpad0"}]) {
      const event = keyEvent({target, ...keys});
      handler(event);
      assert.equal(event.prevented, true);
      assert.equal(event.stopped, true);
    }
  }
  assert.deepEqual(messages, Array(6).fill("resetZoom"));
});

test("other keys and modifier combinations retain existing behavior", () => {
  const {handler, messages} = setup();
  for (const keys of [
    {ctrlKey: false}, {altKey: true}, {shiftKey: true}, {metaKey: true},
    {key: "+", code: "Equal"}, {key: "-", code: "Minus"},
    {key: "c", code: "KeyC"}, {key: "z", code: "KeyZ"}
  ]) {
    const event = keyEvent(keys);
    handler(event);
    assert.equal(event.prevented, false);
    assert.equal(event.stopped, false);
  }
  assert.deepEqual(messages, []);
});
