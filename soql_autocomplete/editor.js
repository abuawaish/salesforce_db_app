function mountEditor(root) {
  const box = root.querySelector("textarea"), mirror = root.querySelector(".mirror");
  const popup = root.querySelector(".popup"), list = root.querySelector("#choices");
  const track = root.querySelector(".track"), status = root.querySelector(".status");
  const run = root.querySelector(".run");
  let api, index, generation, revision, saved, pending, timer, expires;
  let matches, selected = 0, dismissed = false, composing = false, failed = new Set();
  let paused = false;
  const listeners = new AbortController();
  function on(target, event, fn, options = {}) {
    target.addEventListener(event, fn, {...options, signal: listeners.signal});
  }
  const focused = () => root.getRootNode().activeElement === box;
  const payload = () => ({generation, revision, text: box.value});
  function hide() {
    if (popup.matches(":popover-open")) popup.hidePopover();
    popup.hidden = true;
    box.removeAttribute("aria-activedescendant");
  }
  function position() {
    if (popup.hidden) return;
    const rect = box.getBoundingClientRect();
    Object.assign(mirror.style, {left:rect.left+"px", top:rect.top+"px",
      width:(box.clientWidth + 2)+"px", height:rect.height+"px"});
    const caret = box.selectionStart;
    const mark = document.createElement("span");
    mark.textContent = box.value.slice(caret) || "\u200b";
    mirror.replaceChildren(document.createTextNode(box.value.slice(0, caret)), mark);
    mirror.scrollTop = box.scrollTop;
    mirror.scrollLeft = box.scrollLeft;
    const r = mark.getClientRects()[0] || rect;
    const x = Math.min(Math.max(8, r.left), window.innerWidth - popup.offsetWidth - 8);
    const bottom = Math.max(rect.top, Math.min(rect.bottom, r.bottom)) + 4;
    const y = bottom + popup.offsetHeight <= innerHeight ? bottom : Math.max(4, r.top - popup.offsetHeight - 4);
    popup.style.left = x+"px";
    popup.style.top = y+"px";
  }
  function draw() {
    const items = matches.items, first = Math.max(0, Math.floor(list.scrollTop / 32) - 1);
    track.style.height = items.length * 32 + "px";
    const rows = document.createDocumentFragment();
    for (let i = first; i < Math.min(first + 10, items.length); i++) {
      const row = document.createElement("div"), label = document.createElement("span"), kind = document.createElement("small");
      row.className = "option";
      row.id = "soql-option-" + i;
      row.dataset.index = i;
      row.style.top = i * 32 + "px";
      row.setAttribute("role", "option");
      row.setAttribute("aria-selected", String(i === selected));
      row.setAttribute("aria-posinset", i + 1);
      row.setAttribute("aria-setsize", items.length);
      label.textContent = items[i].label;
      kind.textContent = items[i].kind;
      row.append(label, kind);
      rows.appendChild(row);
    }
    track.replaceChildren(rows);
    if (items[selected]) box.setAttribute("aria-activedescendant", "soql-option-" + selected);
    else box.removeAttribute("aria-activedescendant");
  }
  function request(names) {
    const id = crypto.randomUUID ? crypto.randomUUID() : String(performance.now());
    pending = {id, names};
    api.setTriggerValue("metadata", {id, names, revision, generation});
  }
  function refresh(keep = false) {
    clearTimeout(timer);
    if (!focused() || dismissed || composing || box.selectionStart !== box.selectionEnd) {hide(); return;}
    const prior = keep && matches?.items[selected];
    matches = complete(box.value, box.selectionStart, index);
    const desired = matches.needs;
    const usesCatalog = desired.length || matches.items.some(item =>
      ["Field", "Relationship", "Object"].includes(item.kind));
    if (usesCatalog && performance.now() >= expires && !pending) {hide(); request([]); return;}
    const missing = desired.filter(n => !index.schema.has(n) && !failed.has(n));
    if (!pending && !paused && missing.length) {
      timer = setTimeout(() => request(missing.slice(0, api.data.batch)), 100);
    }
    const incomplete = (paused && missing.length) || desired.some(n => failed.has(n));
    status.textContent = missing.length && !paused ? "Loading Salesforce fields…" :
      incomplete && desired.length ? "Some fields are unavailable. Use Refresh Data to retry." : "";
    if (!matches.items.length && !status.textContent) {hide(); return;}
    if (popup.hidden) {
      popup.hidden = false;
      popup.showPopover?.();
    }
    selected = prior ? Math.max(0, matches.items.findIndex(i => i.label === prior.label && i.kind === prior.kind)) : 0;
    if (!keep) list.scrollTop = 0;
    draw();
    position();
  }
  function choose(i) {
    const item = matches?.items[i];
    if (!item) return;
    const edit = replacement(box.value, matches, item);
    const scroll = box.scrollTop;
    box.setRangeText(edit.text, edit.start, edit.end, "end");
    box.setSelectionRange(edit.anchor, edit.focus);
    box.scrollTop = scroll;
    dismissed = true;
    clearTimeout(timer);
    hide();
    if (item.kind === "Function" || item.kind === "Relationship") {
      dismissed = false; refresh();
    }
  }
  function submit() {
    clearTimeout(timer);
    dismissed = true;
    hide();
    saved = box.value;
    api.setTriggerValue("run", payload());
  }
  on(box, "input", () => {dismissed = false; refresh();});
  on(box, "click", () => {dismissed = false; refresh();});
  on(box, "focus", () => {dismissed = false; refresh();});
  on(box, "blur", e => {
    clearTimeout(timer); hide();
    if (e.relatedTarget !== run && box.value !== saved) {
      saved = box.value; api.setStateValue("draft", payload());
    }
  });
  on(box, "compositionstart", () => {composing = true; hide();});
  on(box, "compositionend", () => {composing = false; dismissed = false; refresh();});
  on(box, "keydown", e => {
    if (e.isComposing || composing) return;
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {e.preventDefault(); submit(); return;}
    if (popup.hidden) return;
    if (e.key === "Escape") {e.preventDefault(); dismissed = true; clearTimeout(timer); hide(); return;}
    if (!matches.items.length || e.ctrlKey || e.altKey || e.metaKey || e.shiftKey) return;
    if (["ArrowDown", "ArrowUp"].includes(e.key)) {
      e.preventDefault();
      selected = (selected + (e.key === "ArrowDown" ? 1 : -1) + matches.items.length) % matches.items.length;
      if (selected * 32 < list.scrollTop) list.scrollTop = selected * 32;
      if ((selected + 1) * 32 > list.scrollTop + list.clientHeight) list.scrollTop = (selected + 1) * 32 - list.clientHeight;
      draw();
    } else if (e.key === "Enter" || e.key === "Tab") {
      e.preventDefault(); choose(selected);
    }
  });
  on(box, "keyup", e => {
    if (["ArrowLeft", "ArrowRight", "Home", "End", "PageUp", "PageDown"].includes(e.key) ||
        (popup.hidden && ["ArrowUp", "ArrowDown"].includes(e.key))) {dismissed = false; refresh();}
  });
  on(list, "scroll", draw);
  on(list, "mousedown", e => e.preventDefault());
  on(list, "click", e => {
    const row = e.target.closest("[data-index]");
    if (row) choose(Number(row.dataset.index));
  });
  on(run, "click", submit);
  on(window, "resize", position);
  on(window, "scroll", position, {capture:true, passive:true});
  on(box, "scroll", position);
  return {
    update(component) {
      api = component;
      const data = api.data;
      root.querySelector(".unavailable").hidden = !data.unavailable;
      const fresh = generation !== data.generation, replace = revision !== data.revision;
      if (fresh) {
        index = new SchemaIndex(data.objects);
        failed.clear(); pending = null; paused = false;
      }
      // A schema refresh preserves the active draft, selection and native undo buffer.
      if (generation === undefined || replace) {
        box.value = data.text; saved = box.value;
        dismissed = true; pending = null;
      }
      generation = data.generation; revision = data.revision;
      expires = performance.now() + data.ttl * 1000;
      if (pending && data.reply?.id === pending.id) {
        index.add(data.reply.schema);
        if (data.reply.unavailable) paused = true;
        else for (const name of pending.names) if (!index.schema.has(name)) failed.add(name);
        pending = null;
      }
      refresh(true);
    },
    dispose() {clearTimeout(timer); listeners.abort(); hide();}
  };
}

export default function(component) {
  const root = component.parentElement.querySelector(".editor");
  root.controller ??= mountEditor(root);
  root.controller.update(component);
  return () => {
    // Streamlit may invoke cleanup before updating this same mounted element.
    queueMicrotask(() => {
      if (!root.isConnected) {root.controller?.dispose(); delete root.controller;}
    });
  };
}
