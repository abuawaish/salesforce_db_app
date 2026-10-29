"""
SF Cloud Code — a lightweight IDE for Apex classes and LWC components.

Pick a component from the dropdowns (for LWC, pick the file inside the
bundle), edit it, **Save** the draft, repeat for other files, then hit
**Deploy** once to push every saved change of that component to the org.
Deploys go through the Tooling API, which compiles server-side, so errors
come back instantly with line/column.

Two draft levels, like a real editor:
  * the editor text itself (auto-stashed per file, survives switching), and
  * the *saved* draft in the workspace, tracked with Git-style status
    letters (U untracked / M modified / C conflict). Only saved drafts
    deploy.
"""

import html as _html

import streamlit as st

import cloud_code as cc
from permissions import render_access_mode_toggle

try:
    from streamlit_ace import st_ace as _st_ace

    _ACE_AVAILABLE = True
except Exception:  # package not installed — the editor falls back to
    _st_ace = None  # the text area + synced gutter (see the editor block).
    _ACE_AVAILABLE = False

# ------------------------------------------------------------
# Page Configuration — MUST be first Streamlit command
# ------------------------------------------------------------
st.set_page_config(
    page_title="SF Cloud Code",
    page_icon="🌩️",
    layout="wide",
    initial_sidebar_state="auto",
)

# ------------------------------------------------------------
# Check connection
# ------------------------------------------------------------
if "sf" not in st.session_state or not st.session_state.get("config_ok"):
    st.warning(":material/warning: Please configure your Salesforce connection first (:material/settings: Configuration page).")
    st.info(
        ":material/emoji_objects: **What this page does:** once connected, edit Apex "
        "classes, Apex triggers, and Lightning Web Components from your live org in a VS Code-style "
        "workspace — with Git-style change indicators, diffs against the server copy, "
        "and one-click deploy with instant compile feedback."
    )
    st.stop()

sf = st.session_state["sf"]

# Repair the connection if an earlier Metadata API (SOAP) call in this
# session poisoned its shared headers (Content-Type: text/xml), which
# makes every Tooling call fail with "MediaType of 'text/xml' is not
# supported by this resource". Harmless when the session is healthy.
cc.heal_session_headers(sf)

# Sidebar access-mode toggle (same control as the other pages) so Admin
# mode can be enabled without leaving this page. Deploying follows the
# app's access model; editing and saving drafts are local and always open.
render_access_mode_toggle()
can_deploy = bool(st.session_state.get("can_modify_schema")) and (
    st.session_state.get("access_mode", "Read-Only") == "Admin"
)

# ------------------------------------------------------------
# Styles
# ------------------------------------------------------------
st.markdown(
    """
<style>
    textarea {
        font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace !important;
        font-size: 0.85rem !important;
        line-height: 1.55 !important;
        padding: 10px 12px !important;
        /* Long lines scroll left/right instead of wrapping. */
        white-space: pre !important;
        overflow-x: auto !important;
        overflow-wrap: normal !important;
        word-break: normal !important;
    }
    .cc-gutter-wrap {
        overflow: hidden;
    }
    .cc-gutter-inner {
        font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
        font-size: 0.85rem;
        line-height: 1.55;
        text-align: right;
        padding-right: 0.3rem;
        opacity: 0.45;
        user-select: none;
        will-change: transform;
    }
    .cc-pill {
        display: inline-block;
        padding: 2px 10px;
        border-radius: 999px;
        font-size: 0.72rem;
        font-weight: 700;
        letter-spacing: 0.04em;
        text-transform: uppercase;
    }
    .cc-meta {
        font-size: 0.78rem;
        color: var(--text-color);
        opacity: 0.62;
        font-variant-numeric: tabular-nums;
    }
    .cc-diff {
        border: 1px solid rgba(128, 128, 128, 0.2);
        border-radius: 10px;
        padding: 10px 12px;
        max-height: 420px;
        overflow: auto;
        font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
        font-size: 0.76rem;
        line-height: 1.5;
    }
    .cc-diff-row { display: flex; }
    .cc-diff .cc-ln {
        flex: 0 0 2.6rem;
        text-align: right;
        padding-right: 0.55rem;
        opacity: 0.45;
        user-select: none;
    }
    .cc-diff .cc-dtext { flex: 1 1 auto; white-space: pre; }
    .cc-diff .add { background: rgba(34, 197, 94, 0.13); }
    .cc-diff .del { background: rgba(239, 68, 68, 0.11); }
    .cc-diff .hunk { color: var(--primary-color); font-weight: 700; }
    .cc-legend {
        font-size: 0.76rem;
        color: var(--text-color);
        opacity: 0.75;
        line-height: 1.6;
    }
    /* The two script embeds (Ace polish, gutter sync) are srcdoc
       iframes — pure script carriers with nothing to show. Keep them
       truly invisible and out of the layout flow: rendered as plain
       elements, a 1px srcdoc frame can paint a stray light pill at
       the editor's lower edge. (The Ace editor itself loads via src,
       not srcdoc, so it is unaffected.) */
    iframe[srcdoc] {
        position: absolute !important;
        width: 1px !important;
        height: 1px !important;
        opacity: 0 !important;
        pointer-events: none !important;
        border: none !important;
    }
</style>
""",
    unsafe_allow_html=True,
)

# Scroll-sync for the editor's line-number gutter: keeps the numbers
# aligned with the code while the text area scrolls internally,
# renumbers live as lines are added/removed, and self-calibrates the
# first line's offset by measuring the real textarea. Injected via
# a 1px st.iframe (same-origin srcdoc, so it can reach the page's
# DOM); if a browser ever blocks it, the gutter simply stays static —
# the editor itself is unaffected. The frame is pinned to 1px:
# height="content" would measure-and-inflate the invisible script
# frame, leaving a tall blank gap under the editor.
_GUTTER_SYNC_JS = """
<script>
(function () {
  var doc = window.parent.document;
  function sync() {
    var ta = doc.querySelector('[data-testid="stTextArea"] textarea');
    var wrap = doc.querySelector('.cc-gutter-wrap');
    var inner = doc.querySelector('.cc-gutter-inner');
    if (!ta || !wrap || !inner) return;
    var lines = ta.value.split(String.fromCharCode(10)).length;
    if (inner.getAttribute('data-count') !== String(lines)) {
      var html = '';
      for (var i = 1; i <= lines; i++) html += i + '<br>';
      inner.innerHTML = html;
      inner.setAttribute('data-count', String(lines));
    }
    inner.style.transform = 'translateY(' + (-ta.scrollTop) + 'px)';
    if (!ta.getAttribute('data-cc-sync')) {
      ta.setAttribute('data-cc-sync', '1');
      ta.addEventListener('scroll', sync, { passive: true });
      ta.addEventListener('input', sync);
    }
    if (!inner.getAttribute('data-aligned')) {
      var cs = window.parent.getComputedStyle(ta);
      var offset = (ta.getBoundingClientRect().top
        + parseFloat(cs.borderTopWidth || 0)
        + parseFloat(cs.paddingTop || 0))
        - wrap.getBoundingClientRect().top;
      inner.style.marginTop = offset + 'px';
      inner.setAttribute('data-aligned', '1');
    }
  }
  var obs = new MutationObserver(function () { sync(); });
  obs.observe(doc.body, { childList: true, subtree: true });
  sync();
  setInterval(sync, 1500);
})();
</script>
"""

# Polish for the streamlit-ace component's own chrome, plus live
# theme sync. In manual (auto_update=False) mode the component renders
# its own "Apply (Ctrl+Enter)" bar inside its iframe, which renders as
# faint ghost text on a light strip under the editor — a small
# stylesheet is injected into the iframe (same-origin) so the bar
# matches the app theme. The script also keeps the editor's Ace theme
# in sync with the app theme IN THE BROWSER: st.context.theme (used
# server-side for the first paint) lags one rerun behind a theme
# switch in the Settings menu, so this script reads the app's real
# rendered background and calls Ace's setTheme the moment it flips.
# If the component's markup ever changes, the script simply does
# nothing — the editor itself is unaffected.
_ACE_POLISH_JS = """
<script>
(function () {
  var doc = window.parent.document;
  var CSS = [
    'body, #root { background: transparent !important; }',
    'button {',
    '  background: #1f2937 !important;',
    '  color: #f3f4f6 !important;',
    '  border: 1px solid rgba(255, 255, 255, 0.28) !important;',
    '  border-radius: 6px !important;',
    '  padding: 3px 12px !important;',
    '  font-size: 11px !important;',
    '  font-weight: 600 !important;',
    '  letter-spacing: 0.02em !important;',
    '  text-transform: none !important;',
    '  opacity: 1 !important;',
    '  cursor: pointer !important;',
    '  position: relative !important;',
    '  overflow: hidden !important;',
    '  transition: background 0.15s ease, border-color 0.15s ease,',
    '    box-shadow 0.15s ease !important;',
    '}',
    'button::after {',
    '  content: "" !important;',
    '  position: absolute !important;',
    '  top: 0 !important;',
    '  left: -90% !important;',
    '  width: 45% !important;',
    '  height: 100% !important;',
    '  background: linear-gradient(105deg, rgba(255, 255, 255, 0) 0%, rgba(255, 255, 255, 0.45) 50%, rgba(255, 255, 255, 0) 100%) !important;',
    '  transform: skewX(-20deg) !important;',
    '  transition: left 0.55s ease !important;',
    '  pointer-events: none !important;',
    '}',
    'button:hover::after {',
    '  left: 140% !important;',
    '}',
    '@keyframes cc-apply-bounce {',
    '  0% { transform: translateY(0); }',
    '  30% { transform: translateY(-3px); }',
    '  55% { transform: translateY(0); }',
    '  75% { transform: translateY(-2px); }',
    '  100% { transform: translateY(-1px); }',
    '}',
    'button:hover {',
    '  background: #374151 !important;',
    '  border-color: rgba(255, 255, 255, 0.55) !important;',
    '  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.35) !important;',
    '  transform: translateY(-1px) !important;',
    '  animation: cc-apply-bounce 0.55s ease !important;',
    '}',
    'button:active {',
    '  transform: translateY(0) !important;',
    '  box-shadow: none !important;',
    '}'
  ].join('\\n');
  function bgLuminance(el) {
    try {
      var bg = window.parent.getComputedStyle(el).backgroundColor || '';
      if (!bg || bg.indexOf('(') === -1) return null;
      var parts = bg.split('(')[1].split(')')[0].split(',');
      if (parts.length >= 4 && parseFloat(parts[3]) === 0) return null;
      return (0.299 * parseFloat(parts[0]) + 0.587 * parseFloat(parts[1])
        + 0.114 * parseFloat(parts[2])) / 255;
    } catch (e) { return null; }
  }
  function appMode() {
    // The app's real theme, from its rendered background color —
    // always current, unlike a server round-trip. Transparent
    // containers are skipped (they say nothing about the theme).
    var sels = ['[data-testid="stApp"]', '[data-testid="stAppViewContainer"]'];
    for (var i = 0; i < sels.length; i++) {
      var el = doc.querySelector(sels[i]);
      if (!el) continue;
      var lum = bgLuminance(el);
      if (lum !== null) return lum > 0.5 ? 'light' : 'dark';
    }
    var bodyLum = bgLuminance(doc.body);
    if (bodyLum !== null) return bodyLum > 0.5 ? 'light' : 'dark';
    return null;
  }
  function applyTheme(idoc, mode) {
    // Flip the Ace editor's theme inside its iframe, live.
    try {
      var view = idoc.defaultView;
      if (!view || !view.ace) return;
      var el = idoc.querySelector('.ace_editor');
      if (!el) return;
      var editor = view.ace.edit(el);
      var want = 'ace/theme/' + (mode === 'light' ? 'tomorrow' : 'tomorrow_night');
      if (editor && editor.getTheme() !== want) editor.setTheme(want);
    } catch (e) { /* editor not ready yet — the interval retries */ }
  }
  function polish() {
    var mode = appMode();
    var frames = doc.querySelectorAll('iframe');
    for (var i = 0; i < frames.length; i++) {
      var f = frames[i];
      if (!f.src || f.src.indexOf('streamlit_ace') === -1) continue;
      try {
        var idoc = f.contentDocument;
        if (!idoc || !idoc.head) continue;
        if (!idoc.getElementById('cc-ace-polish')) {
          var style = idoc.createElement('style');
          style.id = 'cc-ace-polish';
          style.textContent = CSS;
          idoc.head.appendChild(style);
        }
        if (mode) applyTheme(idoc, mode);
      } catch (e) { /* not ready yet — the interval retries */ }
    }
  }
  var obs = new MutationObserver(function () { polish(); });
  obs.observe(doc.body, {
    childList: true, subtree: true,
    attributes: true, attributeFilter: ['class', 'style']
  });
  polish();
  setInterval(polish, 1500);
})();
</script>
"""

# ------------------------------------------------------------
# Workspace + component lists
# ------------------------------------------------------------
ws: dict = st.session_state.setdefault("cc_ws", {})
unsaved: dict = st.session_state.setdefault("cc_unsaved", {})

# Pending UI operations: button handlers run AFTER the widgets they touch
# have been instantiated this run, and Streamlit forbids writing a widget's
# key at that point ("cannot be modified after the widget ... is
# instantiated"). Handlers therefore queue state writes, and they are
# applied now — before any widget renders.
for _pk, _pv in st.session_state.pop("cc_pending_state", {}).items():
    st.session_state[_pk] = _pv
for _rk in st.session_state.pop("cc_pending_editor_resets", []):
    st.session_state.pop(f"cc_editor_{_rk}", None)
selected: str | None = st.session_state.get("cc_selected")


def _queue_state(**kv) -> None:
    """Queue session-state writes for the top of the next run (see above)."""
    st.session_state.setdefault("cc_pending_state", {}).update(kv)


def _load_lists(force: bool = False) -> None:
    if force or "cc_apex_list" not in st.session_state:
        st.session_state["cc_apex_list"] = cc.list_apex_classes(sf)
    if force or "cc_trigger_list" not in st.session_state:
        st.session_state["cc_trigger_list"] = cc.list_apex_triggers(sf)
    if force or "cc_lwc_list" not in st.session_state:
        st.session_state["cc_lwc_list"] = cc.list_lwc_bundles(sf)


try:
    with st.spinner("Loading components from your org…"):
        _load_lists()
except Exception as exc:
    st.error(f":material/settings_alert: Could not load components via the Tooling API: {exc}")
    st.caption("The connected user needs API access to the Tooling API. Click below to retry.")
    if st.button("↻ Retry"):
        st.session_state.pop("cc_apex_list", None)
        st.session_state.pop("cc_trigger_list", None)
        st.session_state.pop("cc_lwc_list", None)
        st.rerun()
    st.stop()

apex_list: list[dict] = st.session_state["cc_apex_list"]
trigger_list: list[dict] = st.session_state["cc_trigger_list"]
lwc_list: list[dict] = st.session_state["cc_lwc_list"]

# ------------------------------------------------------------
# Header
# ------------------------------------------------------------
counts = cc.change_counts(ws)
instance_label = getattr(sf, "sf_instance", "") or "Salesforce"

st.title("🌩️ SF Cloud Code")
st.caption(
    f"Connected to **{instance_label}** · {len(apex_list)} Apex classes · "
    f"{len(trigger_list)} Apex triggers · "
    f"{len(lwc_list)} LWC bundles · {len(ws)} file(s) open in your workspace"
)
chip_bits = []
if counts["M"]:
    chip_bits.append(f"🟠 {counts['M']} modified")
if counts["U"]:
    chip_bits.append(f"🟢 {counts['U']} untracked")
if counts["C"]:
    chip_bits.append(f"🔴 {counts['C']} conflict")
if chip_bits:
    st.markdown("Workspace: " + " · ".join(chip_bits))

if not can_deploy:
    st.info(
        "👀 **Deploy is disabled** (editing and saving drafts still work — "
        "they're local to your session). Deploying needs a profile with "
        "schema permissions and **Admin** access mode — enable it in the "
        "sidebar on the left."
    )

# ------------------------------------------------------------
# Open helpers
# ------------------------------------------------------------
def _open_apex(meta: dict) -> None:
    key = cc.apex_key(meta["name"])
    if key not in ws:
        with st.spinner(f"Fetching {meta['name']}…"):
            fresh = cc.fetch_apex_body(sf, meta["id"])
        ws[key] = cc.new_apex_entry(
            meta["name"], meta["id"], fresh["body"],
            last_modified=fresh["last_modified"] or meta.get("last_modified", ""),
            namespace=meta.get("namespace", ""),
            api_version=fresh.get("api_version") or meta.get("api_version"),
        )
    st.session_state["cc_selected"] = key


def _open_trigger(meta: dict) -> None:
    key = cc.trigger_key(meta["name"])
    if key not in ws:
        with st.spinner(f"Fetching {meta['name']}…"):
            fresh = cc.fetch_trigger_body(sf, meta["id"])
        ws[key] = cc.new_trigger_entry(
            meta["name"], meta["id"], fresh["body"],
            sobject=fresh.get("sobject") or meta.get("sobject", ""),
            status=fresh.get("status") or meta.get("status", "") or "Active",
            last_modified=fresh["last_modified"] or meta.get("last_modified", ""),
            namespace=meta.get("namespace", ""),
            api_version=fresh.get("api_version") or meta.get("api_version"),
        )
    st.session_state["cc_selected"] = key


def _load_bundle_metadata(meta: dict) -> None:
    """Cache a bundle's file list (names/ids only — no sources). Files
    enter the workspace only when the user picks them in the File
    dropdown; selecting a component alone opens nothing."""
    cache = st.session_state.setdefault("cc_bundle_meta", {})
    if meta["name"] not in cache:
        with st.spinner(f"Loading {meta['name']}…"):
            files = cc.list_lwc_files(sf, meta["id"])
        cache[meta["name"]] = {
            "id": meta["id"],
            "namespace": meta.get("namespace", ""),
            "files": files,
        }


def _open_lwc_file(bundle: str, file_name: str) -> None:
    """Explicitly open one LWC file into the workspace + editor."""
    key = cc.lwc_key(bundle, file_name)
    if key not in ws:
        meta = st.session_state.get("cc_bundle_meta", {}).get(bundle)
        file_meta = next(
            (f for f in (meta or {}).get("files", []) if f["file_name"] == file_name),
            None,
        )
        if meta is None or file_meta is None:
            return
        with st.spinner(f"Fetching {file_name}…"):
            fresh = cc.fetch_lwc_resource(sf, file_meta["id"])
        ws[key] = cc.new_lwc_entry(
            bundle, meta["id"], file_meta["id"], file_name, fresh["source"],
            file_format=file_meta["format"],
            last_modified=fresh["last_modified"] or file_meta.get("last_modified", ""),
            namespace=meta.get("namespace", ""),
        )
    st.session_state["cc_selected"] = key


def _bundle_file_keys(bundle: str) -> list[str]:
    """Workspace keys of one bundle, in editor order: js, html, css, xml, rest."""
    rank = {".js": 0, ".html": 1, ".css": 2, ".xml": 3}
    keys = [k for k, e in ws.items() if e["kind"] == "lwc" and e.get("bundle") == bundle]
    return sorted(
        keys,
        key=lambda k: (
            next((r for suffix, r in rank.items() if ws[k]["file_name"].endswith(suffix)), 4),
            ws[k]["file_name"].lower(),
        ),
    )


def _status_suffix(key: str) -> str:
    entry = ws.get(key)
    if not entry:
        return ""
    status = cc.file_status(entry)
    suffix = ""
    if status:
        dot, _ = cc.STATUS_META[status]
        suffix = f" {dot} {status}"
    if key in unsaved and unsaved[key] != entry["current"]:
        suffix += " ●"
    return suffix


def _display_name(entry: dict) -> str:
    """File label as shown in workspace rows and the editor header."""
    if entry["kind"] == "apex":
        return f"{entry['name']}.cls"
    if entry["kind"] == "trigger":
        return f"{entry['name']}.trigger"
    return entry["file_name"]


def _select_from_workspace(key: str) -> None:
    """Jump the editor (and the dropdowns) to a workspace file. Only queues
    the jump — the widget-state writes happen in the pending-state applier
    at the top of the next run (see there for why)."""
    entry = ws[key]
    kv = {"cc_selected": key}
    if entry["kind"] == "apex":
        kv.update(cc_dd_type="Apex Class", cc_dd_apex=entry["name"])
    elif entry["kind"] == "trigger":
        kv.update(cc_dd_type="Apex Trigger", cc_dd_trigger=entry["name"])
    else:
        kv.update(
            cc_dd_type="LWC Component",
            cc_dd_bundle=entry["bundle"],
            cc_dd_file=entry["file_name"],
        )
    _queue_state(**kv)


def _close_file(key: str) -> None:
    """Remove a file from the workspace ONLY — nothing is deleted or
    changed in the org. A not-yet-deployed local draft is discarded,
    since the workspace is the only place it exists."""
    entry = ws.pop(key, None)
    unsaved.pop(key, None)
    # Also drop the editor session value: on reopen it must reseed
    # from the freshly fetched server copy, not resurrect the closed
    # file's stale editor text as a phantom "unsaved edits" pill.
    st.session_state.pop(f"cc_editor_{key}", None)
    # And its feedback: a persistent error/warning must not reappear
    # when the file is reopened later.
    st.session_state.pop(f"cc_feedback_{key}", None)
    if entry is None:
        return
    if st.session_state.get("cc_selected") == key:
        st.session_state["cc_selected"] = None
    # Reset the matching dropdown to its placeholder (queued — its widget
    # is already rendered this run) so picking the same name again later
    # registers as a fresh change and reopens the file.
    if entry["kind"] == "apex":
        if st.session_state.get("cc_dd_apex") == entry["name"]:
            _queue_state(cc_dd_apex="")
    elif entry["kind"] == "trigger":
        if st.session_state.get("cc_dd_trigger") == entry["name"]:
            _queue_state(cc_dd_trigger="")
    elif st.session_state.get("cc_dd_file") == entry["file_name"]:
        _queue_state(cc_dd_file="")


# ------------------------------------------------------------
# Create dialogs
# ------------------------------------------------------------
@st.dialog(":material/code: New Apex Class")
def _new_apex_dialog() -> None:
    name = st.text_input("Class name", placeholder="e.g. AccountService").strip()
    problem = cc.validate_apex_name(name) if name else None
    if name and not problem and (
        cc.apex_key(name) in ws or any(a["name"] == name for a in apex_list)
    ):
        problem = "A class with this name already exists (org or workspace)."
    if problem:
        st.warning(":material/warning:" + problem)
    if st.button("Create draft", type="primary", disabled=bool(problem) or not name):
        ws[cc.apex_key(name)] = cc.new_apex_entry(name, None, cc.apex_template(name))
        _select_from_workspace(cc.apex_key(name))
        st.rerun()


@st.dialog(":material/bolt: New Apex Trigger")
def _new_trigger_dialog() -> None:
    name = st.text_input("Trigger name", placeholder="e.g. AccountTrigger").strip()
    # Object dropdown from the org's global describe (cached per session).
    # If describe fails, fall back to the typed API name so the dialog
    # still works. Failures are not cached, so a later rerun retries the
    # describe; the name field above is identical in both branches, so
    # nothing typed is lost if the branch flips.
    objects = st.session_state.get("cc_object_list")
    if objects is None:
        try:
            objects = cc.list_triggerable_objects(sf)
            st.session_state["cc_object_list"] = objects
        except Exception:
            objects = []
    if objects:
        # API names only, exactly like the Field Analysis object list.
        sobject = st.selectbox(
            "Object",
            [""] + [o["name"] for o in objects],
            format_func=lambda n: "Select an object…" if n == "" else n,
        )
    else:
        st.caption("⚠️ Could not load the object list — type the API name instead.")
        sobject = st.text_input("Object API name", placeholder="e.g. Account").strip()
    problem = cc.validate_trigger_name(name) if name else None
    if name and not problem and (
        cc.trigger_key(name) in ws or any(t["name"] == name for t in trigger_list)
    ):
        problem = "A trigger with this name already exists (org or workspace)."
    if not problem and sobject and not objects:
        # Dropdown values come from the org, so they are valid by
        # construction; only the typed fallback needs validating.
        problem = cc.validate_sobject_name(sobject)
    if problem:
        st.warning(":material/warning:" + problem)
    st.caption(
        "Creates a local draft (before insert template). Nothing reaches "
        "the org until you Deploy — new triggers deploy as Active."
    )
    if st.button("Create draft", type="primary",
                 disabled=bool(problem) or not name or not sobject):
        ws[cc.trigger_key(name)] = cc.new_trigger_entry(
            name, None, cc.trigger_template(name, sobject), sobject=sobject,
        )
        _select_from_workspace(cc.trigger_key(name))
        st.rerun()


@st.dialog(":material/component_exchange: New LWC Component")
def _new_lwc_dialog() -> None:
    name = st.text_input("Component name (camelCase)", placeholder="e.g. helloWorld").strip()
    problem = cc.validate_lwc_name(name) if name else None
    if name and not problem and (
        any(b["name"] == name for b in lwc_list)
        or any(e.get("bundle") == name for e in ws.values() if e["kind"] == "lwc")
    ):
        problem = "A bundle with this name already exists (org or workspace)."
    if problem:
        st.warning(":material/warning:" + problem)
    st.caption("Creates a draft bundle with .js, .html, .css and .js-meta.xml files. Nothing reaches the org until you Deploy.")
    if st.button("Create draft bundle", type="primary", disabled=bool(problem) or not name):
        api_version = str(getattr(sf, "sf_version", "59.0") or "59.0")
        for file_name, source in cc.lwc_templates(name, api_version).items():
            ws[cc.lwc_key(name, file_name)] = cc.new_lwc_entry(
                name, None, None, file_name, source
            )
        _select_from_workspace(cc.lwc_key(name, f"{name}.js"))
        st.rerun()


# ------------------------------------------------------------
# Toolbar
# ------------------------------------------------------------
tb1, tb2, tb3, tb4 = st.columns([1.2, 1.4, 1.2, 1.4])
with tb1:
    if st.button(":material/sync: Refresh list", width="stretch"):
        _load_lists(force=True)
        st.session_state.pop("cc_bundle_meta", None)
        st.session_state.pop("cc_object_list", None)
        st.rerun()
with tb2:
    if st.button(":material/note_add: New Apex Class", width="stretch", disabled=not can_deploy):
        _new_apex_dialog()
with tb3:
    if st.button(":material/bolt: New Apex Trigger", width="stretch", disabled=not can_deploy):
        _new_trigger_dialog()
with tb4:
    if st.button(":material/library_add: New LWC", width="stretch", disabled=not can_deploy):
        _new_lwc_dialog()

st.divider()

# ------------------------------------------------------------
# Layout: picker + workspace | editor
# ------------------------------------------------------------
picker, editor = st.columns([1, 3], gap="small")

with picker:
    st.markdown("#### :material/folder_open: Open from org")
    comp_type = st.radio(
        "Component type",
        ["Apex Class", "Apex Trigger", "LWC Component"],
        key="cc_dd_type",
        horizontal=True,
    )

    prev = st.session_state.setdefault(
        "cc_prev_dd", {"apex": "", "bundle": "", "file": ""}
    )

    if comp_type == "Apex Trigger":
        trigger_names = sorted(
            {t["name"] for t in trigger_list}
            | {e["name"] for e in ws.values() if e["kind"] == "trigger"},
            key=str.lower,
        )
        st.selectbox(
            "Apex trigger",
            [""] + trigger_names,
            key="cc_dd_trigger",
            format_func=lambda n: (
                "Select a trigger…" if n == ""
                else f"{n}.trigger{_status_suffix(cc.trigger_key(n))}"
            ),
        )
        chosen_trigger = st.session_state.get("cc_dd_trigger", "")
        if chosen_trigger:
            # Same rule as the Apex dropdown: open whenever the dropdowns
            # imply a different file than the one currently shown.
            _trigger_key = cc.trigger_key(chosen_trigger)
            if _trigger_key != selected:
                meta = next((t for t in trigger_list if t["name"] == chosen_trigger), None)
                if meta is not None:
                    _open_trigger(meta)
                elif _trigger_key in ws:
                    st.session_state["cc_selected"] = _trigger_key
                selected = st.session_state.get("cc_selected")
        prev["trigger"] = chosen_trigger
    elif comp_type == "Apex Class":
        apex_names = sorted(
            {a["name"] for a in apex_list}
            | {e["name"] for e in ws.values() if e["kind"] == "apex"},
            key=str.lower,
        )
        st.selectbox(
            "Apex class",
            [""] + apex_names,
            key="cc_dd_apex",
            format_func=lambda n: (
                "Select a class…" if n == ""
                else f"{n}.cls{_status_suffix(cc.apex_key(n))}"
            ),
        )
        chosen_apex = st.session_state.get("cc_dd_apex", "")
        if chosen_apex:
            # Open whenever the dropdowns imply a different file than the
            # one currently shown. The old "changed since prev" check
            # went stale: prev kept the last dropdown value even after
            # the selection moved elsewhere (type switch, workspace
            # click), so returning to that file never reopened it and
            # the editor kept showing the previous file's code.
            _apex_key = cc.apex_key(chosen_apex)
            if _apex_key != selected:
                meta = next((a for a in apex_list if a["name"] == chosen_apex), None)
                if meta is not None:
                    _open_apex(meta)
                elif _apex_key in ws:
                    st.session_state["cc_selected"] = _apex_key
                selected = st.session_state.get("cc_selected")
        prev["apex"] = chosen_apex
    else:
        bundle_names = sorted(
            {b["name"] for b in lwc_list}
            | {e["bundle"] for e in ws.values() if e["kind"] == "lwc"},
            key=str.lower,
        )
        st.selectbox(
            "LWC component",
            [""] + bundle_names,
            key="cc_dd_bundle",
            format_func=lambda n: "Select a component…" if n == "" else n,
        )
        # Load the bundle's file list BEFORE the File dropdown renders, so
        # its options are populated in the same run. Loading the list opens
        # nothing — a file enters the workspace only when picked below.
        chosen_bundle = st.session_state.get("cc_dd_bundle", "")
        if chosen_bundle and chosen_bundle != prev["bundle"]:
            meta = next((b for b in lwc_list if b["name"] == chosen_bundle), None)
            if meta is not None:
                _load_bundle_metadata(meta)
            _sel = st.session_state.get("cc_selected")
            if _sel in ws and ws[_sel].get("bundle") == chosen_bundle:
                # Workspace jump into this bundle: keep its file selected.
                prev["file"] = ws[_sel]["file_name"]
            else:
                st.session_state["cc_dd_file"] = ""
                prev["file"] = ""
        prev["bundle"] = chosen_bundle
        bundle_meta = (
            st.session_state.get("cc_bundle_meta", {}).get(chosen_bundle)
            if chosen_bundle else None
        )
        # Union of org files and workspace files: a pending (not yet
        # deployed) file must stay pickable even when the org file list
        # exists — otherwise a partial bundle's File dropdown shows
        # only what already deployed.
        if chosen_bundle:
            org_files = (
                [f["file_name"] for f in bundle_meta["files"]]
                if bundle_meta else []
            )
            ws_files = [
                ws[k]["file_name"] for k in _bundle_file_keys(chosen_bundle)
            ]
            file_options = list(set(org_files) | set(ws_files))
        else:
            file_options = []
        _rank = {".js": 0, ".html": 1, ".css": 2, ".xml": 3}
        file_options = sorted(
            file_options,
            key=lambda f: (
                next((r for s, r in _rank.items() if f.endswith(s)), 4),
                f.lower(),
            ),
        )
        st.selectbox(
            "File",
            [""] + file_options,
            key="cc_dd_file",
            format_func=lambda f: (
                "Select a file…" if f == ""
                else f"{f}{_status_suffix(cc.lwc_key(chosen_bundle, f))}"
            ),
            disabled=not chosen_bundle,
        )
        # Picking a file is the explicit open action. Same rule as the
        # Apex dropdown: open whenever the dropdowns imply a different
        # file than the one currently shown (see there for why the old
        # "changed since prev" check went stale on type-switch returns).
        chosen_file = st.session_state.get("cc_dd_file", "")
        if chosen_bundle and chosen_file:
            _file_key = cc.lwc_key(chosen_bundle, chosen_file)
            if _file_key != selected:
                _open_lwc_file(chosen_bundle, chosen_file)
                selected = st.session_state.get("cc_selected")
        prev["file"] = chosen_file

    st.markdown("---")
    st.markdown(f"#### :material/workspace_premium: Workspace ({len(ws)})")
    if not ws:
        st.caption(
            "Empty — nothing is loaded automatically. Files appear here only "
            "when you open them above or create them."
        )

    def _row_slug(k: str) -> str:
        """CSS/DOM-safe slug of a workspace key (used for row containers)."""
        return "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in k)

    if selected and selected in ws:
        # Subtle selected-row highlight (tint + accent bar) instead of a
        # loud full-width primary button — applied via the row's keyed
        # container class.
        st.markdown(
            "<style>"
            f".st-key-cc_wsrow_{_row_slug(selected)} "
            'button[kind="secondary"], '
            f".st-key-cc_wsrow_{_row_slug(selected)} "
            'button[data-testid="stBaseButton-secondary"] {'
            "background: rgba(255, 75, 75, 0.10);"
            "box-shadow: inset 3px 0 0 var(--primary-color);"
            "font-weight: 600;"
            "}"
            "</style>",
            unsafe_allow_html=True,
        )

    def _ws_row(key: str) -> None:
        entry = ws[key]
        label = _display_name(entry)
        with st.container(key=f"cc_wsrow_{_row_slug(key)}"):
            row_main, row_close = st.columns([2, 1])
            with row_main:
                if st.button(
                    f"{label}{_status_suffix(key)}",
                    key=f"cc_ws_open_{key}",
                    width="content",
                    type="secondary",
                ):
                    _select_from_workspace(key)
                    st.rerun()
            with row_close:
                close_help = (
                    f"Close {label} — discards this not-yet-deployed local draft"
                    if entry.get("is_new") else
                    f"Close {label} — removes it from the workspace only; "
                    "the file in the org is untouched"
                )
                if st.button(":material/close_small:", key=f"cc_close_{key}", width="content", help=close_help):
                    _close_file(key)
                    st.rerun()

    apex_keys = sorted(
        (k for k, e in ws.items() if e["kind"] == "apex"),
        key=lambda k: ws[k]["name"].lower(),
    )
    if apex_keys:
        st.markdown("**:material/folder_special: Apex Classes**")
        for _k in apex_keys:
            _ws_row(_k)

    trigger_keys = sorted(
        (k for k, e in ws.items() if e["kind"] == "trigger"),
        key=lambda k: ws[k]["name"].lower(),
    )
    if trigger_keys:
        st.markdown("**:material/folder_special: Apex Triggers**")
        for _k in trigger_keys:
            _ws_row(_k)

    lwc_bundles = sorted(
        {e["bundle"] for e in ws.values() if e["kind"] == "lwc"}, key=str.lower
    )
    if lwc_bundles:
        st.markdown("**:material/folder_special: LWC Components**")
        for _bundle in lwc_bundles:
            st.markdown(f":material/folder_code: **{_bundle}**")
            for _k in _bundle_file_keys(_bundle):
                _ws_row(_k)

    st.markdown("---")
    st.markdown(
        '<div class="cc-legend">'
        "🟢 <b>U</b> = new &nbsp;·&nbsp; 🟠 <b>M</b> = modified &nbsp;·&nbsp; "
        "🔴 <b>C</b> = conflict<br>"
        "● = unsaved edits &nbsp;·&nbsp; no letter = clean / in sync"
        "</div>",
        unsafe_allow_html=True,
    )


# ------------------------------------------------------------
# Editor pane
# ------------------------------------------------------------
def _bump_editor_gen() -> None:
    """Force the Ace editor to remount on the next run (fresh iframe
    with the current seed). Used after Refetch and conflict resolution:
    a rerun that only changes elements above the editor can leave the
    component's iframe blank until something else forces a re-render —
    the remount guarantees the editor is visible immediately, with the
    correct content. File switches remount via the selected-file part
    of the editor key, not via this counter."""
    st.session_state["cc_editor_gen"] = st.session_state.get("cc_editor_gen", 0) + 1


def _reset_editor_widget(key: str) -> None:
    """Queue the editor to re-seed from the saved draft on the next run
    (widget keys can't be touched after they render this run), and drop
    any stashed unsaved text for the file. The fallback text area is
    dropped from session state so it reseeds; the Ace editor remounts
    via the generation bump."""
    resets = st.session_state.setdefault("cc_pending_editor_resets", [])
    if key not in resets:
        resets.append(key)
    unsaved.pop(key, None)
    _bump_editor_gen()


def _ace_language(entry: dict) -> str:
    """Ace editor language mode for a workspace entry."""
    if entry["kind"] in ("apex", "trigger"):
        return "java"  # closest Ace mode to Apex
    return {"js": "javascript"}.get(entry.get("format") or "",
                                    entry.get("format") or "plain_text")


def _deploy_targets(key: str) -> list[dict]:
    """Saved changes that Deploy would push for this file's component."""
    entry = ws[key]
    if entry["kind"] in ("apex", "trigger"):
        pool = [entry]
    else:
        pool = [ws[k] for k in _bundle_file_keys(entry["bundle"])]
    targets = [e for e in pool
               if e.get("is_new") or e.get("org_deleted")
               or e["current"] != e["original"]]
    # Deploy order for Tooling PATCHes (pure updates) and the "Deploy
    # will push" caption. New/partial bundles go through the Metadata
    # API instead (see _deploy_component), so this order no longer
    # gates bundle creation.
    order = {".js": 0, ".js-meta.xml": 1, ".html": 2, ".css": 3}
    targets.sort(
        key=lambda e: next(
            (p for suffix, p in order.items() if e["file_name"].endswith(suffix)), 4
        )
    )
    return targets


def _attach_ref_lines(rows: list[dict], sources_by_name: dict[str, str]) -> None:
    """Append a line pointer to rows that name an unknown component.

    ``sources_by_name`` maps file names to their current text. A row
    translated from a "No MODULE named" error carries the reference in
    row["ref"] ("lightning:car", "c:foo"); the reference appears in
    source as a tag/selector ("lightning-car") or an import
    ("lightning/car", "c/foo"). Rows that already carry a platform line
    are left alone.
    """
    for row in rows:
        ref = row.get("ref")
        if not ref or row.get("line") is not None:
            continue
        forms = [ref.replace(":", "-"), ref.replace(":", "/")]
        names = []
        if row.get("file"):
            base = row["file"].rsplit("/", 1)[-1]
            if base in sources_by_name:
                names = [base]
        if not names:
            names = list(sources_by_name)
        for name in names:
            found = None
            for i, line in enumerate(sources_by_name[name].splitlines(), 1):
                if any(f in line for f in forms):
                    found = i
                    break
            if found is not None:
                row["message"] += f" (line {found})"
                break


def _deploy_component(key: str) -> None:
    """Push every saved change of the component (class, or whole bundle)."""
    targets = _deploy_targets(key)
    if not targets:
        return
    deployed: list[str] = []
    used_metadata = False
    try:
        # LWC creates go through the Metadata API, whole bundle at once:
        # Tooling resource creates cannot bootstrap a bundle (see
        # cc.deploy_lwc_bundle_mdapi) — the first file lands and every
        # later file fails with "No MODULE named". Tooling PATCH stays
        # for pure updates (all targets already deployed).
        if ws[key]["kind"] == "lwc" and any(
            e.get("is_new") or e.get("org_deleted") for e in targets
        ):
            bundle_name = ws[key]["bundle"]
            bundle_files = {
                ws[k]["file_name"]: ws[k]["current"]
                for k in _bundle_file_keys(bundle_name)
            }
            meta_entry = next(
                (e for e in ws.values()
                 if e["kind"] == "lwc" and e.get("bundle") == bundle_name
                 and e["file_name"] == f"{bundle_name}.js-meta.xml"),
                None,
            )
            metadata = cc.lwc_bundle_metadata(
                meta_entry["current"] if meta_entry else "",
                getattr(sf, "sf_version", "59.0") or "59.0",
            )
            try:
                cc.deploy_lwc_bundle_mdapi(
                    sf, bundle_name, bundle_files, str(metadata["apiVersion"])
                )
            except Exception as exc:
                rows = [{"message": "Failed to deploy the "
                                    f"**{bundle_name}** bundle via the "
                                    "Metadata API.",
                         "line": None, "column": None}]
                rows += cc.parse_deploy_error(exc)
                _attach_ref_lines(rows, bundle_files)
                st.session_state[f"cc_feedback_{key}"] = ("error", rows)
                return
            # Adopt the new ids, all-or-nothing: if the read-back fails
            # or is incomplete, leave the entries untouched — Deploy
            # stays available and re-running the atomic deploy is safe.
            try:
                bundle_rec = next(
                    (b for b in cc.list_lwc_bundles(sf)
                     if b["name"] == bundle_name),
                    None,
                )
                resources = (
                    cc.fetch_lwc_resources(sf, bundle_rec["id"])
                    if bundle_rec else []
                )
                by_name = {r["file_name"]: r for r in resources}
                bundle_keys = _bundle_file_keys(bundle_name)
                if bundle_rec is None or any(
                    ws[k]["file_name"] not in by_name for k in bundle_keys
                ):
                    raise RuntimeError("incomplete read-back")
                for k in bundle_keys:
                    e = ws[k]
                    r = by_name[e["file_name"]]
                    e["id"] = r["id"]
                    e["bundle_id"] = bundle_rec["id"]
                    e["original"] = e["current"]
                    e["is_new"] = False
                    e["conflict"] = False
                    e["org_deleted"] = False
                    e["server_copy"] = None
                    if r.get("last_modified"):
                        e["server_modified"] = r["last_modified"]
            except Exception:
                st.session_state[f"cc_feedback_{key}"] = (
                    "warning",
                    f"Deployed via the Metadata API, but the app could not "
                    f"read back the new file ids — close and reopen the "
                    f"**{bundle_name}** bundle from the org to sync.",
                )
                return
            _load_lists(force=True)
            st.session_state[f"cc_feedback_{key}"] = (
                "success",
                ":material/rocket_launch: Deployed: "
                + ", ".join(
                    f"**{ws[k]['file_name']}**"
                    for k in _bundle_file_keys(bundle_name)
                )
                + " — via the **Metadata API** (whole bundle, one deploy).",
            )
            return
        # Brand-new bundle: create it first, then land files in
        # dependency order (see _deploy_targets: .js, then meta,
        # then the rest). Normally unreachable — LWC creates go through
        # the Metadata API path above; kept as a safety net.
        if any(
            e["kind"] == "lwc" and not e.get("bundle_id") for e in targets
        ):
            bundle_name = targets[0]["bundle"]
            meta_entry = next(
                (e for e in ws.values()
                 if e["kind"] == "lwc" and e.get("bundle") == bundle_name
                 and e["file_name"] == f"{bundle_name}.js-meta.xml"),
                None,
            )
            metadata = cc.lwc_bundle_metadata(
                meta_entry["current"] if meta_entry else "",
                getattr(sf, "sf_version", "59.0") or "59.0",
            )
            try:
                bundle_id = cc.create_lwc_bundle(sf, bundle_name,
                                                 metadata=metadata)
            except Exception as exc:
                # Bundle creation happens before any file deploys, so the
                # generic handler below would blame targets[0] ("Failed
                # on <meta file>") and send the user to check a file
                # that is not the problem. Name the real failure.
                rows = [{"message": "Failed to create the "
                                    f"LightningComponentBundle "
                                    f"**{bundle_name}**.",
                         "line": None, "column": None}]
                rows += cc.parse_deploy_error(exc)
                st.session_state[f"cc_feedback_{key}"] = ("error", rows)
                return
            for e in ws.values():
                if e["kind"] == "lwc" and e.get("bundle") == bundle_name:
                    e["bundle_id"] = bundle_id
        for e in targets:
            result = cc.deploy_entry(sf, e)
            if result.get("via") == "metadata":
                used_metadata = True
            e["id"] = result["id"] or e["id"]
            e["original"] = e["current"]
            e["is_new"] = False
            e["conflict"] = False
            e["org_deleted"] = False
            e["server_copy"] = None
            if result.get("last_modified"):
                e["server_modified"] = result["last_modified"]
            # Triggers only: deploy_entry refreshes these from the server.
            if result.get("status"):
                e["status"] = result["status"]
            if result.get("sobject"):
                e["sobject"] = result["sobject"]
            deployed.append(e["file_name"])
        _load_lists(force=True)
        success_msg = ":material/rocket_launch: Deployed: " + ", ".join(f"**{n}**" for n in deployed)
        if used_metadata:
            success_msg += (
                " — Apex went through the **Metadata API** (your org "
                "rejected the Tooling container path)."
            )
        st.session_state[f"cc_feedback_{key}"] = ("success", success_msg)
    except Exception as exc:
        rows = cc.parse_deploy_error(exc)
        failing_entry = targets[len(deployed)] if len(deployed) < len(targets) else None
        if failing_entry is not None and failing_entry["kind"] == "lwc":
            _attach_ref_lines(
                rows, {failing_entry["file_name"]: failing_entry["current"]}
            )
        failing = failing_entry["file_name"] if failing_entry is not None else "?"
        note = f"Failed on **{failing}**."
        if deployed:
            note += " Already deployed in this run: " + ", ".join(deployed) + "."
        rows = [{"message": note, "line": None, "column": None}] + rows
        st.session_state[f"cc_feedback_{key}"] = ("error", rows)


def _refetch(key: str) -> None:
    """Re-read the server copy; flag a conflict if it moved under a draft."""
    entry = ws[key]
    try:
        if entry["kind"] == "apex":
            fresh = cc.fetch_apex_body(sf, entry["id"])
            server_body, server_mod = fresh["body"], fresh["last_modified"]
        elif entry["kind"] == "trigger":
            fresh = cc.fetch_trigger_body(sf, entry["id"])
            server_body, server_mod = fresh["body"], fresh["last_modified"]
        else:
            fresh_r = cc.fetch_lwc_resource(sf, entry["id"])
            server_body, server_mod = fresh_r["source"], fresh_r["last_modified"]
    except Exception as exc:
        if cc.is_gone_error(exc):
            # The org record was deleted outside this app (Salesforce UI,
            # another tool). This is a state to act on, not a failed
            # action: the local copy is intact, and Deploy recreates it.
            entry["org_deleted"] = True
            entry["conflict"] = False
            entry["server_copy"] = None
            st.session_state[f"cc_feedback_{key}"] = (
                "warning",
                f"🗑️ **{entry['file_name']}** no longer exists in the org — "
                "it was deleted outside this app. Your local copy is intact: "
                "**Deploy** will recreate it in the org, or close the file "
                "to discard it.",
            )
            return
        st.session_state[f"cc_feedback_{key}"] = ("error", cc.parse_deploy_error(exc))
        return

    if server_body == entry["original"]:
        st.session_state[f"cc_feedback_{key}"] = (
            "success", "Server copy is unchanged — nothing to refetch.",
        )
        return
    if entry["current"] == entry["original"]:
        # No saved draft: adopt the newer server copy. Unsaved editor text
        # (if any) is kept — it was written against the older copy, so the
        # user decides whether to Save it over the new base.
        entry["original"] = entry["current"] = server_body
        entry["server_modified"] = server_mod
        if entry["kind"] == "trigger":
            # Adopting the server copy also adopts its status/object.
            entry["status"] = fresh.get("status") or entry.get("status", "")
            entry["sobject"] = fresh.get("sobject") or entry.get("sobject", "")
        if key not in unsaved:
            _reset_editor_widget(key)
        st.session_state[f"cc_feedback_{key}"] = (
            "success", "Refetched — workspace now holds the latest server copy.",
        )
        return
    # Saved draft + moved server = conflict. No feedback banner here:
    # the conflict warning + resolution buttons below already say it,
    # and a red "Something failed" banner is wrong — a conflict is a
    # state to resolve, not a failed action. (Genuine failures — the
    # fetch exception above — still get the error banner.)
    entry["server_copy"] = server_body
    entry["server_modified_latest"] = server_mod
    entry["conflict"] = True
    # Remount the editor on the next run so it stays visible with the
    # current draft after this rerun. Deliberately NOT a full editor
    # reset: unsaved editor text is preserved (it was written against
    # the older copy, and the user decides what to do with it).
    _bump_editor_gen()


def _merge_three_way(base: str, server: str, draft: str,
                     mark_open: str = "//", mark_close: str = "") -> tuple[str, int]:
    """Three-way line merge of the server copy and the saved draft against
    their common ancestor (the previously fetched copy).

    - A region changed by only one side is taken from that side.
    - A region changed identically by both sides is taken once.
    - A region changed differently by both sides keeps BOTH versions,
      wrapped in comment markers, and counts as one manual conflict.
    Returns (merged_text, manual_conflict_count). Nothing is silently
    overwritten: the caller reports the count so the user knows review
    is required, and the markers stay in the code until edited out.
    """
    import difflib

    base_lines = base.split("\n")
    server_lines = server.split("\n")
    draft_lines = draft.split("\n")

    def _hunks(lines: list[str]) -> list[tuple[int, int, list[str]]]:
        out = []
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
                None, base_lines, lines).get_opcodes():
            if tag != "equal":
                out.append((i1, i2, lines[j1:j2]))
        return out

    # (base_start, base_end, side, replacement) — side 0 = server, 1 = draft.
    all_hunks = [(s, e, 0, rep) for (s, e, rep) in _hunks(server_lines)]
    all_hunks += [(s, e, 1, rep) for (s, e, rep) in _hunks(draft_lines)]
    all_hunks.sort(key=lambda h: (h[0], h[1], h[2]))

    def _overlaps(a: tuple, b: tuple) -> bool:
        s1, e1, s2, e2 = a[0], a[1], b[0], b[1]
        if s1 == e1 and s2 == e2:
            return s1 == s2  # two insertions at the same point
        if s1 == e1:
            return s2 <= s1 < e2  # insertion inside the other's span
        if s2 == e2:
            return s1 <= s2 < e1
        return s1 < e2 and s2 < e1

    merged: list[str] = []
    conflicts = 0
    i = 0  # next untouched base line
    k = 0
    while k < len(all_hunks):
        group = [all_hunks[k]]
        k += 1
        grown = True
        while grown and k < len(all_hunks):
            grown = False
            for h in group:
                if _overlaps(h, all_hunks[k]):
                    group.append(all_hunks[k])
                    k += 1
                    grown = True
                    break
        g_start = min(h[0] for h in group)
        g_end = max(h[1] for h in group)
        if g_start > i:
            merged.extend(base_lines[i:g_start])
        if len({h[2] for h in group}) == 1:
            for h in sorted(group, key=lambda x: (x[0], x[1])):
                merged.extend(h[3])
        else:
            srv_rep: list[str] = []
            dft_rep: list[str] = []
            for h in sorted(group, key=lambda x: (x[2], x[0], x[1])):
                (srv_rep if h[2] == 0 else dft_rep).extend(h[3])
            if srv_rep == dft_rep:
                merged.extend(srv_rep)
            else:
                conflicts += 1
                merged.append(
                    f"{mark_open} <<<<<<< SERVER VERSION "
                    f"(manual resolution required){mark_close}")
                merged.extend(srv_rep)
                merged.append(f"{mark_open} ======={mark_close}")
                merged.extend(dft_rep)
                merged.append(
                    f"{mark_open} >>>>>>> DRAFT VERSION "
                    f"(manual resolution required){mark_close}")
        i = max(i, g_end)
    if i < len(base_lines):
        merged.extend(base_lines[i:])
    return "\n".join(merged), conflicts


with editor:
    if not selected or selected not in ws:
        st.info(
            "👈 Pick an Apex class, trigger, or LWC component from the dropdowns to "
            "start editing. Edit → **Save** each file → **Deploy** pushes all "
            "saved changes of the component at once."
        )
    else:
        entry = ws[selected]
        status = cc.file_status(entry)
        status_dot, status_help = cc.STATUS_META[status]
        is_managed = bool(entry.get("namespace"))
        editable = not is_managed
        added, removed = cc.diff_stats(entry["original"], entry["current"])

        editor_key = f"cc_editor_{selected}"
        if editor_key not in st.session_state:
            st.session_state[editor_key] = unsaved.get(selected, entry["current"])
        widget_text = st.session_state.get(editor_key, entry["current"])
        has_unsaved = widget_text != entry["current"]

        path_label = (
            f"{entry['bundle']}/{entry['file_name']}" if entry["kind"] == "lwc"
            else _display_name(entry)
        )
        st.markdown(f"### 📄 {path_label}")
        pill_bg = {"U": "rgba(34,197,94,0.15)", "M": "rgba(217,119,6,0.15)",
                   "C": "rgba(239,68,68,0.15)", "D": "rgba(107,114,128,0.20)",
                   "": "rgba(128,128,128,0.15)"}[status]
        pill_txt = {"D": "DELETED"}.get(status, status or "CLEAN")
        meta_bits = [
            f'<span class="cc-pill" style="background:{pill_bg};">{pill_txt}</span>',
        ]
        if status:
            # The pill already says CLEAN for a clean file — only add the
            # descriptive text when it adds information (M / C / U).
            meta_bits.append(
                f'<span class="cc-meta">{_html.escape(status_help)}</span>'
            )
        if entry["kind"] == "trigger":
            # A trigger that looks deployed but is Inactive never fires —
            # its status and object always stay visible in the header.
            meta_bits.append(
                f'<span class="cc-meta">Trigger on '
                f'{_html.escape(entry.get("sobject") or "?")} · '
                f'{_html.escape(entry.get("status") or "Unknown")}</span>'
            )
        if has_unsaved:
            meta_bits.append(
                '<span class="cc-pill" style="background:rgba(217,119,6,0.15);">● Unsaved edits</span>'
            )
        if entry.get("server_modified") and not entry.get("org_deleted"):
            # Suppressed for deleted entries: the timestamp belongs to a
            # record that no longer exists, so showing it would imply the
            # org copy is still there.
            meta_bits.append(
                f'<span class="cc-meta">server modified: '
                f'{_html.escape(cc.format_server_time(entry["server_modified"]))}</span>'
            )
        if status in ("M", "C"):
            meta_bits.append(f'<span class="cc-meta">saved draft: +{added} / −{removed} lines</span>')
        if is_managed:
            meta_bits.append('<span class="cc-meta">🔒 managed package — read-only</span>')
        st.markdown(" &nbsp;·&nbsp; ".join(meta_bits), unsafe_allow_html=True)

        # Panel-local rerun flag: editor-panel handlers set this
        # instead of calling st.rerun() directly. Any rerun fired
        # BEFORE the Diff toggle below is created resets that toggle
        # to its default OFF (the run aborts before the toggle
        # exists, so its ON value is lost) — which is why the diff
        # body used to stay hidden after Save / Deploy / Revert /
        # Refetch until the user re-toggled. The trailing rerun at
        # the end of this panel fires instead, after the toggle and
        # the diff section have rendered.
        _panel_rerun = False
        _defer_success_toast = False

        # ----- queued deploy: runs here so its spinner sits inside the
        # editor panel (above the code), and the result banner renders
        # right below it in this same run -----
        _pending_deploy = st.session_state.pop("cc_deploy_pending", None)
        if _pending_deploy is not None and _pending_deploy in ws:
            # Placeholder slot: the bordered spinner box is cleared once the
            # deploy finishes, so no empty box is left above the banner.
            _spin_slot = st.empty()
            with _spin_slot.container(border=True):
                with st.spinner(":material/rocket_launch: Deploying to your org…"):
                    _deploy_component(_pending_deploy)
            _spin_slot.empty()
            # The picker rendered BEFORE this deploy ran, so it still
            # shows the pre-deploy M/U/C letters. The trailing rerun at the end of this panel refreshes every
            # indicator to the post-deploy state.
            # The success/error feedback stays in session state and
            # renders on the rerun; the pending flag was already
            # popped, so this cannot loop or redeploy.
            # Success toasts are NOT rendered in this run: the toast
            # below pops on render, so rendering here would flash it
            # for the fraction of a second until the trailing rerun
            # replaces this output. It renders on the rerun instead,
            # where it stays for its full duration.
            _panel_rerun = True
            _defer_success_toast = True

        # ----- feedback from the last action -----
        # Successes are transient (a toast) so they never push the editor
        # down or linger. Failures and warnings PERSIST across reruns:
        # the old code popped the message on its first render, so the
        # rerun that follows a deploy (the editor remounts) wiped a
        # deploy error off the screen before it could be read. A
        # persistent message is cleared only by the next action on this
        # file (which overwrites the key), a successful deploy (the
        # success toast below pops the key), or closing the file.
        feedback = st.session_state.get(f"cc_feedback_{selected}")
        if feedback:
            kind, payload = feedback
            if kind == "success":
                if not _defer_success_toast:
                    st.toast(payload, icon=":material/task_alt:")
                    st.session_state.pop(f"cc_feedback_{selected}", None)
            elif kind == "warning":
                # Actionable, not a failure: no "Something failed" banner.
                st.warning(":material/warning:" + payload)
            else:
                st.error(":material/settings_alert: Something failed:")
                for row in payload:
                    loc = ""
                    if row.get("line"):
                        loc = f"Line {row['line']}"
                        if row.get("column"):
                            loc += f", Col {row['column']}"
                        loc += " — "
                    st.markdown(f"- {loc}{_html.escape(row['message'])}")

        # ----- conflict resolution -----
        if entry.get("conflict") and entry.get("server_copy") is not None:
            st.warning(
                "🔴 **Conflict:** the server copy changed after you fetched this "
                "file. Compare in the diff below, then choose which copy wins — "
                "or combine both."
            )
            c1, c2, c3, _ = st.columns([1.3, 1.3, 1.6, 0.4])
            with c1:
                if st.button(":material/arrow_downward_alt: Use server copy", width="stretch"):
                    entry["original"] = entry["current"] = entry["server_copy"]
                    entry["server_modified"] = entry.get("server_modified_latest", entry["server_modified"])
                    entry["server_copy"] = None
                    entry["conflict"] = False
                    _reset_editor_widget(selected)
                    _panel_rerun = True
            with c2:
                if st.button(":material/arrow_upward_alt: Keep my draft", width="stretch"):
                    # Rebase: diff/deploy now measured against the latest server.
                    entry["original"] = entry["server_copy"]
                    entry["server_modified"] = entry.get("server_modified_latest", entry["server_modified"])
                    entry["server_copy"] = None
                    entry["conflict"] = False
                    _panel_rerun = True
            with c3:
                if st.button(":material/Handshake: Accept Both Changes", width="stretch"):
                    # Combine the server copy and the saved draft against
                    # their common ancestor. Comment style follows the
                    # file type so conflict markers never break syntax.
                    _fn = entry["file_name"]
                    if _fn.endswith((".html", ".xml")):
                        _mo, _mc = "<!--", " -->"
                    elif _fn.endswith(".css"):
                        _mo, _mc = "/*", " */"
                    else:  # Apex, JS
                        _mo, _mc = "//", ""
                    merged, n_conf = _merge_three_way(
                        entry["original"], entry["server_copy"],
                        entry["current"], _mo, _mc)
                    entry["current"] = merged
                    entry["original"] = entry["server_copy"]
                    entry["server_modified"] = entry.get("server_modified_latest", entry["server_modified"])
                    entry["server_copy"] = None
                    entry["conflict"] = False
                    _reset_editor_widget(selected)
                    if n_conf:
                        st.session_state[f"cc_feedback_{selected}"] = (
                            "warning",
                            f"⚠️ Combined both versions, but {n_conf} conflicting "
                            f"section(s) could not be merged automatically — they "
                            f"are marked in the code above. Please review and edit "
                            f"them before deploying.",
                        )
                    else:
                        st.session_state[f"cc_feedback_{selected}"] = (
                            "success",
                            "🤝 Both versions combined — server and draft changes "
                            "are now in your workspace draft.",
                        )
                    _panel_rerun = True

        # ----- the editor -----
        # Primary: the Ace code editor (streamlit-ace) — line numbers
        # inside it, scrolling with the code, ~50-line viewport.
        # Fallback (package not installed): the text area with a
        # scroll-synced line-number gutter (_GUTTER_SYNC_JS).
        # Snapshot the stashed unsaved text BEFORE the widget runs: if
        # the widget block newly stashes edits (Apply in Ace, on_change
        # in the fallback), the picker above already rendered with the
        # old indicators — a trailing rerun at the end of this panel
        # refreshes them without any manual interaction.
        _unsaved_before = unsaved.get(selected)
        _seed_text = unsaved.get(selected, entry["current"])
        if _ACE_AVAILABLE:
            # Panel height follows the file: one row per line, capped at
            # 50 lines (longer files scroll inside the editor), with a
            # 10-line floor so small files still get a usable editor.
            _ace_lines = max(10, min(_seed_text.count("\n") + 1, 50))
            # Follow the app theme: Ace's "tomorrow" family has a light
            # and a dark variant. st.context.theme gives the first-paint
            # value (dark when unknown); it can lag one rerun behind a
            # Settings-menu switch, so _ACE_POLISH_JS additionally keeps
            # the editor's theme in sync live in the browser.
            try:
                _app_theme = (st.context.theme or {}).get("type")
            except Exception:
                _app_theme = None
            _ace_theme = "tomorrow" if _app_theme == "light" else "tomorrow_night"
            _ace_text = _st_ace(
                value=_seed_text,
                language=_ace_language(entry),
                theme=_ace_theme,
                keybinding="vscode",
                # The key MUST change when the file changes: this
                # component instance keeps displaying the text it was
                # mounted with and does not reliably pick up a new
                # value prop, so a same-key switch leaves the previous
                # file's code on screen. The generation additionally
                # remounts on Refetch / conflict resolution (see
                # _bump_editor_gen). Typing changes neither part, so
                # the editor is never torn down mid-edit. (An earlier
                # stable-key attempt caused exactly this stale display;
                # the old removeChild crash it was guarding against
                # was the broken ace install, gone since the reinstall.)
                key=f"cc_ace_editor#{selected}#{st.session_state.get('cc_editor_gen', 0)}",
                height=_ace_lines * 15 + 8,  # ~15px per line at font 13
                font_size=13,
                tab_size=4,
                wrap=False,
                show_gutter=True,
                readonly=not editable,
                auto_update=False,
            )
            _live_text = _ace_text if _ace_text is not None else _seed_text
            if _seed_text != st.session_state.get("cc_editor_seed"):
                # The seed just changed (file switch, revert, refetch,
                # conflict resolution): the component's value this run
                # is still the previous file's text — ignore it, or it
                # would be stashed into the wrong file. The editor
                # re-syncs from the new value prop; the next run's
                # value is trustworthy again.
                _live_text = _seed_text
            st.session_state["cc_editor_seed"] = _seed_text
            if _live_text != _seed_text:
                unsaved[selected] = _live_text
            widget_text = _live_text
            has_unsaved = widget_text != entry["current"]
            # Keep the shared editor session value in sync with the Ace
            # live text. The header pills and Save button above were
            # computed BEFORE this widget rendered, from that value —
            # and the Ace branch otherwise never updates it, so after
            # a save or deploy it would keep showing stale "unsaved"
            # state. (No widget with this key renders in the Ace
            # branch, so writing it here is safe.)
            st.session_state[editor_key] = _live_text
            st.iframe(_ACE_POLISH_JS, height=1)
            st.caption(
                ":material/keyboard: **Ctrl+Enter** in the editor applies your edits "
                "(or use its Apply button) — then **Save draft** below."
            )
        else:
            def _stash_editor(k=selected, ek=editor_key) -> None:
                unsaved[k] = st.session_state[ek]

            # Same dynamic sizing as the Ace editor: the viewport fits
            # the file's lines, capped at 50 (internal scroll beyond).
            _line_count = widget_text.count("\n") + 1
            _EDITOR_H = max(10, min(_line_count, 50)) * 15 + 8
            _gutter_col, _code_col = st.columns([0.06, 1], gap="small")
            with _gutter_col:
                st.markdown(
                    f'<div class="cc-gutter-wrap" style="height: {_EDITOR_H}px">'
                    '<div class="cc-gutter-inner">'
                    + "<br>".join(str(n) for n in range(1, _line_count + 1))
                    + "</div></div>",
                    unsafe_allow_html=True,
                )
            with _code_col:
                st.text_area(
                    "Code",
                    key=editor_key,
                    height=_EDITOR_H,
                    label_visibility="collapsed",
                    disabled=not editable,
                    on_change=_stash_editor,
                    help=None if editable else "Managed package components are read-only.",
                )
            st.iframe(_GUTTER_SYNC_JS, height=1)

        # ----- actions -----
        targets = _deploy_targets(selected)
        blocked_by_conflict = any(e.get("conflict") for e in targets)

        a1, a2, a3, a4 = st.columns(4)
        with a1:
            if st.button(":material/save: Save draft", width="stretch",
                         disabled=not (editable and has_unsaved)):
                entry["current"] = widget_text
                unsaved.pop(selected, None)
                st.session_state[f"cc_feedback_{selected}"] = (
                    "success",
                    f":material/save: **{entry['file_name']}** saved to your workspace draft. "
                    "Not on the server yet — Deploy when you're done.",
                )
                _panel_rerun = True
        with a2:
            if st.button(":material/rocket: Deploy", type="primary", width="stretch",
                         disabled=not (can_deploy and targets and not blocked_by_conflict)):
                # Queue the deploy: it runs at the top of the editor panel
                # on the next run so the spinner renders inside the panel,
                # aligned with the code — not floating under these buttons.
                st.session_state["cc_deploy_pending"] = selected
                _panel_rerun = True
        with a3:
            if st.button("↩ Revert", width="stretch",
                         disabled=entry["current"] == entry["original"] and not has_unsaved):
                entry["current"] = entry["original"]
                _reset_editor_widget(selected)
                _panel_rerun = True
        with a4:
            if st.button("♻ Refetch", width="stretch",
                         disabled=bool(entry.get("is_new"))):
                _refetch(selected)
                _panel_rerun = True

        b1, b2 = st.columns(2)
        with b1:
            show_diff = st.toggle(":material/text_compare: Diff (saved draft vs server)", value=False,
                                  key=f"cc_diff_{selected}")
        with b2:
            if entry.get("is_new"):
                if st.button("🗑 Discard draft", width="stretch"):
                    bundle = entry.get("bundle")
                    del ws[selected]
                    unsaved.pop(selected, None)
                    st.session_state.pop(f"cc_editor_{selected}", None)
                    st.session_state.pop(f"cc_feedback_{selected}", None)
                    if entry["kind"] == "lwc" and not entry.get("bundle_id"):
                        # A not-yet-deployed bundle exists only as a unit.
                        for k in [k for k, e in ws.items()
                                  if e["kind"] == "lwc" and e.get("bundle") == bundle
                                  and not e.get("bundle_id")]:
                            del ws[k]
                            unsaved.pop(k, None)
                            st.session_state.pop(f"cc_editor_{k}", None)
                            st.session_state.pop(f"cc_feedback_{k}", None)
                    st.session_state["cc_selected"] = None
                    st.rerun()

        # ----- deploy explainer -----
        if targets:
            names = ", ".join(
                f"{e['file_name']} "
                f"({'recreate' if cc.file_status(e) == 'D'
                    else cc.file_status(e) or 'new'})"
                for e in targets
            )
            st.caption(f"🚀 Deploy will push: {names}")
        elif not entry.get("is_new"):
            st.caption("No saved changes to deploy for this component.")
        if has_unsaved:
            st.caption("● This file has **unsaved edits** — Save draft to include them in the next deploy.")
        if entry["kind"] == "lwc" and entry.get("is_new") and not entry.get("bundle_id"):
            st.caption(
                "🟢 This bundle exists only in your workspace. Deploying "
                "creates the bundle and pushes all of its saved files."
            )

        # ----- diff (saved draft vs server) -----
        if show_diff and (entry["current"] != entry["original"] or entry.get("conflict")):
            base = entry["original"]
            base_name = "server"
            if entry.get("conflict") and entry.get("server_copy") is not None:
                base = entry["server_copy"]
                base_name = "server (latest)"
            rows = cc.diff_rows(base, entry["current"])
            # Header stats must describe THIS diff (base → draft), not
            # original → draft: during a conflict the base is the latest
            # server copy, whose counts differ from the saved-draft
            # counts shown in the header pills above.
            d_added, d_removed = cc.diff_stats(base, entry["current"])
            rendered = []
            for row in rows:
                esc = _html.escape(row["text"]) or "&nbsp;"
                if row["kind"] == "hunk":
                    rendered.append(
                        '<div class="cc-diff-row hunk"><span class="cc-ln"></span>'
                        f'<span class="cc-ln"></span><span class="cc-dtext">{esc}</span></div>'
                    )
                    continue
                sign = {"add": "+", "del": "−", "context": " "}[row["kind"]]
                old_no = row["old_no"] if row["old_no"] is not None else ""
                new_no = row["new_no"] if row["new_no"] is not None else ""
                rendered.append(
                    f'<div class="cc-diff-row {row["kind"]}">'
                    f'<span class="cc-ln">{old_no}</span><span class="cc-ln">{new_no}</span>'
                    f'<span class="cc-dtext">{sign} {esc}</span></div>'
                )
            st.markdown(
                f"**Diff** — {base_name} → saved draft &nbsp;·&nbsp; +{d_added} / −{d_removed} lines"
            )
            if has_unsaved:
                st.caption("Unsaved editor edits are not included in this diff.")
            st.markdown(
                f'<div class="cc-diff">{"".join(rendered)}</div>',
                unsafe_allow_html=True,
            )
        elif show_diff:
            st.caption("No differences — the saved draft matches the server copy.")

        # The picker (workspace rows, dropdown suffixes) and the header
        # pills rendered BEFORE the widget block above, so if that
        # block newly stashed edits, they still show the pre-edit
        # state. Rerun once so every indicator reflects the edit
        # immediately — no manual switch or toggle needed. This cannot
        # loop: on the rerun the live text already equals the stash,
        # loop: on the rerun the live text already equals the stash, so nothing changes anymore. Editor-panel handlers do NOT rerun directly: they set _panel_rerun above, so this fires for them too — after the toggle and the diff have rendered, which is what keeps the toggle's ON value alive.
        if _panel_rerun or unsaved.get(selected) != _unsaved_before:
            st.rerun()
