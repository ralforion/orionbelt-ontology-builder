// Just enough DOM to drive case_picker.js under Node, for tests/test_case_picker.py.
//
// Usage: node case_picker_dom.mjs <path to case_picker.js> <scenario JSON>
// The scenario is a list of steps; the script prints what each "look" saw.

class ClassList {
  constructor() {
    this.names = new Set();
  }
  toggle(name, on) {
    if (on === undefined ? !this.names.has(name) : on) this.names.add(name);
    else this.names.delete(name);
  }
  add(name) {
    this.names.add(name);
  }
  contains(name) {
    return this.names.has(name);
  }
}

class El {
  constructor(tag) {
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.dataset = {};
    this.attrs = {};
    this.hidden = false;
    this.disabled = false;
    this.value = "";
    this.placeholder = "";
    this.textContent = "";
    this.classList = new ClassList();
    this.style = { setProperty() {} };
    this.listeners = {};
  }
  set className(name) {
    this.classList = new ClassList();
    for (const part of name.split(" ").filter(Boolean)) this.classList.add(part);
  }
  get firstChild() {
    return this.children[0];
  }
  setAttribute(name, value) {
    this.attrs[name] = String(value);
  }
  getAttribute(name) {
    return this.attrs[name] ?? null;
  }
  addEventListener(type, fn) {
    this.listeners[type] = fn;
  }
  append(...nodes) {
    this.children.push(...nodes);
  }
  replaceChildren(...nodes) {
    this.children = nodes;
  }
  scrollIntoView() {}
  querySelectorAll(selector) {
    if (selector === "li[data-row]") {
      return this.children.filter((c) => c.tagName === "LI" && c.dataset.row !== undefined);
    }
    throw new Error(`unsupported selector ${selector}`);
  }
  getRootNode() {
    return globalThis.document;
  }
}

globalThis.document = {
  activeElement: null,
  body: new El("body"),
  createElement: (tag) => new El(tag),
  querySelector: () => null,
};
globalThis.getComputedStyle = () => ({ backgroundColor: "" });

const [modulePath, scenarioJson] = process.argv.slice(2);
const { default: mount } = await import(modulePath);

// The component's markup, as case_picker.py writes it.
const root = new El("div");
const label = new El("label");
label.append(new El("span"));
const parts = {
  ".cp-root": root,
  input: new El("input"),
  ul: Object.assign(new El("ul"), { hidden: true }),
  ".cp-chips": new El("span"),
  ".cp-clear": Object.assign(new El("button"), { hidden: true }),
  label,
  ".cp-help": new El("span"),
};
root.querySelector = (selector) => parts[selector];
const parentElement = { querySelector: (selector) => parts[selector] };
const { input } = parts;
const list = parts.ul;
const clear = parts[".cp-clear"];
const chips = parts[".cp-chips"];

const reports = [];
const setStateValue = (name, value) => reports.push(value[0]);
const render = (data) => mount({ data, parentElement, setStateValue });

const out = [];
for (const step of JSON.parse(scenarioJson)) {
  const [op, arg] = step;
  if (op === "render") render(arg);
  else if (op === "focus") {
    document.activeElement = input;
    input.onfocus();
  } else if (op === "blur") {
    document.activeElement = null;
    input.onblur();
  } else if (op === "type") {
    input.value = arg;
    input.oninput();
  } else if (op === "key") {
    input.onkeydown({ key: arg, preventDefault() {} });
  } else if (op === "look") {
    out.push({
      value: input.value,
      clear: !clear.hidden,
      open: !list.hidden,
      rows: list.children.map((li) => li.textContent),
      chips: chips.children.map((chip) => chip.textContent),
      reports: [...reports],
    });
  }
}
console.log(JSON.stringify(out));
