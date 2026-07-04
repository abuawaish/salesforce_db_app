import streamlit as st
from simple_salesforce import Salesforce
import time
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
    initial_sidebar_state="expanded"
)

st.title("⚙️ Salesforce Connection")
st.caption("Connect to your Salesforce org using your username and password.")

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
    env = st.radio(
        "Environment",
        options=["Production", "Sandbox"],
        index=0,
        help="Choose 'Production' for your live org, or 'Sandbox' for a developer/test sandbox."
    )

    if env == "Production":
        st.info("ℹ️ **Hint:** Use 'Sandbox' if you are connecting to a developer sandbox (test.salesforce.com).")
    else:
        st.info("ℹ️ **Hint:** Use 'Production' if you are connecting to a live org (login.salesforce.com).")

    username = st.text_input(
        "Salesforce Username",
        placeholder="your.email@company.com"
    )
    password = st.text_input(
        "Password",
        type="password",
        placeholder="Your Salesforce password"
    )

    # Optional security token – visible but clearly optional
    security_token = st.text_input(
        "Security Token (optional)",
        type="password",
        placeholder="Paste your security token here, or leave blank",
        help=(
            "Required only if your Salesforce org enforces IP restrictions. "
            "Get it via: Salesforce → Settings → My Personal Information → Reset My Security Token. "
            "If your IP is already trusted/whitelisted in Salesforce, leave this blank."
        )
    )

    st.markdown(
        """<div class="info-box">
        💡 <strong>No security token?</strong> Leave it blank if your IP address is trusted in Salesforce
        (Setup → Network Access). Otherwise reset your token via
        <em>Settings → My Personal Information → Reset My Security Token</em>.
        </div>""",
        unsafe_allow_html=True
    )
    st.write("")  # spacing

    if st.session_state.get("config_ok") and "sf" in st.session_state:
        action = st.form_submit_button("🔌 Disconnect", width="stretch")
    else:
        action = st.form_submit_button("🔌 Test Connection", width="stretch")

# ------------------------------------------------------------
# Handle connection test or disconnect
# ------------------------------------------------------------
if action:
    if st.session_state.get("config_ok") and "sf" in st.session_state:
        st.session_state["config_ok"] = False
        st.session_state.pop("sf", None)
        st.session_state.pop("username", None)
        st.session_state.pop("profile_name", None)
        st.session_state.pop("can_modify_schema", None)
        st.session_state.pop("access_mode", None)
        st.toast("Successfully disconnected from the Salesforce org.", icon="✅")
        time.sleep(1.5)
        st.rerun()
    elif not username or not password:
        st.error("❌ Please enter both username and password.")
    else:
        try:
            with st.spinner("Connecting to Salesforce..."):
                domain = "login" if env == "Production" else "test"

                # simple_salesforce requires security_token to be a non-None string.
                # Passing "" works for IP-whitelisted orgs (token is simply not appended).
                sf = Salesforce(
                    username=username,
                    password=password,
                    security_token=security_token.strip() if security_token else "",
                    domain=domain,
                )
                # Lightweight sanity-check call
                sf.describe()

            # Store connection in session state
            st.session_state["sf"] = sf
            st.session_state["config_ok"] = True
            st.session_state["username"] = username

            # Look up the connected user's REAL Salesforce permissions.
            # This — not any button in this app — is what decides whether
            # schema-changing pages (Object Manager) are available.
            perm_profile = load_permission_profile(sf, username)
            st.session_state["profile_name"] = perm_profile["profile_name"]
            st.session_state["can_modify_schema"] = perm_profile["can_modify_schema"]
            init_access_mode()

            st.toast(
                f"Connected successfully! Authenticated to {env} as {username} "
                f"(Profile: {perm_profile['profile_name']})",
                icon="✅",
            )
            time.sleep(1.5)
            st.rerun()

        except Exception as e:
            # Clear any previous connection
            st.session_state["config_ok"] = False
            st.session_state.pop("sf", None)

            err_str = str(e)

            st.markdown(
                f"""
                <div class="error-box">
                    ❌ <strong>Connection failed</strong><br>
                    <span style="font-size:0.9rem;">{err_str}</span>
                </div>
                """,
                unsafe_allow_html=True
            )

            # Targeted troubleshooting hints
            if "INVALID_LOGIN" in err_str:
                st.warning(
                    "🔍 **Troubleshooting – Invalid Login:**\n"
                    "- Double-check your username and password.\n"
                    "- If your org enforces IP restrictions, add a Security Token above.\n"
                    "- For sandbox accounts make sure you selected **Sandbox**.\n"
                    "- Accounts locked after too many attempts — check your email."
                )
            elif "security token" in err_str.lower():
                st.warning(
                    "🔍 **Troubleshooting – Security Token Required:**\n"
                    "- Your org requires a security token. Enter it in the **Security Token** field above.\n"
                    "- Reset it via: Salesforce → Settings → My Personal Information → Reset My Security Token."
                )
            elif "UNKNOWN" in err_str or "404" in err_str or "Could not connect" in err_str:
                st.warning(
                    "🔍 **Troubleshooting – Wrong Environment:**\n"
                    "- Verify you selected the correct **Environment** (Production vs Sandbox).\n"
                    "- Check that your Salesforce org URL matches the selected environment."
                )
            else:
                st.warning(
                    "🔍 **General troubleshooting:**\n"
                    "- Verify your credentials and environment selection.\n"
                    "- Check that your IP is trusted or provide a Security Token."
                )

# ------------------------------------------------------------
# Persistent connection status banner
# ------------------------------------------------------------
if st.session_state.get("config_ok") and "sf" in st.session_state:
    st.markdown(
        f"""
        <div class="success-box" style="margin-top: 20px;">
            ✅ <strong>Currently connected</strong> as <code>{st.session_state.get('username', '')}</code>
        </div>
        """,
        unsafe_allow_html=True
    )
    render_access_mode_toggle()
elif not action:
    st.caption("Fill in your credentials above and click 'Test Connection' to authenticate.")