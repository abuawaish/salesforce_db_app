import streamlit as st

# ------------------------------------------------------------
# Page Configuration
# ------------------------------------------------------------
st.set_page_config(
    page_title="Salesforce Data Query",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ------------------------------------------------------------
# FORCE REFRESH: increment this number to bust cache
# ------------------------------------------------------------
# v2

st.markdown("""
<style>

/* ==========================================================
   GLOBAL VARIABLES
========================================================== */
:root {
    --accent: #FFA500;
    --bg-black: #000000;
    --bg-dark: #080808;
    --bg-card: #0d0d0d;
    --text-white: #FFFFFF;
    --text-muted: #AAAAAA;
    --border: #333333;
}

/* ==========================================================
   MAIN APP BACKGROUND
========================================================== */
.stApp {
    background-color: var(--bg-black);
}

/* ==========================================================
   SIDEBAR
========================================================== */

section[data-testid="stSidebar"] {
    background-color: var(--bg-dark) !important;
    border-right: 1px solid #1a1a1a !important;
}

/* ==========================================================
   SIDEBAR TEXT → Make all text white by default
========================================================== */

[data-testid="stSidebar"] * {
    color: #FFFFFF !important;
}

/* But keep the title orange – override the above */
.sidebar-app-title {
    color: var(--accent) !important;
}
.sidebar-app-title span {
    color: #FFFFFF !important;   /* version badge white */
}

/* ==========================================================
   NAVIGATION LINKS (already white, but reinforce)
========================================================== */

[data-testid="stSidebarNav"] a {
    color: #FFFFFF !important;
    border-radius: 12px !important;
    padding: 0.75rem 1rem !important;
    text-decoration: none !important;
    border-left: 3px solid transparent !important;
    transition: all .25s ease !important;
    font-weight: 500 !important;
}

[data-testid="stSidebarNav"] a:hover {
    background: #161616 !important;
    border-left-color: var(--accent) !important;
    transform: translateX(4px);
}

[data-testid="stSidebarNav"] a[aria-current="page"] {
    background: rgba(255,165,0,0.12) !important;
    border-left: 4px solid var(--accent) !important;
    box-shadow: inset 0 0 8px rgba(255,165,0,0.15);
    color: var(--accent) !important;
    font-weight: 600 !important;
}

/* ==========================================================
   SIDEBAR BRANDING
========================================================== */

.sidebar-app-title {
    color: var(--accent);
    font-size: 1.4rem;
    font-weight: 700;
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: .75rem;
}

.sidebar-app-title span {
    background: rgba(255,165,0,.15);
    padding: 3px 10px;
    border-radius: 999px;
    font-size: .75rem;
    color: #FFFFFF !important;
}

.sidebar-header-line {
    border: none;
    height: 1px;
    background: linear-gradient(
        to right,
        var(--accent),
        rgba(255,165,0,.25),
        transparent
    );
    margin-bottom: 1rem;
}

/* ==========================================================
   HERO SECTION (unchanged)
========================================================== */

.hero-container {
    background-color: var(--bg-black);
    padding: 2rem;
    border-radius: 16px;
    border-left: 6px solid var(--accent);
    margin-bottom: 2rem;
    box-shadow: 0 4px 12px rgba(255,165,0,.12);
}
.hero-title {
    color: var(--accent);
    font-size: 2.8rem;
    font-weight: 700;
    margin-bottom: 6px;
}
.hero-sub {
    color: var(--text-white);
    font-size: 1.2rem;
}
.hero-caption {
    color: var(--text-muted);
    font-size: 0.9rem;
}

/* ==========================================================
   FEATURE CARDS (unchanged)
========================================================== */

.main-card {
    background-color: var(--bg-black);
    padding: 24px;
    border-radius: 16px;
    border: 1px solid var(--border);
    box-shadow: 0 4px 12px rgba(255,165,0,.12);
    height: 100%;
    transition: all .25s ease;
}
.main-card:hover {
    transform: translateY(-4px);
    border-color: var(--accent);
    box-shadow: 0 10px 24px rgba(255,165,0,.25);
}
.main-card h4 {
    color: var(--accent);
    margin-top: 0;
}
.main-card p {
    color: var(--text-white);
    line-height: 1.6;
}
.feature-icon {
    font-size: 2.8rem;
    display: block;
    margin-bottom: 12px;
}

/* ==========================================================
   STEP CARDS (unchanged)
========================================================== */

.step-container {
    background-color: var(--bg-black);
    padding: 24px;
    border-radius: 16px;
    border-left: 6px solid var(--accent);
    box-shadow: 0 2px 8px rgba(255,165,0,.08);
    transition: all .25s ease;
}
.step-container:hover {
    box-shadow: 0 8px 20px rgba(255,165,0,.15);
}
.step-container h4 {
    color: var(--accent);
}
.step-container p {
    color: var(--text-white);
    line-height: 1.6;
}

/* ==========================================================
   STATUS BADGES
========================================================== */

.status-badge {
    padding: 5px 14px;
    border-radius: 20px;
    font-weight: 600;
    display: inline-block;
}
.badge-connected {
    background: #d4edda;
    color: #155724;
}
.badge-disconnected {
    background: #f8d7da;
    color: #721c24;
}

/* ==========================================================
   LIGHT MODE OVERRIDES
========================================================== */

@media (prefers-color-scheme: light) {
    .stMarkdown h2 {
        color: #1a1a1a !important;
    }
}

/* ==========================================================
   STATUS MESSAGE
========================================================== */

.status-container {
    background-color: var(--bg-card);
    border-left: 4px solid var(--accent);
    padding: 10px 16px;
    border-radius: 10px;
}
.status-message {
    color: var(--text-white);
    margin: 0;
}
.status-message strong {
    color: var(--accent);
}

/* ==========================================================
   DIVIDERS
========================================================== */

.custom-divider {
    margin: 2rem 0;
    border: none;
    height: 1px;
    background: linear-gradient(
        to right,
        #333333,
        #555555,
        #333333
    );
}

</style>
""", unsafe_allow_html=True)

# ============================================================
# SIDEBAR: Custom Header (Optional)
# ============================================================
with st.sidebar:
    st.markdown("""
    <div class="sidebar-app-title">
        ⚡ Salesforce <span>v1.0</span>
    </div>
    <hr class="sidebar-header-line">
    """, unsafe_allow_html=True)

# ============================================================
# HERO SECTION
# ============================================================
st.markdown("""
<div class="hero-container">
    <div class="hero-title">📊 Salesforce Data Query & Editor</div>
    <div class="hero-sub">Run powerful SOQL queries and edit your data inline — all from your browser.</div>
    <div class="hero-caption">Built with Streamlit · simple-salesforce · Standard REST API</div>
</div>
""", unsafe_allow_html=True)

st.markdown('<hr class="custom-divider">', unsafe_allow_html=True)

# ============================================================
# FEATURE CARDS
# ============================================================
col1, col2, col3 = st.columns(3, gap="medium")

with col1:
    st.markdown("""
    <div class="main-card">
        <span class="feature-icon">🔍</span>
        <h4>Run SOQL Queries</h4>
        <p>
            Write any <strong>SELECT</strong> query against Salesforce objects. 
            Results are displayed instantly in a beautiful, sortable table.
        </p>
    </div>
    """, unsafe_allow_html=True)

with col2:
    st.markdown("""
    <div class="main-card">
        <span class="feature-icon">📋</span>
        <h4>Interactive Results</h4>
        <p>
            View your data with <strong>scrollable tables</strong>, column sorting, 
            and one-click CSV export for easy analysis.
        </p>
    </div>
    """, unsafe_allow_html=True)

with col3:
    st.markdown("""
    <div class="main-card">
        <span class="feature-icon">✏️</span>
        <h4>Inline DML</h4>
        <p>
            Edit records directly in the table. Perform <strong>Insert, Update, 
            and Delete</strong> operations with a simple checkbox and save button.
        </p>
    </div>
    """, unsafe_allow_html=True)

st.markdown('<hr class="custom-divider">', unsafe_allow_html=True)

# ============================================================
# HOW TO USE
# ============================================================
st.markdown("""
<h2 style="
    display: flex;
    align-items: center;
    gap: 12px;
    margin-top: 1.5rem;
    margin-bottom: 1rem;
">
    <span style="font-size: 2rem;">🚀</span>
    <span style="
        background: linear-gradient(135deg, #FFA500 0%, #FF8C00 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        font-size: 2rem;
        font-weight: 700;
    ">
        How to Get Started
    </span>
</h2>
""", unsafe_allow_html=True)

left_step, right_step = st.columns(2, gap="medium")

with left_step:
    st.markdown("""
    <div class="step-container" style="border-left-color: #FFA500;">
        <h4>⚙️ Step 1: Configuration</h4>
        <p>
            Use the sidebar to navigate to the <strong>Configuration</strong> page. 
            Enter your Salesforce credentials 
            (<em>Username, Password</em>) 
            and click <strong>"Test Connection"</strong>.
        </p>
    </div>
    """, unsafe_allow_html=True)

with right_step:
    st.markdown("""
    <div class="step-container" style="border-left-color: #FF8C00;">
        <h4>📊 Step 2: Query & Edit</h4>
        <p>
            Once connected, switch to the <strong>Salesforce SOQL Editor</strong> page. 
            Run your SOQL queries, view results, and edit or delete records 
            directly in the interactive data editor.
        </p>
    </div>
    """, unsafe_allow_html=True)

st.markdown('<hr class="custom-divider">', unsafe_allow_html=True)

# ============================================================
# FOOTER / CONNECTION STATUS
# ============================================================
is_connected = "sf" in st.session_state and st.session_state.get("config_ok")

if is_connected:
    badge_html = '<span class="status-badge badge-connected">🟢 Connected</span>'
    message_text = 'Your session is active. You can now use the <strong>Salesforce SOQL Editor</strong> to manage your Salesforce data.'
else:
    badge_html = '<span class="status-badge badge-disconnected">🔴 Not Connected</span>'
    message_text = 'Please configure your Salesforce connection using the sidebar to unlock all features.'

st.markdown(f"""
<div style="display: flex; align-items: center; gap: 12px;">
    {badge_html}
    <div class="status-container" style="flex: 1; margin: 0;">
        <p class="status-message">{message_text}</p>
    </div>
</div>
""", unsafe_allow_html=True)