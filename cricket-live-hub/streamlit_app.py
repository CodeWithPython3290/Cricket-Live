"""
Cricket Live Hub
----------------
Tab 1: Live cricket scores (from ESPNcricinfo's free, public RSS feed), ranked so
       international matches and the IPL come before domestic/local games, plus a
       player for official, publicly available live streams (YouTube embeds).
Tab 2: HTML file viewer - upload an .html file, preview it, or open it in a
       fresh about:blank tab. Includes ready-made templates (e.g. a 3D cricket game).

Run with:  streamlit run streamlit_app.py
"""

import html
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests
import streamlit as st
import streamlit.components.v1 as components

import multiplayer

SCORES_FEED = "https://static.cricinfo.com/rss/livescores.xml"
REFRESH_SECONDS = 30

TEMPLATE_DIR = Path(__file__).parent / "templates"
TEMPLATES = {
    "3D Cricket League": {
        "file": "cricket_league_3d.html",
        "icon": "🏏",
        "desc": "Cartoon 3D cricket with IPL teams. Play the CPU, or create an account and play "
                "a friend on another computer.",
        "tags": ["Game", "3D", "Online multiplayer"],
        "online": True,
    },
}

# --------------------------------------------------------------------------- #
# Team knowledge used for ranking + badges   name: (code, background, text)
# --------------------------------------------------------------------------- #
FULL_MEMBERS = {
    "India": ("IND", "#1e5bc6", "#fff"),
    "Australia": ("AUS", "#f5c400", "#111"),
    "England": ("ENG", "#c8102e", "#fff"),
    "South Africa": ("SA", "#007a4d", "#fff"),
    "New Zealand": ("NZ", "#1a1a1a", "#fff"),
    "Pakistan": ("PAK", "#01411c", "#fff"),
    "Sri Lanka": ("SL", "#0b3d91", "#fff"),
    "West Indies": ("WI", "#7b0041", "#fff"),
    "Bangladesh": ("BAN", "#006a4e", "#fff"),
    "Afghanistan": ("AFG", "#1f4fa0", "#fff"),
    "Ireland": ("IRE", "#169b62", "#fff"),
    "Zimbabwe": ("ZIM", "#d40000", "#fff"),
}
ASSOCIATES = {
    "Netherlands": "NED", "Scotland": "SCO", "Nepal": "NEP", "United Arab Emirates": "UAE",
    "United States of America": "USA", "USA": "USA", "Oman": "OMA", "Namibia": "NAM",
    "Canada": "CAN", "Hong Kong": "HK", "Papua New Guinea": "PNG", "Kenya": "KEN",
    "Uganda": "UGA", "Jersey": "JER", "Italy": "ITA", "Germany": "GER", "Denmark": "DEN",
    "Thailand": "THA", "Malaysia": "MAS", "Singapore": "SIN", "Kuwait": "KUW", "Qatar": "QAT",
    "Bahrain": "BHR", "Saudi Arabia": "KSA", "Tanzania": "TAN", "Rwanda": "RWA", "Nigeria": "NGA",
}
IPL_TEAMS = {
    "Chennai Super Kings": ("CSK", "#f9cd05", "#111"),
    "Mumbai Indians": ("MI", "#004ba0", "#fff"),
    "Royal Challengers Bengaluru": ("RCB", "#d11d1d", "#fff"),
    "Royal Challengers Bangalore": ("RCB", "#d11d1d", "#fff"),
    "Kolkata Knight Riders": ("KKR", "#3a225d", "#fff"),
    "Delhi Capitals": ("DC", "#17449b", "#fff"),
    "Punjab Kings": ("PBKS", "#dd1f2d", "#fff"),
    "Rajasthan Royals": ("RR", "#ea1a85", "#fff"),
    "Sunrisers Hyderabad": ("SRH", "#f7631b", "#fff"),
    "Gujarat Titans": ("GT", "#1b2133", "#fff"),
    "Lucknow Super Giants": ("LSG", "#0057e2", "#fff"),
}
MAJOR_DOMESTIC = {
    # Sheffield Shield / Australian states
    "New South Wales", "Victoria", "Queensland", "Western Australia", "South Australia", "Tasmania",
    # Big Bash
    "Adelaide Strikers", "Brisbane Heat", "Hobart Hurricanes", "Melbourne Renegades", "Melbourne Stars",
    "Perth Scorchers", "Sydney Sixers", "Sydney Thunder",
    # PSL
    "Islamabad United", "Karachi Kings", "Lahore Qalandars", "Multan Sultans", "Peshawar Zalmi",
    "Quetta Gladiators",
    # CPL
    "Barbados Royals", "Guyana Amazon Warriors", "Jamaica Tallawahs", "St Kitts and Nevis Patriots",
    "Saint Lucia Kings", "Trinbago Knight Riders", "Antigua and Barbuda Falcons",
    # SA20
    "Durban's Super Giants", "Joburg Super Kings", "MI Cape Town", "Paarl Royals", "Pretoria Capitals",
    "Sunrisers Eastern Cape",
    # The Hundred
    "Birmingham Phoenix", "London Spirit", "Manchester Originals", "Northern Superchargers",
    "Oval Invincibles", "Southern Brave", "Trent Rockets", "Welsh Fire",
    # English counties
    "Derbyshire", "Durham", "Essex", "Glamorgan", "Gloucestershire", "Hampshire", "Kent", "Lancashire",
    "Leicestershire", "Middlesex", "Northamptonshire", "Nottinghamshire", "Somerset", "Surrey", "Sussex",
    "Warwickshire", "Worcestershire", "Yorkshire",
    # New Zealand
    "Auckland", "Wellington", "Canterbury", "Otago", "Central Districts", "Northern Districts",
    # Indian domestic (Ranji / SMAT)
    "Mumbai", "Delhi", "Karnataka", "Tamil Nadu", "Saurashtra", "Vidarbha", "Bengal", "Punjab",
    "Madhya Pradesh", "Rajasthan", "Gujarat", "Kerala", "Baroda", "Hyderabad", "Uttar Pradesh",
    "Andhra", "Haryana", "Himachal Pradesh", "Jharkhand", "Odisha", "Maharashtra", "Railways",
    "Services", "Assam", "Goa", "Tripura", "Uttarakhand", "Jammu & Kashmir", "Chhattisgarh",
    # Other well-known domestic sides
    "Titans", "Lions", "Dolphins", "Warriors", "Knights", "Western Province", "Boland",
}

SECTIONS = ["International", "IPL", "Leagues & Domestic", "Other"]
SECTION_ICONS = {"International": "🌍", "IPL": "🏆", "Leagues & Domestic": "🏟️", "Other": "📍"}
STATUS_ORDER = {"live": 0, "latest": 1, "upcoming": 2}
PALETTE = ["#334155", "#475569", "#0f766e", "#4338ca", "#9d174d", "#a16207", "#1d4ed8", "#7c3aed", "#b45309"]

OFFICIAL_SOURCES = [
    ("ICC", "https://www.youtube.com/@ICC/streams"),
    ("cricket.com.au", "https://www.youtube.com/@cricketcomau/streams"),
    ("England Cricket", "https://www.youtube.com/@englandcricket/streams"),
    ("ICC.tv", "https://www.icc-cricket.com/icc-tv"),
    ("Live on YouTube", "https://www.youtube.com/results?search_query=cricket+live&sp=EgJAAQ%253D%253D"),
]

st.set_page_config(page_title="Cricket Live Hub", page_icon="🏏", layout="wide")

# --------------------------------------------------------------------------- #
# Styling
# --------------------------------------------------------------------------- #
st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@600;700&display=swap');

:root {
  --accent: #10b981; --accent-2: #34d399; --live: #ef4444;
  --nav: #0b1220; --line: rgba(127,127,127,.18); --soft: rgba(127,127,127,.06);
  --muted: rgba(127,127,127,1);
}
.stApp, .stApp p, .stApp label, .stApp input, .stApp textarea, .stApp button { font-family: 'Inter', system-ui, sans-serif; }
header[data-testid="stHeader"], footer, #MainMenu, [data-testid="stToolbar"] { display: none !important; }
.block-container { padding: 0 2.2rem 2rem !important; max-width: 100% !important; }

/* ---------- top navigation (the main tabs) ---------- */
.stTabs [data-baseweb="tab-list"] {
  position: sticky; top: 0; z-index: 1000;
  background: var(--nav); margin: 0 -2.2rem; padding: 0 2.2rem; gap: 4px;
  border-bottom: 1px solid rgba(255,255,255,.08); box-shadow: 0 8px 30px rgba(2,6,23,.25);
}
.stTabs [data-baseweb="tab-list"]::before {
  content: "🏏  CRICKET LIVE HUB"; color: #fff; font-weight: 800; letter-spacing: .14em;
  font-size: .85rem; display: flex; align-items: center; margin-right: auto; white-space: nowrap;
}
.stTabs [data-baseweb="tab"] {
  height: 62px; padding: 0 20px; background: transparent !important;
}
.stTabs [data-baseweb="tab"] p { color: rgba(255,255,255,.62); font-weight: 600; font-size: .92rem; }
.stTabs [data-baseweb="tab"]:hover p { color: #fff; }
.stTabs [aria-selected="true"] p { color: #fff; }
.stTabs [data-baseweb="tab-highlight"] { background: var(--accent); height: 3px; border-radius: 3px 3px 0 0; }
.stTabs [data-baseweb="tab-border"] { display: none; }
.stTabs [data-baseweb="tab-panel"] { padding-top: 1.6rem; }

/* ---------- page header ---------- */
.page-head { display: flex; justify-content: space-between; align-items: flex-end; flex-wrap: wrap;
  gap: 16px; margin-bottom: 1.4rem; padding-bottom: 1.2rem; border-bottom: 1px solid var(--line); }
.eyebrow { color: var(--accent); font-size: .72rem; font-weight: 700; letter-spacing: .16em; }
.page-head h2 { margin: 4px 0 2px; padding: 0; font-size: 1.9rem; font-weight: 800; letter-spacing: -.02em; }
.page-head p { margin: 0; opacity: .6; font-size: .92rem; }
.head-meta { display: flex; align-items: center; gap: 8px; font-size: .82rem; opacity: .75;
  border: 1px solid var(--line); border-radius: 999px; padding: 7px 14px; }
.dot { width: 8px; height: 8px; border-radius: 50%; background: var(--live); display: inline-block;
  box-shadow: 0 0 0 0 rgba(239,68,68,.6); animation: ping 1.8s infinite; }
@keyframes ping { 0% {box-shadow: 0 0 0 0 rgba(239,68,68,.55);} 70% {box-shadow: 0 0 0 8px rgba(239,68,68,0);} 100% {box-shadow: 0 0 0 0 rgba(239,68,68,0);} }

/* ---------- stats strip ---------- */
.stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 1px; background: var(--line);
  border: 1px solid var(--line); border-radius: 14px; overflow: hidden; margin: 6px 0 22px; }
.stat { background: var(--soft); padding: 14px 18px; backdrop-filter: blur(2px); }
.stat .k { font-size: .7rem; letter-spacing: .12em; font-weight: 700; opacity: .55; text-transform: uppercase; }
.stat .v { font-size: 1.55rem; font-weight: 800; margin-top: 2px; letter-spacing: -.02em; }
.stat .v.live { color: var(--live); }
@media (max-width: 700px) { .stats { grid-template-columns: repeat(2, 1fr); } }

/* ---------- sections + cards ---------- */
.sec-head { display: flex; align-items: center; gap: 10px; margin: 22px 0 12px; }
.sec-head .t { font-weight: 700; font-size: 1rem; letter-spacing: -.01em; }
.sec-head .c { font-size: .72rem; font-weight: 700; border-radius: 999px; padding: 2px 9px;
  background: rgba(16,185,129,.14); color: var(--accent); }
.sec-head .ln { flex: 1; height: 1px; background: var(--line); }

.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 14px; }
a.card { display: flex; flex-direction: column; gap: 4px; text-decoration: none !important; color: inherit !important;
  border: 1px solid var(--line); border-radius: 16px; padding: 14px 16px 12px; background: var(--soft);
  transition: transform .15s ease, border-color .15s ease, box-shadow .15s ease; position: relative; overflow: hidden; }
a.card:hover { transform: translateY(-2px); border-color: rgba(16,185,129,.6); box-shadow: 0 10px 28px rgba(2,6,23,.16); }
a.card.live::before { content: ""; position: absolute; inset: 0 auto 0 0; width: 3px; background: var(--live); }
.card-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.chip { font-size: .64rem; font-weight: 700; letter-spacing: .12em; opacity: .55; text-transform: uppercase; }
.status { font-size: .66rem; font-weight: 800; letter-spacing: .1em; display: flex; align-items: center; gap: 6px;
  padding: 3px 9px; border-radius: 999px; }
.status.live { color: var(--live); background: rgba(239,68,68,.12); }
.status.latest { opacity: .6; background: rgba(127,127,127,.14); }
.status.upcoming { color: #3b82f6; background: rgba(59,130,246,.12); }
.row { display: grid; grid-template-columns: 38px 1fr auto; align-items: center; gap: 10px; padding: 6px 0; }
.av { width: 38px; height: 38px; border-radius: 10px; display: flex; align-items: center; justify-content: center;
  font-size: .66rem; font-weight: 800; letter-spacing: .04em; box-shadow: inset 0 0 0 1px rgba(255,255,255,.12); }
.nm { font-weight: 600; font-size: .93rem; line-height: 1.2; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.row.dim .nm, .row.dim .sc b { opacity: .7; }
.sc { text-align: right; font-family: 'JetBrains Mono', ui-monospace, monospace; white-space: nowrap; }
.sc b { font-size: 1rem; font-weight: 700; }
.sc small { font-size: .72rem; opacity: .5; margin-right: 6px; }
.row.bat .sc b { color: var(--accent); }
.bat-tag { font-size: .6rem; font-weight: 700; color: var(--accent); margin-left: 6px; letter-spacing: .08em; }
.card-foot { display: flex; justify-content: flex-end; font-size: .74rem; font-weight: 600; opacity: .45;
  margin-top: 6px; padding-top: 8px; border-top: 1px solid var(--line); }
a.card:hover .card-foot { opacity: .9; color: var(--accent); }

.empty { text-align: center; padding: 48px 20px; border: 1px dashed rgba(127,127,127,.35);
  border-radius: 16px; opacity: .75; }
.note { font-size: .78rem; opacity: .55; line-height: 1.5; }
.panel-title { font-weight: 700; font-size: 1rem; margin: 2px 0 10px; display: flex; align-items: center; gap: 8px; }

/* ---------- template cards ---------- */
.tpl { display: flex; gap: 14px; align-items: center; }
.tpl-icon { width: 54px; height: 54px; flex: none; border-radius: 14px; display: flex; align-items: center;
  justify-content: center; font-size: 1.7rem; background: linear-gradient(135deg, #064e3b, #10b981); }
.tpl-name { font-weight: 800; font-size: 1.05rem; letter-spacing: -.01em; }
.tpl-desc { font-size: .85rem; opacity: .65; margin: 2px 0 6px; }
.tpl-tag { display: inline-block; font-size: .66rem; font-weight: 700; letter-spacing: .08em; text-transform: uppercase;
  padding: 2px 8px; margin-right: 6px; border-radius: 999px; background: rgba(16,185,129,.14); color: var(--accent); }

/* ---------- widgets ---------- */
[data-testid="stVerticalBlockBorderWrapper"] { border-radius: 16px !important; }
.stButton button, .stDownloadButton button, .stLinkButton a { border-radius: 10px; font-weight: 600; }
.stTextInput input, .stTextArea textarea { border-radius: 10px; }
</style>
""",
    unsafe_allow_html=True,
)


# --------------------------------------------------------------------------- #
# Live score helpers
# --------------------------------------------------------------------------- #
@st.cache_data(ttl=REFRESH_SECONDS - 5, show_spinner=False)
def fetch_scores():
    """Download and parse the public ESPNcricinfo live-scores RSS feed."""
    resp = requests.get(SCORES_FEED, timeout=10, headers={"User-Agent": "CricketLiveHub/1.0"})
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    matches = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("guid") or item.findtext("link") or "").strip()
        if title:
            matches.append(parse_match(title, link.replace("http://", "https://")))
    return matches


def base_name(name):
    """'India Women' -> 'India'"""
    return re.sub(r"\s+Women('s)?$", "", name).strip()


def parse_team(text):
    """'India 245/6 & 120/3 *' -> ('India', '245/6 & 120/3', True)"""
    batting = "*" in text
    text = text.replace("*", "").strip()
    m = re.match(r"^(.*?)\s+(\d.*)$", text)
    if m:
        return m.group(1).strip(), re.sub(r"\s+", " ", m.group(2)).strip(), batting
    return text, "", batting


def classify(names):
    """Return (section, rank-within-section) - lower rank = more important."""
    bases = [base_name(n) for n in names if n]
    if not bases:
        return "Other", 9

    def national(n):
        if n in FULL_MEMBERS or n in ASSOCIATES:
            return True
        return re.sub(r"\s+(A|Lions|Under-19s|U19|Emerging|XI)$", "", n) in FULL_MEMBERS

    if all(national(n) for n in bases):
        if all(n in FULL_MEMBERS for n in bases):
            rank = 0
        elif any(n in FULL_MEMBERS for n in bases):
            rank = 1
        elif all(n in ASSOCIATES for n in bases):
            rank = 2
        else:
            rank = 3  # A teams, U19s etc.
        return "International", rank
    if any(n in IPL_TEAMS for n in bases):
        return "IPL", 0
    if any(n in MAJOR_DOMESTIC for n in bases):
        return "Leagues & Domestic", 0 if all(n in MAJOR_DOMESTIC for n in bases) else 1
    return "Other", 0


def parse_match(title, link):
    parts = re.split(r"\s+v\s+", title, maxsplit=1)
    teams = [parse_team(p) for p in parts]
    if len(teams) == 1:
        teams.append(("", "", False))
    live = any(t[2] for t in teams)
    started = any(t[1] for t in teams)
    section, rank = classify([t[0] for t in teams])
    women = any(re.search(r"\bWomen\b", t[0]) for t in teams)
    return {
        "title": title, "link": link, "teams": teams, "section": section, "rank": rank, "women": women,
        "status": "live" if live else ("latest" if started else "upcoming"),
    }


def badge(name):
    b = base_name(name)
    if b in FULL_MEMBERS:
        return FULL_MEMBERS[b]
    if b in IPL_TEAMS:
        return IPL_TEAMS[b]
    words = re.findall(r"[A-Za-z]+", b)
    code = ASSOCIATES.get(b) or ("".join(w[0] for w in words[:3]).upper() if len(words) > 1 else b[:3].upper())
    return code or "?", PALETTE[sum(map(ord, b)) % len(PALETTE)], "#fff"


def score_html(score):
    if not score:
        return "<b>—</b>"
    innings = [s.strip() for s in score.split("&")]
    prev = "".join(f"<small>{html.escape(s)}</small>" for s in innings[:-1])
    return prev + f"<b>{html.escape(innings[-1])}</b>"


def match_card(m):
    label = {"live": '<span class="dot"></span>LIVE', "latest": "RECENT", "upcoming": "UPCOMING"}[m["status"]]
    chip = m["section"] if m["section"] != "Other" else "Club & Local"
    if m["women"]:
        chip += " · Women"
    rows = []
    for name, score, batting in m["teams"]:
        code, bg, fg = badge(name or "TBC")
        cls = "bat" if batting else ("dim" if m["status"] == "live" else "")
        tag = '<span class="bat-tag">BAT</span>' if batting else ""
        rows.append(
            f'<div class="row {cls}"><span class="av" style="background:{bg};color:{fg}">{html.escape(code)}</span>'
            f'<span class="nm" title="{html.escape(name)}">{html.escape(name or "TBC")}{tag}</span>'
            f'<span class="sc">{score_html(score)}</span></div>'
        )
    return (
        f'<a class="card {m["status"]}" href="{html.escape(m["link"])}" target="_blank" rel="noopener">'
        f'<div class="card-top"><span class="chip">{html.escape(chip)}</span>'
        f'<span class="status {m["status"]}">{label}</span></div>'
        + "".join(rows)
        + '<div class="card-foot">Full scorecard →</div></a>'
    )


@st.fragment(run_every=f"{REFRESH_SECONDS}s")
def scores_panel(search, live_only, category):
    try:
        matches = fetch_scores()
    except Exception as exc:  # network issues, feed down, etc.
        st.error(f"Couldn't load live scores right now ({exc}). Retrying automatically…")
        return

    live = sum(m["status"] == "live" for m in matches)
    intl = sum(m["section"] == "International" for m in matches)
    ipl = sum(m["section"] == "IPL" for m in matches)
    st.markdown(
        '<div class="stats">'
        f'<div class="stat"><div class="k">Live now</div><div class="v live">{live}</div></div>'
        f'<div class="stat"><div class="k">International</div><div class="v">{intl}</div></div>'
        f'<div class="stat"><div class="k">IPL</div><div class="v">{ipl}</div></div>'
        f'<div class="stat"><div class="k">Updated</div><div class="v">{datetime.now():%H:%M:%S}</div></div>'
        "</div>",
        unsafe_allow_html=True,
    )

    shown = [
        m for m in matches
        if (not live_only or m["status"] == "live")
        and (category in (None, "All") or m["section"] == category)
        and (not search or search.lower() in m["title"].lower())
    ]
    if not shown:
        st.markdown('<div class="empty">No matches fit these filters right now.</div>', unsafe_allow_html=True)
        return

    out = []
    for section in SECTIONS:
        group = sorted(
            (m for m in shown if m["section"] == section),
            key=lambda m: (STATUS_ORDER[m["status"]], m["rank"]),
        )
        if not group:
            continue
        title = "Club & Local" if section == "Other" else section
        out.append(
            f'<div class="sec-head"><span>{SECTION_ICONS[section]}</span><span class="t">{title}</span>'
            f'<span class="c">{len(group)}</span><span class="ln"></span></div>'
            '<div class="grid">' + "".join(match_card(m) for m in group) + "</div>"
        )
    out.append(
        f'<p class="note" style="margin-top:18px">Source: ESPNcricinfo public live-scores feed · '
        f"refreshes every {REFRESH_SECONDS}s · international and IPL fixtures are listed first.</p>"
    )
    st.markdown("".join(out), unsafe_allow_html=True)


# --------------------------------------------------------------------------- #
# Stream helpers
# --------------------------------------------------------------------------- #
def youtube_embed_url(url):
    """Turn any normal YouTube link into an embeddable URL, or None."""
    url = url.strip()
    if not url:
        return None
    p = urlparse(url if "://" in url else "https://" + url)
    host = p.netloc.lower().removeprefix("www.").removeprefix("m.")
    vid = None
    if host == "youtu.be":
        vid = p.path.lstrip("/").split("/")[0]
    elif host.endswith("youtube.com") or host.endswith("youtube-nocookie.com"):
        if p.path == "/watch":
            vid = parse_qs(p.query).get("v", [None])[0]
        else:
            m = re.match(r"^/(?:live|embed|shorts|v)/([\w-]{6,})", p.path)
            vid = m.group(1) if m else None
    if vid and re.fullmatch(r"[\w-]{6,}", vid):
        return f"https://www.youtube-nocookie.com/embed/{vid}?autoplay=1&rel=0"
    return None


def stream_panel():
    with st.container(border=True):
        st.markdown('<div class="panel-title"><span class="dot"></span>Live Stream</div>', unsafe_allow_html=True)
        mode = st.segmented_control(
            "Stream source", ["YouTube link", "Official channel"], default="YouTube link",
            label_visibility="collapsed",
        )

        embed = None
        if mode == "Official channel":
            channel = st.text_input(
                "Channel ID", placeholder="Official broadcaster's YouTube channel ID (UC…)",
                label_visibility="collapsed",
            ).strip()
            if channel:
                if re.fullmatch(r"UC[\w-]{22}", channel):
                    embed = f"https://www.youtube-nocookie.com/embed/live_stream?channel={channel}&autoplay=1"
                else:
                    st.warning("Channel IDs start with 'UC' and are 24 characters long.")
        else:
            url = st.text_input(
                "YouTube link", placeholder="Paste an official YouTube live link…",
                label_visibility="collapsed",
            )
            embed = youtube_embed_url(url)
            if url and not embed:
                st.warning("That doesn't look like a valid YouTube link.")

        if embed:
            components.html(
                f'<iframe src="{html.escape(embed)}" style="width:100%;aspect-ratio:16/9;border:0;'
                f'border-radius:12px;background:#000" allow="autoplay; encrypted-media; picture-in-picture; '
                f'fullscreen" allowfullscreen></iframe>',
                height=400,
            )
        else:
            st.markdown(
                '<div class="empty" style="aspect-ratio:16/9;display:flex;align-items:center;'
                'justify-content:center;flex-direction:column;gap:6px;padding:20px">'
                '<div style="font-size:2.2rem">📡</div><div><b>No stream selected</b></div>'
                '<div class="note">Paste a link from an official channel to start watching.</div></div>',
                unsafe_allow_html=True,
            )

    with st.container(border=True):
        st.markdown('<div class="panel-title">Official free sources</div>', unsafe_allow_html=True)
        cols = st.columns(2)
        for i, (name, link) in enumerate(OFFICIAL_SOURCES):
            cols[i % 2].link_button(f"{name} ↗", link, width="stretch")
        st.markdown(
            '<p class="note" style="margin:8px 0 0">Only publicly available, officially published streams are '
            "supported. Most international matches are shown by paid rights-holders (e.g. JioHotstar, "
            "Sky Sports, Willow, Fox Cricket) — watch those on the broadcaster's own site or app.</p>",
            unsafe_allow_html=True,
        )


# --------------------------------------------------------------------------- #
# HTML viewer helpers
# --------------------------------------------------------------------------- #
def open_blank_button(content, label="Open in about:blank  ↗"):
    """A button that opens about:blank in a new browser tab and writes the HTML into it.

    No window features are passed to window.open, so browsers open a regular tab
    (not a sized pop-up window). It runs on a user click, so it isn't blocked.
    """
    payload = json.dumps(content).replace("</", "<\\/")
    components.html(
        f"""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@600;700&display=swap');
  body {{margin:0; font-family: Inter, system-ui, sans-serif;}}
  button {{width:100%; height:44px; border:0; border-radius:10px; cursor:pointer; font-family:inherit;
    font-size:14px; font-weight:700; color:#fff; letter-spacing:.01em;
    background:linear-gradient(135deg,#059669,#10b981); box-shadow:0 6px 18px rgba(16,185,129,.28);
    transition:transform .12s, box-shadow .12s;}}
  button:hover {{transform:translateY(-1px); box-shadow:0 10px 22px rgba(16,185,129,.35);}}
  #msg {{font-size:12px; color:#ef4444; margin-top:4px; min-height:14px;}}
</style>
<button id="open">{label}</button>
<div id="msg"></div>
<script>
  const html = {payload};
  document.getElementById("open").addEventListener("click", () => {{
    const w = window.open("about:blank", "_blank");
    if (!w) {{
      document.getElementById("msg").textContent = "Your browser blocked the new tab - allow this site to open tabs and try again.";
      return;
    }}
    w.document.open();
    w.document.write(html);
    w.document.close();
  }});
</script>
""",
        height=66,
    )


def page_head(eyebrow, title, subtitle, meta):
    st.markdown(
        f'<div class="page-head"><div><div class="eyebrow">{eyebrow}</div><h2>{title}</h2>'
        f'<p>{subtitle}</p></div><div class="head-meta">{meta}</div></div>',
        unsafe_allow_html=True,
    )


@st.cache_data(show_spinner=False)
def load_template(file_name):
    return (TEMPLATE_DIR / file_name).read_text(encoding="utf-8")


# The cricket game's Play button is a small custom component (templates/index.html). Besides opening the
# game, it relays the game's online requests (sign-in, rooms, each ball) to multiplayer.py, which keeps
# everything in cricket_multiplayer.db - so players anywhere can meet in the same room.
cricket_bridge = components.declare_component("cricket_bridge", path=str(TEMPLATE_DIR))


@st.fragment
def cricket_launcher():
    request = st.session_state.get("cricket_bridge") or {}
    done = st.session_state.setdefault("cricket_done", {})
    responses = {}
    for req in (request.get("reqs") or [])[:50]:
        rid = str(req.get("id", ""))
        if rid and rid not in done:
            done[rid] = multiplayer.handle(req.get("op"), req.get("data"), rid)
        if rid in done:
            responses[rid] = done[rid]
    for rid in list(done)[:-300]:  # keep the reply cache small
        done.pop(rid)
    cricket_bridge(responses=responses, key="cricket_bridge", default=None)


def inspect_template(template_name):
    st.session_state.viewer_src = "Template"
    st.session_state.viewer_tpl = template_name


def templates_gallery():
    st.markdown('<div class="sec-head" style="margin-top:0"><span>✨</span><span class="t">Templates</span>'
                f'<span class="c">{len(TEMPLATES)}</span><span class="ln"></span></div>', unsafe_allow_html=True)
    for name, t in TEMPLATES.items():
        with st.container(border=True):
            info, play, inspect = st.columns([3.4, 1.3, 1], vertical_alignment="center", gap="medium")
            tags = "".join(f'<span class="tpl-tag">{html.escape(tag)}</span>' for tag in t["tags"])
            server = ""
            if t.get("online"):
                server = ('<div class="tpl-desc" style="margin-top:6px">🌐 <b>Online:</b> create a room and share its code. '
                          'Friends anywhere can join by opening this app. Keep this tab open while you play online.</div>')
            info.markdown(
                f'<div class="tpl"><div class="tpl-icon">{t["icon"]}</div><div><div class="tpl-name">{html.escape(name)}'
                f'</div><div class="tpl-desc">{html.escape(t["desc"])}</div><div>{tags}</div>{server}</div></div>',
                unsafe_allow_html=True,
            )
            with play:
                if t.get("online"):
                    cricket_launcher()
                else:
                    open_blank_button(load_template(t["file"]), "▶  Play in new tab")
            inspect.button("View code", key=f"inspect_{name}", on_click=inspect_template, args=(name,), width="stretch")


def html_viewer_tab():
    page_head("TOOLS", "HTML Viewer", "Preview an HTML file, inspect its source, or launch it in a clean about:blank tab.",
              "📄 .html · .htm")
    templates_gallery()
    st.session_state.setdefault("viewer_src", "Upload")
    st.session_state.setdefault("viewer_tpl", next(iter(TEMPLATES)))
    left, right = st.columns([1, 2.6], gap="large")

    with left:
        with st.container(border=True):
            st.markdown('<div class="panel-title">Source file</div>', unsafe_allow_html=True)
            source = st.segmented_control("Input", ["Upload", "Paste", "Template"], key="viewer_src",
                                          label_visibility="collapsed")
            name, content = None, ""
            if source == "Template":
                tpl = st.selectbox("Template", list(TEMPLATES), key="viewer_tpl", label_visibility="collapsed")
                name, content = TEMPLATES[tpl]["file"], load_template(TEMPLATES[tpl]["file"])
            elif source == "Paste":
                content = st.text_area("Paste HTML", height=240, placeholder="<!doctype html>\n<html>…</html>",
                                       label_visibility="collapsed")
                name = "pasted.html" if content.strip() else None
            else:
                up = st.file_uploader("Drop an HTML file", type=["html", "htm"], label_visibility="collapsed")
                if up is not None:
                    name, content = up.name, up.getvalue().decode("utf-8", errors="replace")

        height = 780
        if content.strip():
            with st.container(border=True):
                title = re.search(r"<title[^>]*>(.*?)</title>", content, re.I | re.S)
                st.markdown(
                    '<div class="panel-title">File details</div>'
                    '<div class="stats" style="grid-template-columns:repeat(2,1fr);margin:0 0 12px">'
                    f'<div class="stat"><div class="k">Size</div><div class="v">{len(content.encode()) / 1024:.1f} KB</div></div>'
                    f'<div class="stat"><div class="k">Lines</div><div class="v">{content.count(chr(10)) + 1}</div></div>'
                    "</div>"
                    f'<p class="note" style="margin:0 0 12px">📄 <b>{html.escape(name)}</b><br>'
                    f'Title: {html.escape(title.group(1).strip()) if title else "(none)"}</p>',
                    unsafe_allow_html=True,
                )
                open_blank_button(content)
                st.download_button("Download file", content, file_name=name, mime="text/html", width="stretch")
                height = st.slider("Preview height", 400, 1600, 780, step=40)

    with right:
        if content.strip():
            view = st.segmented_control("View", ["Preview", "Source"], default="Preview",
                                        label_visibility="collapsed")
            if view == "Source":
                st.code(content, language="html", line_numbers=True, height=height)
            else:
                components.html(content, height=height, scrolling=True)
        else:
            st.markdown(
                f'<div class="empty" style="height:{height}px;display:flex;align-items:center;'
                'justify-content:center;flex-direction:column;gap:8px">'
                '<div style="font-size:2.6rem">📄</div><div><b>Your preview will appear here</b></div>'
                '<div class="note">Upload or paste an HTML file, or pick a template, to get started.</div></div>',
                unsafe_allow_html=True,
            )


# --------------------------------------------------------------------------- #
# Layout - the tabs double as the top navigation bar
# --------------------------------------------------------------------------- #
tab_live, tab_viewer = st.tabs(["Live Centre", "HTML Viewer"])

with tab_live:
    page_head(
        "LIVE CENTRE", "Cricket Scores",
        "Ball-by-ball updates from around the world — international and IPL action first.",
        f'<span class="dot"></span>{datetime.now():%a %d %b %Y}',
    )
    scores_col, stream_col = st.columns([3, 2], gap="large")
    with scores_col:
        category = st.segmented_control("Category", ["All"] + SECTIONS, default="All",
                                        format_func=lambda s: "Club & Local" if s == "Other" else s,
                                        label_visibility="collapsed")
        f1, f2, f3 = st.columns([3, 1.2, 1], vertical_alignment="center")
        search = f1.text_input("Search", placeholder="🔍  Search teams…", label_visibility="collapsed")
        live_only = f2.toggle("Live only", value=False)
        if f3.button("↻ Refresh", width="stretch"):
            fetch_scores.clear()
        scores_panel(search, live_only, category)
    with stream_col:
        stream_panel()

with tab_viewer:
    html_viewer_tab()
