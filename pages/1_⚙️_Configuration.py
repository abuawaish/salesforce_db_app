import html
import streamlit as st
import time
from configuration import (
    API_VERSIONS,
    SalesforceAuthError,
    connect,
)
from permissions import (
    init_access_mode,
    load_permission_profile,
    render_access_mode_toggle,
)

# ------------------------------------------------------------
# Page Configuration
# ------------------------------------------------------------
st.set_page_config(
    page_title="Salesforce Configuration",
    page_icon="⚙️",
    layout="wide",
    initial_sidebar_state="auto"
)

st.title(":material/settings: Salesforce Connection")
st.caption(
    "Connect to your Salesforce org with an External Client App using the "
    "OAuth 2.0 Client Credentials flow."
)

# ------------------------------------------------------------
# Custom CSS
# ------------------------------------------------------------
st.markdown("""
<style>
    .stButton button {
        transition: all 0.2s ease;
        border-radius: 8px;
        font-weight: 600;
    }
    .stButton button:hover {
        transform: scale(1.02);
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    }
    .success-box {
        padding: 12px 16px;
        background-color: #d4edda;
        border-left: 6px solid #28a745;
        border-radius: 6px;
        color: #155724;
        font-weight: 500;
        margin-top: 8px;
    }
    .error-box {
        padding: 12px 16px;
        background-color: #f8d7da;
        border-left: 6px solid #dc3545;
        border-radius: 6px;
        color: #721c24;
        font-weight: 500;
        margin-top: 8px;
        margin-bottom: 12px;
    }
    .info-box {
        padding: 10px 14px;
        background-color: #e8f4fd;
        border-left: 5px solid #3498db;
        border-radius: 6px;
        color: #1a5276;
        font-size: 0.88rem;
        margin-top: 6px;
    }
</style>
""", unsafe_allow_html=True)

# ------------------------------------------------------------
# Input fields
# ------------------------------------------------------------
with st.form("config_form"):
    # Environment selection
    col1, col2 = st.columns([5, 2])
    with col1:
        env = st.radio(
            "Environment",
            options=["Production", "Sandbox"],
            index=0,
            help="Choose 'Production' for your live org, or 'Sandbox' for a developer/test sandbox."
        )
    with col2:
        api_version = st.selectbox(
            "API Version",
            options=API_VERSIONS,
            index=len(API_VERSIONS) - 1,
            help=(
                "API version used for REST, Bulk and Metadata calls. "
                "This does not affect authentication — the Client Credentials "
                "flow is version-independent."
            )
        )

    if env == "Production":
        st.info(":material/info: **Hint:** Use 'Sandbox' if the External Client App lives in a developer sandbox (test.salesforce.com).")
    else:
        st.info(":material/info: **Hint:** Use 'Production' if the External Client App lives in a live org (login.salesforce.com).")

    login_host = st.text_input(
        "My Domain login host",
        placeholder="acme.my.salesforce.com",
        help=(
            "Salesforce only accepts the Client Credentials grant on your org's "
            "My Domain. Find it in Setup → Company Settings → My Domain.\n\n"
            "Production: acme.my.salesforce.com\n"
            "Sandbox: acme--dev.sandbox.my.salesforce.com\n\n"
            "Pasting the full token URL is fine — the scheme and "
            "/services/oauth2/token suffix are stripped automatically."
        ),
    )

    consumer_key = st.text_input(
        "Client ID (Consumer Key)",
        placeholder="3MVG9...",
        help=(
            "From Salesforce Setup → External Client Apps → your app → "
            "OAuth Settings. 'Client ID' and 'Consumer Key' are the same value."
        ),
    )
    consumer_secret = st.text_input(
        "Client Secret (Consumer Secret)",
        type="password",
        placeholder="Paste the Consumer Secret",
        help=(
            "Shown once when the app's credentials are created. If you no "
            "longer have it, use 'Rotate Consumer Secret' in the External "
            "Client App and paste the new value."
        ),
    )

    st.markdown(
        """<div class="info-box">
        💡 <strong>Before you connect:</strong> in the External Client App's OAuth settings, enable
        <em>Client Credentials Flow</em> and assign a <em>Run As</em> user with the
        <strong>API Enabled</strong> permission. Client credentials tokens carry no refresh token —
        this app requests a new one automatically when the old one expires.
        </div>""",
        unsafe_allow_html=True
    )
    st.write("")  # spacing

    if st.session_state.get("config_ok") and "sf" in st.session_state:
        action = st.form_submit_button(":material/exit_to_app: Disconnect", width="content", type="primary")
    else:
        action = st.form_submit_button(":material/plug_connect: Connect", width="content", type="primary")

# ------------------------------------------------------------
# Handle connection or disconnect
# ------------------------------------------------------------
_CONNECTION_STATE_KEYS = (
    "sf", "username", "display_name", "user_id", "org_id", "instance_url",
    "environment", "api_version", "auth_flow", "profile_name",
    "can_modify_schema", "access_mode",
)


def _clear_connection_state() -> None:
    """Drop every trace of a previous connection after a failed attempt, so a
    stale profile/permission flag can never outlive the session it came from.
    Widget values are deliberately kept, so the user can fix a typo and retry.
    """
    for key in _CONNECTION_STATE_KEYS:
        st.session_state.pop(key, None)
    st.session_state["config_ok"] = False


if action:
    if st.session_state.get("config_ok") and "sf" in st.session_state:
        # Clear everything: connection, caches, editor drafts, chat history,
        # widget state (including any lingering credential inputs). A new
        # connection — possibly to a different org — must never see stale state.
        st.session_state.clear()
        st.toast("Successfully disconnected from the Salesforce org.", icon=":material/task_alt:")
        time.sleep(1.5)
        st.rerun()
    elif not consumer_key or not consumer_secret:
        st.toast("Please enter both the Client ID and Client Secret.", icon=":material/error:")
    elif not login_host.strip():
        st.toast(
            "Enter your My Domain login host — Salesforce rejects Client "
            "Credentials on login.salesforce.com and test.salesforce.com.",
            icon=":material/error:",
        )
    else:
        try:
            with st.spinner("Requesting an access token..."):
                conn = connect(
                    consumer_key,
                    consumer_secret,
                    environment=env,
                    api_version=api_version,
                    login_host=login_host,
                )

            # Resolve the Run As user's real Salesforce permissions. With
            # client credentials there is no interactive login, so look the
            # user up by the Id carried in the token's identity URL.
            perm_profile = load_permission_profile(
                conn.sf,
                user_id=conn.user_id or None,
                username=conn.username or None,
            )

            # Drop any stale state from a previous session, then store the new
            # connection. This also wipes the Client ID/Secret widget values,
            # so neither credential lingers in session state after auth — the
            # secret is only reachable through the connection object's
            # refresh closure.
            st.session_state.clear()
            st.session_state["sf"] = conn.sf
            st.session_state["config_ok"] = True
            st.session_state["username"] = conn.username or conn.display_name
            st.session_state["display_name"] = conn.display_name
            st.session_state["user_id"] = conn.user_id
            st.session_state["org_id"] = conn.org_id
            st.session_state["instance_url"] = conn.instance_url
            st.session_state["environment"] = conn.environment
            st.session_state["api_version"] = conn.api_version
            st.session_state["auth_flow"] = "OAuth 2.0 Client Credentials"
            st.session_state["profile_name"] = perm_profile["profile_name"]
            st.session_state["can_modify_schema"] = perm_profile["can_modify_schema"]
            init_access_mode()

            st.toast(
                f"Connected to {conn.environment} as {conn.display_name or conn.username} "
                f"(Profile: {perm_profile['profile_name']})",
                icon=":material/task_alt:",
            )
            time.sleep(1.5)
            st.rerun()

        except SalesforceAuthError as e:
            _clear_connection_state()

            st.markdown(
                f"""
                <div class="error-box">
                    ❌ <strong>Connection failed</strong><br>
                    <span style="font-size:0.9rem;">{html.escape(str(e))}</span>
                </div>
                """,
                unsafe_allow_html=True
            )
            if e.hint:
                st.warning(f":material/troubleshoot: **How to fix it:** {e.hint}")

        except Exception as e:
            # Clear any previous connection state (same as the auth-error path)
            _clear_connection_state()

            st.markdown(
                f"""
                <div class="error-box">
                    ❌ <strong>Connection failed</strong><br>
                    <span style="font-size:0.9rem;">{html.escape(str(e))}</span>
                </div>
                """,
                unsafe_allow_html=True
            )
            st.warning(
                ":material/troubleshoot: **General troubleshooting:**\n"
                "- Verify the Client ID and Client Secret come from the same External Client App.\n"
                "- Confirm the Environment matches where the app is defined (Production vs Sandbox).\n"
                "- Check that Client Credentials Flow is enabled and a Run As user is assigned."
            )

# ------------------------------------------------------------
# Persistent connection status banner
# ------------------------------------------------------------
if st.session_state.get("config_ok") and "sf" in st.session_state:
    st.markdown(
        f"""
        <div class="success-box" style="margin-top: 20px;">
            ✅ <strong>Currently connected</strong> as <code>{html.escape(st.session_state.get('username', ''))}</code>
            &nbsp;·&nbsp; {html.escape(st.session_state.get('environment', ''))}
            &nbsp;·&nbsp; API v{html.escape(st.session_state.get('api_version', ''))}
            <br><span style="font-size:0.82rem;">{html.escape(st.session_state.get('auth_flow', ''))} · {html.escape(st.session_state.get('instance_url', ''))}</span>
        </div>
        """,
        unsafe_allow_html=True
    )
    render_access_mode_toggle()
elif not action:
    st.caption("Fill in your External Client App credentials above and click 'Connect' to authenticate.")