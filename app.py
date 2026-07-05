import streamlit as st

# ------------------------------------------------------------
# Page Configuration
# ------------------------------------------------------------
st.set_page_config(
    page_title="Salesforce Data Query",
    page_icon="☁️",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>

/* ==========================================================
   GLOBAL VARIABLES
========================================================== */
:root {
    --accent: #FFA500;
    --accent-soft: rgba(255,165,0,.14);
    --sf-blue: #00A1E0;
    --success: #2ED9A3;
    --success-soft: rgba(46,217,163,.12);
    --danger: #FF6B6B;
    --danger-soft: rgba(255,107,107,.12);
    --bg-black: #000000;
    --bg-dark: #080808;
    --bg-card: #0d0d0d;
    --text-white: #FFFFFF;
    --text-muted: #A6A6A6;
    --border: #2a2a2a;
    --font-body: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    --font-mono: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;
}

/* ==========================================================
   MAIN APP BACKGROUND & TYPOGRAPHY
========================================================== */
.stApp {
    background-color: var(--bg-black);
    font-family: var(--font-body);
    zoom: 0.9;
}
.stApp p, .stApp li {
    font-family: var(--font-body);
    line-height: 1.7;
}
.stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5, .stApp h6 {
    font-family: var(--font-body);
}

/* ==========================================================
   SIDEBAR
========================================================== */

section[data-testid="stSidebar"] {
    background-color: var(--bg-dark) !important;
    border-right: 1px solid #1a1a1a !important;
}

[data-testid="stSidebar"] * {
    color: #FFFFFF !important;
}

.sidebar-app-title {
    color: var(--accent) !important;
}
.sidebar-app-title span {
    color: #FFFFFF !important;
    font-family: var(--font-mono);
}

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

[data-testid="stSidebarNav"] a:focus-visible,
a:focus-visible {
    outline: 2px solid var(--accent) !important;
    outline-offset: 2px;
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
   HERO SECTION
========================================================== */

.hero-container {
    background-color: var(--bg-black);
    padding: 2.2rem 2.4rem;
    border-radius: 16px;
    border-left: 6px solid var(--accent);
    box-shadow: 0 4px 12px rgba(255,165,0,.12);
    height: 100%;
}
.hero-eyebrow {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    font-family: var(--font-mono);
    font-size: .78rem;
    letter-spacing: .08em;
    text-transform: uppercase;
    color: var(--success);
    margin-bottom: 14px;
}
.hero-eyebrow .live-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--success);
    animation: pulseDot 1.8s infinite;
}
.hero-title {
    font-family: var(--font-body);
    color: var(--accent);
    font-size: 2.6rem;
    font-weight: 800;
    letter-spacing: -.01em;
    line-height: 1.2;
    margin-bottom: 10px;
}
.hero-sub {
    font-family: var(--font-body);
    color: var(--text-white);
    font-size: 1.12rem;
    line-height: 1.65;
    max-width: 46ch;
    margin-bottom: 14px;
}
.hero-caption {
    color: var(--text-muted);
    font-size: 0.85rem;
    font-family: var(--font-mono);
}

/* ==========================================================
   LIVE QUERY CONSOLE
========================================================== */

.console-panel {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 14px;
    overflow: hidden;
    height: 100%;
    box-shadow: 0 0 0 1px rgba(255,165,0,.05);
    animation: consoleGlow 4s ease-in-out infinite;
}
@keyframes consoleGlow {
    0%, 100% { box-shadow: 0 0 0 1px rgba(255,165,0,.05), 0 0 18px -6px rgba(255,165,0,.15); }
    50%      { box-shadow: 0 0 0 1px rgba(0,161,224,.08), 0 0 22px -4px rgba(0,161,224,.22); }
}
.console-header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 14px;
    background: #111111;
    border-bottom: 1px solid var(--border);
}
.console-dot {
    width: 10px; height: 10px; border-radius: 50%;
}
.dot-red { background: #FF5F56; }
.dot-yellow { background: #FFBD2E; }
.dot-green { background: #27C93F; }
.console-title {
    margin-left: 6px;
    font-family: var(--font-mono);
    font-size: .78rem;
    color: var(--text-muted);
}
.console-body {
    padding: 18px 18px 20px;
    min-height: 230px;
    overflow-x: hidden;
}
.console-line {
    font-family: var(--font-mono);
    font-size: .92rem;
    color: var(--text-white);
    white-space: nowrap;
}
.console-prompt {
    color: var(--sf-blue);
    margin-right: 8px;
}
.console-typed {
    display: inline-block;
    overflow: hidden;
    white-space: nowrap;
    width: 0;
    border-right: 2px solid var(--accent);
    vertical-align: bottom;
    animation: typeQuery 14s infinite steps(46), blinkCursor .8s step-end infinite;
}
@keyframes typeQuery {
    0%       { width: 0; }
    26%      { width: 46ch; }
    90%      { width: 46ch; }
    96%,100% { width: 0; }
}
@keyframes blinkCursor { 50% { border-color: transparent; } }

.console-meta {
    font-family: var(--font-mono);
    font-size: .78rem;
    color: var(--success);
    margin: 10px 0 12px;
    opacity: 0;
    animation: metaFade 14s infinite;
}
@keyframes metaFade {
    0%, 30% { opacity: 0; transform: translateY(4px); }
    35%     { opacity: 1; transform: translateY(0); }
    88%     { opacity: 1; }
    94%,100%{ opacity: 0; }
}

.console-table { font-family: var(--font-mono); font-size: .82rem; }
.console-row {
    display: flex;
    justify-content: space-between;
    gap: 14px;
    padding: 6px 4px;
    border-bottom: 1px solid #1c1c1c;
    color: var(--text-white);
    opacity: 0;
    transform: translateX(-8px);
}
.console-row-head {
    color: var(--text-muted);
    font-size: .72rem;
    text-transform: uppercase;
    letter-spacing: .04em;
    opacity: 1 !important;
    transform: none !important;
    border-bottom: 1px solid var(--border);
}
.r1 { animation: rowIn1 14s infinite; }
.r2 { animation: rowIn2 14s infinite; }
.r3 { animation: rowIn3 14s infinite; }
@keyframes rowIn1 {
    0%,38%   { opacity: 0; transform: translateX(-8px); }
    42%      { opacity: 1; transform: translateX(0); }
    88%      { opacity: 1; }
    94%,100% { opacity: 0; }
}
@keyframes rowIn2 {
    0%,46%   { opacity: 0; transform: translateX(-8px); }
    50%      { opacity: 1; transform: translateX(0); }
    88%      { opacity: 1; }
    94%,100% { opacity: 0; }
}
@keyframes rowIn3 {
    0%,54%   { opacity: 0; transform: translateX(-8px); }
    58%      { opacity: 1; transform: translateX(0); }
    88%      { opacity: 1; }
    94%,100% { opacity: 0; }
}
.editing {
    border: 1px solid var(--accent);
    border-radius: 6px;
    padding: 5px 6px !important;
    animation: rowIn3 14s infinite, editPulse 1.6s ease-in-out infinite;
}
@keyframes editPulse {
    0%,100% { box-shadow: 0 0 0 0 rgba(255,165,0,.35); }
    50%     { box-shadow: 0 0 0 4px rgba(255,165,0,0); }
}
.edit-pencil { color: var(--accent); margin-left: 6px; }

@media (max-width: 900px) {
    .console-line, .console-typed, .console-table { font-size: .66rem; }
}

.console-save {
    font-family: var(--font-mono);
    font-size: .8rem;
    color: var(--success);
    margin-top: 12px;
    opacity: 0;
    animation: saveIn 14s infinite;
}
@keyframes saveIn {
    0%,64%   { opacity: 0; transform: translateY(4px); }
    68%      { opacity: 1; transform: translateY(0); }
    88%      { opacity: 1; }
    94%,100% { opacity: 0; }
}

/* ==========================================================
   FEATURE CARDS
========================================================== */

.main-card {
    background-color: var(--bg-black);
    padding: 24px;
    border-radius: 16px;
    border: 1px solid var(--border);
    box-shadow: 0 4px 12px rgba(255,165,0,.12);
    height: 100%;
    transition: transform .25s ease, border-color .25s ease, box-shadow .25s ease;
    opacity: 0;
    animation: fadeInUp .6s ease-out forwards;
}
.main-card:hover {
    transform: translateY(-4px);
    border-color: var(--accent);
    box-shadow: 0 10px 24px rgba(255,165,0,.25);
}
.main-card:hover .feature-icon {
    transform: scale(1.12) rotate(-4deg);
}
.main-card h4 {
    color: var(--accent);
    margin-top: 0;
}
.main-card p {
    color: var(--text-white);
    line-height: 1.65;
}
.feature-icon {
    font-size: 2.8rem;
    display: block;
    margin-bottom: 12px;
    transition: transform .3s ease;
}

@keyframes fadeInUp {
    from { opacity: 0; transform: translateY(16px); }
    to   { opacity: 1; transform: translateY(0); }
}

/* ==========================================================
   STEP CARDS
========================================================== */

.step-container {
    background-color: var(--bg-black);
    padding: 24px;
    border-radius: 16px;
    border-left: 6px solid var(--accent);
    box-shadow: 0 2px 8px rgba(255,165,0,.08);
    transition: box-shadow .25s ease, transform .25s ease;
    opacity: 0;
    animation: fadeInUp .6s ease-out forwards;
}
.step-container:hover {
    box-shadow: 0 8px 20px rgba(255,165,0,.15);
    transform: translateY(-2px);
}
.step-container h4 {
    color: var(--accent);
}
.step-container p {
    color: var(--text-white);
    line-height: 1.65;
}
.step-number {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 22px; height: 22px;
    border-radius: 50%;
    background: var(--accent-soft);
    color: var(--accent);
    font-family: var(--font-mono);
    font-size: .75rem;
    font-weight: 700;
    margin-right: 8px;
}

/* ==========================================================
   STATUS BADGES — dark-mode native
========================================================== */
.status-badge {
    padding: 6px 16px;
    border-radius: 999px;
    font-weight: 600;
    font-size: .85rem;
    display: inline-flex;
    align-items: center;
    gap: 8px;
    font-family: var(--font-mono);
}
.status-badge .dot {
    width: 8px; height: 8px; border-radius: 50%;
}
.badge-connected {
    background: var(--success-soft);
    color: var(--success);
    border: 1px solid rgba(46,217,163,.35);
}
.badge-connected .dot {
    background: var(--success);
    animation: pulseDot 1.8s infinite;
}
.badge-disconnected {
    background: var(--danger-soft);
    color: var(--danger);
    border: 1px solid rgba(255,107,107,.35);
}
@keyframes pulseDot {
    0%   { box-shadow: 0 0 0 0 rgba(46,217,163,.5); }
    70%  { box-shadow: 0 0 0 7px rgba(46,217,163,0); }
    100% { box-shadow: 0 0 0 0 rgba(46,217,163,0); }
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

.status-header {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 1rem;
    flex-wrap: wrap;
}
.status-label {
    font-family: var(--font-mono);
    font-size: .86rem;
    font-weight: 700;
    letter-spacing: .12em;
    text-transform: uppercase;
    color: blue !important;
}
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

/* ==========================================================
   DIVIDER VISIBILITY
========================================================== */
.stMarkdown hr.custom-divider,
div[data-testid="stMarkdown"] hr.custom-divider {
    margin: 2rem 0 !important;
    border: none !important;
    height: 2px !important;
    background: linear-gradient(
        to right,
        #555555,
        #888888,
        #555555
    ) !important;
    opacity: 1 !important;
    visibility: visible !important;
    display: block !important;
    width: 100% !important;
}

/* ==========================================================
   ACCESSIBILITY: respect reduced-motion
========================================================== */
@media (prefers-reduced-motion: reduce) {
    * { animation-duration: 0.001ms !important; animation-iteration-count: 1 !important; }
    .console-typed { width: 46ch !important; border-right: none !important; }
    .console-meta, .console-row, .console-save { opacity: 1 !important; transform: none !important; }
    .main-card, .step-container { opacity: 1 !important; }
}

</style>
""", unsafe_allow_html=True)

#------------------------------------------------------------
# HEADER / CONNECTION STATUS BADGE
#-----------------------------------------------------------

is_connected = "sf" in st.session_state and st.session_state.get("config_ok")

if is_connected:
    badge_html = '<span class="status-badge badge-connected"><span class="dot"></span>Connected</span>'
    message_text = 'Your session is active. Head to the <strong>Salesforce SOQL Editor</strong> to query and manage your data.'
else:
    badge_html = '<span class="status-badge badge-disconnected"><span class="dot" style="background: var(--danger);"></span>Not Connected</span>'
    message_text = 'Configure your Salesforce connection from the sidebar to unlock every page.'

st.markdown(f"""
<div class="status-header">
    <span class="status-label">ORG STATUS</span>
    {badge_html}
</div>
""", unsafe_allow_html=True)

# ============================================================
# SIDEBAR: Custom Header (Optional)
# ============================================================
with st.sidebar:
    st.markdown("""
    <div class="sidebar-app-title">
        ⚡ Salesforce <span>v2.0</span>
    </div>
    <hr class="sidebar-header-line">
    """, unsafe_allow_html=True)

# ============================================================
# HERO SECTION — title/pitch on the left, a live animated
# SOQL console on the right that shows the app's whole loop
# (query → results → inline edit → save) without needing a
# real connection.
# ============================================================
hero_left, hero_right = st.columns([1.15, 1], gap="medium")

with hero_left:
    st.markdown("""
    <div class="hero-container">
        <div class="hero-eyebrow"><span class="live-dot"></span> Streamlit · simple-salesforce · REST API</div>
        <div class="hero-title">☁️ Salesforce Data Query &amp; Editor</div>
        <div class="hero-sub">
            Query, browse, and edit your Salesforce data straight from your browser —
            no dev console, no separate SOQL tool, no context switching.
        </div>
        <div class="hero-caption">Built for admins and developers who live in their org every day.</div>
    </div>
    """, unsafe_allow_html=True)

with hero_right:
    st.markdown("""
    <div class="console-panel">
        <div class="console-header">
            <span class="console-dot dot-red"></span>
            <span class="console-dot dot-yellow"></span>
            <span class="console-dot dot-green"></span>
            <span class="console-title">SOQL Editor — live preview</span>
        </div>
        <div class="console-body">
            <div class="console-line">
                <span class="console-prompt">&gt;</span><span class="console-typed">SELECT Id, Name, Industry FROM Account LIMIT 5</span>
            </div>
            <div class="console-meta">🟢 Query executed in 189ms · 3 of 5 rows shown</div>
            <div class="console-table">
                <div class="console-row console-row-head"><span>Name</span><span>Industry</span></div>
                <div class="console-row r1"><span>Acme Corporation</span><span>Manufacturing</span></div>
                <div class="console-row r2"><span>Global Logistics Inc.</span><span>Transportation</span></div>
                <div class="console-row r3 editing"><span>Pinnacle Health Group<span class="edit-pencil">✎</span></span><span>Healthcare</span></div>
            </div>
            <div class="console-save">✅ Record updated in Salesforce</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

st.markdown('<hr class="custom-divider">', unsafe_allow_html=True)

# ============================================================
# FEATURE CARDS
# ============================================================
col1, col2, col3 = st.columns(3, gap="medium")

with col1:
    st.markdown("""
    <div class="main-card" style="animation-delay:.05s;">
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
    <div class="main-card" style="animation-delay:.18s;">
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
    <div class="main-card" style="animation-delay:.31s;">
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
    <div class="step-container" style="border-left-color: #FFA500; animation-delay:.05s;">
        <h4><span class="step-number">1</span>Configuration</h4>
        <p>
            Open the <strong>Configuration</strong> page from the sidebar.
            Enter your Salesforce username, password, and security token,
            then click <strong>"Test Connection"</strong>.
        </p>
    </div>
    """, unsafe_allow_html=True)

with right_step:
    st.markdown("""
    <div class="step-container" style="border-left-color: #FF8C00; animation-delay:.18s;">
        <h4><span class="step-number">2</span>Query &amp; Edit</h4>
        <p>
            Once connected, open the <strong>Salesforce SOQL Editor</strong> page.
            Run queries, review results, and edit or delete records
            directly in the interactive data editor.
        </p>
    </div>
    """, unsafe_allow_html=True)

st.markdown('<hr class="custom-divider">', unsafe_allow_html=True)

# ============================================================
# FOOTER / CONNECTION STATUS MESSAGE
# ============================================================

st.markdown(f"""
    <div class="status-container" style="flex: 1; margin: 0;">
        <p class="status-message">{message_text}</p>
    </div>
""", unsafe_allow_html=True)