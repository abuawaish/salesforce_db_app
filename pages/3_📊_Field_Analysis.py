import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from collections import Counter


# ------------------------------------------------------------
# Page Configuration
# ------------------------------------------------------------
st.set_page_config(
    page_title="Field Analysis", 
    page_icon="📊", 
    layout="centered",
    initial_sidebar_state="expanded"
)

# ------------------------------------------------------------
# Check connection
# ------------------------------------------------------------
if "sf" not in st.session_state or not st.session_state.get("config_ok"):
    st.warning("Please configure your Salesforce connection first (⚙️ Configuration page).")
    st.stop()

sf = st.session_state["sf"]

# ------------------------------------------------------------
# Helper functions
# ------------------------------------------------------------
def get_object_metadata(object_name):
    """Fetch full describe result for an object."""
    return sf.__getattr__(object_name).describe()

def compute_stats(describe_result):
    """
    Compute all statistics from the describe result.
    Returns a dict with keys: total_fields, relationships, custom_fields,
    required_fields, child_relations, field_types, stats_for_bar.
    """
    fields = describe_result["fields"]
    child_rels = describe_result.get("childRelationships", [])

    # Total fields
    total_fields = len(fields)

    # Relationships: fields of type 'reference' that have a relationshipName
    relationships = [f for f in fields if f["type"] == "reference" and f.get("relationshipName")]
    total_relationships = len(relationships)

    # Custom fields: end with '__c'
    custom_fields = [f for f in fields if f["name"].endswith("__c")]
    total_custom = len(custom_fields)

    # Required fields: nillable == False
    required_fields = [f for f in fields if f.get("nillable") == False]
    total_required = len(required_fields)

    # Child relations
    child_relations = [cr for cr in child_rels if cr.get("childSObject")]
    total_child_relations = len(child_relations)

    # Field type distribution (for pie chart)
    type_counts = Counter(f["type"] for f in fields)
    field_types_df = pd.DataFrame(list(type_counts.items()), columns=["Field Type", "Count"])

    # Bar chart statistics: Custom, Standard, Required, Unique, Lookup, Formula
    standard_fields = total_fields - total_custom
    unique_fields = [f for f in fields if f.get("unique", False)]
    total_unique = len(unique_fields)
    # Lookup fields: reference type but NOT master-detail
    lookup_fields = [f for f in fields if f["type"] == "reference" and f.get("relationshipName") and not f.get("calculated", False)]
    total_lookup = len(lookup_fields)
    # Formula fields: type 'formula' or 'summary' or 'calculated'
    formula_fields = [f for f in fields if f["type"] in ["formula", "summary", "calculated"]]
    total_formula = len(formula_fields)

    stats_for_bar = {
        "Custom": total_custom,
        "Standard": standard_fields,
        "Required": total_required,
        "Unique": total_unique,
        "Lookup": total_lookup,
        "Formula": total_formula,
    }

    return {
        "total_fields": total_fields,
        "relationships": total_relationships,
        "custom_fields": total_custom,
        "required_fields": total_required,
        "child_relations": total_child_relations,
        "field_types_df": field_types_df,
        "stats_for_bar": stats_for_bar,
    }

# ------------------------------------------------------------
# Object selection with placeholder
# ------------------------------------------------------------
all_objects = [obj["name"] for obj in sf.describe()["sobjects"]]
all_objects_sorted = sorted(all_objects)

object_options = ["-- Select an object to analyze --"] + all_objects_sorted

selected_object = st.selectbox(
    "Select an object to analyze",
    options=object_options,
    index=0,
    help="Choose any Salesforce object (standard or custom)."
)

# ------------------------------------------------------------
# Load and display stats only if a real object is selected
# ------------------------------------------------------------
if selected_object and selected_object != "-- Select an object to analyze --":
    with st.spinner(f"Fetching metadata for {selected_object}..."):
        try:
            describe = get_object_metadata(selected_object)
            stats = compute_stats(describe)
            fields = describe["fields"]

            # ---- Display key metrics in columns ----
            col1, col2, col3, col4, col5 = st.columns(5)
            col1.metric("Total Fields", stats["total_fields"])
            col2.metric("Relationships", stats["relationships"])
            col3.metric("Custom Fields", stats["custom_fields"])
            col4.metric("Required Fields", stats["required_fields"])
            col5.metric("Child Relations", stats["child_relations"])

            st.divider()

            # ---- Charts ----
            chart_col1, chart_col2 = st.columns(2)

            # Pie chart: Field Type Distribution
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

            # Bar chart: Field Statistics
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
                    title="Custom, Standard, Required, Unique, Lookup, Formula",
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

            # ---- Optional: show field details in a table (collapsible) ----
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

            # Filter fields that are picklist or multipicklist
            picklist_fields = [f for f in fields if f["type"] in ["picklist", "multipicklist"]]

            if not picklist_fields:
                st.info(f"ℹ️ No picklist fields found on {selected_object}.")
            else:
                # Show total count
                st.metric("Total Picklist Fields", len(picklist_fields))

                # 🔥 NEW: Add placeholder for picklist dropdown
                picklist_options = {f["name"]: f"{f['name']} ({f['label']})" for f in picklist_fields}
                picklist_names = list(picklist_options.keys())

                # Add placeholder at the beginning
                picklist_options_with_placeholder = ["-- Select a picklist field --"] + picklist_names

                selected_picklist = st.selectbox(
                    "Select a picklist field to view its values",
                    options=picklist_options_with_placeholder,
                    index=0,
                    format_func=lambda x: picklist_options[x] if x in picklist_options else x,
                    help="Choose a picklist field to see all allowed values."
                )

                # Only show values if a real picklist is selected
                if selected_picklist and selected_picklist != "-- Select a picklist field --":
                    # Find the field describe
                    field_describe = next(f for f in picklist_fields if f["name"] == selected_picklist)
                    picklist_values = field_describe.get("picklistValues", [])

                    if picklist_values:
                        # Create a dataframe of values with their label and if they are active
                        values_df = pd.DataFrame([
                            {
                                "Label": val["label"],
                                "Value": val["value"],
                                "Active": val.get("active", True),
                                "Default": val.get("defaultValue", False),
                            }
                            for val in picklist_values
                        ])
                        st.dataframe(values_df, width="stretch", height=300)
                        st.caption(f"Showing {len(picklist_values)} values.")
                    else:
                        st.info("This picklist has no defined values (or it is a global picklist).")
                else:
                    st.info("👈 **Please select a picklist field from the dropdown above to view its values.**")

        except Exception as e:
            st.error(f"❌ Failed to analyze object: {e}")
            st.code(str(e), language="text")
else:
    # Show a prompt when no object is selected
    st.info("👈 **Please select an object from the dropdown above to begin the analysis.**")