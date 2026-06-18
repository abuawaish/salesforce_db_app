import streamlit as st
import pandas as pd
import json
import re


# ------------------------------------------------------------
# Page Configuration
# ------------------------------------------------------------
st.set_page_config(
    page_title="Salesforce SOQL Editor",
    page_icon="📝",
    layout="centered",
    initial_sidebar_state="expanded"
)

# ------------------------------------------------------------
# Helper functions
# ------------------------------------------------------------
@st.cache_data(ttl=300)
def get_object_fields(_sf, object_name: str):
    try:
        describe = _sf.__getattr__(object_name).describe()
        return [f["name"] for f in describe["fields"]]
    except Exception:
        return []

def clean_where_clause(clause: str) -> str:
    if not clause:
        return ""
    cleaned = " ".join(clause.split())
    if cleaned.upper().startswith("WHERE "):
        cleaned = cleaned[6:].strip()
    return cleaned

def format_salesforce_error(e: Exception) -> str:
    """
    Convert a simple_salesforce exception into a clean, human-readable
    message instead of dumping the raw "Malformed request <url>. Response
    content: [...]" repr.

    simple_salesforce errors (SalesforceMalformedRequest, etc.) carry a
    `.content` attribute with the parsed JSON error body — typically a
    list of {"message": ..., "errorCode": ..., "fields": [...]} dicts.
    We prefer that structured data when available, and fall back to
    scraping the same fields out of str(e) for any other exception shape.
    """
    def _format_entries(entries) -> list:
        out = []
        for item in entries:
            if not isinstance(item, dict) or "message" not in item:
                continue
            code = item.get("errorCode", "")
            msg = item["message"]
            fields = item.get("fields") or []
            if fields:
                msg += f" (field(s): {', '.join(fields)})"
            out.append(f"**{code}** — {msg}" if code else msg)
        return out

    content = getattr(e, "content", None)
    messages = []
    if isinstance(content, list):
        messages = _format_entries(content)
    elif isinstance(content, dict):
        messages = _format_entries([content])

    if messages:
        return "  \n".join(messages)

    # Fallback: scrape message/errorCode straight out of the string repr
    text = str(e)
    msg_match = re.search(r"'message':\s*'([^']*)'", text)
    code_match = re.search(r"'errorCode':\s*'([^']*)'", text)
    if msg_match:
        msg = msg_match.group(1)
        code = code_match.group(1) if code_match else ""
        return f"**{code}** — {msg}" if code else msg

    return text

def show_error(title: str, e: Exception):
    """Display a clean error message with the raw exception tucked away
    in an expander, instead of dumping the full request/response repr
    straight into the UI."""
    st.error(f"❌ **{title}:** {format_salesforce_error(e)}")
    with st.expander("Show technical details"):
        st.code(str(e), language="text")

def explode_soql_record(record: dict) -> list:
    """
    Flattens a single SOQL result record into one or more "rows" (dicts).

    Parent relationship lookups (e.g. Account.Owner.Name) flatten into
    dotted column names on the same row, same as before.

    Child relationship subqueries (e.g. a nested
    "SELECT ... (SELECT ... FROM Contacts) FROM Account") come back as
    {"totalSize": N, "done": bool, "records": [...]}. Rather than dumping
    that whole structure into one cell as JSON, we explode it: one output
    row per child record, with child fields flattened to
    "<RelationshipName>.<Field>" columns and the parent's own fields
    repeated on each row. A parent with zero child records still gets one
    row, with the child columns simply left blank.
    """
    record = dict(record)
    record.pop("attributes", None)

    flat_parent = {}
    child_relationships = {}

    for key, value in record.items():
        if isinstance(value, dict) and "records" in value and "totalSize" in value:
            child_relationships[key] = value.get("records") or []
        elif isinstance(value, dict):
            # Parent relationship lookup, e.g. Account: {Name: ..., Id: ...}
            for sub_k, sub_v in value.items():
                if sub_k == "attributes":
                    continue
                flat_parent[f"{key}.{sub_k}"] = sub_v
        else:
            flat_parent[key] = value

    if not child_relationships:
        return [flat_parent]

    rows = [dict(flat_parent)]
    for rel_name, children in child_relationships.items():
        new_rows = []
        if not children:
            new_rows = [dict(r) for r in rows]
        else:
            for child in children:
                child = dict(child)
                child.pop("attributes", None)
                flat_child = {f"{rel_name}.{k}": v for k, v in child.items()}
                for base_row in rows:
                    merged = dict(base_row)
                    merged.update(flat_child)
                    new_rows.append(merged)
        rows = new_rows

    return rows

def format_complex_cell(val):
    if isinstance(val, (dict, list)):
        return json.dumps(val, indent=2)
    return val

def clean_nan_for_salesforce(obj):
    if isinstance(obj, dict):
        return {k: clean_nan_for_salesforce(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [clean_nan_for_salesforce(v) for v in obj]
    elif pd.isna(obj):
        return None
    else:
        return obj

def get_query_fields(selected_fields):
    """
    Always ensure 'Id' is included (and first) in the list of fields used
    for the SOQL query, regardless of what the user picked in the
    multiselect. We need Id internally for update/delete, even though
    it's hidden from the displayed table.
    """
    return ["Id"] + [f for f in selected_fields if f != "Id"]

def compute_changes(original_df, edited_df):
    """
    Compare the originally-loaded data against the user-edited data and
    return only what genuinely needs to be sent to Salesforce:
      - rows_to_update: list of (id, payload) for rows whose values
        actually differ from what was originally loaded
      - rows_to_insert: list of payload dicts for new rows (blank Id)
        that have at least one field filled in

    This avoids two problems: (1) re-sending an identical payload for
    rows nobody touched, and (2) treating the data_editor's always-present
    empty "add a row" placeholder as a real insert when it was never
    filled in.
    """
    clean_edited = edited_df.drop(columns=["🗑️ Delete?"], errors="ignore")

    original_lookup = {}
    if "Id" in original_df.columns:
        for _, orig_row in original_df.iterrows():
            rid = orig_row.get("Id")
            if pd.notna(rid):
                orig_clean = orig_row.drop(labels=["Id", "🗑️ Delete?"], errors="ignore")
                original_lookup[rid] = clean_nan_for_salesforce(orig_clean.to_dict())

    rows_to_update = []
    update_rows = clean_edited[clean_edited["Id"].notna()]
    for _, row in update_rows.iterrows():
        rid = row["Id"]
        payload = row.drop("Id").to_dict()
        payload = clean_nan_for_salesforce(payload)
        payload.pop("Id", None)

        if payload != original_lookup.get(rid):
            rows_to_update.append((rid, payload))

    rows_to_insert = []
    insert_rows = clean_edited[clean_edited["Id"].isna()]
    for _, row in insert_rows.iterrows():
        rec = row.to_dict()
        rec = clean_nan_for_salesforce(rec)
        rec.pop("Id", None)
        rec.pop("🗑️ Delete?", None)
        # Skip entirely-blank rows (e.g. the data_editor's unused add-row)
        if any(v not in (None, "") for v in rec.values()):
            rows_to_insert.append(rec)

    return rows_to_update, rows_to_insert

def run_records_query(sf, object_name, selected_fields, where_clause):
    query_fields = get_query_fields(selected_fields)
    field_str = ", ".join(query_fields)
    q = f"SELECT {field_str} FROM {object_name}"
    if where_clause:
        q += f" WHERE {where_clause}"
    records = sf.query_all(q)["records"]
    if records:
        clean_records = []
        for rec in records:
            rec.pop("attributes", None)
            clean_records.append(rec)
        df = pd.DataFrame(clean_records)
    else:
        df = pd.DataFrame(columns=query_fields)
    df["🗑️ Delete?"] = False
    return df

# ------------------------------------------------------------
# Check connection
# ------------------------------------------------------------
if "sf" not in st.session_state or not st.session_state.get("config_ok"):
    st.warning("Please configure your Salesforce connection first (⚙️ Configuration page).")
    st.stop()

sf = st.session_state["sf"]
all_objects = [obj["name"] for obj in sf.describe()["sobjects"]]

# Tracks how many times we've loaded fresh data into the editor. We bump
# this every time we (re)load records from Salesforce, and use it as part
# of the data_editor's `key`. Streamlit ties a data_editor's edit history
# (added/edited/deleted rows) to its key, so reusing the same key across
# reruns causes old draft edits to be silently reapplied on top of newly
# fetched data. Changing the key forces a clean editor with no leftover
# drafts.
st.session_state.setdefault("editor_version", 0)

# ------------------------------------------------------------
# Page Title
# ------------------------------------------------------------
st.title("🧾 Data Query & Editor")
st.caption("Run SOQL queries and edit records inline using the dynamic spreadsheet below.")
st.divider()

# ============================================================
# SECTION 1: Execute SOQL SELECT
# ============================================================
st.subheader("🔍 1. Run SOQL Query")
soql = st.text_area(
    "SOQL Query (SELECT only)",
    height=100,
    placeholder="Enter a SOQL query here, e.g.:\nSELECT Id, Name FROM Account WHERE CreatedDate > LAST_N_DAYS:30"
)

if st.button("🚀 Run Query"):
    try:
        result = sf.query_all(soql)
        records = result["records"]
        if records:
            cleaned_records = []
            for rec in records:
                cleaned_records.extend(explode_soql_record(rec))
            df = pd.DataFrame(cleaned_records)
            df = df.map(format_complex_cell)
        else:
            df = pd.DataFrame()
        st.session_state["query_df"] = df
        if records and len(df) != len(records):
            st.success(f"✅ {len(records)} record(s) returned → {len(df)} row(s) after expanding child relationships")
        else:
            st.success(f"✅ {len(df)} records returned")
    except Exception as e:
        show_error("Query failed", e)
        st.session_state["query_df"] = None

if "query_df" in st.session_state and st.session_state["query_df"] is not None:
    df = st.session_state["query_df"]
    if not df.empty:
        st.subheader("📋 Retrieved Fields")
        st.caption(f"Columns fetched: {', '.join(df.columns)}")
        st.subheader("📊 Query Results")
        st.dataframe(df, width="stretch", height=400)
        st.caption(f"Showing {len(df)} records")
        csv = df.to_csv(index=False)
        st.download_button(
            label="⬇️ Download as CSV",
            data=csv,
            file_name="query_results.csv",
            mime="text/csv"
        )
    else:
        st.info("📭 Query returned 0 records (empty dataset).")

st.divider()

# ============================================================
# SECTION 2: Record Editor (Inline CRUD) – FIXED
# ============================================================
st.subheader("✏️ 2. Record Editor (Inline CRUD)")
st.caption("Select an object, pick the fields you want to edit, and load records.")

obj_options = ["Select an object..."] + all_objects
selected_obj_label = st.selectbox(
    "Object for editing",
    options=obj_options,
    index=0,
    key="edit_obj_selector"
)

if selected_obj_label != "Select an object...":
    obj_for_edit = selected_obj_label
    all_fields = get_object_fields(sf, obj_for_edit)
else:
    obj_for_edit = None
    all_fields = []

# 'Id' is excluded from the picklist on purpose — it's always fetched
# automatically (required for update/delete) and shown as a read-only
# column, regardless of what the user picks here.
selectable_fields = [f for f in all_fields if f != "Id"]

selected_fields = st.multiselect(
    "Select fields to display and edit",
    options=selectable_fields,
    default=[],
    help="Choose the fields you want to see and modify. 'Id' is always "
         "included and shown as a read-only column, used for saving/deleting.",
)

filter_clause = st.text_input(
    "WHERE clause (optional)",
    value="",
    placeholder="e.g., Name != null",
)

load_btn = st.button("📂 Load Records for Edit")

if load_btn:
    if not obj_for_edit:
        st.error("❌ Please select a valid object.")
    elif not selected_fields:
        st.error("❌ Please select at least one field to display.")
    else:
        try:
            clean_filter = clean_where_clause(filter_clause)
            edit_df = run_records_query(sf, obj_for_edit, selected_fields, clean_filter)

            # Store everything
            st.session_state["edit_target"] = obj_for_edit
            st.session_state["edit_df"] = edit_df
            st.session_state["selected_fields"] = selected_fields
            st.session_state["edit_filter"] = clean_filter
            st.session_state["editor_version"] += 1  # force a fresh editor, drop stale drafts

            st.success(f"✅ Loaded {len(edit_df)} records with {len(selected_fields)} visible fields.")
            st.rerun()  # Force a complete refresh of the data editor
        except Exception as e:
            show_error("Failed to load records", e)

# --- Display the Record Editor ---
if "edit_df" in st.session_state:
    st.write("**Editable Data** – modify inline, add rows, or check the 'Delete?' box to remove records.")

    # IMPORTANT: Id must stay in column_order (i.e. actually be displayed),
    # otherwise Streamlit's data_editor drops its value when reconstructing
    # edited rows — turning every "update" into an accidental "insert" with
    # a blank Id. Instead of hiding Id, we show it but make it read-only.
    display_columns = ["Id"] + st.session_state.get("selected_fields", []) + ["🗑️ Delete?"]

    edited_df = st.data_editor(
        st.session_state["edit_df"],
        num_rows="dynamic",
        key=f"record_editor_{st.session_state['editor_version']}",
        width="stretch",
        column_order=display_columns,
        column_config={
            "Id": st.column_config.TextColumn(
                "Id",
                help="Record ID (read-only). Leave blank on a new row to insert a record.",
                disabled=True,
                width="medium",
            ),
            "🗑️ Delete?": st.column_config.CheckboxColumn(
                "Mark to Delete",
                help="Check this box and click 'Delete Checked Rows'",
                default=False,
            )
        }
    )

    col1, col2 = st.columns(2)

    with col1:
        if st.button("💾 Save Changes (Insert/Update)"):
            try:
                target_obj = st.session_state.get("edit_target")
                if not target_obj:
                    st.error("No object loaded for editing.")
                elif "Id" not in edited_df.columns:
                    st.error("❌ Internal error: 'Id' column missing from editor data. Please reload the records.")
                else:
                    rows_to_update, rows_to_insert = compute_changes(
                        st.session_state["edit_df"], edited_df
                    )

                    if not rows_to_update and not rows_to_insert:
                        st.info("ℹ️ No changes detected — nothing to save.")
                    else:
                        for rid, payload in rows_to_update:
                            sf.__getattr__(target_obj).update(rid, payload)
                        for rec in rows_to_insert:
                            sf.__getattr__(target_obj).create(rec)

                        parts = []
                        if rows_to_update:
                            parts.append(f"{len(rows_to_update)} updated")
                        if rows_to_insert:
                            parts.append(f"{len(rows_to_insert)} inserted")
                        st.success("✅ " + ", ".join(parts) + " successfully!")

                        # ------------------ REFRESH TABLE ------------------
                        clean_filter = st.session_state.get("edit_filter", "")
                        selected_fields = st.session_state.get("selected_fields", [])
                        new_df = run_records_query(sf, target_obj, selected_fields, clean_filter)
                        st.session_state["edit_df"] = new_df
                        st.session_state["editor_version"] += 1  # force a fresh editor, drop stale drafts
                        st.rerun()

            except Exception as e:
                show_error("DML error", e)

    with col2:
        if st.button("🗑️ Delete Checked Rows"):
            try:
                target_obj = st.session_state.get("edit_target")
                if not target_obj:
                    st.error("No object loaded for editing.")
                elif "Id" not in edited_df.columns:
                    st.error("❌ Internal error: 'Id' column missing from editor data. Please reload the records.")
                else:
                    # Identify rows marked for deletion
                    rows_to_delete = edited_df[edited_df["🗑️ Delete?"] == True]
                    delete_ids = rows_to_delete["Id"].dropna().tolist()

                    if not delete_ids:
                        st.warning("No rows checked for deletion. Tick the 'Delete?' box first.")
                    else:
                        for rid in delete_ids:
                            sf.__getattr__(target_obj).delete(rid)

                        st.success(f"✅ Successfully deleted {len(delete_ids)} record(s).")

                        # Refresh the table
                        clean_filter = st.session_state.get("edit_filter", "")
                        selected_fields = st.session_state.get("selected_fields", [])
                        new_df = run_records_query(sf, target_obj, selected_fields, clean_filter)
                        st.session_state["edit_df"] = new_df
                        st.session_state["editor_version"] += 1  # force a fresh editor, drop stale drafts
                        st.rerun()
            except Exception as e:
                show_error("Delete failed", e)