"""
Shared permission helpers for salesforce_db_app.

Security model
---------------
The *authoritative* boundary is always Salesforce itself: a user whose
profile lacks "Modify All Data" / "Customize Application" will get a real
Salesforce API error if they attempt a schema change, no matter what this
app does client-side. A pure client-side toggle (e.g. a radio button
anyone can flip to "Admin") would NOT be real security — it's just a
button.

So this module does two things:

1. Right after login, it looks up the connected user's *actual* Salesforce
   permissions (`load_permission_profile`). This is the real gate.
2. It adds an app-level "Access Mode" toggle on top of that, defaulting
   everyone — even real admins — to Read-Only. Admins have to deliberately
   switch into Admin mode. Non-admins never see the toggle, since it
   wouldn't do anything for them anyway.

Import this from any page that needs to gate a feature:

    from permissions import require_admin_mode
    require_admin_mode("Object Manager")
"""

import streamlit as st


def load_permission_profile(sf, username: str) -> dict:
    """
    Query the connected user's real Salesforce permissions.
    Call this once, immediately after a successful login.
    """
    safe_username = username.replace("'", r"\'")
    query = f"""
        SELECT Id, Profile.Name,
               Profile.PermissionsModifyAllData,
               Profile.PermissionsCustomizeApplication
        FROM User
        WHERE Username = '{safe_username}'
        LIMIT 1
    """
    result = sf.query(query)

    if not result.get("records"):
        # Shouldn't happen for the user who just logged in — fail safe.
        return {"profile_name": "Unknown", "can_modify_schema": False}

    profile = result["records"][0].get("Profile") or {}
    can_modify_schema = bool(
        profile.get("PermissionsModifyAllData")
        or profile.get("PermissionsCustomizeApplication")
    )
    return {
        "profile_name": profile.get("Name", "Unknown"),
        "can_modify_schema": can_modify_schema,
    }


def init_access_mode() -> None:
    """
    Call once right after login. Everyone starts Read-Only, including
    users whose Salesforce profile *does* allow schema changes — they
    have to explicitly opt in via the sidebar toggle.
    """
    st.session_state.setdefault("access_mode", "Read-Only")


def render_access_mode_toggle() -> None:
    """
    Sidebar control. Only rendered for users whose real Salesforce
    permissions allow schema changes. Non-admins just see a status
    caption — there's no toggle for them to flip because it wouldn't
    change anything: the underlying permission check would still fail.
    """
    can_modify = st.session_state.get("can_modify_schema", False)
    profile_name = st.session_state.get("profile_name", "Unknown")

    if not can_modify:
        st.sidebar.caption(
            f"👤 Profile: **{profile_name}**\n\n🔒 Read-Only — this profile has no schema-modification permission."
        )
        st.session_state["access_mode"] = "Read-Only"
        return

    current = st.session_state.get("access_mode", "Read-Only")
    mode = st.sidebar.radio(
        "Access Mode",
        options=["Read-Only", "Admin"],
        index=0 if current == "Read-Only" else 1,
        help=(
            f"Your Salesforce profile (**{profile_name}**) has schema-modification "
            "permissions. Switch to Admin to enable schema-changing pages here."
        ),
    )
    st.session_state["access_mode"] = mode

    if mode == "Admin":
        st.sidebar.warning("⚠️ Admin mode active — schema changes are enabled.")


def require_admin_mode(feature_name: str = "This feature") -> None:
    """
    Call at the very top of any page (or section) that performs schema
    changes or other destructive admin-only operations. Halts the page
    with `st.stop()` if the user isn't cleared to proceed.
    """
    can_modify = st.session_state.get("can_modify_schema", False)
    access_mode = st.session_state.get("access_mode", "Read-Only")
    profile_name = st.session_state.get("profile_name", "Unknown")

    if not can_modify:
        st.error(
            f"🔒 **{feature_name} requires schema-modification permissions.**\n\n"
            f"Your connected Salesforce user's profile (**{profile_name}**) has "
            "neither *Modify All Data* nor *Customize Application*. Ask your "
            "Salesforce admin to grant one of those if you need this page."
        )
        st.stop()

    if access_mode != "Admin":
        st.warning(
            f"🔒 **{feature_name} is admin-only.** "
            "Your profile allows it, but you're currently in Read-Only mode. "
            "Switch to **Admin** in the sidebar to continue."
        )
        st.stop()