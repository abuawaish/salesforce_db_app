import streamlit as st
import pandas as pd
import json
import re

# ------------------------------------------------------------
# Page Configuration
# ------------------------------------------------------------
st.set_page_config(
    page_title="SOQL Editor & Record Management",
    page_icon="📝",
    layout="wide",
    initial_sidebar_state="auto"
)

# ------------------------------------------------------------
# Check connection
# ------------------------------------------------------------
if "sf" not in st.session_state or not st.session_state.get("config_ok"):
    st.warning("Please configure your Salesforce connection first (⚙️ Configuration page).")
    st.info(
        "💡 **What this page does:** once connected, write and run SOQL "
        "`SELECT` queries against any Salesforce object, view the results "
        "in a sortable table, edit records inline, and export what you find "
        "to CSV — all without leaving your browser."
    )
    st.stop()

sf = st.session_state["sf"]

# ------------------------------------------------------------
# Session-state caches (shared with Field Analysis page)
# ------------------------------------------------------------
# Describe results keyed by object name — fetched once, reused instantly
# across both this page and Field Analysis.
if "fa_describe_cache" not in st.session_state:
    st.session_state["fa_describe_cache"] = {}

# Global object list — fetched once per session.
if "fa_all_objects" not in st.session_state:
    st.session_state["fa_all_objects"] = sorted(
        obj["name"] for obj in sf.describe()["sobjects"]
    )

# ------------------------------------------------------------
# Constant for delete checkbox column name
# ------------------------------------------------------------
DELETE_COL = "🗑️ Delete?"
WRITE_EXCLUDED_COLUMNS = {"attributes", DELETE_COL}

# ------------------------------------------------------------
# Helper functions
# ------------------------------------------------------------
def _get_describe(object_name: str) -> dict:
    """Return full describe from session cache; only hits API on first call."""
    cache = st.session_state["fa_describe_cache"]
    if object_name not in cache:
        cache[object_name] = sf.__getattr__(object_name).describe()
    return cache[object_name]


def get_object_fields(object_name: str):
    try:
        return [f["name"] for f in _get_describe(object_name)["fields"]]
    except Exception:
        return []


def get_object_field_metadata(object_name: str):
    """
    Returns Salesforce field metadata for the selected object.

    Used for:
    - checking whether CSV columns are real Salesforce API field names
    - checking createable/updateable permissions
    """
    try:
        return {f["name"]: f for f in _get_describe(object_name)["fields"]}
    except Exception:
        return {}


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
    """
    Display a clean error message with the raw exception tucked away
    in an expander, instead of dumping the full request/response repr
    straight into the UI.
    """
    def _clean_exception_text(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip().replace("\\n", "")

    st.error(f"❌ **{title}:** {format_salesforce_error(e)}")
    with st.expander("Show technical details"):
        st.code(_clean_exception_text(str(e)), language="text")


def init_soql_history():
    st.session_state.setdefault("soql_history", [])
    st.session_state.setdefault("soql_query_input", "")
    st.session_state.setdefault(
        "soql_history_selector",
        "-- Select a previously executed query --"
    )


def add_query_history(query: str):
    query = query.strip()
    if not query:
        return

    history = st.session_state.soql_history

    if query in history:
        history.remove(query)

    history.insert(0, query)
    st.session_state.soql_history = history[:50]


def select_history_query():
    selected_query = st.session_state.soql_history_selector
    if selected_query and selected_query != "-- Select a previously executed query --":
        st.session_state.soql_query_input = selected_query


def clear_query_history():
    st.session_state.soql_history = []
    st.session_state.soql_history_selector = "-- Select a previously executed query --"
    st.session_state.soql_query_input = ""


def explode_soql_record(record: dict) -> list:
    """
    Flattens a single SOQL result record into one or more "rows" (dicts).

    Parent relationship lookups flatten into dotted column names on the same row.

    Child relationship subqueries are exploded into one output row per child
    record, with parent fields repeated.
    """
    record = dict(record)
    record.pop("attributes", None)

    flat_parent = {}
    child_relationships = {}

    for key, value in record.items():
        if isinstance(value, dict) and "records" in value and "totalSize" in value:
            child_relationships[key] = value.get("records") or []
        elif isinstance(value, dict):
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
    Always ensure 'Id' is included first in the query field list.
    """
    return ["Id"] + [f for f in selected_fields if f != "Id"]


def compute_changes(original_df, edited_df):
    """
    Compare originally-loaded data against user-edited data.

    Returns:
      - rows_to_update: list of (id, payload)
      - rows_to_insert: list of payload dicts
    """
    clean_edited = edited_df.drop(columns=[DELETE_COL], errors="ignore")

    original_lookup = {}

    if "Id" in original_df.columns:
        for _, orig_row in original_df.iterrows():
            rid = orig_row.get("Id")

            if pd.notna(rid):
                orig_clean = orig_row.drop(
                    labels=["Id", DELETE_COL],
                    errors="ignore"
                )
                original_lookup[rid] = clean_nan_for_salesforce(orig_clean.to_dict())

    rows_to_update = []
    update_rows = clean_edited[clean_edited["Id"].notna()]

    for _, row in update_rows.iterrows():
        rid = row["Id"]
        current = clean_nan_for_salesforce(row.drop("Id").to_dict())
        original = original_lookup.get(rid, {})

        changed_payload = {
            field: new_val
            for field, new_val in current.items()
            if field not in original or original[field] != new_val
        }

        if changed_payload:
            rows_to_update.append((rid, changed_payload))

    rows_to_insert = []
    insert_rows = clean_edited[clean_edited["Id"].isna()]

    for _, row in insert_rows.iterrows():
        rec = row.to_dict()
        rec = clean_nan_for_salesforce(rec)
        rec.pop("Id", None)
        rec.pop(DELETE_COL, None)

        # Skip Streamlit's empty dynamic add-row placeholder
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

    df[DELETE_COL] = False
    return df


def _is_blank(value):
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except Exception:
        pass
    return value == ""


def _same_value(old_value, new_value):
    try:
        if pd.isna(old_value) and pd.isna(new_value):
            return True
    except Exception:
        pass
    return old_value == new_value


def get_salesforce_writeable_fields(field_metadata):
    createable_fields = {
        field["name"] for field in field_metadata
        if field.get("createable", False)
    }
    updateable_fields = {
        field["name"] for field in field_metadata
        if field.get("updateable", False)
    }
    return createable_fields, updateable_fields


def show_temporary_message(message, level="warning"):
    """
    Show a temporary toast message that auto-dismisses.
    Uses st.toast() for non-blocking, ephemeral notifications.
    """
    if level == "error":
        st.toast(message, icon="❌")
    elif level == "success":
        st.toast(message, icon="✅")
    elif level == "info":
        st.toast(message, icon="ℹ️")
    else:
        st.toast(message, icon="⚠️")


def build_insert_payload(row_dict, createable_fields):
    raw_values = {}
    for key, value in row_dict.items():
        if key in WRITE_EXCLUDED_COLUMNS or key == "Id":
            continue
        if _is_blank(value):
            continue
        raw_values[key] = None if pd.isna(value) else value

    blocked_fields = sorted(
        field_name
        for field_name in raw_values
        if field_name not in createable_fields
    )

    payload = {
        field_name: field_value
        for field_name, field_value in raw_values.items()
        if field_name in createable_fields
    }

    return payload, blocked_fields


def build_update_payload(original_row, edited_row, updateable_fields):
    changed_fields = {}
    for key, new_value in edited_row.items():
        if key in WRITE_EXCLUDED_COLUMNS or key == "Id":
            continue
        old_value = original_row.get(key)
        if _same_value(old_value, new_value):
            continue
        changed_fields[key] = None if pd.isna(new_value) else new_value

    blocked_fields = sorted(
        field_name
        for field_name in changed_fields
        if field_name not in updateable_fields
    )

    payload = {
        field_name: field_value
        for field_name, field_value in changed_fields.items()
        if field_name in updateable_fields
    }

    return payload, blocked_fields


# ------------------------------------------------------------
# Bulk CSV helper functions
# ------------------------------------------------------------
def normalize_csv_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Trim spaces around CSV column names and detect duplicate columns.
    Example: ' Name ' becomes 'Name'.
    """
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]

    duplicate_cols = df.columns[df.columns.duplicated()].tolist()

    if duplicate_cols:
        raise ValueError(
            f"Duplicate column(s) found in CSV: {', '.join(duplicate_cols)}"
        )

    return df


def validate_bulk_csv_fields(object_name: str, df: pd.DataFrame, operation: str):
    """
    Validate uploaded CSV columns based on operation type.

    Insert:
      - Id is not required
      - Id will be ignored if present
      - At least one non-Id field is required

    Update:
      - Id is required
      - At least one other field is required

    Delete:
      - Only Id is required
      - Extra fields are ignored
    """
    errors = []
    warnings = []

    if df.empty:
        errors.append("Uploaded CSV file is empty.")
        return errors, warnings

    field_metadata = get_object_field_metadata(object_name)
    if not field_metadata:
        errors.append(
            f"You don't have permission to describe object '{object_name}', "
            "or the object does not exist."
        )
        return errors, warnings

    available_fields = set(field_metadata.keys())
    csv_fields = list(df.columns)
    operation = operation.lower()

    if operation in ("insert", "update"):
        for field in csv_fields:
            if field not in available_fields:
                errors.append(
                    f"The field '{field}' is not available in the selected object "
                    f"'{object_name}', please select the valid field for this object."
                )

        if errors:
            return errors, warnings

    elif operation == "delete":
        if "Id" not in csv_fields:
            errors.append("For bulk deletion, only Id field is required.")

        extra_fields = [f for f in csv_fields if f != "Id"]

        if extra_fields:
            warnings.append(
                "For bulk deletion, only Id field is required. "
                "Extra field(s) will be ignored: " + ", ".join(extra_fields)
            )

        return errors, warnings

    else:
        errors.append("Invalid bulk operation selected.")
        return errors, warnings

    if operation == "insert":
        non_id_fields = [f for f in csv_fields if f != "Id"]

        if not non_id_fields:
            errors.append(
                "For bulk insertion, CSV must contain at least one field other than Id."
            )

        if "Id" in csv_fields:
            warnings.append(
                "Id field is present in CSV but will be ignored for bulk insertion."
            )

        non_createable_fields = [
            f for f in non_id_fields
            if not field_metadata.get(f, {}).get("createable", False)
        ]

        if non_createable_fields:
            errors.append(
                "These field(s) are not createable in Salesforce and cannot be used for insert: "
                + ", ".join(non_createable_fields)
            )

    elif operation == "update":
        if "Id" not in csv_fields:
            errors.append("For bulk updation, Id field is required.")

        update_fields = [f for f in csv_fields if f != "Id"]

        if not update_fields:
            errors.append(
                "For bulk updation, CSV must contain Id and at least one field to update."
            )

        non_updateable_fields = [
            f for f in update_fields
            if not field_metadata.get(f, {}).get("updateable", False)
        ]

        if non_updateable_fields:
            errors.append(
                "These field(s) are not updateable in Salesforce and cannot be used for update: "
                + ", ".join(non_updateable_fields)
            )

    return errors, warnings


def prepare_bulk_records_from_csv(df: pd.DataFrame, operation: str):
    """
    Convert uploaded CSV dataframe into Salesforce Bulk API compatible records.
    """
    operation = operation.lower()
    df = normalize_csv_columns(df)
    records_from_csv = clean_nan_for_salesforce(df.to_dict(orient="records"))

    records = []

    if operation == "insert":
        for row in records_from_csv:
            row.pop("Id", None)

            # Skip fully blank rows
            if any(v not in (None, "") for v in row.values()):
                records.append(row)

    elif operation == "update":
        for row in records_from_csv:
            rid = row.get("Id")

            if rid in (None, ""):
                continue

            record = {"Id": rid}

            for field, value in row.items():
                if field != "Id":
                    record[field] = value

            records.append(record)

    elif operation == "delete":
        for row in records_from_csv:
            rid = row.get("Id")

            if rid not in (None, ""):
                records.append({"Id": rid})

    return records


def chunk_records(records: list, chunk_size: int = 200):
    """
    Split records into smaller chunks for bulk processing.
    This helps show progress after each batch.
    """
    for i in range(0, len(records), chunk_size):
        yield records[i:i + chunk_size]


def run_bulk_operation_with_progress(
    sf,
    object_name: str,
    operation: str,
    records: list,
    batch_size: int = 200,
    progress_bar=None,
    status_placeholder=None
):
    """
    Execute Salesforce Bulk API operation in chunks and update Streamlit progress bar.
    """
    bulk_obj = sf.bulk.__getattr__(object_name)
    operation = operation.lower()

    all_results = []
    total_records = len(records)
    processed_records = 0

    chunks = list(chunk_records(records, batch_size))
    total_batches = len(chunks)

    for batch_index, batch_records in enumerate(chunks, start=1):
        if status_placeholder:
            status_placeholder.info(
                f"Processing batch {batch_index} of {total_batches} "
                f"({len(batch_records)} record(s))..."
            )

        if operation == "insert":
            batch_results = bulk_obj.insert(batch_records, batch_size=len(batch_records))
        elif operation == "update":
            batch_results = bulk_obj.update(batch_records, batch_size=len(batch_records))
        elif operation == "delete":
            batch_results = bulk_obj.delete(batch_records, batch_size=len(batch_records))
        else:
            raise ValueError("Invalid bulk operation.")

        all_results.extend(batch_results)

        processed_records += len(batch_records)
        progress_percent = processed_records / total_records

        if progress_bar:
            progress_bar.progress(progress_percent)

    if status_placeholder:
        status_placeholder.success(
            f"Bulk {operation} processing completed for {processed_records} record(s)."
        )

    return all_results


def summarize_bulk_results(results):
    """
    Summarize Salesforce Bulk API result response.
    """
    success_count = 0
    failure_count = 0
    failed_rows = []

    for idx, result in enumerate(results, start=1):
        if result.get("success") is True:
            success_count += 1
        else:
            failure_count += 1
            failed_rows.append({
                "Row Number": idx,
                "Id": result.get("id"),
                "Errors": result.get("errors")
            })

    return success_count, failure_count, failed_rows

init_soql_history()

all_objects = st.session_state["fa_all_objects"]

# Tracks fresh editor versions to avoid stale Streamlit data_editor drafts.
st.session_state.setdefault("editor_version", 0)

# ------------------------------------------------------------
# Page Title
# ------------------------------------------------------------
st.title("🧾 Data Query & Editor")
st.caption("Run SOQL queries, edit records inline, and perform bulk CSV operations.")

btn_spacer, btn_col1, btn_col2 = st.columns([4, 1, 1])
with btn_col1:
    if st.button("🔄 Refresh Data", width="stretch", type="secondary"):
        st.cache_data.clear()
        st.session_state.pop("fa_describe_cache", None)
        st.session_state.pop("fa_all_objects", None)
        st.rerun()
with btn_col2:
    if st.button("🗑️ Clear Cache", width="stretch", type="secondary"):
        st.cache_data.clear()
        st.session_state.pop("fa_describe_cache", None)
        st.session_state.pop("fa_all_objects", None)
        st.toast("Cache cleared! Data will refresh on next load.", icon="✅")

st.divider()

# ============================================================
# SECTION 1: Execute SOQL SELECT
# ============================================================
st.subheader("🔍 1. Run SOQL Query")

with st.form("soql_query_form"):
    soql = st.text_area(
        "SOQL Query (SELECT only)",
        height=120,
        placeholder="Enter a valid SOQL SELECT query here (e.g., SELECT Id, Name FROM Account LIMIT 10)",
        key="soql_query_input",
    )

    st.caption(
        "💡Press Ctrl+Enter to submit the query."
    )

    run_query_pressed = st.form_submit_button("Run Query", icon="🚀")

if run_query_pressed:
    soql = st.session_state.soql_query_input.strip()
    if not soql:
        st.toast("No SOQL query entered.", icon="❌")
        st.error("❌ Please enter a SOQL query.")
    else:
        add_query_history(soql)

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

            st.toast("Query executed successfully!", icon="✅")
            if records and len(df) != len(records):
                st.success(
                    f"✅ {len(records)} record(s) returned → "
                    f"{len(df)} row(s) after expanding child relationships"
                )
            else:
                st.success(f"✅ {len(df)} records returned")

        except Exception as e:
            st.toast("Exception occurred while executing query.", icon="❌")
            show_error("Query failed", e)
            st.session_state["query_df"] = None


history_options = ["-- Select a previously executed query --"] + st.session_state.soql_history
history_index = 0

if st.session_state.soql_history_selector in history_options:
    history_index = history_options.index(st.session_state.soql_history_selector)

history_col1, history_col2 = st.columns([5, 1], vertical_alignment="bottom")

with history_col1:
    selected_history_query = st.selectbox(
        "SOQL History Tracker",
        options=history_options,
        index=history_index,
        key="soql_history_selector",
        on_change=select_history_query,
        help="Select a previously executed SOQL query to reload it into the query box.",
    )

with history_col2:
    st.button(
        "Clear History",
        on_click=clear_query_history,
        help="Remove all saved SOQL query history.",
        disabled=not st.session_state.soql_history,
        width="content",
    )

if not st.session_state.soql_history:
    st.caption("No saved SOQL queries yet. Run a query to add it to history.")


if "query_df" in st.session_state and st.session_state["query_df"] is not None:
    df = st.session_state["query_df"]

    if not df.empty:
        st.subheader("📋 Retrieved Fields")

        expanded_prefixes = {col.split(".")[0] for col in df.columns if "." in col}
        spurious_cols = [col for col in df.columns if col in expanded_prefixes]

        if spurious_cols:
            df = df.drop(columns=spurious_cols)
            st.session_state["query_df"] = df

        st.caption(f"Columns fetched: {', '.join(df.columns)}")
        st.subheader("📊 Query Results")

        ROW_PX = 35
        HEADER_PX = 38
        dynamic_height = max(HEADER_PX + ROW_PX * len(df), 120)
        dynamic_height = min(dynamic_height, 650)

        st.dataframe(df, width="stretch", height=dynamic_height)
        st.caption(f"Showing {len(df)} record(s) · {len(df.columns)} column(s)")

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
# SECTION 2: Record Editor Inline CRUD
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
    # Uses session-state cache — instant if already described on Field Analysis page
    all_fields = get_object_fields(obj_for_edit)
else:
    obj_for_edit = None
    all_fields = []

selectable_fields = [f for f in all_fields if f != "Id"]

selected_fields = st.multiselect(
    "Select fields to display and edit",
    options=selectable_fields,
    default=[],
    help=(
        "Choose the fields you want to see and modify. 'Id' is always "
        "included and shown as a read-only column, used for saving/deleting."
    ),
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
        with st.spinner("Loading records..."):
            try:
                clean_filter = clean_where_clause(filter_clause)
                edit_df = run_records_query(
                    sf,
                    obj_for_edit,
                    selected_fields,
                    clean_filter
                )

                st.session_state["edit_target"] = obj_for_edit
                st.session_state["edit_df"] = edit_df
                st.session_state["selected_fields"] = selected_fields
                st.session_state["edit_filter"] = clean_filter
                st.session_state["editor_version"] += 1
                st.session_state["original_fetched_df"] = edit_df.copy(deep=True)
                if "Id" in edit_df.columns:
                    st.session_state["original_rows_by_id"] = (
                        edit_df.set_index("Id").to_dict("index")
                    )
                else:
                    st.session_state["original_rows_by_id"] = {}

                st.success(
                    f"✅ Loaded {len(edit_df)} records with "
                    f"{len(selected_fields)} visible fields."
                )
                st.rerun()

            except Exception as e:
                show_error("Failed to load records", e)


# --- Display the Record Editor ---
if "edit_df" in st.session_state:
    st.write(
        "**Editable Data** – modify inline, add rows, or check the "
        "'Delete?' box to remove records."
    )

    display_columns = ["Id"] + st.session_state.get("selected_fields", []) + [DELETE_COL]

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
            DELETE_COL: st.column_config.CheckboxColumn(
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
                    st.error(
                        "❌ Internal error: 'Id' column missing from editor data. "
                        "Please reload the records."
                    )

                else:
                    _, is_insert = compute_changes(
                        st.session_state["edit_df"],
                        edited_df
                    )

                    # Check if there were completely blank rows ignored
                    blank_mask = (
                        edited_df["Id"].isna() &
                        edited_df.drop(columns=["Id", DELETE_COL], errors="ignore")
                            .apply(lambda row: all(pd.isna(v) or v == "" for v in row), axis=1)
                    )
                    if (is_insert and blank_mask.any()):
                        st.info(
                            "ℹ️ Blank rows were ignored. Only rows with at least one "
                            "non‑empty field are inserted."
                        )

                    # --- Prepare metadata and writable field sets ---------------------------
                    field_metadata = get_object_field_metadata(target_obj)
                    createable_fields, updateable_fields = get_salesforce_writeable_fields(
                        field_metadata.values()
                    )
                    original_rows_by_id = st.session_state.get("original_rows_by_id", {})
                    # -----------------------------------------------------------------------

                    # --- Build update payloads (only changed writable fields) ---------------
                    rows_to_update = []
                    update_rows = edited_df[edited_df["Id"].notna()]
                    for _, row in update_rows.iterrows():
                        row_dict = row.to_dict()
                        record_id = row_dict.get("Id")
                        if not record_id:
                            continue
                        original_row = original_rows_by_id.get(record_id, {})
                        payload, blocked_fields = build_update_payload(
                            original_row=original_row,
                            edited_row=row_dict,
                            updateable_fields=updateable_fields,
                        )
                        if blocked_fields:
                            show_temporary_message(
                                "Salesforce does not allow updating read-only/"
                                "system-generated field(s): " + ", ".join(blocked_fields),
                                level="warning",
                            )
                        if payload:
                            rows_to_update.append((record_id, payload))
                    # -----------------------------------------------------------------------

                    # --- Build insert payloads (only createable fields) -------------------
                    rows_to_insert = []
                    insert_rows = edited_df[edited_df["Id"].isna()]
                    for _, row in insert_rows.iterrows():
                        row_dict = row.to_dict()
                        row_dict.pop("Id", None)
                        row_dict.pop(DELETE_COL, None)
                        if all(v in (None, "") for v in row_dict.values()):
                            continue
                        payload, blocked_fields = build_insert_payload(
                            row_dict=row_dict,
                            createable_fields=createable_fields,
                        )
                        if blocked_fields:
                            show_temporary_message(
                                "Salesforce skipped read-only/system field(s) during insert: "
                                + ", ".join(blocked_fields),
                                level="warning",
                            )
                        if payload:
                            rows_to_insert.append(payload)
                    # -----------------------------------------------------------------------

                    if not rows_to_update and not rows_to_insert:
                        st.info("ℹ️ No changes detected — nothing to save.")

                    else:
                        update_success = 0
                        update_failures = []

                        insert_success = 0
                        insert_failures = []

                        with st.spinner("Saving inline changes..."):
                            for rid, payload in rows_to_update:
                                try:
                                    sf.__getattr__(target_obj).update(rid, payload)
                                    update_success += 1
                                except Exception as e:
                                    update_failures.append({
                                        "Id": rid,
                                        "Payload": payload,
                                        "Error": format_salesforce_error(e)
                                    })

                            for rec in rows_to_insert:
                                try:
                                    sf.__getattr__(target_obj).create(rec)
                                    insert_success += 1
                                except Exception as e:
                                    insert_failures.append({
                                        "Record": rec,
                                        "Error": format_salesforce_error(e)
                                    })

                        parts = []

                        if update_success:
                            parts.append(f"{update_success} updated")

                        if insert_success:
                            parts.append(f"{insert_success} inserted")

                        if parts:
                            st.success("✅ " + ", ".join(parts) + " successfully!")

                        total_failures = len(update_failures) + len(insert_failures)

                        if total_failures:
                            st.error(
                                f"❌ {total_failures} record(s) failed during save."
                            )

                            if update_failures:
                                st.subheader("❌ Update Failures")
                                st.dataframe(
                                    pd.DataFrame(update_failures), width="stretch"
                                )

                            if insert_failures:
                                st.subheader("❌ Insert Failures")
                                st.dataframe(
                                    pd.DataFrame(insert_failures), width="stretch"
                                )

                        # Refresh table only if everything succeeded
                        if total_failures == 0:
                            clean_filter = st.session_state.get("edit_filter", "")
                            selected_fields = st.session_state.get("selected_fields", [])

                            new_df = run_records_query(
                                sf,
                                target_obj,
                                selected_fields,
                                clean_filter
                            )

                            st.session_state["edit_df"] = new_df
                            st.session_state["editor_version"] += 1
                            if "Id" in new_df.columns:
                                st.session_state["original_rows_by_id"] = (
                                    new_df.set_index("Id").to_dict("index")
                                )
                            else:
                                st.session_state["original_rows_by_id"] = {}
                            st.rerun()
                        else:
                            st.warning(
                                "⚠️ Please review the errors above and correct the data. "
                                "The table has not been refreshed."
                            )

            except Exception as e:
                show_error("DML error", e)

    with col2:
        delete_confirm = st.checkbox(
            "I confirm deletion of checked inline rows",
            key="inline_delete_confirm"
        )

        if st.button("🗑️ Delete Checked Rows", disabled=not delete_confirm):
            try:
                target_obj = st.session_state.get("edit_target")

                if not target_obj:
                    st.error("No object loaded for editing.")

                elif "Id" not in edited_df.columns:
                    st.error(
                        "❌ Internal error: 'Id' column missing from editor data. "
                        "Please reload the records."
                    )

                else:
                    if DELETE_COL not in edited_df.columns:
                        edited_df[DELETE_COL] = False

                    delete_mask = edited_df[DELETE_COL].fillna(False).astype(bool)
                    rows_marked_for_delete = edited_df.loc[delete_mask].copy()
                    delete_ids = rows_marked_for_delete["Id"].dropna().tolist()

                    if not rows_marked_for_delete.empty:
                        st.caption(
                            f"{len(rows_marked_for_delete)} row(s) currently marked for deletion."
                        )

                    if not delete_ids:
                        if rows_marked_for_delete.empty:
                            st.info(
                                f"No rows are currently marked for deletion. "
                                f"Tick the '{DELETE_COL}' checkbox for the row(s) "
                                f"you want to delete, then click delete again."
                            )
                        else:
                            st.warning(
                                "Checked rows for deletion have no Salesforce ID. "
                                "Only existing records can be deleted; new/unsaved "
                                "rows will be ignored."
                            )

                    else:
                        delete_success = 0
                        delete_failures = []

                        with st.spinner("Deleting checked records..."):
                            for rid in delete_ids:
                                try:
                                    sf.__getattr__(target_obj).delete(rid)
                                    delete_success += 1
                                except Exception as e:
                                    delete_failures.append({
                                        "Id": rid,
                                        "Error": format_salesforce_error(e)
                                    })

                        if delete_success:
                            st.success(
                                f"✅ Successfully deleted {delete_success} record(s)."
                            )

                        if delete_failures:
                            st.error(
                                f"❌ {len(delete_failures)} record(s) failed during delete."
                            )
                            st.dataframe(
                                pd.DataFrame(delete_failures),
                                width="stretch"
                            )

                        # Refresh table only if everything succeeded
                        if not delete_failures:
                            clean_filter = st.session_state.get("edit_filter", "")
                            selected_fields = st.session_state.get("selected_fields", [])

                            new_df = run_records_query(
                                sf,
                                target_obj,
                                selected_fields,
                                clean_filter
                            )

                            st.session_state["edit_df"] = new_df
                            st.session_state["editor_version"] += 1
                            if "Id" in new_df.columns:
                                st.session_state["original_rows_by_id"] = (
                                    new_df.set_index("Id").to_dict("index")
                                )
                            else:
                                st.session_state["original_rows_by_id"] = {}
                            st.rerun()
                        else:
                            st.warning(
                                "⚠️ Some deletions failed. Please review the errors above. "
                                "The table has not been refreshed."
                            )

            except Exception as e:
                show_error("Delete failed", e)


st.divider()

# ============================================================
# SECTION 3: BULK CSV OPERATIONS - Insert / Update / Delete
# ============================================================
st.subheader("📦 3. Bulk CSV Operations")
st.caption("Upload a CSV file to perform bulk Insert, Update, or Delete operations on Salesforce records.")

bulk_obj_options = ["Select an object..."] + all_objects

bulk_object = st.selectbox(
    "Select Object for Bulk Operation",
    options=bulk_obj_options,
    index=0,
    key="bulk_object_selector"
)

bulk_operation = st.radio(
    "Select Bulk Operation",
    options=["Insert", "Update", "Delete"],
    horizontal=True,
    key="bulk_operation_selector"
)

uploaded_csv = st.file_uploader(
    "Upload file as CSV",
    type=["csv"],
    key=f"bulk_csv_uploader_{bulk_object}_{bulk_operation}"
)

if uploaded_csv is not None:
    try:
        if bulk_object == "Select an object...":
            st.error("❌ Please select a valid object for bulk operation.")

        else:
            bulk_df = pd.read_csv(uploaded_csv)
            bulk_df = normalize_csv_columns(bulk_df)

            st.subheader("👀 CSV Preview")

            ROW_PX = 35
            HEADER_PX = 38
            dynamic_height = max(HEADER_PX + ROW_PX * len(bulk_df), 120)
            dynamic_height = min(dynamic_height, 650)

            st.dataframe(bulk_df, width="stretch", height=dynamic_height)
            st.caption(
                f"Previewing {len(bulk_df)} row(s) and "
                f"{len(bulk_df.columns)} column(s)."
            )

            # Uses session-state cache — no extra API call if object was already described
            validation_errors, validation_warnings = validate_bulk_csv_fields(
                bulk_object,
                bulk_df,
                bulk_operation
            )

            for warning in validation_warnings:
                st.warning("⚠️ " + warning)

            if validation_errors:
                for err in validation_errors:
                    st.error("❌ " + err)

            else:
                bulk_records = prepare_bulk_records_from_csv(
                    bulk_df,
                    bulk_operation
                )

                if not bulk_records:
                    st.warning("⚠️ No valid records found in uploaded CSV.")

                else:
                    st.info(
                        f"Ready to perform bulk {bulk_operation.lower()} "
                        f"for {len(bulk_records)} record(s) on {bulk_object}."
                    )

                    if bulk_operation == "Insert":
                        st.caption(
                            "Criteria: Id field is not required for bulk insertion. "
                            "Salesforce will auto-populate Id."
                        )

                    elif bulk_operation == "Update":
                        st.caption(
                            "Criteria: Id and at least one update field are "
                            "required for bulk updation."
                        )

                    elif bulk_operation == "Delete":
                        st.caption(
                            "Criteria: Only Id field is required for bulk deletion."
                        )

                    confirm_bulk = st.checkbox(
                        f"I confirm bulk {bulk_operation.lower()} operation on {bulk_object}",
                        key=f"confirm_bulk_{bulk_object}_{bulk_operation}"
                    )

                    proceed_bulk = st.button(
                        f"🚀 Proceed Bulk {bulk_operation}",
                        disabled=not confirm_bulk,
                        key=f"proceed_bulk_{bulk_object}_{bulk_operation}"
                    )

                    if proceed_bulk:
                        try:
                            progress_bar = st.progress(0)
                            status_placeholder = st.empty()

                            with st.spinner(
                                f"Running bulk {bulk_operation.lower()}..."
                            ):
                                results = run_bulk_operation_with_progress(
                                    sf=sf,
                                    object_name=bulk_object,
                                    operation=bulk_operation,
                                    records=bulk_records,
                                    batch_size=200,
                                    progress_bar=progress_bar,
                                    status_placeholder=status_placeholder
                                )

                            progress_bar.progress(1.0)

                            success_count, failure_count, failed_rows = (
                                summarize_bulk_results(results)
                            )

                            st.subheader("📊 Bulk Operation Summary")

                            st.write(f"**Object:** {bulk_object}")
                            st.write(f"**Operation:** {bulk_operation}")
                            st.write(f"**Total records submitted:** {len(bulk_records)}")
                            st.write(f"**Successful records:** {success_count}")
                            st.write(f"**Failed records:** {failure_count}")

                            if success_count:
                                st.success(
                                    f"✅ Bulk {bulk_operation.lower()} completed: "
                                    f"{success_count} record(s) succeeded."
                                )

                            if failure_count:
                                st.error(
                                    f"❌ Bulk {bulk_operation.lower()} completed with "
                                    f"{failure_count} failed record(s)."
                                )

                                failed_df = pd.DataFrame(failed_rows)

                                st.subheader("❌ Failed Records")

                                ROW_PX = 35
                                HEADER_PX = 38
                                dynamic_height = max(HEADER_PX + ROW_PX * len(failed_df), 120)
                                dynamic_height = min(dynamic_height, 650)

                                st.dataframe(failed_df, width="stretch", height=dynamic_height)

                                failed_csv = failed_df.to_csv(index=False)

                                st.download_button(
                                    label="⬇️ Download Failed Records",
                                    data=failed_csv,
                                    file_name=(
                                        f"failed_bulk_"
                                        f"{bulk_operation.lower()}_"
                                        f"{bulk_object}.csv"
                                    ),
                                    mime="text/csv"
                                )

                            if failure_count == 0:
                                st.success("🎉 All records processed successfully.")

                        except Exception as e:
                            show_error(f"Bulk {bulk_operation} failed", e)

    except Exception as e:
        show_error("CSV processing failed", e)