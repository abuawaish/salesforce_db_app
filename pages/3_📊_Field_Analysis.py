import streamlit as st
import pandas as pd
import plotly.express as px
from collections import Counter


# ------------------------------------------------------------
# Page Configuration
# ------------------------------------------------------------
st.set_page_config(
    page_title="Field Analysis", 
    page_icon="📊", 
    layout="wide",
    initial_sidebar_state="auto"
)

# ------------------------------------------------------------
# Check connection
# ------------------------------------------------------------
if "sf" not in st.session_state or not st.session_state.get("config_ok"):
    st.warning("Please configure your Salesforce connection first (⚙️ Configuration page).")
    st.info(
        "💡 **What this page does:** once connected, inspect any Salesforce "
        "object's field metadata — data types, required fields, picklist "
        "values, and relationships — so you know exactly what's available "
        "before you write a query or build an integration."
    )
    st.stop()

sf = st.session_state["sf"]

st.title("📊 Field Analysis")
st.caption("Inspect Salesforce object field metadata and relationships.")

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

# ------------------------------------------------------------
# Session-state caches (persist across page navigation)
# ------------------------------------------------------------
# Describe results keyed by object name — fetched once, reused instantly.
if "fa_describe_cache" not in st.session_state:
    st.session_state["fa_describe_cache"] = {}

# Global object list — fetched once per session.
if "fa_all_objects" not in st.session_state:
    st.session_state["fa_all_objects"] = sorted(
        obj["name"] for obj in sf.describe()["sobjects"]
    )

# ------------------------------------------------------------
# Helper functions
# ------------------------------------------------------------
def get_object_metadata(object_name):
    """Return describe result from cache; only hits the API on first call."""
    cache = st.session_state["fa_describe_cache"]
    if object_name not in cache:
        cache[object_name] = sf.__getattr__(object_name).describe()
    return cache[object_name]


def compute_stats(describe_result):
    fields = describe_result["fields"]
    child_rels = describe_result.get("childRelationships", [])

    total_fields = len(fields)
    relationships = [f for f in fields if f["type"] == "reference" and f.get("relationshipName")]
    custom_fields = [f for f in fields if f["name"].endswith("__c")]
    required_fields = [f for f in fields if f.get("nillable") == False]
    child_relations = [cr for cr in child_rels if cr.get("childSObject")]

    type_counts = Counter(f["type"] for f in fields)
    field_types_df = pd.DataFrame(list(type_counts.items()), columns=["Field Type", "Count"])

    standard_fields = total_fields - len(custom_fields)
    unique_fields = [f for f in fields if f.get("unique", False)]
    lookup_fields = [
        f for f in fields
        if f["type"] == "reference" and f.get("relationshipName") and not f.get("calculated", False)
    ]
    formula_fields = [f for f in fields if f["type"] in ["formula", "summary", "calculated"]]

    stats_for_bar = {
        "Custom": len(custom_fields),
        "Standard": standard_fields,
        "Required": len(required_fields),
        "Unique": len(unique_fields),
        "Lookup": len(lookup_fields),
        "Formula": len(formula_fields),
    }

    return {
        "total_fields": total_fields,
        "relationships": len(relationships),
        "custom_fields": len(custom_fields),
        "required_fields": len(required_fields),
        "child_relations": len(child_relations),
        "field_types_df": field_types_df,
        "stats_for_bar": stats_for_bar,
    }


# ------------------------------------------------------------
# History state helpers
# ------------------------------------------------------------
def _default_analysis_state():
    return {
        "object": "-- Select an object to analyze --",
        "picklist": "-- Select a picklist field --",
    }


def ensure_widget_state(key, default_value):
    if key not in st.session_state:
        st.session_state[key] = default_value


def init_history_state():
    if "history_stack" not in st.session_state:
        st.session_state.history_stack = []
    if "future_stack" not in st.session_state:
        st.session_state.future_stack = []
    if "field_analysis_state" not in st.session_state:
        st.session_state.field_analysis_state = _default_analysis_state()
    if "field_analysis_last_state" not in st.session_state:
        st.session_state.field_analysis_last_state = st.session_state.field_analysis_state.copy()
    if "field_analysis_object" not in st.session_state:
        st.session_state.field_analysis_object = st.session_state.field_analysis_state["object"]
    if "field_analysis_picklist" not in st.session_state:
        st.session_state.field_analysis_picklist = st.session_state.field_analysis_state["picklist"]


def push_history_state(state):
    if not state or state.get("object") == "-- Select an object to analyze --":
        return
    if not st.session_state.history_stack or st.session_state.history_stack[-1] != state:
        st.session_state.history_stack.append(state.copy())
        if len(st.session_state.history_stack) > 50:
            st.session_state.history_stack = st.session_state.history_stack[-50:]


def on_object_change():
    if st.session_state.get("suppress_history", False):
        return

    current_state = st.session_state.field_analysis_state.copy()
    new_object = st.session_state.field_analysis_object

    if new_object != current_state["object"]:
        if current_state["object"] != "-- Select an object to analyze --":
            push_history_state(current_state)
            st.session_state.future_stack.clear()

        new_state = {
            "object": new_object,
            "picklist": "-- Select a picklist field --",
        }
        st.session_state.field_analysis_state = new_state
        st.session_state.field_analysis_picklist = new_state["picklist"]
        st.session_state.field_analysis_last_state = new_state.copy()


def on_picklist_change():
    if st.session_state.get("suppress_history", False):
        return

    current_state = st.session_state.field_analysis_state.copy()
    new_picklist = st.session_state.field_analysis_picklist

    if new_picklist != current_state["picklist"]:
        if current_state["object"] != "-- Select an object to analyze --":
            push_history_state(current_state)
            st.session_state.future_stack.clear()

        st.session_state.field_analysis_state = {
            "object": current_state["object"],
            "picklist": new_picklist,
        }
        st.session_state.field_analysis_last_state = st.session_state.field_analysis_state.copy()


def _set_analysis_state(target_state):
    st.session_state.suppress_history = True
    try:
        st.session_state.field_analysis_state = target_state.copy()
        st.session_state.field_analysis_object = target_state["object"]
        st.session_state.field_analysis_picklist = target_state["picklist"]
        st.session_state.field_analysis_last_state = target_state.copy()
    finally:
        st.session_state.suppress_history = False


def go_back():
    if not st.session_state.history_stack:
        return
    current_state = st.session_state.field_analysis_state.copy()
    target_state = st.session_state.history_stack.pop()
    st.session_state.future_stack.append(current_state)
    _set_analysis_state(target_state)


def go_forward():
    if not st.session_state.future_stack:
        return
    current_state = st.session_state.field_analysis_state.copy()
    target_state = st.session_state.future_stack.pop()
    st.session_state.history_stack.append(current_state)
    _set_analysis_state(target_state)


# ------------------------------------------------------------
# Object selection
# ------------------------------------------------------------
init_history_state()
ensure_widget_state("field_analysis_object", st.session_state.field_analysis_state["object"])
ensure_widget_state("field_analysis_picklist", st.session_state.field_analysis_state["picklist"])

object_options = ["-- Select an object to analyze --"] + st.session_state["fa_all_objects"]

selected_object = st.selectbox(
    "Select an object to analyze",
    options=object_options,
    key="field_analysis_object",
    on_change=on_object_change,
    help="Choose any Salesforce object (standard or custom)."
)

button_col1, button_col2, button_col3 = st.columns([1, 1, 6])
with button_col1:
    st.button("⬅ Back", on_click=go_back, disabled=not st.session_state.history_stack)
with button_col2:
    st.button("➡ Forward", on_click=go_forward, disabled=not st.session_state.future_stack)
with button_col3:
    st.caption(f"History: {len(st.session_state.history_stack)} back / {len(st.session_state.future_stack)} forward")

# ------------------------------------------------------------
# Load and display stats only if a real object is selected
# ------------------------------------------------------------
if selected_object and selected_object != "-- Select an object to analyze --":
    already_cached = selected_object in st.session_state["fa_describe_cache"]
    try:
        # Show spinner only on first fetch; cached objects render instantly.
        if not already_cached:
            with st.spinner(f"Fetching metadata for **{selected_object}**..."):
                describe = get_object_metadata(selected_object)
        else:
            describe = get_object_metadata(selected_object)

        stats = compute_stats(describe)
        fields = describe["fields"]

        # ---- Key metrics ----
        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("Total Fields", stats["total_fields"])
        col2.metric("Relationships", stats["relationships"])
        col3.metric("Custom Fields", stats["custom_fields"])
        col4.metric("Required Fields", stats["required_fields"])
        col5.metric("Child Relations", stats["child_relations"])

        st.divider()

        # ---- Charts ----
        chart_col1, chart_col2 = st.columns(2)

        with chart_col1:
            st.subheader("📈 Field Type Distribution")
            fig_pie = px.pie(
                stats["field_types_df"],
                values="Count",
                names="Field Type",
                title=f"Field Types in {selected_object}",
                color_discrete_sequence=px.colors.qualitative.Set3,
                hole=0.3,
            )
            fig_pie.update_layout(
                template="plotly_dark",
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="white"),
                margin=dict(l=20, r=20, t=40, b=20),
            )
            st.plotly_chart(fig_pie, width='stretch')

        with chart_col2:
            st.subheader("📊 Field Statistics")
            stats_df = pd.DataFrame(
                list(stats["stats_for_bar"].items()),
                columns=["Category", "Count"]
            )
            fig_bar = px.bar(
                stats_df,
                x="Category",
                y="Count",
                title="Field Stats",
                color="Category",
                color_discrete_sequence=px.colors.qualitative.Pastel,
                text="Count",
            )
            fig_bar.update_traces(textposition="outside")
            fig_bar.update_layout(
                template="plotly_dark",
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="white"),
                xaxis=dict(title=""),
                yaxis=dict(title="Count"),
                margin=dict(l=20, r=20, t=40, b=20),
                showlegend=False,
            )
            st.plotly_chart(fig_bar, width='stretch')

        # ---- Field details table ----
        with st.expander("📋 View All Fields (Detailed)"):
            fields_df = pd.DataFrame([
                {
                    "Field Name": f["name"],
                    "Label": f["label"],
                    "Type": f["type"],
                    "Required": not f.get("nillable", True),
                    "Unique": f.get("unique", False),
                    "Custom": "✅" if f["name"].endswith("__c") else "",
                    "Relationship": f.get("relationshipName", ""),
                }
                for f in fields
            ])
            st.dataframe(fields_df, width="stretch", height=400)

        # ============================================================
        # Picklist Exporter
        # ============================================================
        st.divider()
        st.subheader("📋 Picklist Exporter")

        picklist_fields = [f for f in fields if f["type"] in ["picklist", "multipicklist"]]

        if not picklist_fields:
            st.info(f"ℹ️ No picklist fields found on {selected_object}.")
        else:
            st.metric("Total Picklist Fields", len(picklist_fields))

            picklist_options = {f["name"]: f"{f['name']} ({f['label']})" for f in picklist_fields}
            picklist_options_with_placeholder = ["-- Select a picklist field --"] + list(picklist_options.keys())

            selected_picklist = st.selectbox(
                "Select a picklist field to view its values",
                options=picklist_options_with_placeholder,
                key="field_analysis_picklist",
                on_change=on_picklist_change,
                format_func=lambda x: picklist_options[x] if x in picklist_options else x,
                help="Choose a picklist field to see all allowed values."
            )

            if selected_picklist and selected_picklist != "-- Select a picklist field --":
                with st.spinner(f"Loading values for **{picklist_options.get(selected_picklist, selected_picklist)}**..."):
                    field_describe = next(f for f in picklist_fields if f["name"] == selected_picklist)
                    picklist_values = field_describe.get("picklistValues", [])

                if picklist_values:
                    values_df = pd.DataFrame([
                        {
                            "Label": val["label"],
                            "Value": val["value"],
                            "Active": val.get("active", True),
                            "Default": val.get("defaultValue", False),
                        }
                        for val in picklist_values
                    ])

                    ROW_PX, HEADER_PX = 35, 38
                    dynamic_height = min(max(HEADER_PX + ROW_PX * len(values_df), 120), 650)

                    st.dataframe(values_df, width="stretch", height=dynamic_height)
                    st.caption(f"Showing {len(picklist_values)} values.")
                else:
                    st.info("This picklist has no defined values (or it is a global picklist).")
            else:
                st.info("👈 **Please select a picklist field from the dropdown above to view its values.**")

    except Exception as e:
        st.error(f"❌ Failed to analyze object: {e}")
        st.code(str(e), language="text")
else:
    st.info("👈 **Please select an object from the dropdown above to begin the analysis.**")