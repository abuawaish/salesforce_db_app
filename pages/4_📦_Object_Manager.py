import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Tuple
import pandas as pd
import streamlit as st
from permissions import require_admin_mode

# ------------------------------------------------------------
# Page Configuration
# ------------------------------------------------------------

st.set_page_config(
    page_title="Object Manager",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="auto",
)

# ------------------------------------------------------------
# Connection check
# ------------------------------------------------------------
if "sf" not in st.session_state or not st.session_state.get("config_ok"):
    st.warning("Please configure your Salesforce connection first (⚙️ Configuration page).")
    st.info(
        "💡 **What this page does:** once connected, browse every "
        "Salesforce object, drill into its existing fields, and create new "
        "custom fields directly from here. Since this page can change your "
        "org's schema, it also requires your connected user to have real "
        "admin permissions in Salesforce."
    )
    st.stop()

# ------------------------------------------------------------
# Permission check — this page performs schema changes, so it's
# gated on the connected user's REAL Salesforce permissions plus
# an explicit Admin-mode opt-in (see permissions.py).
# ------------------------------------------------------------
require_admin_mode("Object Manager")

sf = st.session_state["sf"]

# ----------------------------------------------------------------
# Session-state caches (shared with other pages)
# ----------------------------------------------------------------
# No eager loading – objects are fetched on demand via get_all_objects()
# Describe cache is initialised empty; it fills as objects are accessed.
if "fa_describe_cache" not in st.session_state:
    st.session_state["fa_describe_cache"] = {}

# Global object list is not pre‑fetched – will be loaded lazily
# We just ensure the key exists (it may be missing initially).
if "fa_all_objects" not in st.session_state:
    st.session_state["fa_all_objects"] = None  # placeholder; will be populated on demand

# ------------------------------------------------------------
# Constants
# ------------------------------------------------------------
FIELD_TYPE_OPTIONS: Dict[str, Dict[str, Any]] = {
    "Text": {"metadata_type": "Text", "supports_length": True},
    "Long Text Area": {"metadata_type": "LongTextArea", "supports_length": True},
    "Number": {"metadata_type": "Number", "supports_precision": True, "supports_scale": True},
    "Currency": {"metadata_type": "Currency", "supports_precision": True, "supports_scale": True},
    "Percent": {"metadata_type": "Percent", "supports_precision": True, "supports_scale": True},
    "Date": {"metadata_type": "Date"},
    "Date/Time": {"metadata_type": "DateTime"},
    "Checkbox": {"metadata_type": "Checkbox"},
    "Picklist": {"metadata_type": "Picklist", "supports_picklist": True},
    "Multi-Select Picklist": {"metadata_type": "MultiselectPicklist", "supports_picklist": True},
    "Email": {"metadata_type": "Email"},
    "Phone": {"metadata_type": "Phone"},
    "URL": {"metadata_type": "Url"},
}

FIELD_TYPE_LABELS = list(FIELD_TYPE_OPTIONS.keys())

# ------------------------------------------------------------
# FLS / Object-permission grant limits
# ------------------------------------------------------------
# Each Profile selected for a grant costs one Profile.read() + one
# Profile.update() Metadata API call, which counts against the org's
# daily Metadata API limit. These caps keep a single submission from
# silently burning through a large chunk of that limit. Profile reads
# are also heavier than Permission Set reads (a Profile carries a lot
# more metadata), so keep an eye on this if the cap is ever raised.
MAX_PROFILES_PER_GRANT = 5             # hard cap enforced per picker widget
WARN_TOTAL_METADATA_CALLS_AT = 15      # soft warning threshold, shown pre-submit
CUSTOM_SUFFIX = "__c"
API_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


# ------------------------------------------------------------
# Notification helpers (auto‑dismiss via toast)
# ------------------------------------------------------------
def notify_success(msg: str) -> None:
    st.toast(msg, icon="✅")


def notify_error(msg: str) -> None:
    st.toast(msg, icon="❌")


def notify_warning(msg: str) -> None:
    st.toast(msg, icon="⚠️")


def notify_info(msg: str) -> None:
    st.toast(msg, icon="ℹ️")


# ------------------------------------------------------------
# Session state for dynamic field rows
# ------------------------------------------------------------
def init_state() -> None:
    if "create_field_row_ids" not in st.session_state:
        st.session_state.create_field_row_ids = [0, 1]  # two rows by default
    if "create_field_next_id" not in st.session_state:
        st.session_state.create_field_next_id = 2


init_state()


# ------------------------------------------------------------
# Utility helpers
# ------------------------------------------------------------
def ensure_custom_suffix(value: str) -> str:
    value = value.strip()
    if not value.endswith(CUSTOM_SUFFIX):
        value = f"{value}{CUSTOM_SUFFIX}"
    return value


def validate_custom_api_name(value: str, label: str) -> str:
    value = ensure_custom_suffix(value)
    base_name = value[:-3]

    if not base_name:
        raise ValueError(f"{label} is required.")

    if not API_NAME_PATTERN.match(base_name):
        raise ValueError(
            f"{label} must start with a letter and contain only letters, numbers, and underscores."
        )

    return value


def derive_label_from_api_name(api_name: str) -> str:
    cleaned = api_name.replace(CUSTOM_SUFFIX, "").strip("_")
    cleaned = re.sub(r"_+", " ", cleaned)
    return cleaned.title() if cleaned else "Custom Field"


def parse_picklist_values(raw: str) -> List[str]:
    values = [item.strip() for item in raw.split(",") if item.strip()]
    if not values:
        raise ValueError("Picklist values cannot be empty for Picklist or Multi-Select Picklist fields.")
    return values


def to_serializable(obj: Any) -> Any:
    """Serialize zeep/SOAP objects, dicts, lists, and primitives recursively."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, list):
        return [to_serializable(item) for item in obj]
    if isinstance(obj, tuple):
        return [to_serializable(item) for item in obj]
    if isinstance(obj, dict):
        return {key: to_serializable(value) for key, value in obj.items()}

    # 1. Zeep objects (sf.mdapi returns zeep CompoundValue / ValueList)
    try:
        from zeep.helpers import serialize_object
        zeep_serialized = serialize_object(obj)
        if zeep_serialized is not obj:
            return to_serializable(zeep_serialized)
    except Exception:
        pass

    # 2. Plain Python objects (__dict__)
    try:
        if hasattr(obj, "__dict__"):
            d = vars(obj)
            if d:
                return {
                    key: to_serializable(value)
                    for key, value in d.items()
                    if not key.startswith("_")
                }
    except TypeError:
        pass

    # 3. Deep fallback: iterate dir()
    result: Dict[str, Any] = {}
    for key in dir(obj):
        if key.startswith("_"):
            continue
        try:
            val = getattr(obj, key)
            if callable(val):
                continue
            result[key] = to_serializable(val)
        except Exception:
            pass
    if result:
        return result

    return str(obj)


# ------------------------------------------------------------
# Core data access (lazy loading)
# ------------------------------------------------------------
def get_all_objects(custom_only: bool = False) -> List[str]:
    """
    Return object names from the session cache – fetches once and caches.
    Uses lazy loading: only calls sf.describe() when this function is first called.
    """
    # If the cache is empty or None, fetch the object list
    if "fa_all_objects" not in st.session_state or st.session_state["fa_all_objects"] is None:
        try:
            st.session_state["fa_all_objects"] = sorted(
                obj["name"] for obj in sf.describe()["sobjects"]
            )
        except Exception as exc:
            st.error(f"Unable to load Salesforce objects: {exc}")
            return []

    names = st.session_state["fa_all_objects"]
    if custom_only:
        names = [name for name in names if name.endswith(CUSTOM_SUFFIX)]
    return names


def get_object_fields(object_name: str) -> List[Dict[str, Any]]:
    """
    Fetch fields via REST describe() (cached) and enrich with Metadata API
    custom fields if needed.
    """
    # Ensure describe cache exists
    if "fa_describe_cache" not in st.session_state:
        st.session_state["fa_describe_cache"] = {}

    fields: List[Dict[str, Any]] = []

    # 1. Primary source: REST API describe
    try:
        cache = st.session_state["fa_describe_cache"]
        if object_name not in cache:
            cache[object_name] = getattr(sf, object_name).describe()
        fields = list(cache[object_name].get("fields", []))
    except Exception as exc:
        notify_warning(f"REST describe failed for {object_name}: {exc}")

    # 2. Enrich / backfill with Metadata API custom fields
    #    (REST describe can lag behind Metadata API creation)
    try:
        rest_custom_names = {f.get("name") for f in fields if f.get("name", "").endswith("__c")}
        obj_meta = sf.mdapi.CustomObject.read(object_name)
        md_fields = getattr(obj_meta, "fields", None)

        if md_fields:
            if not isinstance(md_fields, list):
                md_fields = [md_fields]

            for md_field in md_fields:
                full_name = getattr(md_field, "fullName", "")
                if full_name and full_name.endswith("__c") and full_name not in rest_custom_names:
                    fields.append(
                        {
                            "name": full_name,
                            "label": getattr(md_field, "label", full_name),
                            "type": getattr(md_field, "type", "Unknown"),
                            "nillable": not getattr(md_field, "required", False),
                            "unique": getattr(md_field, "unique", False),
                            "custom": True,
                        }
                    )
    except Exception:
        pass  # Metadata API may fail for standard objects; that's fine

    return fields


def clear_row_widget_state(row_id: int) -> None:
    keys = [
        f"create_field_name_{row_id}",
        f"create_field_label_{row_id}",
        f"create_field_type_{row_id}",
        f"create_field_length_{row_id}",
        f"create_field_precision_{row_id}",
        f"create_field_scale_{row_id}",
        f"create_field_picklist_{row_id}",
    ]
    for key in keys:
        st.session_state.pop(key, None)


def add_create_field_row() -> None:
    row_id = st.session_state.create_field_next_id
    st.session_state.create_field_row_ids.append(row_id)
    st.session_state.create_field_next_id += 1


def remove_last_create_field_row() -> None:
    if len(st.session_state.create_field_row_ids) <= 1:
        return
    removed = st.session_state.create_field_row_ids.pop()
    clear_row_widget_state(removed)


def collect_create_field_specs() -> List[Dict[str, Any]]:
    collected: List[Dict[str, Any]] = []
    seen_names = set()

    for row_id in st.session_state.create_field_row_ids:
        raw_name = st.session_state.get(f"create_field_name_{row_id}", "").strip()
        raw_label = st.session_state.get(f"create_field_label_{row_id}", "").strip()
        ui_type = st.session_state.get(f"create_field_type_{row_id}", "")

        if not raw_name and not raw_label:
            continue

        if not ui_type:
            raise ValueError(f"Please select a field type for row {row_id + 1}.")

        api_name = validate_custom_api_name(raw_name, "Field API Name")
        if api_name.lower() in seen_names:
            raise ValueError(f"Duplicate field API name found: {api_name}")
        seen_names.add(api_name.lower())

        metadata_info = FIELD_TYPE_OPTIONS[ui_type]
        field_spec: Dict[str, Any] = {
            "api_name": api_name,
            "label": raw_label or derive_label_from_api_name(api_name),
            "ui_type": ui_type,
            "metadata_type": metadata_info["metadata_type"],
        }

        if metadata_info.get("supports_length"):
            length_value = int(st.session_state.get(f"create_field_length_{row_id}", 255))
            if length_value <= 0:
                raise ValueError(f"Length must be greater than 0 for field {api_name}.")
            field_spec["length"] = length_value

        if metadata_info.get("supports_precision"):
            precision = int(st.session_state.get(f"create_field_precision_{row_id}", 18))
            scale = int(st.session_state.get(f"create_field_scale_{row_id}", 2))
            if precision <= 0:
                raise ValueError(f"Precision must be greater than 0 for field {api_name}.")
            if scale < 0:
                raise ValueError(f"Scale cannot be negative for field {api_name}.")
            if scale > precision:
                raise ValueError(f"Scale cannot be greater than precision for field {api_name}.")
            field_spec["precision"] = precision
            field_spec["scale"] = scale

        if metadata_info.get("supports_picklist"):
            picklist_raw = st.session_state.get(f"create_field_picklist_{row_id}", "")
            field_spec["picklist_values"] = parse_picklist_values(picklist_raw)

        collected.append(field_spec)

    return collected


# ------------------------------------------------------------
# Salesforce Metadata API wrappers
# ------------------------------------------------------------
def build_picklist_value_set(mdapi: Any, values: List[str]) -> Any:
    custom_values = [
        mdapi.CustomValue(
            fullName=value,
            default=(index == 0),
            label=value,
            isActive=True,
        )
        for index, value in enumerate(values)
    ]

    return mdapi.ValueSet(
        restricted=True,
        valueSetDefinition=mdapi.ValueSetValuesDefinition(
            sorted=False,
            value=custom_values,
        ),
    )


def build_custom_field_metadata(mdapi: Any, object_api_name: str, field_spec: Dict[str, Any]) -> Any:
    metadata_type = field_spec["metadata_type"]
    kwargs: Dict[str, Any] = {
        "fullName": f"{object_api_name}.{field_spec['api_name']}",
        "label": field_spec["label"],
        "type": metadata_type,
        "required": False,
    }

    if metadata_type == "Text":
        kwargs["length"] = field_spec.get("length", 255)

    elif metadata_type == "LongTextArea":
        kwargs["length"] = field_spec.get("length", 32768)
        kwargs["visibleLines"] = 3

    elif metadata_type in {"Number", "Currency", "Percent"}:
        kwargs["precision"] = field_spec.get("precision", 18)
        kwargs["scale"] = field_spec.get("scale", 2)

    elif metadata_type == "Checkbox":
        kwargs["defaultValue"] = "false"

    elif metadata_type in {"Picklist", "MultiselectPicklist"}:
        kwargs["valueSet"] = build_picklist_value_set(mdapi, field_spec["picklist_values"])
        if metadata_type == "MultiselectPicklist":
            kwargs["visibleLines"] = 3

    return mdapi.CustomField(**kwargs)


# ------------------------------------------------------------
# Field-Level Security (FLS) helpers — Profile based
# ------------------------------------------------------------
def _resolve_profile_fullname(profile_id: str, fallback_label: str) -> str:
    """
    Resolve a Profile's Metadata API developer name (FullName) via the
    Tooling API. Standard SOQL only exposes Profile.Name as the display
    LABEL (e.g. "System Administrator") — the Metadata API's Profile.read()
    needs the developer name instead (e.g. "Admin"), and they only match
    for custom profiles. The Tooling API's Profile object exposes the real
    FullName, but Salesforce restricts any query selecting FullName to a
    single row, so this must be resolved one profile at a time.

    Falls back to the label if the lookup fails, which is only actually
    correct for custom profiles — a failed lookup on a standard profile
    will surface later as a failed FLS/object-access grant with a clear
    profile name in the warning, rather than failing silently here.
    """
    try:
        result = sf.toolingexecute(
            "query/",
            params={"q": f"SELECT Id, FullName FROM Profile WHERE Id = '{profile_id}'"},
        )
        records = result.get("records", [])
        if records and records[0].get("FullName"):
            return records[0]["FullName"]
    except Exception:
        pass
    return fallback_label


def get_profiles() -> List[Dict[str, str]]:
    """
    Fetch Profiles (cached for the session), for use as an explicit picker
    when granting FLS on newly created fields. Each entry carries both the
    display `label` (Profile.Name, shown in the picker) and the real
    Metadata API `fullname` (used for every mdapi.Profile.read/update call).

    Resolving `fullname` costs one Tooling API call PER profile (see
    _resolve_profile_fullname), which is slow done sequentially in orgs
    with many profiles. These are independent, network-bound reads, so
    they're resolved concurrently via a thread pool instead — this is
    the main first-load latency this page has, so it's worth the
    parallelism. Result is cached for the rest of the session either way.
    """
    if st.session_state.get("fa_profiles") is None:
        profiles: List[Dict[str, str]] = []
        try:
            result = sf.query("SELECT Id, Name FROM Profile ORDER BY Name")
            records = result.get("records", [])
        except Exception:
            records = []

        if records:
            with st.spinner(f"Resolving {len(records)} Profile name(s) for FLS…"):
                with ThreadPoolExecutor(max_workers=min(10, len(records))) as executor:
                    future_to_record = {
                        executor.submit(_resolve_profile_fullname, r["Id"], r["Name"]): r
                        for r in records
                    }
                    resolved: Dict[str, str] = {}
                    for future in as_completed(future_to_record):
                        record = future_to_record[future]
                        try:
                            resolved[record["Id"]] = future.result()
                        except Exception:
                            resolved[record["Id"]] = record["Name"]

            # Thread completion order isn't the original alphabetical order —
            # rebuild the list in the original SELECT ... ORDER BY Name order.
            profiles = [
                {"id": r["Id"], "label": r["Name"], "fullname": resolved.get(r["Id"], r["Name"])}
                for r in records
            ]

        st.session_state["fa_profiles"] = profiles
    return st.session_state["fa_profiles"]


def _label_to_fullname_map() -> Dict[str, str]:
    """Build {display_label: metadata_fullname} from get_profiles()."""
    return {p["label"]: p["fullname"] for p in get_profiles()}


def get_profile_labels() -> List[str]:
    """Just the display labels, for simple picker widgets."""
    return [p["label"] for p in get_profiles()]


def assign_fls_to_profiles(
    object_api_name: str,
    field_api_names: List[str],
    profile_labels: List[str],
    visible: bool = True,
    read_only: bool = False,
) -> List[Tuple[str, str]]:
    """
    Set field-level security for one or more fields, across one or more
    Profiles, mirroring Salesforce's native "Set Field-Level Security"
    page:
        - Visible unchecked              -> not readable, not editable
        - Visible checked, Read-Only     -> readable, not editable
        - Visible checked, not Read-Only -> readable AND editable

    All of `field_api_names` get the SAME Visible/Read-Only setting in a
    single partial Profile update per Profile (fullName + one
    fieldPermissions entry per field) — Salesforce merges partial Profile
    updates incrementally (supported since API v35.0), so this only ever
    touches the specific field/Profile combinations listed here and
    leaves the rest of each Profile untouched.

    Each Profile is updated independently (not batched together in one
    call), so one Profile failing — e.g. a bad fullName — can never mask
    or block the grants for the other Profiles, and each failure keeps
    its own real Salesforce error message. A field created moments
    earlier can occasionally not be indexed yet, so each grant gets one
    short retry before being counted as a real failure.

    profile_labels are the display names shown in the picker (e.g.
    "System Administrator", "Read Only") — resolved here to each
    Profile's real Metadata API developer name via the Tooling-API-backed
    get_profiles() cache, rather than a hardcoded label->fullName table.
    Hardcoded tables are a real source of bugs: profile developer names
    are not guaranteed the same across every org/edition (e.g. "Read
    Only" is not always "ReadOnly").

    This only sets FIELD-level access. It does not grant object-level
    (CRUD) access — the selected Profile must already have Read access
    to the parent object for the field permission to take effect. Also
    note: Salesforce always gives the System Administrator profile full
    field access regardless of FLS settings, so granting/denying FLS on
    that profile specifically has no real effect.

    Returns a list of (profile_label, error_message) for any grants that
    failed after the retry.
    """
    if not profile_labels or not field_api_names:
        return []

    mdapi = sf.mdapi
    label_to_fullname = _label_to_fullname_map()
    readable = bool(visible)
    editable = bool(visible and not read_only)

    field_perms = [
        mdapi.ProfileFieldLevelSecurity(
            field=f"{object_api_name}.{field_api_name}",
            editable=editable,
            readable=readable,
        )
        for field_api_name in field_api_names
    ]

    failures: List[Tuple[str, str]] = []

    for profile_label in profile_labels:
        fullname = label_to_fullname.get(profile_label, profile_label)
        last_error = ""
        for attempt in range(2):
            try:
                partial_profile = mdapi.Profile(
                    fullName=fullname,
                    fieldPermissions=field_perms,
                )
                mdapi.Profile.update(partial_profile)
                last_error = ""
                break
            except Exception as exc:
                last_error = str(exc)
                if attempt == 0:
                    time.sleep(2)
        if last_error:
            failures.append((profile_label, last_error))

    return failures


def grant_object_level_security(
    object_api_name: str,
    profile_labels: List[str],
    allow_read: bool = True,
    allow_create: bool = True,
    allow_edit: bool = True,
    allow_delete: bool = False,
    view_all_records: bool = False,
    modify_all_records: bool = False,
) -> List[Tuple[str, str]]:
    """
    Ensure the given Profiles (by display label — resolved internally to
    the real Metadata API developer name, same as assign_fls_to_profiles)
    have object-level (CRUD) access to object_api_name. FLS alone does
    nothing if the Profile can't even see the object, so this is normally
    granted alongside FLS for brand-new custom objects.

    This reads the Profile first only to check whether it already has
    broader access than requested (e.g. Delete) so that access is never
    downgraded — but the read result itself is never written back. Only
    a PARTIAL Profile update (fullName + a single merged objectPermissions
    entry) is submitted, for the same reason described in
    assign_fls_to_profiles: writing back a Profile's entire metadata
    document risks opaque failures from unrelated sections.

    Returns a list of (profile_label, error_message) for any grants that
    failed after one retry.
    """
    mdapi = sf.mdapi
    label_to_fullname = _label_to_fullname_map()
    failures: List[Tuple[str, str]] = []

    for profile_label in profile_labels:
        fullname = label_to_fullname.get(profile_label, profile_label)
        last_error = ""
        for attempt in range(2):
            try:
                merged_read = allow_read
                merged_create = allow_create
                merged_edit = allow_edit
                merged_delete = allow_delete
                merged_view_all = view_all_records
                merged_modify_all = modify_all_records

                try:
                    existing = mdapi.Profile.read(fullname)
                    for op in (getattr(existing, "objectPermissions", None) or []):
                        if getattr(op, "object", None) == object_api_name:
                            merged_read = bool(getattr(op, "allowRead", False) or allow_read)
                            merged_create = bool(getattr(op, "allowCreate", False) or allow_create)
                            merged_edit = bool(getattr(op, "allowEdit", False) or allow_edit)
                            merged_delete = bool(getattr(op, "allowDelete", False) or allow_delete)
                            merged_view_all = bool(getattr(op, "viewAllRecords", False) or view_all_records)
                            merged_modify_all = bool(getattr(op, "modifyAllRecords", False) or modify_all_records)
                            break
                except Exception:
                    # If the inspect-only read fails, fall back to granting
                    # exactly what was requested rather than blocking the
                    # whole operation on a read problem.
                    pass

                partial_profile = mdapi.Profile(
                    fullName=fullname,
                    objectPermissions=[
                        mdapi.ProfileObjectPermissions(
                            object=object_api_name,
                            allowRead=merged_read,
                            allowCreate=merged_create,
                            allowEdit=merged_edit,
                            allowDelete=merged_delete,
                            viewAllRecords=merged_view_all,
                            modifyAllRecords=merged_modify_all,
                        )
                    ],
                )
                mdapi.Profile.update(partial_profile)
                last_error = ""
                break
            except Exception as exc:
                last_error = str(exc)
                if attempt == 0:
                    time.sleep(2)
        if last_error:
            failures.append((profile_label, last_error))

    return failures


def _format_grant_failures(failures: List[Tuple[str, str]]) -> str:
    """Render (profile_name, error_message) pairs as a readable bullet list."""
    lines = []
    for name, err in failures:
        err = (err or "Unknown error").strip()
        if len(err) > 300:
            err = err[:300] + "…"
        lines.append(f"- **{name}** — {err}")
    return "\n".join(lines)


def create_custom_object(
    object_api_name: str,
    object_label: str,
    plural_label: str,
    description: str,
    field_specs: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Creates the object, then creates each field ONE AT A TIME — not as a
    single batch array. Salesforce's createMetadata call validates each
    field independently, but simple-salesforce raises on the very first
    failure in a batch, which used to abort the whole handler even when
    the object (and possibly other valid fields) had already been created
    server-side, and skip FLS entirely as a result. Creating one at a time
    isolates each field's outcome so a bad field (e.g. duplicate picklist
    values) can never block the object or the other valid fields.

    Returns:
        {
            "created_fields": [api_name, ...],
            "failed_fields": [(api_name, error_message), ...],
        }
    FLS/object-access grants are handled by the caller using
    `created_fields`, not inside this function.
    """
    mdapi = sf.mdapi

    custom_object = mdapi.CustomObject(
        fullName=object_api_name,
        label=object_label,
        pluralLabel=plural_label,
        description=description or "",
        deploymentStatus="Deployed",
        sharingModel="ReadWrite",
        nameField=mdapi.CustomField(
            label="Name",
            type="Text",
            length=80,
        ),
    )

    mdapi.CustomObject.create(custom_object)

    created_fields: List[str] = []
    failed_fields: List[Tuple[str, str]] = []

    for spec in field_specs:
        try:
            field_metadata = build_custom_field_metadata(mdapi, object_api_name, spec)
            mdapi.CustomField.create(field_metadata)
            created_fields.append(spec["api_name"])
        except Exception as exc:
            failed_fields.append((spec["api_name"], str(exc)))

    return {
        "created_fields": created_fields,
        "failed_fields": failed_fields,
    }


def update_custom_field(
    object_name: str,
    field_name: str,
    new_label: str,
    new_description: str,
    new_help_text: str,
) -> None:
    mdapi = sf.mdapi
    full_name = f"{object_name}.{field_name}"

    existing_field = mdapi.CustomField.read(full_name)
    existing_field.label = new_label
    existing_field.description = new_description
    existing_field.inlineHelpText = new_help_text

    mdapi.CustomField.update(existing_field)


def delete_custom_field(object_name: str, field_name: str) -> None:
    sf.mdapi.CustomField.delete(f"{object_name}.{field_name}")


def read_custom_object_metadata(object_name: str) -> Any:
    return sf.mdapi.CustomObject.read(object_name)


def update_custom_object_metadata(
    object_name: str,
    new_label: str,
    new_plural_label: str,
    new_description: str,
    new_sharing_model: str,
    new_deployment_status: str,
) -> None:
    mdapi = sf.mdapi
    obj_meta = mdapi.CustomObject.read(object_name)
    obj_meta.label = new_label
    obj_meta.pluralLabel = new_plural_label
    obj_meta.description = new_description
    obj_meta.sharingModel = new_sharing_model
    obj_meta.deploymentStatus = new_deployment_status
    mdapi.CustomObject.update(obj_meta)


def delete_custom_object(object_name: str) -> None:
    sf.mdapi.CustomObject.delete(object_name)


def fetch_custom_objects_via_list_metadata() -> List[Any]:
    mdapi = sf.mdapi
    query = mdapi.ListMetadataQuery(type="CustomObject")
    return mdapi.list_metadata(query)


# ------------------------------------------------------------
# Page UI
# ------------------------------------------------------------
st.title("📦 Salesforce Object Manager")
st.caption("Create custom objects, manage custom fields, and perform metadata operations safely.")

# Refresh / Clear cache buttons
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

# Tabs
tabs = st.tabs(
    [
        "✨ Create Custom Object",
        "🔧 Manage Fields",
        "🛠️ Modify Custom Object",
    ]
)

# ============================================================
# TAB 1: Create Custom Object
# ============================================================
with tabs[0]:
    st.markdown('<div class="section-card"><h3>✨ Create Custom Object</h3>', unsafe_allow_html=True)

    # Object details
    col1, col2 = st.columns(2)
    with col1:
        obj_label = st.text_input(
            "Object Label *",
            placeholder="e.g., Invoice",
            help="The user-friendly name shown in page layouts and reports.",
            key="create_obj_label",
        )
        obj_api = st.text_input(
            "Object API Name *",
            placeholder="e.g., Invoice__c",
            help="Only letters, numbers, and underscores. __c is auto-appended if missing.",
            key="create_obj_api",
        )

    with col2:
        plural_label = st.text_input(
            "Plural Label *",
            placeholder="e.g., Invoices",
            help="Used in related lists and tab labels.",
            key="create_plural_label",
        )
        description = st.text_area(
            "Description",
            placeholder="Brief description of this object",
            key="create_description",
        )

    st.divider()

    st.markdown("#### Fields")
    st.caption("Leave a row blank if you do not want to create that field.")

    control_col1, control_col2, control_col3 = st.columns([1, 1, 4])
    with control_col1:
        st.button("Insert Row", on_click=add_create_field_row, width="content")
    with control_col2:
        st.button(
            "Delete Row",
            on_click=remove_last_create_field_row,
            disabled=len(st.session_state.create_field_row_ids) <= 1,
            width="content",
        )
    with control_col3:
        st.markdown(
            f'<div class="small-note">Field rows: {len(st.session_state.create_field_row_ids)}</div>',
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)
    for index, row_id in enumerate(st.session_state.create_field_row_ids, start=1):
        st.markdown(f"**Field {index}**")
        cols = st.columns([2.1, 2.1, 1.5, 1.2, 1.2])

        with cols[0]:
            st.text_input(
                "API Name",
                key=f"create_field_name_{row_id}",
                placeholder="e.g., Status__c",
                help="Must end with __c (auto-added).",
            )

        with cols[1]:
            st.text_input(
                "Label",
                key=f"create_field_label_{row_id}",
                placeholder="e.g., Status",
                help="Optional; auto-generated if blank",
            )

        with cols[2]:
            type_options = [""] + FIELD_TYPE_LABELS
            st.selectbox(
                "Type",
                type_options,
                key=f"create_field_type_{row_id}",
                help="Choose a type to reveal relevant options instantly.",
            )

        selected_type = st.session_state.get(f"create_field_type_{row_id}", "")
        selected_type_meta = FIELD_TYPE_OPTIONS.get(selected_type, {})

        with cols[3]:
            if selected_type_meta.get("supports_length"):
                default_length = 255 if selected_type == "Text" else 32768
                st.number_input(
                    "Length",
                    min_value=1,
                    value=default_length,
                    key=f"create_field_length_{row_id}",
                )
            elif selected_type_meta.get("supports_precision"):
                st.number_input(
                    "Precision",
                    min_value=1,
                    max_value=18,
                    value=18,
                    key=f"create_field_precision_{row_id}",
                )
            else:
                st.write("")

        with cols[4]:
            if selected_type_meta.get("supports_precision"):
                st.number_input(
                    "Scale",
                    min_value=0,
                    max_value=18,
                    value=2,
                    key=f"create_field_scale_{row_id}",
                )
            else:
                st.write("")

        if selected_type_meta.get("supports_picklist"):
            st.text_input(
                "Picklist Values",
                key=f"create_field_picklist_{row_id}",
                placeholder="e.g., New,In Progress,Closed",
                help="Comma-separated values. First value becomes the default.",
            )

        st.markdown("---")

    # ------------------------------------------------------------
    # Default Field-Level Security — applied in bulk, once, to every
    # field that's successfully created above (not per-row). Matches
    # Salesforce's native "Set Field-Level Security" page: one Visible /
    # Read-Only setting per submission, applied across the fields you
    # just created and the Profiles you pick here.
    # ------------------------------------------------------------
    st.markdown("#### Default Field-Level Security (FLS) for New Fields")
    st.caption(
        "These FLS settings apply in bulk to every custom field that's "
        "successfully created above — including if one field fails "
        "validation, the others still get created and still get FLS."
    )
    st.info(
        "💡 Use **Set Field-Level Security** below to make this field "
        "visible/editable for specific Profiles right away, using the "
        "same **Visible** / **Read-Only** model as Salesforce's native "
        "FLS page. If you skip it, Field-Level Security (FLS) will not apply "
        "your new custom field(s) to any selected profile(s) "
        "— including the System Administrator profile — by default."
    )

    tab1_profile_labels = get_profile_labels()
    fls_cols_tab1 = st.columns([2.6, 1, 1], vertical_alignment="bottom")

    with fls_cols_tab1[0]:
        if tab1_profile_labels:
            selected_profiles_tab1 = st.multiselect(
                "Set Field-Level Security for Profile(s)",
                options=tab1_profile_labels,
                max_selections=MAX_PROFILES_PER_GRANT,
                help="Optional. Leave empty to skip FLS. Capped at "
                     f"{MAX_PROFILES_PER_GRANT} — each Profile is a separate "
                     "Metadata API call.",
                key="create_obj_profiles",
            )
        else:
            selected_profiles_tab1 = []
            st.caption("No Profiles found in this org — FLS grant skipped.")

    with fls_cols_tab1[1]:
        is_visible_tab1 = st.checkbox(
            "Visible",
            value=True,
            key="create_obj_visible",
            help="Matches Salesforce's native FLS page. Unchecked = fields "
                 "hidden from the selected Profile(s) entirely.",
        )

    with fls_cols_tab1[2]:
        is_read_only_tab1 = st.checkbox(
            "Read-Only",
            value=False,
            key="create_obj_readonly",
            help="Only applies if Visible is checked. Checked = the selected "
                 "Profile(s) can see but not edit these fields.",
        )

    st.markdown("<br>", unsafe_allow_html=True)
    grant_object_access_tab1 = st.checkbox(
        "Also grant object-level access (Read/Create/Edit) on this new object "
        "to the Profile(s) selected above",
        value=False,
        key="create_obj_grant_object_access",
        help="A brand-new object has no access configured for anyone but "
             "System Administrator. FLS above has no real effect for other "
             "Profiles until they also have object-level Read access — check "
             "this if you're not granting it separately in Setup.",
    )

    _fls_profile_count = len(st.session_state.get("create_obj_profiles", []))
    _grants_object_access_tab1 = st.session_state.get("create_obj_grant_object_access", False)
    # FLS = 1 partial update per Profile (covers every field created in this
    # submission in one call). Object access (if opted in) = 1 read + 1
    # update per Profile, on the same Profiles.
    _total_grant_calls = _fls_profile_count * (1 + (2 if _grants_object_access_tab1 else 0))

    if _total_grant_calls > 0:
        _grant_msg = (
            f"This submission will make **{_total_grant_calls}** Metadata API call(s) "
            f"for permission grants (FLS: 1 update per Profile"
            + (
                "; object access: 1 read + 1 update per Profile"
                if _grants_object_access_tab1 else ""
            )
            + "), on top of the object/field creation calls."
        )
        if _total_grant_calls >= WARN_TOTAL_METADATA_CALLS_AT:
            st.warning(
                "⚠️ " + _grant_msg + " That's a fairly large number for one submission — "
                "consider granting access to fewer Profiles at once if you're "
                "concerned about your org's daily Metadata API limit."
            )
        else:
            st.caption(_grant_msg)

    if st.button("🚀 Create Object & Fields", width="stretch", key="create_object_btn"):
        try:
            if not obj_label.strip():
                raise ValueError("Object Label is required.")
            if not plural_label.strip():
                raise ValueError("Plural Label is required.")
            object_api_name = validate_custom_api_name(obj_api, "Object API Name")

            field_specs = collect_create_field_specs()

            result = create_custom_object(
                object_api_name=object_api_name,
                object_label=obj_label.strip(),
                plural_label=plural_label.strip(),
                description=description.strip(),
                field_specs=field_specs,
            )
            created_fields = result["created_fields"]
            failed_fields = result["failed_fields"]

            # The object itself is confirmed created at this point — report
            # that plainly regardless of what happens with individual fields
            # below, instead of the old behavior where one bad field made
            # the whole thing look like "Failed to create object".
            notify_success(f"Object `{object_api_name}` created successfully.")

            if created_fields:
                notify_success(
                    f"{len(created_fields)} of {len(field_specs)} field(s) created: "
                    f"{', '.join(created_fields)}."
                )
            if failed_fields:
                for field_name, err in failed_fields:
                    notify_error(f"Field `{field_name}` failed to create: {err}")

            selected_profiles_tab1 = st.session_state.get("create_obj_profiles", [])
            is_visible_tab1 = st.session_state.get("create_obj_visible", True)
            is_read_only_tab1 = st.session_state.get("create_obj_readonly", False)
            grant_object_access_tab1 = st.session_state.get("create_obj_grant_object_access", False)

            # FLS is applied only to fields that actually succeeded above —
            # this is the core fix: a failed field no longer causes FLS to
            # be skipped entirely for the fields that DID get created.
            if created_fields and selected_profiles_tab1:
                if grant_object_access_tab1:
                    obj_failures = grant_object_level_security(
                        object_api_name=object_api_name,
                        profile_labels=selected_profiles_tab1,
                    )
                    if obj_failures:
                        notify_warning(
                            f"Object-level access grant failed:\n\n"
                            f"{_format_grant_failures(obj_failures)}\n\n"
                            f"Grant access manually in Setup if needed."
                        )
                    else:
                        notify_success(
                            f"Object-level access granted on `{object_api_name}` to "
                            f"{len(selected_profiles_tab1)} Profile(s)."
                        )

                fls_failures = assign_fls_to_profiles(
                    object_api_name=object_api_name,
                    field_api_names=created_fields,
                    profile_labels=selected_profiles_tab1,
                    visible=is_visible_tab1,
                    read_only=is_read_only_tab1,
                )
                if fls_failures:
                    notify_warning(
                        f"FLS grant failed for some Profile(s):\n\n"
                        f"{_format_grant_failures(fls_failures)}\n\n"
                        f"Grant access manually in Setup if needed."
                    )
                else:
                    notify_success(
                        f"FLS applied to {len(created_fields)} field(s) for "
                        f"{len(selected_profiles_tab1)} Profile(s)."
                    )

            # Sync: add new object to the shared global list
            if "fa_all_objects" not in st.session_state or st.session_state["fa_all_objects"] is None:
                st.session_state["fa_all_objects"] = []

            if object_api_name not in st.session_state["fa_all_objects"]:
                st.session_state["fa_all_objects"].append(object_api_name)
                st.session_state["fa_all_objects"].sort()

            # Warm the describe cache for the new object
            try:
                if "fa_describe_cache" not in st.session_state:
                    st.session_state["fa_describe_cache"] = {}
                st.session_state["fa_describe_cache"][object_api_name] = (
                    getattr(sf, object_api_name).describe()
                )
            except Exception:
                pass

        except Exception as exc:
            notify_error(f"Failed to create object: {exc}")

    st.markdown("</div>", unsafe_allow_html=True)


# ============================================================
# TAB 2: Manage Fields
# ============================================================
with tabs[1]:
    st.markdown('<div class="section-card"><h3>🔧 Manage Fields</h3>', unsafe_allow_html=True)

    all_objects = get_all_objects(custom_only=False)
    if not all_objects:
        st.info("No objects found in this org.")
    else:
        selected_obj = st.selectbox(
            "Select Object",
            all_objects,
            index=None,
            placeholder="Choose an object...",
            key="manage_fields_object",
        )

        if selected_obj:
            # Ensure describe cache exists
            if "fa_describe_cache" not in st.session_state:
                st.session_state["fa_describe_cache"] = {}

            already_cached = selected_obj in st.session_state["fa_describe_cache"]
            with st.spinner(f"Loading fields for {selected_obj}...") if not already_cached else st.empty():
                fields = get_object_fields(selected_obj)

            if not fields:
                st.info("No fields found or the object could not be described.")
            else:
                fields_df = pd.DataFrame(
                    [
                        {
                            "Name": field.get("name", ""),
                            "Label": field.get("label", ""),
                            "Type": field.get("type", ""),
                            "Required": not field.get("nillable", True),
                            "Unique": field.get("unique", False),
                            "Custom": "Yes" if field.get("name", "").endswith(CUSTOM_SUFFIX) else "No",
                        }
                        for field in fields
                    ]
                )
                st.dataframe(fields_df, width="stretch", height=320)

                custom_fields = [field for field in fields if field.get("name", "").endswith(CUSTOM_SUFFIX)]

                st.markdown("---")
                st.subheader("Modify or Delete a Custom Field")

                if not custom_fields:
                    st.info("No custom fields are available for this object.")
                else:
                    field_names = [field["name"] for field in custom_fields]
                    selected_field_name = st.selectbox(
                        "Select Custom Field",
                        field_names,
                        index=None,
                        placeholder="Choose a custom field...",
                        key="selected_custom_field",
                    )

                    if selected_field_name:
                        selected_field_meta = next(
                            (field for field in custom_fields if field["name"] == selected_field_name),
                            None,
                        )

                        if selected_field_meta:
                            field_type = selected_field_meta.get("type", "Unknown")

                            st.caption(
                                f"💡 Current type: **{field_type}**. "
                                "This screen updates metadata such as label / description / help text. "
                                "Changing field type is intentionally not exposed because Salesforce often restricts it."
                            )

                            with st.form("modify_field_form", clear_on_submit=False):
                                new_label = st.text_input(
                                    "Field Label",
                                    value=selected_field_meta.get("label", ""),
                                )
                                new_description = st.text_area(
                                    "Description",
                                    value=selected_field_meta.get("description", "") or "",
                                    help="Stored as the field's description metadata.",
                                )
                                new_help_text = st.text_area(
                                    "Inline Help Text",
                                    value=selected_field_meta.get("inlineHelpText", "") or "",
                                    help="Shown as a tooltip next to the field in the UI.",
                                )

                                st.markdown("#### Field-Level Security (FLS)")
                                st.caption(
                                    "Optional — update FLS for this field alongside your "
                                    "other changes. Leave Profile(s) empty to leave FLS "
                                    "untouched."
                                )
                                modify_fls_cols = st.columns([2.6, 1, 1], vertical_alignment="bottom")
                                modify_available_profiles = get_profile_labels()
                                with modify_fls_cols[0]:
                                    if modify_available_profiles:
                                        modify_selected_profiles = st.multiselect(
                                            "Set Field-Level Security for Profile(s)",
                                            options=modify_available_profiles,
                                            max_selections=MAX_PROFILES_PER_GRANT,
                                            key="modify_field_profiles",
                                        )
                                    else:
                                        modify_selected_profiles = []
                                        st.caption("No Profiles found in this org.")
                                with modify_fls_cols[1]:
                                    modify_is_visible = st.checkbox(
                                        "Visible", value=True, key="modify_field_visible"
                                    )
                                with modify_fls_cols[2]:
                                    modify_is_read_only = st.checkbox(
                                        "Read-Only", value=False, key="modify_field_readonly"
                                    )

                                st.markdown("<br>", unsafe_allow_html=True)
                                delete_field_flag = st.checkbox("Delete this field")
                                apply_field_changes = st.form_submit_button("Apply Changes", width="stretch")

                                if apply_field_changes:
                                    try:
                                        if delete_field_flag:
                                            delete_custom_field(selected_obj, selected_field_name)
                                            st.session_state["fa_describe_cache"].pop(selected_obj, None)
                                            notify_success(f"Field `{selected_field_name}` deleted successfully.")
                                        else:
                                            if not new_label.strip():
                                                raise ValueError("Field Label cannot be empty.")

                                            update_custom_field(
                                                object_name=selected_obj,
                                                field_name=selected_field_name,
                                                new_label=new_label.strip(),
                                                new_description=new_description.strip(),
                                                new_help_text=new_help_text.strip(),
                                            )
                                            st.session_state["fa_describe_cache"].pop(selected_obj, None)
                                            notify_success(f"Field `{selected_field_name}` updated successfully.")

                                            if modify_selected_profiles:
                                                modify_fls_failures = assign_fls_to_profiles(
                                                    object_api_name=selected_obj,
                                                    field_api_names=[selected_field_name],
                                                    profile_labels=modify_selected_profiles,
                                                    visible=modify_is_visible,
                                                    read_only=modify_is_read_only,
                                                )
                                                if modify_fls_failures:
                                                    notify_warning(
                                                        f"Field updated, but FLS grant failed:\n\n"
                                                        f"{_format_grant_failures(modify_fls_failures)}\n\n"
                                                        f"Grant access manually in Setup if needed."
                                                    )
                                                else:
                                                    notify_success(
                                                        f"FLS updated on `{selected_field_name}` for "
                                                        f"{len(modify_selected_profiles)} Profile(s)."
                                                    )
                                    except Exception as exc:
                                        notify_error(f"Failed to apply field changes: {exc}")

                # --- Create New Custom Field ---
                st.markdown("---")
                st.subheader("✨ Create New Custom Field")
                st.caption(f"Add a new custom field to the **{selected_obj}** object.")

                st.info(
                    "💡 Use **Set Field-Level Security** below to make this field "
                    "visible/editable for specific Profiles right away, using the "
                    "same **Visible** / **Read-Only** model as Salesforce's native "
                    "FLS page. If you skip it, Field-Level Security (FLS) will not apply "
                    "your new custom field to any selected profile(s) "
                    "— including the System Administrator profile — by default."
                )

                new_field_cols = st.columns([2.1, 2.1, 1.5, 1.2, 1.2])

                with new_field_cols[0]:
                    new_field_api = st.text_input(
                        "API Name *",
                        placeholder="e.g., Status__c",
                        help="Must end with __c (auto-added).",
                        key="new_field_api",
                    )

                with new_field_cols[1]:
                    new_field_label = st.text_input(
                        "Label",
                        placeholder="e.g., Status",
                        help="Optional; auto-generated if blank",
                        key="new_field_label",
                    )

                with new_field_cols[2]:
                    new_field_type_options = [""] + FIELD_TYPE_LABELS
                    new_field_type = st.selectbox(
                        "Type *",
                        new_field_type_options,
                        key="new_field_type",
                        help="Choose a type to reveal relevant options instantly.",
                    )

                new_field_type_meta = FIELD_TYPE_OPTIONS.get(new_field_type, {})

                with new_field_cols[3]:
                    if new_field_type_meta.get("supports_length"):
                        default_length = 255 if new_field_type == "Text" else 32768
                        st.number_input(
                            "Length",
                            min_value=1,
                            value=default_length,
                            key="new_field_length",
                        )
                    elif new_field_type_meta.get("supports_precision"):
                        st.number_input(
                            "Precision",
                            min_value=1,
                            max_value=18,
                            value=18,
                            key="new_field_precision",
                        )
                    else:
                        st.write("")

                with new_field_cols[4]:
                    if new_field_type_meta.get("supports_precision"):
                        st.number_input(
                            "Scale",
                            min_value=0,
                            max_value=18,
                            value=2,
                            key="new_field_scale",
                        )
                    else:
                        st.write("")

                if new_field_type_meta.get("supports_picklist"):
                    st.text_input(
                        "Picklist Values",
                        key="new_field_picklist",
                        placeholder="e.g., New,In Progress,Closed",
                        help="Comma-separated values. First value becomes the default.",
                    )

                existing_profile_labels = get_profile_labels()
                if existing_profile_labels:
                    fls_col2, visible_col2, readonly_col2 = st.columns([2.6, 1, 1], vertical_alignment="bottom")
                    with fls_col2:
                        st.multiselect(
                            "Set Field-Level Security for Profile(s)",
                            options=existing_profile_labels,
                            key="new_field_fls",
                            max_selections=MAX_PROFILES_PER_GRANT,
                            help="Optional. Leave empty to skip FLS. Capped "
                                 f"at {MAX_PROFILES_PER_GRANT} — each one is a separate "
                                 "Metadata API call.",
                        )
                    with visible_col2:
                        st.checkbox(
                            "Visible",
                            key="new_field_fls_visible",
                            value=True,
                            help="Matches Salesforce's native FLS page. Unchecked = field "
                                 "hidden from the selected Profile(s) entirely.",
                        )
                    with readonly_col2:
                        st.checkbox(
                            "Read-Only",
                            key="new_field_fls_readonly",
                            value=False,
                            help="Only applies if Visible is checked. Checked = the "
                                 "selected Profile(s) can see but not edit this field.",
                        )
                    
                    st.markdown("<br>", unsafe_allow_html=True)
                    st.checkbox(
                        f"Also grant object-level access (Read/Create/Edit) on "
                        f"`{selected_obj}` to the Profile(s) selected above",
                        key="new_field_grant_object_access",
                        value=False,
                        help="Leave unchecked if these Profiles can already access "
                             f"`{selected_obj}` — this is mainly for objects that were just "
                             "created and have no access configured yet. Existing broader "
                             "access is never downgraded.",
                    )
                else:
                    st.caption("No Profiles found in this org — FLS grant skipped.")

                _existing_fls_count = len(st.session_state.get("new_field_fls", []))
                _grants_object_access = st.session_state.get("new_field_grant_object_access", False)
                # FLS = 1 partial update per Profile. Object access (if opted
                # in) = 1 read + 1 update per Profile, on the same Profiles.
                _total_existing_calls = _existing_fls_count * (1 + (2 if _grants_object_access else 0))

                if _total_existing_calls > 0:
                    _grant_msg_existing = (
                        f"This submission will make **{_total_existing_calls}** Metadata "
                        f"API call(s) for permission grants (FLS: 1 update per Profile"
                        + (
                            "; object access: 1 read + 1 update per Profile"
                            if _grants_object_access else ""
                        )
                        + "), on top of the field creation call."
                    )
                    if _total_existing_calls >= WARN_TOTAL_METADATA_CALLS_AT:
                        st.warning(
                            "⚠️ " + _grant_msg_existing + " That's a fairly large number "
                            "for one submission — consider granting access to fewer "
                            "Profiles at once if you're concerned about your org's "
                            "daily Metadata API limit."
                        )
                    else:
                        st.caption(_grant_msg_existing)

                if st.button("🚀 Create Custom Field", width="stretch", key="create_new_field_btn"):
                    try:
                        if not new_field_type:
                            raise ValueError("Field Type is required.")
                        if not new_field_api.strip():
                            raise ValueError("Field API Name is required.")

                        api_name = validate_custom_api_name(new_field_api, "Field API Name")
                        label = new_field_label.strip() or derive_label_from_api_name(api_name)

                        metadata_info = FIELD_TYPE_OPTIONS[new_field_type]
                        field_spec: Dict[str, Any] = {
                            "api_name": api_name,
                            "label": label,
                            "ui_type": new_field_type,
                            "metadata_type": metadata_info["metadata_type"],
                        }

                        if metadata_info.get("supports_length"):
                            length_value = int(st.session_state.get("new_field_length", 255))
                            if length_value <= 0:
                                raise ValueError("Length must be greater than 0.")
                            field_spec["length"] = length_value

                        if metadata_info.get("supports_precision"):
                            precision = int(st.session_state.get("new_field_precision", 18))
                            scale = int(st.session_state.get("new_field_scale", 2))
                            if precision <= 0:
                                raise ValueError("Precision must be greater than 0.")
                            if scale < 0:
                                raise ValueError("Scale cannot be negative.")
                            if scale > precision:
                                raise ValueError("Scale cannot be greater than precision.")
                            field_spec["precision"] = precision
                            field_spec["scale"] = scale

                        if metadata_info.get("supports_picklist"):
                            picklist_raw = st.session_state.get("new_field_picklist", "")
                            field_spec["picklist_values"] = parse_picklist_values(picklist_raw)

                        mdapi = sf.mdapi
                        field_metadata = build_custom_field_metadata(mdapi, selected_obj, field_spec)
                        mdapi.CustomField.create(field_metadata)

                        st.session_state["fa_describe_cache"].pop(selected_obj, None)
                        notify_success(f"Custom field `{api_name}` created successfully on `{selected_obj}`.")

                        selected_profiles = st.session_state.get("new_field_fls", [])

                        if selected_profiles and st.session_state.get("new_field_grant_object_access", False):
                            obj_perm_failures = grant_object_level_security(
                                object_api_name=selected_obj,
                                profile_labels=selected_profiles,
                            )
                            if obj_perm_failures:
                                notify_warning(
                                    f"Object-level access grant on `{selected_obj}` failed:\n\n"
                                    f"{_format_grant_failures(obj_perm_failures)}\n\n"
                                    f"Grant access manually in Setup if needed."
                                )
                            else:
                                notify_success(
                                    f"Object-level access granted on `{selected_obj}` to "
                                    f"{len(selected_profiles)} Profile(s)."
                                )

                        if selected_profiles:
                            fls_visible = st.session_state.get("new_field_fls_visible", True)
                            fls_read_only = st.session_state.get("new_field_fls_readonly", False)
                            fls_failures = assign_fls_to_profiles(
                                object_api_name=selected_obj,
                                field_api_names=[api_name],
                                profile_labels=selected_profiles,
                                visible=fls_visible,
                                read_only=fls_read_only,
                            )
                            if fls_failures:
                                notify_warning(
                                    f"Field created, but FLS grant failed:\n\n"
                                    f"{_format_grant_failures(fls_failures)}\n\n"
                                    f"Grant access manually in Setup if needed."
                                )
                            else:
                                notify_success(
                                    f"FLS set on `{api_name}` for "
                                    f"{len(selected_profiles)} Profile(s)."
                                )

                    except Exception as exc:
                        notify_error(f"Failed to create custom field: {exc}")

    st.markdown("</div>", unsafe_allow_html=True)


# ============================================================
# TAB 3: Modify Custom Object
# ============================================================
with tabs[2]:
    st.markdown('<div class="section-card"><h3>🛠️ Modify Custom Object</h3>', unsafe_allow_html=True)

    custom_objects = get_all_objects(custom_only=True)
    if not custom_objects:
        st.info("No custom objects found in this org.")
    else:
        custom_obj_selected = st.selectbox(
            "Select Custom Object",
            custom_objects,
            index=None,
            placeholder="Choose a custom object...",
            key="modify_custom_object_select",
        )

        if custom_obj_selected:
            action = st.selectbox(
                "Action",
                ["Read", "Update", "Delete", "Describe"],
                index=None,
                placeholder="Choose an action...",
                key="custom_object_action",
            )

            if action == "Read":
                if st.button("Read Object Metadata", width="stretch"):
                    try:
                        with st.spinner("Loading object metadata..."):
                            obj_meta = read_custom_object_metadata(custom_obj_selected)
                        obj_json = json.dumps(to_serializable(obj_meta), indent=2)
                        st.json(json.loads(obj_json))
                        st.download_button(
                            "⬇️ Download as JSON",
                            data=obj_json,
                            file_name=f"{custom_obj_selected}_metadata.json",
                            mime="application/json",
                            key="download_read_object_json",
                        )
                        notify_success("Object metadata loaded successfully.")
                    except Exception as exc:
                        notify_error(f"Failed to read object metadata: {exc}")

            elif action == "Update":
                try:
                    with st.spinner("Loading current metadata..."):
                        current_meta = read_custom_object_metadata(custom_obj_selected)

                    with st.form("update_custom_object_form", clear_on_submit=False):
                        new_label = st.text_input(
                            "Object Label",
                            value=getattr(current_meta, "label", custom_obj_selected.replace(CUSTOM_SUFFIX, "")),
                        )
                        new_plural_label = st.text_input(
                            "Plural Label",
                            value=getattr(current_meta, "pluralLabel", ""),
                        )
                        new_description = st.text_area(
                            "Description",
                            value=getattr(current_meta, "description", "") or "",
                        )
                        new_sharing = st.selectbox(
                            "Sharing Model",
                            ["Read", "ReadWrite", "ReadWriteTransfer", "FullAccess", "ControlledByParent"],
                            index=1 if getattr(current_meta, "sharingModel", "ReadWrite") == "ReadWrite" else 0,
                        )
                        new_deployment = st.selectbox(
                            "Deployment Status",
                            ["Deployed", "InDevelopment"],
                            index=0 if getattr(current_meta, "deploymentStatus", "Deployed") == "Deployed" else 1,
                        )

                        update_object_submit = st.form_submit_button("Update Object", width="stretch")

                        if update_object_submit:
                            if not new_label.strip():
                                raise ValueError("Object Label cannot be empty.")
                            if not new_plural_label.strip():
                                raise ValueError("Plural Label cannot be empty.")

                            update_custom_object_metadata(
                                object_name=custom_obj_selected,
                                new_label=new_label.strip(),
                                new_plural_label=new_plural_label.strip(),
                                new_description=new_description.strip(),
                                new_sharing_model=new_sharing,
                                new_deployment_status=new_deployment,
                            )
                            notify_success(f"Object `{custom_obj_selected}` updated successfully.")
                except Exception as exc:
                    notify_error(f"Failed to load or update object metadata: {exc}")

            elif action == "Delete":
                st.warning("⚠️ This action is irreversible.")
                confirmation_text = st.text_input(
                    "Type the exact object API name to confirm deletion",
                    placeholder=custom_obj_selected,
                )

                if st.button("Delete Object", width="stretch"):
                    try:
                        if confirmation_text.strip() != custom_obj_selected:
                            raise ValueError("Confirmation text does not match the selected object API name.")

                        delete_custom_object(custom_obj_selected)
                        st.session_state["fa_describe_cache"].pop(custom_obj_selected, None)
                        if "fa_all_objects" in st.session_state and custom_obj_selected in st.session_state["fa_all_objects"]:
                            st.session_state["fa_all_objects"].remove(custom_obj_selected)
                        notify_success(f"Object `{custom_obj_selected}` deleted successfully.")
                    except Exception as exc:
                        notify_error(f"Failed to delete object: {exc}")

            elif action == "Describe":
                if st.button("Describe Object", width="stretch"):
                    try:
                        with st.spinner("Describing object..."):
                            description_data = getattr(sf, custom_obj_selected).describe()
                        obj_json = json.dumps(to_serializable(description_data), indent=2)
                        st.json(json.loads(obj_json))
                        st.download_button(
                            "⬇️ Download as JSON",
                            data=obj_json,
                            file_name=f"{custom_obj_selected}_describe.json",
                            mime="application/json",
                            key="download_describe_object_json",
                        )
                        notify_success("Object described successfully.")
                    except Exception as exc:
                        notify_error(f"Failed to describe object: {exc}")

    st.markdown("</div>", unsafe_allow_html=True)