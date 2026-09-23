// A picker whose search ranks by the case you type (issue #468).
//
// Streamlit's own selectbox ranks case-insensitively, so `fn` and `FN` always
// tie. Here the ranking is ours: a match in the exact case beats the same match
// in another case, and the order the app supplied settles every remaining tie.
// It all happens in the browser, so typing costs no round trip; a pick is
// reported with setStateValue, which inside an st.form waits for the submit.
//
// One choice (a dropdown) or, with `data.multi`, several (chips in the field).

const MAX_SHOWN = 200;

const isWordChar = (ch) => ch !== undefined && /[\p{L}\p{N}]/u.test(ch);

// What separates one name from the next in a caption (`Class: add · label`,
// `ex:add`, a URI's path), as against the `-` and `_` inside a name such as
// `1-cpl-add`, which only separate words.
const isNameEdge = (ch) => ch === undefined || /[\s:·/#(),]/u.test(ch);

// Tier of one match of `q` at `at` in `text`: a whole name beats a whole word,
// which beats the start of a word, which beats anywhere inside one. Lower is
// better. So `add` lists `add` above `1-cpl-add` (issue #479), where both were
// whole words and the supplied order put the digit first.
function placeTier(text, q, at) {
  const before = text[at - 1];
  const after = text[at + q.length];
  if (isNameEdge(before) && isNameEdge(after)) return 0;
  const starts = !isWordChar(before);
  const ends = !isWordChar(after);
  if (starts && ends) return 1;
  return starts ? 2 : 3;
}

function bestPlace(text, q) {
  let best = -1;
  for (let at = text.indexOf(q); at !== -1; at = text.indexOf(q, at + 1)) {
    const tier = placeTier(text, q, at);
    if (best === -1 || tier < best) best = tier;
    if (best === 0) break;
  }
  return best;
}

// How many characters the letters of `q`, in order, span in `text`, taking
// the tightest run that starts at an occurrence of its first letter; -1 when
// they are not all there.
function subsequenceSpan(q, text) {
  let best = -1;
  for (let start = text.indexOf(q[0]); start !== -1; start = text.indexOf(q[0], start + 1)) {
    let at = start;
    for (const ch of q.slice(1)) {
      at = text.indexOf(ch, at + 1);
      if (at === -1) return best;
    }
    const span = at - start + 1;
    if (best === -1 || span < best) best = span;
  }
  return best;
}

// Rank of `caption` for query `q`, or -1 when it does not match. Each place
// tier comes in two cases, exact first, so typing `FN` lists `FN` above `fn`
// and typing `fn` lists `fn` above `FN`. A caption that only holds the letters
// in order still matches, last, as it did with Streamlit's fuzzy search, the
// tighter the run of letters the better (`pytrip` finds `Py-trip` before
// `Py-trig-id`, issue #244).
export function rankCaption(caption, q) {
  if (!q) return 0;
  const exact = bestPlace(caption, q);
  const folded = bestPlace(caption.toLowerCase(), q.toLowerCase());
  if (exact === -1 && folded === -1) {
    const span = subsequenceSpan(q.toLowerCase(), caption.toLowerCase());
    return span === -1 ? -1 : 8 + span / (span + 1);
  }
  if (exact !== -1 && exact <= folded) return exact * 2;
  return folded * 2 + 1;
}

// Indices of the captions matching `q`, best first; a stable sort keeps the
// app's order within a rank. `skip` holds indices to leave out.
export function rankOptions(captions, q, skip = new Set()) {
  const hits = [];
  captions.forEach((caption, index) => {
    if (skip.has(index)) return;
    const rank = rankCaption(caption, q);
    if (rank !== -1) hits.push([rank, index]);
  });
  hits.sort((a, b) => a[0] - b[0]);
  return hits.map((hit) => hit[1]);
}

// The page's own colours, read off the host document so light, dark and
// custom themes all come through: the shadow root inherits text colour and
// font, but not the app background the dropdown sits on, nor the theme's
// secondary background Streamlit fills its fields with. The sidebar is painted
// in that one; without a sidebar the CSS falls back to a tint of the text.
function applyTheme(root) {
  const app = document.querySelector("[data-testid='stApp']") || document.body;
  const background = getComputedStyle(app).backgroundColor;
  if (background) root.style.setProperty("--cp-background", background);
  const sidebar = document.querySelector("[data-testid='stSidebar']");
  const fill = sidebar && getComputedStyle(sidebar).backgroundColor;
  if (fill && fill !== "rgba(0, 0, 0, 0)") root.style.setProperty("--cp-fill", fill);
}

function row(text, className) {
  const li = document.createElement("li");
  li.textContent = text;
  if (className) li.className = className;
  return li;
}

export default function ({ data, parentElement, setStateValue }) {
  const root = parentElement.querySelector(".cp-root");
  const input = root.querySelector("input");
  const list = root.querySelector("ul");
  const chips = root.querySelector(".cp-chips");
  const clear = root.querySelector(".cp-clear");
  const label = root.querySelector("label");
  const help = root.querySelector(".cp-help");

  const { options, captions, multi } = data;
  label.firstChild.textContent = data.label;
  root.classList.toggle("cp-label-hidden", data.labelVisibility === "hidden");
  root.classList.toggle("cp-label-collapsed", data.labelVisibility === "collapsed");
  root.classList.toggle("cp-multi", !!multi);
  help.hidden = !data.help;
  help.title = data.help || "";
  // The help as the field's description, so a screen reader reads it on focus
  // rather than only on hover, as the page shim arranges for Streamlit's own
  // widgets (issue #383).
  root.querySelector("#cp-desc").textContent = data.help || "";
  if (data.help) input.setAttribute("aria-describedby", "cp-desc");
  else input.removeAttribute("aria-describedby");
  input.setAttribute("aria-label", data.label);
  input.placeholder = data.placeholder;
  input.disabled = !!data.disabled;
  applyTheme(root);

  const focused = () =>
    document.activeElement === input || root.getRootNode().activeElement === input;

  // A pick not yet back from the server. Inside a form it only arrives on
  // submit, and until then any rerun redraws with the value the server held
  // when the pick was made: that pick is still what goes in, so it is still
  // what is shown. Once the server reports anything else it has taken over.
  const serverValue = JSON.stringify(data.value ?? null);
  if (root.cpPending && root.cpPending.base !== serverValue) root.cpPending = null;
  const value = root.cpPending ? root.cpPending.value : data.value;

  // What is chosen: one index (single) or indices in the order picked (multi).
  // A rerun that lands while the field is in use keeps the local choice, which
  // may be a pick ahead of the one the rerun was for.
  let current = multi ? -1 : options.indexOf(value);
  // A value typed in where the page accepts new ones, before the rerun that
  // makes it an option; inside a form, that is until the submit.
  let typedValue = !multi && current === -1 && typeof value === "string" ? value : "";
  if (multi) {
    const incoming = (value || [])
      .map((option) => options.indexOf(option))
      .filter((index) => index !== -1);
    root.cpIncoming = incoming;
    if (!(focused() && root.cpChosen)) root.cpChosen = incoming;
  }
  const chosen = () => root.cpChosen;

  let shown = [];
  let rows = []; // what each highlightable row does when taken
  let active = -1;

  const report = (value) => {
    // [value, nonce]: the nonce makes every pick a change, so picking the
    // same entry again after the page moved the value elsewhere is still
    // reported. A list, not an object: Streamlit reads a state holding only a
    // dict-valued `value` as that dict's keys, and the change callback for
    // `value` would never fire.
    root.cpPending = { base: serverValue, value };
    setStateValue("value", [value, Date.now()]);
  };

  // Declared before first use below; the chips call back into it.
  let unchoose;

  const drawChips = () => {
    if (!multi) {
      chips.replaceChildren();
      return;
    }
    chips.replaceChildren(
      ...chosen().map((index, at) => {
        const chip = document.createElement("span");
        chip.className = "cp-chip";
        chip.textContent = captions[index];
        const remove = document.createElement("button");
        remove.type = "button";
        remove.textContent = "×";
        remove.setAttribute("aria-label", `Remove ${captions[index]}`);
        remove.disabled = input.disabled;
        remove.onmousedown = (event) => {
          event.preventDefault();
          unchoose(at);
        };
        chip.append(remove);
        return chip;
      }),
    );
  };

  const showCurrent = () => {
    if (multi) {
      input.value = "";
      input.placeholder = chosen().length ? "" : data.placeholder;
      clear.hidden = !chosen().length || input.disabled;
      drawChips();
      return;
    }
    input.value = current === -1 ? typedValue : captions[current];
    clear.hidden = (current === -1 && !typedValue) || input.disabled;
  };

  const close = () => {
    list.hidden = true;
    input.setAttribute("aria-expanded", "false");
    showCurrent();
  };

  const highlight = (next) => {
    const items = list.querySelectorAll("li[data-row]");
    if (!items.length) return;
    active = Math.max(0, Math.min(next, items.length - 1));
    root.cpActive = active;
    items.forEach((li, i) => li.classList.toggle("cp-active", i === active));
    items[active].scrollIntoView({ block: "nearest" });
  };

  const pick = (index) => {
    current = index;
    typedValue = "";
    close();
    report(index === -1 ? null : options[index]);
  };

  // A value typed in rather than picked, where the page accepts new ones.
  const pickTyped = (text) => {
    current = -1;
    typedValue = text;
    close();
    report(text);
  };

  const commitMany = () => {
    report(chosen().map((index) => options[index]));
    drawChips();
    clear.hidden = !chosen().length || input.disabled;
  };

  const typed = () => {
    const text = input.value.trim();
    return data.acceptNewOptions && text && !options.includes(text) ? text : "";
  };

  const addRow = (li, take) => {
    li.dataset.row = String(rows.length);
    li.setAttribute("role", "option");
    li.addEventListener("mousedown", (event) => {
      event.preventDefault();
      take();
    });
    rows.push(take);
    return li;
  };

  // `keep` is the row to stay on when a rerun redraws an open list.
  const render = (keep) => {
    const q = input.value;
    shown = rankOptions(captions, q, new Set(multi ? chosen() : []));
    rows = [];
    const items = [];
    // The bulk row is offered but never taken by default: it is highlighted
    // only by the arrow keys, so type-and-Enter picks one option, not every
    // match (see SELECT_ALL_NOTE in case_picker.py).
    let firstReal = 0;
    if (multi && data.selectAll && shown.length >= 2) {
      const all = [...shown];
      const text = q ? `Select ${all.length} matches` : "Select all";
      items.push(addRow(row(text, "cp-bulk"), () => choose(all)));
      firstReal = 1;
    }
    for (const index of shown.slice(0, MAX_SHOWN)) {
      const li = row(captions[index], index === current ? "cp-selected" : "");
      items.push(addRow(li, () => (multi ? choose([index]) : pick(index))));
    }
    const text = typed();
    if (text) items.push(addRow(row(`Add: ${text}`), () => pickTyped(text)));
    if (!rows.length) items.push(row("No results", "cp-note"));
    else if (shown.length > MAX_SHOWN) {
      items.push(row(`${shown.length - MAX_SHOWN} more, type to narrow`, "cp-note"));
    }
    list.replaceChildren(...items);
    const selectedAt = !multi && !q ? shown.indexOf(current) : -1;
    if (keep !== undefined) highlight(keep);
    else highlight(selectedAt === -1 ? Math.min(firstReal, rows.length - 1) : selectedAt);
  };

  const choose = (indices) => {
    root.cpChosen = [...chosen(), ...indices];
    input.value = "";
    input.placeholder = "";
    commitMany();
    render();
  };

  unchoose = (at) => {
    root.cpChosen = chosen().filter((_, i) => i !== at);
    commitMany();
    if (!list.hidden) render();
    else showCurrent();
  };

  const open = () => {
    if (input.disabled) return;
    list.hidden = false;
    input.setAttribute("aria-expanded", "true");
    render();
  };

  // Handlers are assigned rather than added: this function runs again for
  // every new `data`, on the same elements.
  input.onfocus = () => {
    input.value = "";
    if (!multi) {
      const shownValue = current === -1 ? typedValue : captions[current];
      input.placeholder = shownValue || data.placeholder;
    }
    open();
  };
  input.onblur = () => {
    input.placeholder = data.placeholder;
    // The page may have reordered what it was sent (the graph filter keeps
    // entity order); take that order once the field is let go, but only when
    // it holds the same options, so a pick still on its way is not undone.
    if (multi) {
      const same = new Set(root.cpIncoming);
      if (same.size === chosen().length && chosen().every((i) => same.has(i))) {
        root.cpChosen = root.cpIncoming;
      }
    }
    close();
  };
  input.oninput = () => {
    if (list.hidden) open();
    else render();
  };
  input.onkeydown = (event) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (list.hidden) open();
      else highlight(active + (event.key === "ArrowDown" ? 1 : -1));
    } else if (event.key === "Enter") {
      // Never let Enter reach the form: it would submit before the pick lands.
      event.preventDefault();
      if (!list.hidden && rows[active]) rows[active]();
    } else if (event.key === "Escape") {
      input.blur();
    } else if (event.key === "Backspace" && multi && !input.value && chosen().length) {
      unchoose(chosen().length - 1);
    } else if (
      !multi &&
      list.hidden &&
      event.key.length === 1 &&
      !event.ctrlKey &&
      !event.metaKey &&
      !event.altKey
    ) {
      // Typing into a field still showing its pick starts a new search, as it
      // does on focus; otherwise `FN` picked and `fn` typed searched `FNfn`.
      input.value = "";
    }
  };
  clear.onmousedown = (event) => {
    event.preventDefault();
    if (multi) {
      root.cpChosen = [];
      commitMany();
      if (!list.hidden) render();
      else showCurrent();
    } else {
      pick(-1);
    }
  };

  // Leave what the user is typing alone when a rerun lands mid-search, but
  // rebuild an open list: its rows belong to the run before, and the keys
  // work through this run's handlers.
  if (!focused()) close();
  else if (list.hidden) drawChips();
  else {
    drawChips();
    render(root.cpActive);
  }
}
