"""
Governor Limits Dashboard — real-time Salesforce API limit monitoring.

Calls GET /services/data/vXX.X/limits/ and renders theme-aware gauges,
KPI tiles, and grouped progress cards so admins can spot consumption
problems at a glance. Works in both Streamlit light and dark mode.
"""

from datetime import datetime, timezone
from html import escape
import math
import re
import textwrap

import pandas as pd
import streamlit as st

# ------------------------------------------------------------
# Page Configuration
# ------------------------------------------------------------
st.set_page_config(
    page_title="Governor Limits Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="auto",
)

# ------------------------------------------------------------
# Check connection
# ------------------------------------------------------------
if "sf" not in st.session_state or not st.session_state.get("config_ok"):
    st.warning(
        ":material/warning: Please configure your Salesforce connection first "
        "(:material/settings: Configuration page)."
    )
    st.info(
        ":material/emoji_objects: **What this page does:** once connected, shows real-time "
        "Salesforce governor limits — API requests, Bulk API, data storage, file storage, "
        "async Apex — with color-coded gauges and usage percentages."
    )
    st.stop()

sf = st.session_state["sf"]

# ------------------------------------------------------------
# Theme detection
# ------------------------------------------------------------
# Streamlit's own CSS variables (--text-color, --background-color, …) flip with
# the theme, but severity colors need explicit light/dark values to stay
# readable. st.context.theme is fairly new — fall back gracefully.
def _theme_type() -> str:
    try:
        theme_type = st.context.theme.type  # type: ignore[union-attr]
        if theme_type in ("light", "dark"):
            return theme_type
    except Exception:
        pass
    return "light"


IS_DARK = _theme_type() == "dark"

# Status palette — chosen per theme for adequate contrast.
if IS_DARK:
    C_OK, C_WARN, C_CRIT = "#34d399", "#fbbf24", "#f87171"
    C_OK_SOFT = "rgba(52, 211, 153, 0.14)"
    C_WARN_SOFT = "rgba(251, 191, 36, 0.14)"
    C_CRIT_SOFT = "rgba(248, 113, 113, 0.16)"
    TRACK = "rgba(148, 163, 184, 0.20)"
else:
    C_OK, C_WARN, C_CRIT = "#059669", "#d97706", "#dc2626"
    C_OK_SOFT = "rgba(5, 150, 105, 0.10)"
    C_WARN_SOFT = "rgba(217, 119, 6, 0.10)"
    C_CRIT_SOFT = "rgba(220, 38, 38, 0.10)"
    TRACK = "rgba(100, 116, 139, 0.18)"

# ------------------------------------------------------------
# Styles — all colors derive from Streamlit theme variables so light
# and dark mode both render correctly.
# ------------------------------------------------------------
st.markdown(
    f"""
<style>
    .gl-dot {{
        width: 9px;
        height: 9px;
        border-radius: 50%;
        display: inline-block;
        flex-shrink: 0;
    }}

    /* ---------- KPI tiles ---------- */
    .gl-kpis {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
        gap: 12px;
        margin-bottom: 18px;
    }}
    .gl-kpi {{
        position: relative;
        background: var(--secondary-background-color);
        border: 1px solid rgba(128, 128, 128, 0.18);
        border-radius: 12px;
        padding: 14px 16px 13px;
        overflow: hidden;
        transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
    }}
    .gl-kpi:hover {{
        transform: translateY(-2px);
        box-shadow: 0 8px 20px rgba(0, 0, 0, 0.08);
        border-color: color-mix(in srgb, var(--primary-color) 40%, transparent);
    }}
    .gl-kpi::before {{
        content: "";
        position: absolute;
        top: 0; left: 0; right: 0;
        height: 3px;
        background: var(--gl-accent, var(--primary-color));
    }}
    .gl-kpi-label {{
        font-size: 0.7rem;
        font-weight: 600;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        color: var(--text-color);
        opacity: 0.62;
        margin-bottom: 6px;
    }}
    .gl-kpi-value {{
        font-size: 1.6rem;
        font-weight: 700;
        line-height: 1.1;
        color: var(--text-color);
        font-variant-numeric: tabular-nums;
    }}
    .gl-kpi-value.text {{
        font-size: 1.3rem;
        line-height: 1.2;
        letter-spacing: -0.01em;
    }}
    .gl-kpi-hint {{
        margin-top: 4px;
        font-size: 0.72rem;
        color: var(--text-color);
        opacity: 0.55;
    }}

    /* ---------- Gauge grid ---------- */
    .gl-gauges {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
        gap: 14px;
        margin-bottom: 6px;
    }}
    .gl-gauge {{
        position: relative;
        background: var(--secondary-background-color);
        border: 1px solid rgba(128, 128, 128, 0.18);
        border-radius: 14px;
        padding: 16px 12px 13px;
        text-align: center;
        overflow: hidden;
        transition: transform 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease;
    }}
    .gl-gauge::before {{
        content: "";
        position: absolute;
        top: 0; left: 0; right: 0;
        height: 3px;
        background: var(--gl-accent, var(--primary-color));
        opacity: 0.85;
    }}
    .gl-gauge:hover {{
        transform: translateY(-2px);
        box-shadow: 0 8px 20px rgba(0, 0, 0, 0.08);
        border-color: color-mix(in srgb, var(--primary-color) 40%, transparent);
    }}
    .gl-gauge svg {{ display: block; margin: 0 auto 6px; }}
    .gl-gauge-ring {{
        fill: none;
        stroke: {TRACK};
        stroke-width: 9;
    }}
    .gl-gauge-arc {{
        fill: none;
        stroke-width: 9;
        stroke-linecap: round;
        transform: rotate(-90deg);
        transform-origin: 50% 50%;
        transition: stroke-dashoffset 0.5s ease;
    }}
    .gl-gauge-num {{
        font-size: 16px;
        font-weight: 700;
        color: var(--text-color);
        fill: currentColor !important;
        font-variant-numeric: tabular-nums;
    }}
    .gl-gauge-label {{
        font-size: 0.78rem;
        font-weight: 600;
        color: var(--text-color);
        line-height: 1.3;
        min-height: 2.2em;
    }}
    .gl-gauge-meta {{
        margin-top: 4px;
        font-size: 0.7rem;
        color: var(--text-color);
        opacity: 0.6;
        font-variant-numeric: tabular-nums;
    }}

    /* ---------- Limit rows ---------- */
    .gl-row {{
        background: var(--secondary-background-color);
        border: 1px solid rgba(128, 128, 128, 0.15);
        border-radius: 12px;
        padding: 12px 16px;
        margin-bottom: 8px;
        transition: border-color 0.18s ease;
    }}
    .gl-row:hover {{
        border-color: color-mix(in srgb, var(--primary-color) 35%, transparent);
    }}
    .gl-row-top {{
        display: flex;
        justify-content: space-between;
        align-items: baseline;
        gap: 12px;
    }}
    .gl-row-name {{
        font-weight: 600;
        font-size: 0.86rem;
        color: var(--text-color);
        word-break: break-word;
    }}
    .gl-row-pct {{
        font-weight: 700;
        font-size: 0.9rem;
        font-variant-numeric: tabular-nums;
        white-space: nowrap;
    }}
    .gl-track {{
        background: {TRACK};
        border-radius: 999px;
        height: 8px;
        margin: 8px 0 7px;
        overflow: hidden;
    }}
    .gl-fill {{
        height: 100%;
        border-radius: 999px;
        transition: width 0.5s ease;
    }}
    .gl-row-meta {{
        font-size: 0.73rem;
        color: var(--text-color);
        opacity: 0.62;
        font-variant-numeric: tabular-nums;
    }}
    .gl-badge {{
        display: inline-block;
        padding: 1px 8px;
        border-radius: 999px;
        font-size: 0.68rem;
        font-weight: 700;
        letter-spacing: 0.03em;
        text-transform: uppercase;
    }}

    /* ---------- Legend ---------- */
    .gl-legend {{
        display: flex;
        flex-wrap: wrap;
        gap: 18px;
        align-items: center;
        font-size: 0.78rem;
        color: var(--text-color);
        opacity: 0.8;
        margin: 4px 0 16px 0;
    }}
    .gl-legend span {{ display: inline-flex; align-items: center; gap: 6px; }}

    @media (max-width: 640px) {{
        .gl-kpi-value {{ font-size: 1.35rem; }}
        .gl-kpi-value.text {{ font-size: 1.15rem; }}
        .gl-gauges {{ grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); }}
    }}
</style>
""",
    unsafe_allow_html=True,
)


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------
def _to_float(value) -> float:
    """Best-effort numeric coercion — a malformed API value becomes 0, not a crash."""
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _pct(consumed: float, maximum: float) -> float | None:
    """Usage percentage, or None when the limit is unlimited (Max == 0)."""
    if not maximum or maximum <= 0:
        return None
    return round(100.0 * consumed / maximum, 1)


def _tone(pct: float | None) -> str:
    # Note: pct often arrives via pandas, where "no value" is NaN, not None.
    if pct is None or (isinstance(pct, float) and math.isnan(pct)):
        return "unlimited"
    if pct >= 90:
        return "critical"
    if pct >= 70:
        return "warning"
    return "ok"


TONE_COLORS = {
    "ok": (C_OK, C_OK_SOFT),
    "warning": (C_WARN, C_WARN_SOFT),
    "critical": (C_CRIT, C_CRIT_SOFT),
    "unlimited": (TRACK, "transparent"),
}

TONE_LABELS = {
    "ok": "Healthy",
    "warning": "Warning",
    "critical": "Critical",
    "unlimited": "Unlimited",
}


def _fmt_num(value: float) -> str:
    value = float(value or 0)
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f}B"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 10_000:
        return f"{value / 1_000:.1f}K"
    return f"{value:,.0f}"


# Categories keep the "All Limits" list scannable instead of one long wall.
CATEGORY_RULES: list[tuple[str, tuple[str, ...]]] = [
    # Bulk before API: "DailyBulkApiRequests" matches both, and belongs in Bulk.
    ("Bulk API", ("bulk",)),
    ("Storage", ("storage",)),
    ("API & Callouts", ("api", "callout", "odata", "rest")),
    ("Apex & Automation", ("apex", "workflow", "queueable", "scheduled", "batch")),
    ("Streaming & Events", ("streaming", "event", "cometd", "push")),
    ("Metadata & Tooling", ("metadata", "tooling")),
    ("Email", ("email",)),
]


def _category_of(name: str) -> str:
    lowered = name.lower()
    for label, needles in CATEGORY_RULES:
        if any(needle in lowered for needle in needles):
            return label
    return "Other"


# Priority limits shown as rings at the top.
GAUGE_KEYS = [
    ("DailyApiRequests", "Daily API Requests"),
    ("DailyBulkApiRequests", "Daily Bulk API Requests"),
    ("DataStorageMB", "Data Storage (MB)"),
    ("FileStorageMB", "File Storage (MB)"),
    ("DailyAsyncApexExecutions", "Async Apex Executions"),
    ("DailyBulkV2QueryFileStorageMB", "Bulk V2 Query Storage (MB)"),
]


# ------------------------------------------------------------
# Fetch limits
# ------------------------------------------------------------
@st.cache_data(ttl=30, show_spinner=False)
def fetch_limits(_sf_client, instance_key: str) -> dict:
    """Cached for 30 s.

    ``instance_key`` is part of the cache key (it is *not* underscore-prefixed),
    so switching orgs — or reconnecting with a fresh session — immediately
    bypasses any previously cached payload. The fetch timestamp travels with
    the payload so the UI can show when the data was actually retrieved,
    not when the page happened to re-render.
    """
    payload = _sf_client.restful("limits/", method="GET")
    return {"limits": payload, "fetched_at": datetime.now().strftime("%H:%M:%S")}


def _humanize(name: str) -> str:
    """'DailyApiRequests' -> 'Daily Api Requests'."""
    out = []
    for i, ch in enumerate(name):
        if i and ch.isupper() and not name[i - 1].isupper():
            out.append(" ")
        out.append(ch)
    return "".join(out)


# ------------------------------------------------------------
# Page header
# ------------------------------------------------------------
# Instance + API version come from the client itself — the Configuration page
# does not store them in session state, so derive them the same way the
# Session Info page does (version parsed out of base_url).
instance_label = getattr(sf, "sf_instance", "") or "Salesforce"
_api_match = re.search(r"/v(\d+\.\d+)", getattr(sf, "base_url", "") or "")
api_version_label = (
    _api_match.group(1) if _api_match else str(getattr(sf, "sf_version", "") or "")
)

st.title("📈 Governor Limits")
header_caption = f"🟢 Live consumption for {instance_label}"
if api_version_label:
    header_caption += f" · API v{api_version_label}"
st.caption(header_caption)

ctrl_refresh, ctrl_auto, _ = st.columns([1, 1, 4])

with ctrl_refresh:
    if st.button("🔄 Refresh now", width="content", type="secondary"):
        fetch_limits.clear()  # scoped: don't wipe other pages' caches
        st.rerun()

with ctrl_auto:
    auto_refresh = st.toggle("⏱️ Auto-refresh (30 s)", value=False)

instance_key = (
    f"{getattr(sf, 'sf_instance', '')}|{getattr(sf, 'sf_version', '')}"
    f"|{getattr(sf, 'session_id', '')}"
)

# ------------------------------------------------------------
# Dashboard
# ------------------------------------------------------------
def render_dashboard() -> None:
    """Fetch + render. Runs as a self-refreshing fragment when auto-refresh is on."""

    with st.spinner("Fetching governor limits from Salesforce…"):
        try:
            result = fetch_limits(sf, instance_key)
        except Exception as exc:
            st.error(f"❌ Could not fetch limits: {exc}")
            return

    raw_limits = result.get("limits") if isinstance(result, dict) else None
    fetched_at = result.get("fetched_at", "—") if isinstance(result, dict) else "—"

    if not isinstance(raw_limits, dict) or not raw_limits:
        st.warning("No limit data returned by the API.")
        return

    # ---------- Normalise into one table ----------
    rows = []
    for key, entry in raw_limits.items():
        if not isinstance(entry, dict):
            continue
        maximum = _to_float(entry.get("Max"))
        remaining = _to_float(entry.get("Remaining"))
        consumed = maximum - remaining
        rows.append(
            {
                "Limit Name": key,
                "Label": _humanize(key),
                "Category": _category_of(key),
                "Consumed": consumed,
                "Remaining": remaining,
                "Max": maximum,
                "% Used": _pct(consumed, maximum),
            }
        )

    if not rows:
        st.info("Salesforce returned limit entries, but none were in a recognised format.")
        return

    df = pd.DataFrame(rows)
    finite = df[df["% Used"].notna()]

    # ---------- KPI strip ----------
    critical = int((finite["% Used"] >= 90).sum())
    warning = int(((finite["% Used"] >= 70) & (finite["% Used"] < 90)).sum())
    healthy = int((finite["% Used"] < 70).sum())
    unlimited = int(df["% Used"].isna().sum())
    peak = finite["% Used"].max() if not finite.empty else 0.0

    if critical:
        overall_tone, overall_text = "critical", "Action needed"
    elif warning:
        overall_tone, overall_text = "warning", "Watch closely"
    else:
        overall_tone, overall_text = "ok", "All clear"

    kpi_html = textwrap.dedent(f"""
    <div class="gl-kpis">
      <div class="gl-kpi" style="--gl-accent:{TONE_COLORS[overall_tone][0]};">
        <div class="gl-kpi-label">Overall status</div>
        <div class="gl-kpi-value text" style="color:{TONE_COLORS[overall_tone][0]};">{overall_text}</div>
        <div class="gl-kpi-hint">Highest usage {peak:.1f}%</div>
      </div>
      <div class="gl-kpi" style="--gl-accent:{C_CRIT};">
        <div class="gl-kpi-label">Critical ≥ 90%</div>
        <div class="gl-kpi-value">{critical}</div>
        <div class="gl-kpi-hint">limits near exhaustion</div>
      </div>
      <div class="gl-kpi" style="--gl-accent:{C_WARN};">
        <div class="gl-kpi-label">Warning 70–89%</div>
        <div class="gl-kpi-value">{warning}</div>
        <div class="gl-kpi-hint">limits worth watching</div>
      </div>
      <div class="gl-kpi" style="--gl-accent:{C_OK};">
        <div class="gl-kpi-label">Healthy</div>
        <div class="gl-kpi-value">{healthy}</div>
        <div class="gl-kpi-hint">below 70% used</div>
      </div>
      <div class="gl-kpi" style="--gl-accent:var(--primary-color);">
        <div class="gl-kpi-label">Tracked limits</div>
        <div class="gl-kpi-value">{len(df)}</div>
        <div class="gl-kpi-hint">{unlimited} unlimited</div>
      </div>
    </div>
    """)
    st.markdown(kpi_html, unsafe_allow_html=True)

    # ---------- Needs attention ----------
    hot = finite[finite["% Used"] >= 70].sort_values("% Used", ascending=False)
    if not hot.empty:
        with st.container(border=True):
            st.markdown("**⚠️ Needs attention** — limits already past 70%")
            for _, row in hot.head(5).iterrows():
                tone = _tone(row["% Used"])
                color, soft = TONE_COLORS[tone]
                tone_label = TONE_LABELS[tone]
                st.markdown(
                    f'<div style="display:flex;justify-content:space-between;'
                    f'align-items:center;gap:12px;padding:5px 0;font-size:0.86rem;'
                    f'color:var(--text-color);">'
                    f'<span><span class="gl-dot" style="background:{color};"></span>'
                    f'&nbsp;{escape(row["Label"])}</span>'
                    f'<span style="font-weight:700;font-variant-numeric:tabular-nums;">'
                    f'{row["% Used"]:.1f}%'
                    f'<span class="gl-badge" style="margin-left:8px;color:{color};'
                    f'background:{soft};">{tone_label}</span></span>'
                    f"</div>",
                    unsafe_allow_html=True,
                )
            if len(hot) > 5:
                st.caption(f"+ {len(hot) - 5} more in the list below.")

    # ---------- Key gauges ----------
    st.markdown("### 🎯 Key Limits")

    gauges = []
    for api_key, label in GAUGE_KEYS:
        entry = raw_limits.get(api_key)
        if not isinstance(entry, dict):
            continue
        maximum = _to_float(entry.get("Max"))
        remaining = _to_float(entry.get("Remaining"))
        consumed = maximum - remaining
        gauges.append((label, consumed, remaining, maximum, _pct(consumed, maximum)))

    if not gauges:
        st.caption("Salesforce did not return any of the headline limit keys for this org.")
    else:
        cards = []
        radius = 32
        circumference = 2 * math.pi * radius
        for label, consumed, _remaining, maximum, pct in gauges:
            tone = _tone(pct)
            color, _soft = TONE_COLORS[tone]
            arc_pct = min(pct or 0.0, 100.0)
            offset = circumference * (1 - arc_pct / 100.0)
            num_text = "∞" if pct is None else f"{pct:.0f}%"
            meta = (
                f"{_fmt_num(consumed)} / {_fmt_num(maximum)}"
                if pct is not None
                else "unlimited"
            )
            cards.append(
                textwrap.dedent(f"""
                <div class="gl-gauge" style="--gl-accent:{color};">
                  <svg width="84" height="84" viewBox="0 0 84 84" role="img"
                       aria-label="{escape(label)}: {num_text} used">
                    <title>{escape(label)}: {num_text} used ({meta})</title>
                    <circle class="gl-gauge-ring" cx="42" cy="42" r="{radius}"></circle>
                    <circle class="gl-gauge-arc" cx="42" cy="42" r="{radius}"
                            stroke="{color}"
                            stroke-dasharray="{circumference:.2f}"
                            stroke-dashoffset="{offset:.2f}">
                      <title>{escape(label)}: {num_text} used ({meta})</title>
                    </circle>
                    <text class="gl-gauge-num" x="42" y="47" text-anchor="middle">{num_text}</text>
                  </svg>
                  <div class="gl-gauge-label">{escape(label)}</div>
                  <div class="gl-gauge-meta">{meta}</div>
                </div>
                """)
            )
        st.markdown(
            f'<div class="gl-gauges">{"".join(cards)}</div>', unsafe_allow_html=True
        )

    st.markdown(
        textwrap.dedent(f"""
        <div class="gl-legend">
          <span><span class="gl-dot" style="background:{C_OK};"></span> &lt; 70% healthy</span>
          <span><span class="gl-dot" style="background:{C_WARN};"></span> 70–89% warning</span>
          <span><span class="gl-dot" style="background:{C_CRIT};"></span> ≥ 90% critical</span>
        </div>
        """),
        unsafe_allow_html=True,
    )

    st.divider()

    # ---------- All limits ----------
    st.markdown("### 📋 All Limits")

    f_col, s_col, o_col = st.columns([2.0, 1.35, 1.8], vertical_alignment="bottom")
    with f_col:
        query = st.text_input(
            "Search",
            placeholder="Filter by name — e.g. Bulk, Data, Apex…",
            label_visibility="collapsed",
        )
    with s_col:
        severity = st.selectbox(
            "Severity",
            options=["All", "Critical", "Warning", "Healthy", "Unlimited"],
            index=0,
            label_visibility="collapsed",
        )
    with o_col:
        sort_by = st.selectbox(
            "Sort",
            options=["% used (high → low)", "Name (A → Z)", "Headroom (low → high)"],
            label_visibility="collapsed",
        )

    view = df.copy()

    if query and query.strip():
        q = query.strip().lower()
        view = view[
            view["Limit Name"].str.lower().str.contains(q, na=False)
            | view["Label"].str.lower().str.contains(q, na=False)
            | view["Category"].str.lower().str.contains(q, na=False)
        ]

    severity = severity or "All"
    if severity == "Critical":
        view = view[view["% Used"] >= 90]
    elif severity == "Warning":
        view = view[(view["% Used"] >= 70) & (view["% Used"] < 90)]
    elif severity == "Healthy":
        view = view[view["% Used"] < 70]
    elif severity == "Unlimited":
        view = view[view["% Used"].isna()]

    if sort_by == "% used (high → low)":
        view = view.sort_values("% Used", ascending=False, na_position="last")
    elif sort_by == "Name (A → Z)":
        view = view.sort_values("Label", ascending=True)
    else:
        view = view.assign(**_headroom(view)).sort_values(
            "_headroom", ascending=True, na_position="last"
        )

    if view.empty:
        st.info("No limits match these filters.")
        return
    if view["% Used"].notna().sum() == 0 and severity != "Unlimited":
        st.info("No finite limits match these filters — try the **Unlimited** view.")
        return

    # Group and render — known categories first, "Other" last.
    present = set(view["Category"])
    ordered = [label for label, _ in CATEGORY_RULES if label in present]
    if "Other" in present:
        ordered.append("Other")
    for category in ordered:
        _render_group(category, view[view["Category"] == category])

    # ---------- Export ----------
    export = view.drop(columns=[c for c in ("_headroom",) if c in view.columns])
    export = export[["Limit Name", "Label", "Category", "Consumed", "Remaining", "Max", "% Used"]]
    export[["Consumed", "Remaining", "Max"]] = export[
        ["Consumed", "Remaining", "Max"]
    ].round(0)
    st.download_button(
        "⬇️ Download as CSV",
        data=export.to_csv(index=False).encode("utf-8"),
        file_name=f"salesforce_governor_limits_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}.csv",
        mime="text/csv",
        width="stretch",
    )

    with st.expander("📄 Table view", expanded=False):
        st.dataframe(
            export,
            width="stretch",
            hide_index=True,
            column_config={
                "% Used": st.column_config.ProgressColumn(
                    "% Used", min_value=0, max_value=100, format="%.1f%%"
                ),
                "Consumed": st.column_config.NumberColumn(format="%d"),
                "Remaining": st.column_config.NumberColumn(format="%d"),
                "Max": st.column_config.NumberColumn(format="%d"),
            },
        )

    version_path = f"v{api_version_label}" if api_version_label else "vXX.X"
    st.caption(
        f"Last fetched at **{fetched_at}** · source `GET /services/data/"
        f"{version_path}/limits/` · cached 30 s · "
        "Consumed = Max − Remaining · limits with Max = 0 are shown as unlimited."
    )


def _headroom(view: pd.DataFrame) -> dict:
    """Sort key: remaining headroom (unlimited pushed to the end)."""
    return {"_headroom": view["Max"] - view["Consumed"]}


def _render_group(category: str, group: pd.DataFrame) -> None:
    n = len(group)
    with st.expander(f"{category} ({n})", expanded=False):
        blocks = []
        for _, row in group.iterrows():
            pct = row["% Used"]
            # Via pandas, "unlimited" arrives as NaN — normalise back to None
            # or every check below mis-renders it (the old code printed "nan%").
            pct = None if pd.isna(pct) else float(pct)
            tone = _tone(pct)
            color, soft = TONE_COLORS[tone]
            bar_width = 0.0 if pct is None else min(pct, 100.0)

            if pct is None:
                pct_text = "Unlimited"
                badge = (
                    f'<span class="gl-badge" style="color:{color};'
                    f'background:rgba(128,128,128,0.16);">{TONE_LABELS[tone]}</span>'
                )
                meta = f"{_fmt_num(row['Consumed'])} consumed · no fixed ceiling"
            else:
                pct_text = f"{pct:.1f}%"
                badge = (
                    f'<span class="gl-badge" style="color:{color};background:{soft};">'
                    f"{TONE_LABELS[tone]}</span>"
                )
                meta = (
                    f"{_fmt_num(row['Consumed'])} consumed · "
                    f"{_fmt_num(row['Remaining'])} remaining · "
                    f"{_fmt_num(row['Max'])} max"
                )

            blocks.append(
                textwrap.dedent(f"""
                <div class="gl-row">
                  <div class="gl-row-top">
                    <span class="gl-row-name">{escape(row['Label'])}
                      <span style="opacity:0.45;font-weight:400;font-size:0.72rem;">
                        {escape(row['Limit Name'])}
                      </span>
                    </span>
                    <span class="gl-row-pct" style="color:{color};">{pct_text} {badge}</span>
                  </div>
                  <div class="gl-track">
                    <div class="gl-fill" style="width:{bar_width:.1f}%;background:{color};">
                    </div>
                  </div>
                  <div class="gl-row-meta">{meta}</div>
                </div>
                """)
            )
        st.markdown("".join(blocks), unsafe_allow_html=True)


# ------------------------------------------------------------
# Render (auto-refresh re-runs only this fragment)
# ------------------------------------------------------------
@st.fragment(run_every="30s")
def _auto_dashboard() -> None:
    render_dashboard()


if auto_refresh:
    _auto_dashboard()
else:
    render_dashboard()
