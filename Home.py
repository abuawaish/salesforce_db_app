import streamlit as st

# ------------------------------------------------------------
# Page Configuration
# ------------------------------------------------------------
st.set_page_config(
    page_title="SF Query Studio Home",
    page_icon="☁️",
    layout="wide",
    initial_sidebar_state="auto",
    menu_items={
        'Get Help': 'https://github.com/abuawaish/salesforce_db_app#readme',
        'Report a bug': 'https://github.com/abuawaish/salesforce_db_app/issues/new',
        'About': """
        ## ☁️ SF Query Studio

        Query, browse, and edit your Salesforce data — no dev console, no separate SOQL tool.

        Built with Streamlit and `simple-salesforce`.

        **Version:** 2.0 \n
        **Author:** [Abu Awaish](https://github.com/abuawaish) \n
        **Source:** [github.com/abuawaish/salesforce_db_app](https://github.com/abuawaish/salesforce_db_app) \n
        **License:** MIT
        """
    }
)

# ============================================================
# CSS — Design System
# ============================================================
st.markdown("""
<style>

html {
    font-size: 90%;
}

/* ==========================================================
   GLOBAL VARIABLES
========================================================== */
:root, .stApp {
    --accent: #D97706;
    --accent-hover: #B45309;
    --accent-soft: rgba(217,119,6,.10);
    --accent-soft-solid: rgba(217,119,6,.14);
    --accent-glow: rgba(217,119,6,.25);

    /* Salesforce brand */
    --sf-blue: #0077B5;
    --sf-blue-soft: rgba(0,119,181,.08);

    /* Semantic */
    --success: #059669;
    --success-soft: rgba(5,150,105,.10);
    --danger: #DC2626;
    --danger-soft: rgba(220,38,38,.08);
    --warning: #D97706;

    /* Typography */
    --font-body: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                 Helvetica, Arial, sans-serif;
    --font-mono: "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, Consolas,
                 "Liberation Mono", monospace;

    /* Surfaces — Streamlit's secondary bg auto-switches */
    --glass-bg: var(--secondary-background-color, #262730);
    --glass-border: rgba(128, 128, 128, 0.12);
    --surface-hover: rgba(128, 128, 128, 0.10);
    --surface-tint: rgba(128, 128, 128, 0.08);

    /* Spacing scale */
    --space-xs: 0.5rem;
    --space-sm: 0.75rem;
    --space-md: 1.25rem;
    --space-lg: 2rem;
    --space-xl: 3rem;
    --space-2xl: 4.5rem;

    /* Radii */
    --radius-sm: 8px;
    --radius-md: 12px;
    --radius-lg: 16px;
    --radius-xl: 20px;
    --radius-pill: 999px;
}

/* ==========================================================
   LOAD GOOGLE FONTS
========================================================== */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500;600&display=swap');

/* ==========================================================
   GLOBAL RESETS & TYPOGRAPHY
========================================================== */
.stApp {
    font-family: var(--font-body);
}
.stApp p, .stApp li {
    font-family: var(--font-body);
    line-height: 1.7;
}
.stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5, .stApp h6 {
    font-family: var(--font-body);
}

/* Hide default Streamlit header spacing */
.block-container {
    padding-top: 3.5rem !important;
}

/* ==========================================================
   SIDEBAR
========================================================== */
section[data-testid="stSidebar"] {
    border-right: 1px solid var(--glass-border) !important;
}

[data-testid="stSidebarNav"] a {
    border-radius: var(--radius-md) !important;
    padding: 0.7rem 1rem !important;
    text-decoration: none !important;
    border-left: 3px solid transparent !important;
    transition: all .2s cubic-bezier(.4,0,.2,1) !important;
    font-weight: 500 !important;
}
[data-testid="stSidebarNav"] a:hover {
    background: var(--surface-hover) !important;
    color: inherit !important;
    border-left-color: var(--accent) !important;
    transform: translateX(3px);
}
[data-testid="stSidebarNav"] a[aria-current="page"] {
    background: var(--accent-soft) !important;
    border-left: 3px solid var(--accent) !important;
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
.sidebar-brand {
    padding: 0 0 var(--space-sm) 0;
    margin-bottom: var(--space-md);
    border-bottom: 1px solid var(--glass-border);
}
.sidebar-brand-title {
    font-size: 1.2rem;
    font-weight: 700;
    display: flex;
    align-items: center;
    gap: 10px;
    margin: 0 0 4px 0;
    letter-spacing: -0.01em;
}
.sidebar-brand-title .brand-icon {
    font-size: 1.3rem;
}
.sidebar-brand-version {
    background: var(--accent-soft-solid);
    color: var(--accent);
    padding: 2px 10px;
    border-radius: var(--radius-pill);
    font-size: .68rem;
    font-family: var(--font-mono);
    font-weight: 600;
    letter-spacing: .04em;
}
.sidebar-brand-sub {
    font-size: .75rem;
    font-family: var(--font-mono);
    margin: 0;
}

/* ==========================================================
   CONNECTION STATUS BAR
========================================================== */
.status-bar {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 10px 12px;
    margin-bottom: var(--space-md);
    padding: 10px 16px;
    background: var(--glass-bg);
    border: 1px solid var(--glass-border);
    border-radius: var(--radius-md);
}
.status-bar-top {
    display: flex;
    align-items: center;
    gap: 12px;
    flex-shrink: 0;
}
.status-bar-label {
    font-family: var(--font-mono);
    font-size: .72rem;
    font-weight: 600;
    letter-spacing: .1em;
    text-transform: uppercase;
    color: rgba(226, 232, 240, 0.6);
    white-space: nowrap;
}
.status-badge {
    padding: 4px 14px;
    border-radius: var(--radius-pill);
    font-weight: 600;
    font-size: .78rem;
    display: inline-flex;
    align-items: center;
    gap: 7px;
    font-family: var(--font-mono);
    white-space: nowrap;
    flex-shrink: 0;
}
.status-badge .dot {
    width: 7px; height: 7px; border-radius: 50%;
    flex-shrink: 0;
}
.badge-connected {
    background: var(--success-soft);
    color: var(--success);
    border: 1px solid rgba(52,211,153,.25);
}
.badge-connected .dot {
    background: var(--success);
    animation: pulseDot 2s ease-in-out infinite;
}
.badge-disconnected {
    background: var(--danger-soft);
    color: var(--danger);
    border: 1px solid rgba(248,113,113,.25);
}
.badge-disconnected .dot {
    background: var(--danger);
}
.status-bar-msg {
    color: rgba(226, 232, 240, 0.7);
    font-size: .82rem;
    line-height: 1.5;
    margin: 0;
    margin-left: auto;
    flex: 1 1 260px;
    min-width: 0;
}
.status-bar-msg strong {
    color: var(--accent);
}

/* On narrow screens: keep label + badge together on their own
   row (never split mid-word), drop the message to a full-width
   row below with a subtle divider instead of squeezing it in */
@media (max-width: 560px) {
    .status-bar {
        flex-direction: column;
        align-items: flex-start;
        gap: 10px;
        padding: 12px 16px;
    }
    .status-bar-msg {
        margin-left: 0;
        flex-basis: 100%;
        padding-top: 10px;
        border-top: 1px solid var(--glass-border);
    }
}

@keyframes pulseDot {
    0%, 100% { box-shadow: 0 0 0 0 rgba(52,211,153,.45); }
    50%      { box-shadow: 0 0 0 5px rgba(52,211,153,0); }
}

/* ==========================================================
   HERO SECTION
========================================================== */
.hero-wrapper {
    background: var(--glass-bg);
    border: 1px solid var(--glass-border);
    border-radius: var(--radius-xl);
    padding: var(--space-xl);
    position: relative;
    overflow: hidden;
    height: 100%;
    display: flex;
    flex-direction: column;
    justify-content: center;
}
/* Decorative gradient orb behind the hero */
.hero-wrapper::before {
    content: "";
    position: absolute;
    top: -40%;
    right: -20%;
    width: 500px;
    height: 500px;
    background: radial-gradient(circle, rgba(245,158,11,.12) 0%, transparent 70%);
    pointer-events: none;
    z-index: 0;
}
.hero-wrapper::after {
    content: "";
    position: absolute;
    bottom: -50%;
    left: -10%;
    width: 400px;
    height: 400px;
    background: radial-gradient(circle, rgba(0,161,224,.08) 0%, transparent 70%);
    pointer-events: none;
    z-index: 0;
}
.hero-wrapper > * {
    position: relative;
    z-index: 1;
}

@media (max-width: 640px) {
    .hero-wrapper {
        padding: var(--space-lg);
    }
}

.hero-eyebrow {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    font-family: var(--font-mono);
    font-size: .72rem;
    letter-spacing: .1em;
    text-transform: uppercase;
    color: var(--success);
    margin-bottom: var(--space-md);
    background: var(--success-soft);
    padding: 5px 14px;
    border-radius: var(--radius-pill);
    width: fit-content;
}
.hero-eyebrow .live-dot {
    width: 6px; height: 6px;
    border-radius: 50%;
    background: var(--success);
    animation: pulseDot 2s ease-in-out infinite;
}

.hero-title {
    font-family: var(--font-body);
    font-size: clamp(1.9rem, 7vw, 2.8rem);
    font-weight: 900;
    letter-spacing: -.03em;
    line-height: 1.1;
    margin: 0 0 var(--space-sm) 0;
}
.hero-title .title-cloud {
    color: inherit;
}
.hero-title .title-accent {
    background: linear-gradient(135deg, var(--accent) 0%, #F97316 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
}

.hero-sub {
    color: rgba(226, 232, 240, 0.75);
    font-size: 1.08rem;
    line-height: 1.7;
    max-width: 48ch;
    margin: 0 0 var(--space-md) 0;
}

.hero-tags {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
}
.hero-tag {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 4px 12px;
    border-radius: var(--radius-pill);
    font-size: .72rem;
    font-family: var(--font-mono);
    font-weight: 500;
    border: 1px solid var(--glass-border);
    background: var(--surface-tint);
    color: rgba(226, 232, 240, 0.7);
    transition: border-color .2s ease, color .2s ease;
}
.hero-tag:hover {
    border-color: var(--accent);
    color: var(--accent);
}

/* ==========================================================
   STATS STRIP
========================================================== */
.stats-strip {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: var(--space-md);
    margin: var(--space-lg) 0;
}
.stat-item {
    background: var(--glass-bg);
    border: 1px solid var(--glass-border);
    border-radius: var(--radius-lg);
    padding: var(--space-md) var(--space-md);
    text-align: center;
    transition: border-color .25s ease, transform .25s ease;
}
.stat-item:hover {
    border-color: var(--accent);
    transform: translateY(-2px);
}
.stat-value {
    font-family: var(--font-body);
    font-size: 1.8rem;
    font-weight: 800;
    letter-spacing: -.02em;
    margin-bottom: 4px;
    background: linear-gradient(135deg, var(--accent) 0%, #F97316 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
}
.stat-label {
    font-family: var(--font-mono);
    font-size: .7rem;
    color: rgba(226, 232, 240, 0.6);
    text-transform: uppercase;
    letter-spacing: .08em;
}
@media (max-width: 768px) {
    .stats-strip { grid-template-columns: repeat(2, 1fr); }
}

/* ==========================================================
   SECTION HEADER
========================================================== */
.section-header {
    display: flex;
    align-items: center;
    gap: 14px;
    margin: var(--space-sm) 0 var(--space-lg) 0;
}
.section-icon {
    width: 42px; height: 42px;
    border-radius: var(--radius-md);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1.3rem;
    flex-shrink: 0;
}
.section-icon-amber {
    background: var(--accent-soft);
    border: 1px solid rgba(245,158,11,.20);
}
.section-icon-blue {
    background: var(--sf-blue-soft);
    border: 1px solid rgba(0,161,224,.20);
}
.section-title {
    font-size: 1.5rem;
    font-weight: 800;
    letter-spacing: -.02em;
    margin: 0;
    line-height: 1.2;
}
.section-subtitle {
    font-size: .82rem;
    margin: 2px 0 0 0;
}

/* ==========================================================
   FEATURE CARDS
========================================================== */
.feature-card {
    background: var(--glass-bg);
    border: 1px solid var(--glass-border);
    border-radius: var(--radius-lg);
    padding: var(--space-lg);
    height: 100%;
    transition: transform .25s cubic-bezier(.4,0,.2,1),
                border-color .25s ease,
                box-shadow .25s ease;
    opacity: 0;
    animation: fadeInUp .5s ease-out forwards;
}
.feature-card:hover {
    transform: translateY(-4px);
    border-color: rgba(245,158,11,.30);
    box-shadow: 0 12px 32px rgba(245,158,11,.12);
}
.feature-card:hover .feature-icon-box {
    transform: scale(1.08);
    border-color: var(--accent);
}

.feature-icon-box {
    width: 48px; height: 48px;
    border-radius: var(--radius-md);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1.5rem;
    margin-bottom: var(--space-md);
    border: 1px solid var(--glass-border);
    transition: transform .3s ease, border-color .3s ease;
}
.icon-amber  { background: var(--accent-soft); }
.icon-blue   { background: var(--sf-blue-soft); }
.icon-green  { background: var(--success-soft); }
.icon-purple { background: rgba(139,92,246,.20); border: 1px solid rgba(139,92,246,.30); }

.feature-card h4 {
    font-weight: 700;
    font-size: 1.05rem;
    margin: 0 0 8px 0;
    letter-spacing: -.01em;
}
.feature-card p {
    color: rgba(226, 232, 240, 0.7);
    font-size: .88rem;
    line-height: 1.65;
    margin: 0;
}
.feature-card p strong {
    color: #f8fafc;
}
.step-card p strong {
    color: #f8fafc;
}

@keyframes fadeInUp {
    from { opacity: 0; transform: translateY(18px); }
    to   { opacity: 1; transform: translateY(0); }
}

/* ==========================================================
   STEP TIMELINE
========================================================== */
.timeline {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: var(--space-lg);
    position: relative;
}
/* Connector line between steps */
.timeline::before {
    content: "";
    position: absolute;
    top: 32px;
    left: calc(16.67% + 20px);
    right: calc(16.67% + 20px);
    height: 2px;
    background: linear-gradient(
        90deg,
        var(--accent),
        rgba(245,158,11,.30),
        var(--accent)
    );
    z-index: 0;
}

.step-card {
    background: var(--glass-bg);
    border: 1px solid var(--glass-border);
    border-radius: var(--radius-lg);
    padding: var(--space-lg);
    position: relative;
    z-index: 1;
    transition: transform .25s ease, border-color .25s ease;
    opacity: 0;
    animation: fadeInUp .5s ease-out forwards;
}
.step-card:hover {
    transform: translateY(-3px);
    border-color: rgba(245,158,11,.25);
}

.step-number {
    width: 36px; height: 36px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-family: var(--font-mono);
    font-size: .85rem;
    font-weight: 700;
    margin-bottom: var(--space-md);
    color: var(--accent);
    background: var(--accent-soft);
    border: 2px solid rgba(245,158,11,.30);
}
.step-card h4 {
    font-weight: 700;
    font-size: 1rem;
    margin: 0 0 8px 0;
}
.step-card p {
    color: rgba(226, 232, 240, 0.7);
    font-size: .86rem;
    line-height: 1.65;
    margin: 0;
}
.step-card p strong {
    color: #f8fafc;
}

@media (max-width: 768px) {
    .timeline { grid-template-columns: 1fr; }
    .timeline::before { display: none; }
}

/* ==========================================================
   TECH STACK BADGES
========================================================== */
.tech-row {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    justify-content: center;
    margin: var(--space-lg) 0;
}
.tech-badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 6px 16px;
    border-radius: var(--radius-pill);
    font-size: .76rem;
    font-family: var(--font-mono);
    font-weight: 500;
    border: 1px solid var(--glass-border);
    background: var(--glass-bg);
    color: rgba(226, 232, 240, 0.7);
    transition: border-color .2s ease, color .2s ease;
}
.tech-badge:hover {
    border-color: var(--accent);
    color: var(--accent);
}

/* ==========================================================
   FOOTER
========================================================== */
.footer-bar {
    margin-top: var(--space-2xl);
    padding: var(--space-lg) 0 var(--space-md) 0;
    border-top: 1px solid var(--glass-border);
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: var(--space-sm);
}
.footer-left {
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: .78rem;
    font-family: var(--font-mono);
}
.footer-left .footer-dot {
    width: 4px; height: 4px;
    border-radius: 50%;
    background: currentColor;
    opacity: .5;
}
.footer-links {
    display: flex;
    gap: var(--space-md);
}
.footer-link {
    font-size: .78rem;
    font-family: var(--font-mono);
    text-decoration: none;
    transition: color .2s ease, opacity .2s ease;
}
.footer-link:hover {
    color: var(--accent);
    opacity: 1;
}

/* ==========================================================
   DIVIDER
========================================================== */
.section-divider {
    border: none;
    height: 1px;
    background: linear-gradient(
        90deg,
        transparent,
        var(--glass-border),
        rgba(245,158,11,.15),
        var(--glass-border),
        transparent
    );
    margin: var(--space-xl) 0 var(--space-md) 0;
}

/* Override Streamlit's default hr handling */
.stMarkdown hr.section-divider,
div[data-testid="stMarkdown"] hr.section-divider {
    margin: var(--space-xl) 0 var(--space-md) 0 !important;
    border: none !important;
    height: 1px !important;
    background: linear-gradient(
        90deg,
        transparent,
        var(--glass-border),
        rgba(245,158,11,.15),
        var(--glass-border),
        transparent
    ) !important;
    opacity: 1 !important;
    visibility: visible !important;
    display: block !important;
    width: 100% !important;
}

/* ==========================================================
   MUTED TEXT — theme-adaptive (sits on the page's own
   background, which switches with light/dark mode, so it
   must inherit the current theme color rather than use a
   fixed dark-mode gray)
========================================================== */
.sidebar-brand-sub,
.section-subtitle,
.footer-left,
.footer-link {
    color: inherit;
    opacity: 0.6;
}

/* ==========================================================
   LIGHT-MODE FIX: force readable text on dark-bg components
   (these sit on --glass-bg, which stays dark regardless of
   theme, so they always need light text — unlike the muted
   text block above)
========================================================== */
.hero-wrapper,
.feature-card,
.step-card,
.stat-item,
.status-bar {
    color: #e2e8f0;
}
.hero-sub,
.feature-card p,
.step-card p,
.stat-label,
.status-bar-msg,
.status-bar-label {
    color: rgba(226, 232, 240, 0.7) !important;
}
.feature-card h4,
.step-card h4 {
    color: #f1f5f9;
}

/* Streamlit auto-attaches a heading anchor-link icon to every h1-h6,
   including our card h4 titles. It follows the page's theme text color
   by default, but these cards stay dark in both themes — so in light
   mode the icon renders dark-on-dark and is nearly invisible. Force it
   to match the card's fixed light text instead. */
.feature-card [data-testid="stHeaderActionElements"],
.step-card [data-testid="stHeaderActionElements"],
.feature-card h4 a,
.step-card h4 a {
    color: rgba(226, 232, 240, 0.75) !important;
}
.feature-card [data-testid="stHeaderActionElements"] svg,
.step-card [data-testid="stHeaderActionElements"] svg,
.feature-card h4 a svg,
.step-card h4 a svg {
    fill: rgba(226, 232, 240, 0.75) !important;
    stroke: rgba(226, 232, 240, 0.75) !important;
}
.feature-card [data-testid="stHeaderActionElements"]:hover,
.step-card [data-testid="stHeaderActionElements"]:hover,
.feature-card h4 a:hover,
.step-card h4 a:hover {
    color: var(--accent) !important;
}
.feature-card [data-testid="stHeaderActionElements"]:hover svg,
.step-card [data-testid="stHeaderActionElements"]:hover svg,
.feature-card h4 a:hover svg,
.step-card h4 a:hover svg {
    fill: var(--accent) !important;
    stroke: var(--accent) !important;
}
.hero-eyebrow {
    color: var(--success);
}
.hero-tags .hero-tag {
    color: rgba(226, 232, 240, 0.7);
}
.hero-tags .hero-tag:hover {
    color: var(--accent);
}

/* ==========================================================
   ACCESSIBILITY: respect reduced-motion
========================================================== */
@media (prefers-reduced-motion: reduce) {
    *, *::before, *::after {
        animation-duration: 0.001ms !important;
        animation-iteration-count: 1 !important;
        transition-duration: 0.001ms !important;
    }
    .feature-card, .step-card, .stat-item { opacity: 1 !important; transform: none !important; }
}

</style>
""", unsafe_allow_html=True)

# ============================================================
# Connection state
# ============================================================
is_connected = "sf" in st.session_state and st.session_state.get("config_ok")

if is_connected:
    badge_html = (
        '<span class="status-badge badge-connected">'
        '<span class="dot"></span>Connected</span>'
    )
    status_msg = (
        'Your session is active. Head to the '
        '<strong>Salesforce SOQL Editor</strong> to query and manage your data.'
    )
else:
    badge_html = (
        '<span class="status-badge badge-disconnected">'
        '<span class="dot"></span>Not Connected</span>'
    )
    status_msg = (
        'Configure your Salesforce connection from the sidebar to unlock every page.'
    )

# ============================================================
# SIDEBAR: Branding
# ============================================================
with st.sidebar:
    st.markdown("""
    <div class="sidebar-brand">
        <div class="sidebar-brand-title">
            <span class="brand-icon">☁️</span> SF Query Studio
            <span class="sidebar-brand-version">v2.0</span>
        </div>
        <p class="sidebar-brand-sub">Salesforce Data Workbench</p>
    </div>
    """, unsafe_allow_html=True)

# ============================================================
# STATUS BAR
# ============================================================
st.markdown(f"""
<div class="status-bar">
    <div class="status-bar-top">
        <span class="status-bar-label">Org Status</span>
        {badge_html}
    </div>
    <p class="status-bar-msg">{status_msg}</p>
</div>
""", unsafe_allow_html=True)

# ============================================================
# HERO SECTION
# ============================================================
st.markdown("""
<div class="hero-wrapper">
    <div class="hero-eyebrow">
        <span class="live-dot"></span> Streamlit &middot; simple-salesforce &middot; REST API
    </div>
    <h1 class="hero-title">
        <span class="title-cloud">☁️ </span><span class="title-accent">SF Query Studio</span>
    </h1>
    <p class="hero-sub">
        Query, browse, and edit your Salesforce data straight from your
        browser &mdash; no dev console, no separate SOQL tool, no context switching.
    </p>
    <div class="hero-tags">
        <span class="hero-tag">🔍 SOQL Queries</span>
        <span class="hero-tag">✏️ Inline Editing</span>
        <span class="hero-tag">📊 CSV Export</span>
        <span class="hero-tag">🔒 Secure Auth</span>
    </div>
</div>
""", unsafe_allow_html=True)

# ============================================================
# STATS STRIP
# ============================================================
st.markdown("""
<div class="stats-strip">
    <div class="stat-item">
        <div class="stat-value">SOQL</div>
        <div class="stat-label">Query Engine</div>
    </div>
    <div class="stat-item">
        <div class="stat-value">DML</div>
        <div class="stat-label">Insert &middot; Update &middot; Delete</div>
    </div>
    <div class="stat-item">
        <div class="stat-value">CSV</div>
        <div class="stat-label">One-Click Export</div>
    </div>
    <div class="stat-item">
        <div class="stat-value">REST</div>
        <div class="stat-label">Salesforce API</div>
    </div>
</div>
""", unsafe_allow_html=True)

st.markdown('<hr class="section-divider">', unsafe_allow_html=True)

# ============================================================
# FEATURES SECTION
# ============================================================
st.markdown("""
<div class="section-header">
    <div class="section-icon section-icon-amber">⚡</div>
    <div>
        <div class="section-title">Core Features</div>
        <p class="section-subtitle">Everything you need to work with your Salesforce data</p>
    </div>
</div>
""", unsafe_allow_html=True)

FEATURES = [
    {
        "icon_class": "icon-amber",
        "icon": "🔍",
        "title": "Run SOQL Queries",
        "body": (
            "Write any <strong>SELECT</strong> query against standard and custom "
            "Salesforce objects. Results render instantly in sortable, paginated tables."
        ),
    },
    {
        "icon_class": "icon-blue",
        "icon": "📋",
        "title": "Interactive Results",
        "body": (
            "Explore data with <strong>scrollable tables</strong>, column sorting, "
            "and one-click CSV export for quick downstream analysis."
        ),
    },
    {
        "icon_class": "icon-green",
        "icon": "✏️",
        "title": "Inline DML",
        "body": (
            "Edit records directly in the table. Perform <strong>Insert, Update, "
            "and Delete</strong> operations with a checkbox and save button."
        ),
    },
    {
        "icon_class": "icon-purple",
        "icon": "🔒",
        "title": "Secure Connection",
        "body": (
            "Authenticate with <strong>username, password &amp; security token</strong>. "
            "Credentials stay in your session &mdash; nothing is stored to disk."
        ),
    },
]

feature_cols = st.columns(len(FEATURES), gap="medium")
for col, feature, delay in zip(feature_cols, FEATURES, (0.05, 0.12, 0.19, 0.26)):
    with col:
        st.markdown(f"""
        <div class="feature-card" style="animation-delay:{delay}s;">
            <div class="feature-icon-box {feature['icon_class']}">{feature['icon']}</div>
            <h4>{feature['title']}</h4>
            <p>{feature['body']}</p>
        </div>
        """, unsafe_allow_html=True)

st.markdown('<hr class="section-divider">', unsafe_allow_html=True)

# ============================================================
# GETTING STARTED — 3-STEP TIMELINE
# ============================================================
st.markdown("""
<div class="section-header">
    <div class="section-icon section-icon-blue">🚀</div>
    <div>
        <div class="section-title">Get Started in Minutes</div>
        <p class="section-subtitle">Three simple steps to query and manage your org</p>
    </div>
</div>
""", unsafe_allow_html=True)

STEPS = [
    {
        "title": "Configure",
        "body": (
            "Open the <strong>Configuration</strong> page. Enter your Salesforce "
            "username, password, and security token, then click "
            '<strong>"Test Connection"</strong>.'
        ),
    },
    {
        "title": "Query",
        "body": (
            "Head to the <strong>SOQL Editor</strong>. Write your query, hit Run, "
            "and watch results populate in a live, interactive data grid."
        ),
    },
    {
        "title": "Edit &amp; Export",
        "body": (
            "Modify records inline or export to <strong>CSV</strong>. Changes "
            "save directly to Salesforce &mdash; no extra tools needed."
        ),
    },
]

step_cols = st.columns(len(STEPS), gap="medium")
for i, (col, step, delay) in enumerate(zip(step_cols, STEPS, (0.05, 0.15, 0.25)), start=1):
    with col:
        st.markdown(f"""
        <div class="step-card" style="animation-delay:{delay}s;">
            <div class="step-number">{i}</div>
            <h4>{step['title']}</h4>
            <p>{step['body']}</p>
        </div>
        """, unsafe_allow_html=True)

st.markdown('<hr class="section-divider">', unsafe_allow_html=True)

# ============================================================
# TECH STACK
# ============================================================
st.markdown("""
<div style="text-align:center; margin-bottom: var(--space-sm);">
    <span style="
        font-family: var(--font-mono);
        font-size: .72rem;
        opacity: .55;
        letter-spacing: .1em;
        text-transform: uppercase;
    ">Built With</span>
</div>
<div class="tech-row">
    <span class="tech-badge">🐍 Python</span>
    <span class="tech-badge">🎈 Streamlit</span>
    <span class="tech-badge">☁️ simple-salesforce</span>
    <span class="tech-badge">🔗 Salesforce REST API</span>
    <span class="tech-badge">🐼 Pandas</span>
</div>
""", unsafe_allow_html=True)

# ============================================================
# FOOTER
# ============================================================
st.markdown("""
<footer class="footer-bar">
    <div class="footer-left">
        <span>☁️ SF Query Studio</span>
        <span class="footer-dot"></span>
        <span>v2.0</span>
        <span class="footer-dot"></span>
        <span>MIT License</span>
    </div>
    <div class="footer-links">
        <a class="footer-link" href="https://github.com/abuawaish/salesforce_db_app" target="_blank" rel="noopener">GitHub</a>
        <a class="footer-link" href="https://github.com/abuawaish/salesforce_db_app#readme" target="_blank" rel="noopener">Docs</a>
        <a class="footer-link" href="https://github.com/abuawaish/salesforce_db_app/issues/new" target="_blank" rel="noopener">Report Bug</a>
    </div>
</footer>
""", unsafe_allow_html=True)