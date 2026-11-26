"""Session-scoped Salesforce metadata and the Section 1 editor."""
from hashlib import sha256
from pathlib import Path
from time import monotonic
from uuid import uuid4

import streamlit as st
from streamlit.components.v2 import component

ASSETS = Path(__file__).parent
WIDGET = "soql_completion_editor"
CACHE = "_soql_completion_catalog"
TTL = 900
BATCH_SIZE = 16

# Inline assets keep the component self-contained on Streamlit Community Cloud.
_editor = component(
    "sf_query_studio_soql",
    html=(ASSETS / "editor.html").read_text(encoding="utf-8"),
    css=(ASSETS / "editor.css").read_text(encoding="utf-8"),
    js="\n".join((ASSETS / f).read_text(encoding="utf-8")
                 for f in ("completion.js", "editor.js")),
)


def connection_key(sf):
    # Private to the server. The random catalog generation sent to the browser
    # is independent of credentials, principal, and Salesforce instance URL.
    return (sf.sf_instance, sha256(sf.session_id.encode()).digest())


def prepare_catalog(sf):
    state = st.session_state
    key = connection_key(sf)
    catalog = state.get(CACHE)
    changed_connection = catalog is not None and catalog["connection"] != key
    if changed_connection:
        state.pop("fa_describe_cache", None)
        state.pop("fa_all_objects", None)
    shared = state.setdefault("fa_describe_cache", {})
    # The catalog survives page switches, it is rebuilt
    # only on first visit, connection change, Clear Cache / Refresh Data (both
    # replace the shared cache dict), or after the TTL expires.
    if (catalog is None or changed_connection
            or shared is not catalog["shared"] or state.get("fa_all_objects") is None
            or catalog["expires"] <= monotonic()):
        try:
            objects = sf.describe()["sobjects"]
            state["fa_all_objects"] = sorted(obj["name"] for obj in objects)
            unavailable = False
        except Exception:
            # Keep manual query execution available during a describe outage.
            objects = []
            state["fa_all_objects"] = state.get("fa_all_objects") or []
            unavailable = True
        names = sorted(obj["name"] for obj in objects
                       if obj.get("queryable") and not obj.get("deprecatedAndHidden")
                       and obj.get("accessible", True))
        catalog = dict(connection=key, shared=shared, names=names, allowed=set(names),
                       schema={}, generation=uuid4().hex, unavailable=unavailable,
                       expires=monotonic() + (30 if unavailable else TTL))
        state[CACHE] = catalog
    return catalog


def compact_describe(body, allowed):
    """Project only read-visible REST describe data. Write permissions are irrelevant."""
    fields = {}
    parents = {}
    for field in body["fields"]:
        if field.get("deprecatedAndHidden") or not field.get("accessible", True):
            continue
        flags = "".join(flag for flag, key in (("f", "filterable"), ("g", "groupable"),
                                               ("s", "sortable"), ("a", "aggregatable"))
                        if field.get(key))
        fields[field["name"]] = [field["type"], flags]
        refs = [name for name in field.get("referenceTo", []) if name in allowed]
        if field.get("relationshipName") and len(refs) == 1:
            parents[field["relationshipName"]] = refs[0]
    children = {r["relationshipName"]: r["childSObject"] for r in body.get("childRelationships", [])
                if r.get("relationshipName") and r.get("childSObject") in allowed
                and not r.get("deprecatedAndHidden")}
    return dict(fields=fields, parents=parents, children=children)


def load_batch(sf, catalog, requested):
    """One composite REST call per cold batch. Never trust browser-supplied paths."""
    allowed, cache = catalog["allowed"], catalog["schema"]
    names = list(dict.fromkeys(n for n in requested[:BATCH_SIZE]
                               if isinstance(n, str) and n in allowed))
    missing = [n for n in names if n not in cache]
    if missing:
        requests = [
            {"method": "GET", "referenceId": f"obj{i}",
             "url": f"/services/data/v{sf.sf_version}/sobjects/{name}/describe"}
            for i, name in enumerate(missing)
        ]
        response = sf.restful("composite", method="POST", json={"compositeRequest": requests},
                              timeout=(5, 25))
        refs = {req["referenceId"]: name for req, name in zip(requests, missing)}
        for item in (response or {}).get("compositeResponse", []):
            ref = item.get("referenceId")
            if ref not in refs:
                continue
            name = refs[ref]
            body = item.get("body")
            if (item["httpStatusCode"] in (401, 429) or item["httpStatusCode"] >= 500
                    or (isinstance(body, list) and any(
                        e.get("errorCode") == "REQUEST_LIMIT_EXCEEDED" for e in body))):
                raise RuntimeError("Salesforce temporarily paused metadata requests.")
            if (item["httpStatusCode"] == 200 and isinstance(body, dict)
                    and body.get("name") == name and body.get("queryable")
                    and isinstance(body.get("fields"), list)):
                cache[name] = compact_describe(body, allowed)
    return {name: cache[name] for name in names if name in cache}


def replace_draft(query):
    state = st.session_state
    state.soql_query_input = query
    state["_soql_draft_revision"] = state.get("_soql_draft_revision", 0) + 1


def _event(name):
    event = st.session_state[WIDGET].get(name)
    catalog = st.session_state.get(CACHE)
    if (isinstance(event, dict) and catalog and event.get("generation") == catalog["generation"]
            and event.get("revision") == st.session_state.get("_soql_draft_revision", 0)):
        return event
    return {}


def _save_draft():
    value = _event("draft").get("text")
    if isinstance(value, str):
        st.session_state.soql_query_input = value


def _submit():
    value = _event("run").get("text")
    if isinstance(value, str):
        st.session_state.soql_query_input = value
        st.session_state["_soql_submit"] = value


def _request():
    st.session_state["_soql_request"] = _event("metadata")


@st.fragment
def render_editor():
    state = st.session_state
    sf = state.sf
    catalog = state[CACHE]
    if "_soql_submit" in state:
        # The outer page owns results/history. Transfer exactly one submission.
        state["_soql_execute"] = state.pop("_soql_submit")
        st.rerun()
    request = state.pop("_soql_request", {})
    if catalog["expires"] <= monotonic() or catalog["connection"] != connection_key(sf):
        st.rerun()
    reply = catalog.get("reply")
    if request.get("generation") == catalog["generation"]:
        requested = request.get("names", [])
        reply = {"id": request.get("id"), "schema": {}}
        if isinstance(requested, list):
            try:
                reply["schema"] = load_batch(sf, catalog, requested)
            except Exception:
                # Query execution stays usable if the describe service is unavailable.
                reply["unavailable"] = True
        catalog["reply"] = reply
    _editor(key=WIDGET, data=dict(
        objects=catalog["names"], generation=catalog["generation"], batch=BATCH_SIZE,
        unavailable=catalog["unavailable"],
        ttl=max(0, catalog["expires"] - monotonic()), reply=reply,
        revision=state.get("_soql_draft_revision", 0), text=state.soql_query_input,
    ), on_metadata_change=_request, on_run_change=_submit, on_draft_change=_save_draft)
