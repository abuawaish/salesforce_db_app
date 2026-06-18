import streamlit as st

# ------------------------------------------------------------
# Page Configuration
# ------------------------------------------------------------
st.set_page_config(
    page_title="Salesforce Data Query",
    page_icon="⛁",
    layout="centered",
    initial_sidebar_state="expanded"
)

# ------------------------------------------------------------
# Custom CSS (Hero + Sidebar + Dark Theme)
# ------------------------------------------------------------
st.markdown("""
<style>
    /* ========== SIDEBAR STYLING (NEW) ========== */
    section[data-testid="stSidebar"] {
        background-color: #080808;
        border-right: 1px solid #1a1a1a;
        padding-top: 1.5rem;
    }

    /* Sidebar navigation container */
    div[data-testid="stSidebarNav"] {
        padding: 0 0.75rem;
    }

    /* Individual nav items */
    div[data-testid="stSidebarNav"] li a {
        color: #c0c0c0 !important;
        font-weight: 500;
        font-size: 0.95rem;
        padding: 0.6rem 1rem !important;
        border-radius: 10px !important;
        transition: all 0.25s ease;
        margin: 3px 0;
        border-left: 3px solid transparent;
        display: flex;
        align-items: center;
        gap: 8px;
        text-decoration: none !important;
    }

    /* Hover effect */
    div[data-testid="stSidebarNav"] li a:hover {
        background-color: #161616 !important;
        color: #FFFFFF !important;
        border-left-color: #FFA500;
        transform: translateX(4px);
    }

    /* Active page highlight */
    div[data-testid="stSidebarNav"] li a[aria-current="page"] {
        background-color: #1a0f00 !important;
        color: #FFA500 !important;
        font-weight: 600;
        border-left: 4px solid #FFA500;
        box-shadow: inset 0 1px 3px rgba(255, 165, 0, 0.15);
    }

    /* Sidebar divider line below header */
    .sidebar-header-line {
        border: none;
        height: 2px;
        background: linear-gradient(to right, #FFA500, #2a1500, transparent);
        margin: 0.5rem 0 1.2rem 0;
        opacity: 0.6;
    }

    /* Custom sidebar title */
    .sidebar-app-title {
        color: #FFA500;
        font-size: 1.3rem;
        font-weight: 700;
        padding: 0 0.5rem 0 0.5rem;
        letter-spacing: -0.5px;
        display: flex;
        align-items: center;
        gap: 10px;
    }
    .sidebar-app-title span {
        background: rgba(255, 165, 0, 0.12);
        padding: 2px 10px;
        border-radius: 20px;
        font-size: 0.7rem;
        font-weight: 400;
        color: #aaa;
    }

    /* ========== HERO SECTION ========== */
    .hero-container {
        background-color: #000000;
        padding: 2rem 2rem 1.2rem 2rem;
        border-radius: 16px;
        border-left: 6px solid #FFA500;
        margin-bottom: 2rem;
        box-shadow: 0 4px 12px rgba(255, 165, 0, 0.10);
        transition: box-shadow 0.3s ease;
    }
    .hero-container:hover {
        box-shadow: 0 8px 24px rgba(255, 165, 0, 0.20);
    }
    .hero-title {
        color: #FFA500 !important;
        font-weight: 700 !important;
        font-size: 2.8rem;
        margin-bottom: 4px !important;
        line-height: 1.2;
    }
    .hero-sub {
        color: #ffffff !important;
        font-size: 1.2rem;
        margin-bottom: 6px !important;
        font-weight: 400;
    }
    .hero-caption {
        color: #aaaaaa !important;
        font-size: 0.9rem;
        margin-top: 4px;
    }

    /* ========== FEATURE CARDS ========== */
    .main-card {
        background-color: #000000;
        padding: 24px 20px 20px 20px;
        border-radius: 16px;
        box-shadow: 0 4px 12px rgba(255, 165, 0, 0.12);
        border: 1px solid #333333;
        height: 100%;
        transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;
    }
    .main-card:hover {
        transform: translateY(-3px);
        box-shadow: 0 12px 28px rgba(255, 165, 0, 0.25);
        border-color: #FFA500;
    }
    .main-card h4 {
        color: #FFA500 !important;
        font-weight: 700 !important;
        margin-top: 0;
        font-size: 1.2rem;
    }
    .main-card p {
        color: #ffffff !important;
        font-size: 0.95rem;
        line-height: 1.5;
    }
    .main-card .feature-icon {
        font-size: 2.8rem;
        margin-bottom: 12px;
        display: block;
    }
    .main-card strong {
        color: #FFA500;
        font-weight: 700;
    }

    /* ========== STEP CONTAINERS ========== */
    .step-container {
        background-color: #000000;
        padding: 24px 28px;
        border-radius: 16px;
        border-left: 6px solid #FFA500;
        box-shadow: 0 2px 8px rgba(255, 165, 0, 0.08);
        height: 100%;
        transition: box-shadow 0.2s ease;
    }
    .step-container:hover {
        box-shadow: 0 8px 20px rgba(255, 165, 0, 0.15);
    }
    .step-container h4 {
        color: #FFA500 !important;
        font-weight: 700 !important;
        margin-top: 0;
        font-size: 1.15rem;
    }
    .step-container p {
        color: #ffffff !important;
        font-size: 0.95rem;
        line-height: 1.6;
        margin-bottom: 0;
    }
    .step-container strong {
        color: #FFA500;
        font-weight: 700;
    }
    .step-container em {
        color: #dddddd;
    }

    /* ========== STATUS BADGES ========== */
    .status-badge {
        padding: 4px 14px;
        border-radius: 20px;
        font-weight: 600;
        font-size: 0.9rem;
        display: inline-block;
    }
    .badge-connected {
        background-color: #d4edda;
        color: #155724;
    }
    .badge-disconnected {
        background-color: #f8d7da;
        color: #721c24;
    }

    /* ========== STATUS MESSAGE ========== */
    .status-message {
        color: #ffffff !important;
        font-size: 0.95rem;
        font-weight: 500;
        padding-top: 4px;
        line-height: 1.5;
    }
    .status-message strong {
        color: #FFA500 !important;
        font-weight: 700;
    }

    .custom-divider {
        margin: 2rem 0;
        border: 0;
        height: 1px;
        background: linear-gradient(to right, #333333, #555555, #333333);
    }
</style>
""", unsafe_allow_html=True)

# ============================================================
# SIDEBAR: Custom Header (Optional visual enhancement)
# ============================================================
# Streamlit's default sidebar nav will show: 
#   Configuration, Salesforce SOQL Editor, Field Analysis
# We add a custom title at the top of the sidebar using st.sidebar.markdown.
st.sidebar.markdown("""
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
    <div class="hero-title">🗐 Salesforce Data Query & Editor</div>
    <div class="hero-sub">Run powerful SOQL queries and edit your data inline — all from your browser.</div>
    <div class="hero-caption">Built with Streamlit · simple-salesforce · Standard REST API</div>
</div>
""", unsafe_allow_html=True)

st.markdown('<hr class="custom-divider">', unsafe_allow_html=True)

# ============================================================
# FEATURE CARDS (3 columns)
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
# HOW TO USE (2 Steps)
# ============================================================
st.subheader("🚀 How to Get Started")

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
status_col1, status_col2 = st.columns([1, 6])

with status_col1:
    if "sf" in st.session_state and st.session_state.get("config_ok"):
        st.markdown('<span class="status-badge badge-connected">✅ Connected</span>', unsafe_allow_html=True)
    else:
        st.markdown('<span class="status-badge badge-disconnected">⛔ Not Connected</span>', unsafe_allow_html=True)

with status_col2:
    if "sf" in st.session_state and st.session_state.get("config_ok"):
        st.markdown(
            '<div class="status-message">Your session is active. You can now use the <strong>Salesforce SOQL Editor</strong> to manage your Salesforce data.</div>',
            unsafe_allow_html=True
        )
    else:
        st.markdown(
            '<div class="status-message">Please configure your Salesforce connection using the sidebar to unlock all features.</div>',
            unsafe_allow_html=True
        )