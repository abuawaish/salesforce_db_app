import re
from datetime import datetime
from html import escape
import requests
import streamlit as st

# ------------------------------------------------------------
# Page Configuration — MUST be first Streamlit command
# ------------------------------------------------------------
st.set_page_config(
    page_title="Session Information",
    page_icon="👤",
    layout="wide",
    initial_sidebar_state="auto",
)

# ------------------------------------------------------------
# Check connection
# ------------------------------------------------------------
if "sf" not in st.session_state or not st.session_state.get("config_ok"):
    st.warning("Please configure your Salesforce connection first (⚙️ Configuration page).")
    st.info(
        "💡 **What this page does:** once connected, view details about "
        "your active Salesforce session — org info, logged-in user, API "
        "usage/limits, and session health — handy for confirming you're "
        "pointed at the right org before you run queries or edits."
    )
    st.stop()

sf = st.session_state["sf"]

# ------------------------------------------------------------
# Custom CSS — theme-safe for light and dark mode
# ------------------------------------------------------------
st.markdown(
    """
<style>
    .metric-container {
        background: var(--secondary-background-color);
        border: 1px solid rgba(128, 128, 128, 0.18);
        border-radius: 12px;
        padding: 20px;
        text-align: center;
        transition: all 0.2s ease;
    }
    .metric-container:hover {
        border-color: var(--primary-color);
        box-shadow: 0 0 0 1px color-mix(in srgb, var(--primary-color) 25%, transparent);
    }
    .metric-label {
        color: var(--text-color);
        opacity: 0.7;
        font-size: 0.75rem;
        text-transform: uppercase;
        letter-spacing: 1px;
        margin-bottom: 8px;
    }
    .footer-panel {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 12px;
        align-items: center;
        padding: 16px 18px;
        margin-top: 20px;
        border-top: 1px solid rgba(128, 128, 128, 0.12);
        background: color-mix(in srgb, var(--secondary-background-color) 92%, transparent);
        border-radius: 12px;
        color: var(--text-color);
        opacity: 0.86;
    }
    .footer-panel .footer-item {
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 0.9rem;
        line-height: 1.6;
        word-break: break-word;
    }
    .footer-panel .footer-item:not(:last-child) {
        border-right: 1px solid rgba(128, 128, 128, 0.12);
        padding-right: 16px;
        margin-right: 12px;
    }
    .footer-icon {
        font-size: 1.05rem;
        display: inline-block;
        margin-right: 6px;
        opacity: 0.95;
    }
    @media (max-width: 640px) {
        .footer-panel {
            grid-template-columns: 1fr;
            padding: 14px 16px;
        }
        .footer-panel .footer-item {
            width: 100%;
            border-right: none;
            padding-right: 0;
            margin-right: 0;
        }
    }
    .footer-panel strong {
        color: var(--text-color);
        opacity: 0.95;
        font-weight: 700;
    }
    .data-table {
        width: 100%;
        border-collapse: collapse;
        border-spacing: 0;
        box-shadow: 0 10px 30px rgba(0, 0, 0, 0.04);
        background: color-mix(in srgb, var(--secondary-background-color) 95%, var(--background-color));
        border-radius: 12px;
        overflow: hidden;
    }
    .data-table tr {
        border-bottom: 1px solid transparent;
        transition: border-color 0.18s ease, background-color 0.18s ease;
    }
    .data-table tr:hover {
        border-bottom-color: rgba(128, 128, 128, 0.12);
        background: color-mix(in srgb, var(--secondary-background-color) 96%, transparent);
    }
    .data-table tr:first-child td:first-child {
        border-top-left-radius: 10px;
    }
    .data-table tr:first-child td:last-child {
        border-top-right-radius: 10px;
    }
    .data-table tr:last-child td:first-child {
        border-bottom-left-radius: 10px;
    }
    .data-table tr:last-child td:last-child {
        border-bottom-right-radius: 10px;
    }
    .data-table tr:last-child {
        border-bottom: none;
    }
    .data-table td {
        padding: 12px 18px;
        vertical-align: top;
    }
    .data-table td:first-child {
        width: 35%;
        color: var(--text-color);
        opacity: 0.75;
        font-weight: 700;
        font-size: 0.9rem;
        text-transform: uppercase;
        letter-spacing: 0.03em;
        padding: 12px 18px 12px 18px;
        padding-right: 16px;
        background: color-mix(in srgb, var(--secondary-background-color) 88%, transparent);
        border-right: 1px solid rgba(128, 128, 128, 0.10);
    }
    .data-table td:last-child {
        color: var(--text-color);
        opacity: 0.85;
        font-weight: 400;
        font-size: 0.9rem;
        word-break: break-word;
    }
    .badge {
        display: inline-block;
        padding: 3px 10px;
        border-radius: 999px;
        font-size: 0.9rem;
        font-weight: 700;
        opacity: 0.95;
    }
    .badge-success {
        background: rgba(34, 197, 94, 0.12);
        color: rgba(22, 163, 74, 0.95);
    }
    .badge-error {
        background: rgba(239, 68, 68, 0.12);
        color: rgba(220, 38, 38, 0.95);
    }
    .badge-neutral {
        background: rgba(245, 158, 11, 0.12);
        color: rgba(217, 119, 6, 0.95);
    }
    .error-banner {
        background: rgba(239, 68, 68, 0.08);
        border: 1px solid rgba(239, 68, 68, 0.25);
        border-radius: 8px;
        padding: 12px 16px;
        margin-bottom: 16px;
        color: #dc2626;
        font-size: 0.85rem;
    }
    .session-id {
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
        font-size: 0.8rem;
        color: var(--text-color);
        background: rgba(127, 127, 127, 0.12);
        padding: 4px 8px;
        border-radius: 6px;
        word-break: break-all;
        display: inline-block;
    }
    .footer-panel {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 12px;
        align-items: center;
        padding: 16px 18px;
        margin-top: 20px;
        border-top: 1px solid rgba(128, 128, 128, 0.12);
        background: color-mix(in srgb, var(--secondary-background-color) 92%, transparent);
        border-radius: 12px;
        color: var(--text-color);
        opacity: 0.86;
    }
    .footer-panel div {
        font-size: 0.9rem;
        line-height: 1.6;
        word-break: break-word;
    }
    .footer-panel div:not(:last-child) {
        border-right: 1px solid rgba(128, 128, 128, 0.12);
        padding-right: 16px;
        margin-right: 12px;
    }
    @media (max-width: 640px) {
        .footer-panel {
            grid-template-columns: 1fr;
            padding: 14px 16px;
        }
        .footer-panel div {
            width: 100%;
            border-right: none;
            padding-right: 0;
            margin-right: 0;
        }
    }
    .footer-panel strong {
        color: var(--text-color);
        opacity: 0.95;
        font-weight: 700;
    }
    div[data-testid="stExpander"] details {
        border: 1px solid rgba(128, 128, 128, 0.15);
        border-radius: 12px;
        background: color-mix(in srgb, var(--secondary-background-color) 92%, transparent);
    }
    div[data-testid="stExpander"] summary {
        font-weight: 600;
        color: var(--text-color);
    }
    div[data-testid="stExpander"] summary:hover {
        color: var(--primary-color);
    }
</style>
""",
    unsafe_allow_html=True,
)

# ------------------------------------------------------------
# Helper functions
# ------------------------------------------------------------
def _clean_exception_text(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\n", " ").replace("\t", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _mask_secret(value: str, prefix: int = 8, suffix: int = 4) -> str:
    if not value:
        return "N/A"
    value = str(value)
    if len(value) <= prefix + suffix:
        return "•" * len(value)
    return f"{value[:prefix]}{'•' * 12}{value[-suffix:]}"


def _instance_root(base_url: str) -> str:
    if not base_url:
        return ""
    m = re.match(r"^(https://[^/]+)", base_url)
    return m.group(1) if m else ""


def _direct_json_get(url: str, session_id: str, timeout: int = 12):
    headers = {
        "Authorization": f"Bearer {session_id}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    response = requests.get(url, headers=headers, timeout=timeout)
    return response.status_code, response.json() if response.content else {}


def _escape_soql(value: str) -> str:
    value = str(value or "")
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _safe_html(value) -> str:
    return "" if value is None else escape(str(value))


def format_bool(val):
    if val is True:
        return "<span class='badge badge-success'>true</span>"
    if val is False:
        return "<span class='badge badge-error'>false</span>"
    return f"<span class='badge badge-neutral'>{_safe_html(val)}</span>"


def render_card(title, icon, rows, error=None):
    rendered_rows = []
    for row in rows:
        if len(row) == 2:
            key, value = row
            is_html = False
        else:
            key, value, is_html = row

        key_html = _safe_html(key)
        value_html = value if is_html else _safe_html(value)
        rendered_rows.append(f"<tr><td>{key_html}</td><td>{value_html}</td></tr>")

    rows_html = "".join(rendered_rows)
    error_html = f'<div class="error-banner">⚠️ {_safe_html(error)}</div>' if error else ""
    html = (
        f'<div class="info-card">'
        f'<div class="info-card-header"><span style="font-size:1.2rem;">{_safe_html(icon)}</span><h4>{_safe_html(title)}</h4></div>'
        f'<div class="info-card-body">{error_html}<table class="data-table">{rows_html}</table></div>'
        f"</div>"
    )
    st.markdown(html, unsafe_allow_html=True)


def _build_user_from_identity(identity_data: dict) -> dict:
    if not identity_data:
        return {}

    aliases = {
        "display_name": "name",
        "name": "name",
        "user_full_name": "name",
        "username": "username",
        "user_name": "username",
        "email": "email",
        "user_email": "email",
        "user_id": "user_id",
        "id": "user_id",
        "organization_id": "org_id",
        "org_id": "org_id",
        "profile_id": "profile_id",
        "user_profile_id": "profile_id",
        "role_id": "role_id",
        "user_role_id": "role_id",
        "user_type": "user_type",
        "language": "language",
        "user_language": "language",
        "locale": "locale",
        "user_locale": "locale",
        "timezone": "timezone",
        "user_timezone": "timezone",
        "accessibility_mode": "accessibility_mode",
        "user_accessibility_mode": "accessibility_mode",
        "chatter_external": "chatter_external",
        "user_chatter_external": "chatter_external",
        "currency_symbol": "currency_symbol",
        "user_currency_symbol": "currency_symbol",
        "session_seconds_valid": "session_seconds_valid",
        "user_session_seconds_valid": "session_seconds_valid",
        "user_default_currency_iso_code": "user_default_currency_iso_code",
        "user_ui_skin": "user_ui_skin",
    }

    user = {}
    for src, dst in aliases.items():
        val = identity_data.get(src)
        if val is not None and dst not in user:
            user[dst] = val
    return user


@st.cache_data(ttl=600, show_spinner=False)
def fetch_session_info(_sf):
    info = {
        "api_version": "Unknown",
        "endpoint": "N/A",
        "client_id": "Streamlit App",
        "user": {},
        "org": {},
        "session_id": "N/A",   # masked only
        "sf_instance": "N/A",
        "domain": "N/A",
        "identity": {},
        "identity_source": "unavailable",
        "errors": [],
        "warnings": [],
    }

    session_id = getattr(_sf, "session_id", None) or ""
    base_url = ""
    instance_root = ""

    # 1. Connection info
    try:
        base_url = getattr(_sf, "base_url", "") or ""
        instance_root = _instance_root(base_url)
        match = re.search(r"/v(\d+\.\d+)", base_url)
        info["api_version"] = match.group(1) if match else "Unknown"
        info["endpoint"] = base_url or "N/A"
        info["session_id"] = _mask_secret(session_id)
        info["sf_instance"] = getattr(_sf, "sf_instance", "N/A") or "N/A"
        info["domain"] = getattr(_sf, "domain", "N/A") or "N/A"
    except Exception as e:
        info["errors"].append(f"Connection: {_clean_exception_text(str(e))}")

    identity_data = {}
    identity_attempt_errors = []

    # 2. Identity URL (best source when available)
    try:
        identity_url = getattr(_sf, "id", None)
        if isinstance(identity_url, str) and identity_url.startswith("http") and session_id:
            status, payload = _direct_json_get(identity_url, session_id)
            if status == 200 and isinstance(payload, dict):
                identity_data = payload
                info["identity_source"] = "identity_url"
            else:
                identity_attempt_errors.append(f"Identity URL returned HTTP {status}")
    except Exception as e:
        identity_attempt_errors.append(f"Identity URL: {_clean_exception_text(str(e))}")

    # 3. OAuth userinfo fallback — direct absolute URL, NOT _sf.restful()
    if not identity_data and instance_root and session_id:
        try:
            userinfo_url = f"{instance_root}/services/oauth2/userinfo"
            status, payload = _direct_json_get(userinfo_url, session_id)
            if status == 200 and isinstance(payload, dict):
                identity_data = {
                    "user_id": payload.get("user_id"),
                    "username": payload.get("preferred_username") or payload.get("username"),
                    "display_name": payload.get("name"),
                    "email": payload.get("email"),
                    "organization_id": payload.get("organization_id") or payload.get("org_id"),
                    **payload,
                }
                info["identity_source"] = "oauth_userinfo"
            elif status not in (400, 401, 403, 404):
                identity_attempt_errors.append(f"OAuth userinfo returned HTTP {status}")
        except Exception as e:
            identity_attempt_errors.append(f"OAuth userinfo: {_clean_exception_text(str(e))}")

    # 4. Chatter current-user fallback — reliable for many session-based auth flows
    if not identity_data:
        try:
            me = _sf.restful("chatter/users/me", method="GET")
            if isinstance(me, dict) and me:
                identity_data = {
                    "id": me.get("id"),
                    "user_id": me.get("id"),
                    "display_name": me.get("name"),
                    "name": me.get("name"),
                    "username": me.get("username"),
                    "email": me.get("email"),
                    **me,
                }
                info["identity_source"] = "chatter_users_me"
        except Exception as e:
            identity_attempt_errors.append(f"chatter/users/me: {_clean_exception_text(str(e))}")

    # Keep raw identity payload if found
    if identity_data:
        info["identity"] = identity_data

    # 5. Organization info — valid Organization fields only
    try:
        org_query = (
            "SELECT Id, Name, OrganizationType, InstanceName, "
            "IsSandbox, NamespacePrefix FROM Organization LIMIT 1"
        )
        org_result = _sf.query(org_query)
        records = org_result.get("records", []) if isinstance(org_result, dict) else []
        if records:
            info["org"] = records[0]
        else:
            info["warnings"].append("Organization query returned no records.")
    except Exception as e:
        err_msg = _clean_exception_text(str(e))
        info["errors"].append(f"Organization: {err_msg}")
        try:
            org_result = _sf.query("SELECT Id, Name FROM Organization LIMIT 1")
            records = org_result.get("records", []) if isinstance(org_result, dict) else []
            if records:
                info["org"] = records[0]
                info["warnings"].append("Limited organization info retrieved (basic fields only).")
        except Exception as e2:
            info["errors"].append(f"Organization fallback: {_clean_exception_text(str(e2))}")

    # 6. Build user info from identity/chatter payload first
    user_info = _build_user_from_identity(identity_data)

    # 7. SOQL fallback — only for the actual current user, never “latest active user”
    try:
        user_id = user_info.get("user_id")
        username = user_info.get("username") or getattr(_sf, "username", None)

        soql = None
        if user_id:
            soql = (
                "SELECT Id, Name, Username, Email, ProfileId, UserRoleId, "
                "UserType, LanguageLocaleKey, LocaleSidKey, TimeZoneSidKey "
                f"FROM User WHERE Id = '{_escape_soql(user_id)}' LIMIT 1"
            )
        elif username:
            soql = (
                "SELECT Id, Name, Username, Email, ProfileId, UserRoleId, "
                "UserType, LanguageLocaleKey, LocaleSidKey, TimeZoneSidKey "
                f"FROM User WHERE Username = '{_escape_soql(username)}' LIMIT 1"
            )

        if soql:
            result = _sf.query(soql)
            records = result.get("records", []) if isinstance(result, dict) else []
            if records:
                rec = records[0]
                soql_user = {
                    "user_id": rec.get("Id"),
                    "name": rec.get("Name"),
                    "username": rec.get("Username"),
                    "email": rec.get("Email"),
                    "profile_id": rec.get("ProfileId"),
                    "role_id": rec.get("UserRoleId"),
                    "user_type": rec.get("UserType"),
                    "language": rec.get("LanguageLocaleKey"),
                    "locale": rec.get("LocaleSidKey"),
                    "timezone": rec.get("TimeZoneSidKey"),
                    "org_id": user_info.get("org_id") or info.get("org", {}).get("Id"),
                }
                for k, v in soql_user.items():
                    if v is not None and not user_info.get(k):
                        user_info[k] = v
            elif not user_info:
                info["warnings"].append("User query returned no records for the current session user.")
    except Exception as e:
        if not user_info:
            info["errors"].append(f"User SOQL: {_clean_exception_text(str(e))}")

    if user_info:
        info["user"] = {k: v for k, v in user_info.items() if v is not None}
    else:
        info["warnings"].append(
            "Unable to fully resolve current user details from this authentication mode."
        )
        if identity_attempt_errors:
            info["warnings"].append("User resolution attempts: " + " | ".join(identity_attempt_errors[:3]))

    return info


# ------------------------------------------------------------
# Main Page
# ------------------------------------------------------------
st.title("👤 Session Information")
st.caption("Detailed information about your current Salesforce session and connection.")

btn_spacer, btn_col1 = st.columns([4, 1])

with btn_col1:
    if st.button("🔄 Refresh Data", width="stretch", type="secondary"):
        st.cache_data.clear()
        st.rerun()

st.divider()

with st.spinner("Fetching session information from Salesforce..."):
    info = fetch_session_info(sf)

if info.get("warnings"):
    with st.expander(f"⚠️ Warnings ({len(info['warnings'])})", expanded=False):
        for w in info["warnings"]:
            st.warning(w)

if info.get("errors"):
    with st.expander(f"🔴 Errors ({len(info['errors'])})", expanded=False):
        for e in info["errors"]:
            st.error(e)

user = info.get("user", {})
org = info.get("org", {})
identity = info.get("identity", {})

user_name = user.get("name") or identity.get("display_name") or identity.get("user_full_name") or "Unknown User"
org_name = org.get("Name") or "Unknown Org"

# ------------------------------------------------------------
# Overview Metrics
# ------------------------------------------------------------
st.subheader("📊 Session Overview")

m1, m2, m3, m4 = st.columns(4)
with m1:
    st.markdown(
        f'<div class="metric-container"><div class="metric-label">API Version</div>'
        f'<div class="metric-value">{_safe_html(info.get("api_version", "N/A"))}</div></div>',
        unsafe_allow_html=True,
    )
with m2:
    st.markdown(
        f'<div class="metric-container"><div class="metric-label">User</div>'
        f'<div class="metric-value" style="font-size:1.1rem;">{_safe_html(user_name)}</div></div>',
        unsafe_allow_html=True,
    )
with m3:
    st.markdown(
        f'<div class="metric-container"><div class="metric-label">Organization</div>'
        f'<div class="metric-value" style="font-size:1.1rem;">{_safe_html(org_name)}</div></div>',
        unsafe_allow_html=True,
    )
with m4:
    org_id_val = org.get("Id") or "N/A"
    st.markdown(
        f'<div class="metric-container"><div class="metric-label">Org ID</div>'
        f'<div class="metric-value" style="font-size:0.95rem;font-family:monospace;">{_safe_html(org_id_val)}</div></div>',
        unsafe_allow_html=True,
    )

st.markdown("<br>", unsafe_allow_html=True)

# ------------------------------------------------------------
# Connection Details
# ------------------------------------------------------------
with st.expander("🔗 Connection Details", expanded=False):
    conn_rows = [
        ("API Version", info.get("api_version", "N/A")),
        ("Client ID", info.get("client_id", "N/A")),
        ("Endpoint", info.get("endpoint", "N/A")),
        ("Instance", info.get("sf_instance", "N/A")),
        ("Domain", info.get("domain", "N/A")),
        ("Identity Source", info.get("identity_source", "unavailable")),
        ("Session ID", f'<span class="session-id">{_safe_html(info.get("session_id", "N/A"))}</span>', True),
    ]
    render_card("Connection", "🔗", conn_rows)

# ------------------------------------------------------------
# User Details
# ------------------------------------------------------------
with st.expander("👤 User Details", expanded=True):
    if user:
        field_defs = [
            ("name", "Name"),
            ("username", "Username"),
            ("email", "Email"),
            ("user_id", "User ID"),
            ("user_type", "User Type"),
            ("org_id", "Organization ID"),
            ("language", "Language"),
            ("locale", "Locale"),
            ("timezone", "Time Zone"),
            ("profile_id", "Profile ID"),
            ("role_id", "Role ID"),
            ("accessibility_mode", "Accessibility Mode"),
            ("chatter_external", "Chatter External"),
            ("currency_symbol", "Currency Symbol"),
            ("session_seconds_valid", "Session Seconds Valid"),
            ("user_default_currency_iso_code", "Default Currency"),
            ("user_ui_skin", "UI Skin"),
        ]

        user_rows = []
        seen = set()

        for key, label in field_defs:
            val = user.get(key)
            if val is not None and key not in seen:
                seen.add(key)
                if isinstance(val, bool):
                    user_rows.append((label, format_bool(val), True))
                else:
                    user_rows.append((label, val))

        for key, val in user.items():
            if key not in seen and val is not None and key not in {
                "sub", "picture", "zoneinfo", "email_verified", "address", "phone_number"
            }:
                label = key.replace("_", " ").title()
                if isinstance(val, bool):
                    user_rows.append((label, format_bool(val), True))
                else:
                    user_rows.append((label, val))

        render_card("User Profile", "👤", user_rows)
    else:
        render_card(
            "User Profile",
            "👤",
            [],
            error=(
                "Unable to retrieve user information. Identity lookup, OAuth userinfo, "
                "and current-user fallbacks did not return usable data."
            ),
        )

# ------------------------------------------------------------
# Organization Details
# ------------------------------------------------------------
with st.expander("🏢 Organization Details", expanded=True):
    if org:
        org_rows = []

        if identity:
            id_org_fields = [
                ("org_attachment_file_size_limit", "Attachment File Size Limit"),
                ("org_default_currency_locale", "Default Currency Locale"),
                ("org_disallow_html_attachments", "Disallow HTML Attachments"),
                ("org_has_person_accounts", "Has Person Accounts"),
            ]
            for key, label in id_org_fields:
                v = identity.get(key)
                if v is not None:
                    if isinstance(v, bool):
                        org_rows.append((label, format_bool(v), True))
                    else:
                        org_rows.append((label, v))

        field_map = {
            "Id": "Organization ID",
            "Name": "Organization Name",
            "OrganizationType": "Type",
            "InstanceName": "Instance",
            "IsSandbox": "Sandbox",
            "NamespacePrefix": "Namespace Prefix",
        }

        for key, label in field_map.items():
            v = org.get(key)
            if v is not None:
                if isinstance(v, bool):
                    org_rows.append((label, format_bool(v), True))
                else:
                    org_rows.append((label, v if v != "" else "(none)"))

        ns = identity.get("organization_namespace")
        if ns is not None:
            org_rows.append(("Namespace", ns if ns else "(none)"))

        render_card("Organization", "🏢", org_rows)
    else:
        render_card("Organization", "🏢", [], error="Unable to retrieve organization information.")

# ------------------------------------------------------------
# Session & Metadata
# ------------------------------------------------------------
with st.expander("⚙️ Session & Metadata", expanded=False):
    meta_rows = []

    if identity:
        for key, label in [
            ("partial_save_allowed", "Partial Save Allowed"),
            ("test_required", "Test Required"),
        ]:
            val = identity.get(key)
            if val is not None:
                meta_rows.append((label, format_bool(val), True))

    meta_rows.extend([
        ("Instance", info.get("sf_instance", "N/A")),
        ("Domain", info.get("domain", "N/A")),
        ("Identity Source", info.get("identity_source", "unavailable")),
        ("Session ID", f'<span class="session-id">{_safe_html(info.get("session_id", "N/A"))}</span>', True),
        ("API Version", info.get("api_version", "N/A")),
        ("Status", "<span class='badge badge-success'>Connected</span>", True),
    ])

    render_card("Session & Metadata", "⚙️", meta_rows)

# ------------------------------------------------------------
# Raw JSON (safe display)
# ------------------------------------------------------------
with st.expander("📄 Raw Data (JSON)", expanded=False):
    st.json(info, expanded=False)

# ------------------------------------------------------------
# Footer
# ------------------------------------------------------------
st.divider()
footer_html = f"""
<div class="footer-panel">
    <div class="footer-item"><span class="footer-icon">📅</span><span><strong>Data fetched at:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</span></div>
    <div class="footer-item"><span class="footer-icon">🔗</span><span><strong>Connected to:</strong> {user_name.upper()} AT {org_name} ON API {info.get('api_version', 'N/A')}</span></div>
</div>
"""
st.markdown(footer_html, unsafe_allow_html=True)
