import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import vm from "node:vm";

const appSource = readFileSync(new URL("../app.js", import.meta.url), "utf8");
const cssSource = readFileSync(new URL("../styles.css", import.meta.url), "utf8");

function getFunction(first, next) {
  const start = appSource.indexOf("  function " + first + "(");
  const end = appSource.indexOf("  function " + next + "(", start);
  assert.ok(start >= 0 && end > start);
  return appSource.slice(start, end);
}

test("popup positions are clamped to the viewport edges", () => {
  const context = vm.createContext({window: {innerWidth: 800, innerHeight: 600}});
  vm.runInContext(getFunction("positionMenu", "activateColumnMenu"), context);
  const menu = {offsetWidth: 250, offsetHeight: 180, style: {}};

  context.positionMenu(menu, 700, 550);
  assert.deepEqual(menu.style, {left: "542px", top: "412px"});

  context.positionMenu(menu, 0, 0);
  assert.deepEqual(menu.style, {left: "8px", top: "8px"});

  context.window.innerWidth = 320;
  context.window.innerHeight = 200;
  menu.offsetWidth = 304;
  menu.offsetHeight = 184;
  context.positionMenu(menu, 200, 100);
  assert.deepEqual(menu.style, {left: "8px", top: "8px"});
});

test("popup menus reposition on resize and disconnect handlers when closed", () => {
  const windowListeners = {};
  const documentListeners = {};
  const observers = [];
  function ResizeObserver(callback) {
    this.callback = callback;
    this.observe = target => { this.target = target; };
    this.disconnect = () => { this.disconnected = true; };
    observers.push(this);
  }
  const context = vm.createContext({
    window: {
      innerWidth: 800, innerHeight: 600,
      addEventListener(name, handler) { windowListeners[name] = handler; },
      removeEventListener(name, handler) {
        if (windowListeners[name] === handler) { delete windowListeners[name]; }
      }
    },
    document: {
      addEventListener(name, handler) { documentListeners[name] = handler; },
      removeEventListener(name, handler) {
        if (documentListeners[name] === handler) { delete documentListeners[name]; }
      }
    },
    ResizeObserver,
    columnMenu: null,
    columnMenuResizeHandler: null,
    columnMenuObserver: null,
    onMenuOutside() {},
    onMenuKey() {}
  });
  vm.runInContext(
    getFunction("positionMenu", "activateColumnMenu") +
      getFunction("activateColumnMenu", "onMenuOutside") +
      getFunction("closeColumnMenu", "distinctValues"),
    context
  );
  const menu = {
    offsetWidth: 250, offsetHeight: 180, style: {},
    remove() { this.removed = true; }
  };
  var repositionCount = 0;
  function reposition() {
    repositionCount += 1;
    context.positionMenu(menu, 700, 550);
  }

  context.activateColumnMenu(menu, reposition);
  assert.equal(repositionCount, 1);
  assert.deepEqual(menu.style, {left: "542px", top: "412px"});
  windowListeners.resize();
  observers[0].callback();
  assert.equal(repositionCount, 3);

  context.closeColumnMenu();
  assert.equal(menu.removed, true);
  assert.equal(observers[0].disconnected, true);
  assert.equal(windowListeners.resize, undefined);
  assert.equal(documentListeners.mousedown, undefined);
  assert.equal(documentListeners.keydown, undefined);
});

test("popup styling constrains width and height while allowing internal scrolling", () => {
  assert.match(cssSource, /\.col-menu\s*\{[^}]*max-width:\s*calc\(100vw - 16px\)/s);
  assert.match(cssSource, /\.col-menu\s*\{[^}]*max-height:\s*calc\(100vh - 16px\)/s);
  assert.match(cssSource, /\.col-menu\s*\{[^}]*overflow-y:\s*auto/s);
});
