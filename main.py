import requests
import json
import time
import urllib.parse
import random
import feedparser
import pytz
import os
import sys
import signal
import logging
import base64
import subprocess
import asyncio
import shutil
from logging.handlers import RotatingFileHandler
from datetime import datetime
from flask import Flask
from threading import Thread, Lock

# ================= VIDEO FEATURE DEPENDENCY (NEW) =================
# edge-tts = Microsoft's free text-to-speech engine, no API key needed.
# Install: pip install edge-tts --break-system-packages
# ffmpeg must also be installed system-wide: sudo apt install ffmpeg
# If either is missing, video posts are silently skipped (logged once) —
# every other bot feature keeps working exactly as before.
try:
    import edge_tts
    EDGE_TTS_AVAILABLE = True
except ImportError:
    EDGE_TTS_AVAILABLE = False

FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None

# ================= .env SUPPORT (NEW) =================
# On Railway, env vars are set in the dashboard. On a VPS/terminal run from GitHub,
# it's much easier to keep them in a local .env file. This loads one if present -
# if python-dotenv isn't installed or there's no .env file, it silently does
# nothing and everything falls back to normal OS environment variables exactly
# like before. See .env.example in the repo.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ================= CONFIG =================
FB_PAGE_ID = os.getenv("FB_PAGE_ID")
FB_ACCESS_TOKEN = os.getenv("FB_ACCESS_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# ── Group auto-share (NEW) ────────────────────────────────────────────────────
# FB_GROUP_IDS  : comma-separated Facebook Group IDs to share every post into.
#                 Example: "123456789,987654321"
# FB_USER_TOKEN : User Access Token with publish_to_groups permission.
#                 Get from Graph API Explorer → User Token → add
#                 publish_to_groups permission. Falls back to FB_ACCESS_TOKEN.
#                 NOTE: publish_to_groups is only allowed in Facebook apps that
#                 are in Development Mode or have been approved. If your app is
#                 in Development Mode you can use it immediately for your own
#                 groups. If you get "permission denied", enable it in
#                 App Dashboard → App Review → Permissions.
FB_GROUP_IDS_RAW = os.getenv("FB_GROUP_IDS", "")
FB_GROUP_IDS = [g.strip() for g in FB_GROUP_IDS_RAW.split(",") if g.strip()]
FB_USER_TOKEN = os.getenv("FB_USER_TOKEN", FB_ACCESS_TOKEN)  # fallback to page token

# NEW: Telegram notifications (replaces the old Discord webhook logger).
# Defaults are set to the bot/chat you gave me, but can still be overridden
# via env vars on Railway/VPS without touching code.
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ================= LIVE CAMERA SYSTEM (ADDED) =================
# Uses the SAME Telegram bot and Facebook Page credentials already used by this bot.
# Camera URLs must be direct streams you are authorized to rebroadcast (HLS/HTTP/MJPEG/RTMP).
LIVE_CAM_MAX_SECONDS = int(os.getenv("LIVE_CAM_MAX_SECONDS", "7200"))
LIVE_CAM_FPS = os.getenv("LIVE_CAM_FPS", "30")
LIVE_CAM_VIDEO_BITRATE = os.getenv("LIVE_CAM_VIDEO_BITRATE", "3500k")
LIVE_CAM_AUDIO_BITRATE = os.getenv("LIVE_CAM_AUDIO_BITRATE", "128k")
LIVE_CAM_WIDTH = os.getenv("LIVE_CAM_WIDTH", "1280")
LIVE_CAM_HEIGHT = os.getenv("LIVE_CAM_HEIGHT", "720")
LIVE_CAM_AUTO_FALLBACK = os.getenv("LIVE_CAM_AUTO_FALLBACK", "true").lower() == "true"
LIVE_CAM_TITLE_PREFIX = os.getenv("LIVE_CAM_TITLE_PREFIX", "LIVE • USA")

LIVE_CAMERAS = []
for _i in range(1, 7):
    LIVE_CAMERAS.append({
        "id": _i,
        "name": os.getenv(f"LIVE_CAM_{_i}_NAME", f"Camera {_i}"),
        "url": os.getenv(f"LIVE_CAM_{_i}_URL", "").strip(),
        "location": os.getenv(f"LIVE_CAM_{_i}_LOCATION", "USA"),
    })

live_state_lock = Lock()
live_enabled = False
live_process = None
live_video_id = None
live_camera_index = None
live_started_at = None
live_monitor_thread = None
# SECURITY NOTE: the real token/chat id used to be hardcoded here as fallback
# values. That means anyone who ever saw this file (a repo, a support chat, a
# screenshot) could message-spam your bot or read your notifications. Put the
# real values ONLY in your .env file / VPS environment variables, never in code.
# If this token was ever shared anywhere, revoke it via @BotFather (/revoke)
# and generate a new one, then update .env.

# NEW: optional Instagram cross-posting - only activates if both are set.
# Leave unset and the bot behaves exactly as before (Facebook-only).
IG_ACCOUNT_ID = os.getenv("IG_ACCOUNT_ID")
IG_ACCESS_TOKEN = os.getenv("IG_ACCESS_TOKEN", FB_ACCESS_TOKEN)

# NEW: these were hardcoded before - now overridable via env for VPS flexibility,
# but default to the EXACT same values, so behavior is unchanged unless you set them.
TIMEZONE_NAME = os.getenv("BOT_TIMEZONE", "America/New_York")
RSS_FEED_URL = os.getenv(
    "RSS_FEED_URL",
    "https://news.google.com/rss/headlines/section/topic/US?hl=en-US&gl=US&ceid=US:en"
)

# ================= US NEWS FEEDS =================
# The Page targets a US audience, so US-focused feeds are preferred.
# The fallback feeds remain broad enough to catch major stories with US relevance.
EXTRA_RSS_FEEDS = [
    "https://news.google.com/rss/search?q=United+States+when:24h&hl=en-US&gl=US&ceid=US:en",
    "https://feeds.bbci.co.uk/news/world/us_and_canada/rss.xml",
    "https://feeds.npr.org/1001/rss.xml",
    "https://rss.nytimes.com/services/xml/rss/nyt/US.xml",
]

# US relevance terms. Stories matching these are preferred; if a feed has
# no matching stories, the bot can still use a major general-news fallback.
US_NEWS_KEYWORDS = {
    "united states": 5, "u.s.": 5, "us ": 3, "america": 4, "american": 4,
    "white house": 5, "washington": 4, "congress": 4, "senate": 4,
    "house of representatives": 4, "supreme court": 5, "president": 3,
    "federal": 3, "fbi": 3, "nasa": 3, "pentagon": 4,
    "california": 3, "texas": 3, "florida": 3, "new york": 3,
    "los angeles": 3, "chicago": 3, "miami": 3, "wall street": 3,
    "nasdaq": 3, "dow": 3, "fed": 2, "inflation": 2,
}
LOG_DIR = os.getenv("LOG_DIR", "logs")

REQUEST_TIMEOUT = 30  # seconds - FIX: no requests call had a timeout before, which
                       # could freeze the whole scheduler loop forever on a bad connection.

# ================= FILE LOGGING (NEW) =================
# On Railway you just read the dashboard console. On a VPS there's no dashboard,
# so this also writes everything to a rotating log file (logs/bot.log, max 5MB x 3
# backups) in addition to printing to console/Discord exactly as before.
os.makedirs(LOG_DIR, exist_ok=True)
_file_logger = logging.getLogger("fb_bot")
_file_logger.setLevel(logging.INFO)
if not _file_logger.handlers:
    _handler = RotatingFileHandler(os.path.join(LOG_DIR, "bot.log"), maxBytes=5_000_000, backupCount=3)
    _handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    _file_logger.addHandler(_handler)

# ================= STATE PERSISTENCE (NEW) =================
# Railway can restart/crash-restart the container without you touching anything.
# Before this, EVERYTHING (posted_slots, seen news, comment ids, etc.) lived only
# in RAM, so a restart made the bot forget what it already posted today and could
# cause duplicate posts or a whole slot getting skipped.
# This saves state to a local JSON file after every loop and reloads it on boot.
# NOTE: on Railway's default ephemeral disk this survives a crash/restart of the
# SAME deployment, but not a fresh redeploy - for that you'd need a Railway Volume
# mounted at STATE_DIR. Nothing about existing posting behavior changes either way.
STATE_DIR = os.getenv("STATE_DIR", "/tmp")
STATE_FILE = os.path.join(STATE_DIR, "bot_state.json")


def _set(lst):
    return set(lst) if lst else set()


def load_state():
    global posted_slots, posted_scenic_slots, posted_cartoon_slots
    global posted_quote_slots, posted_fact_slots
    global seen_news_regular, seen_news_cartoon, seen_quotes_today, seen_facts_today
    global holiday_posted_today, last_replied_comment_ids
    global scenic_daily_places, scenic_last_date, scenic_posted_places_today
    global daily_posted_posts, daily_summary_posted, weekly_history, weekly_summary_posted_on
    global telegram_update_offset
    global CATEGORY_ENABLED, GROUP_SHARE_ENABLED
    global last_reset_date
    global posted_poll_slots, seen_polls_today
    global posted_video_slots, seen_video_topics
    global BOT_PAUSED

    if not os.path.exists(STATE_FILE):
        return

    try:
        with open(STATE_FILE, "r") as f:
            s = json.load(f)

        posted_slots = _set(s.get("posted_slots"))
        posted_scenic_slots = _set(s.get("posted_scenic_slots"))
        posted_cartoon_slots = _set(s.get("posted_cartoon_slots"))
        posted_quote_slots = _set(s.get("posted_quote_slots"))
        posted_fact_slots = _set(s.get("posted_fact_slots"))

        seen_news_regular = _set(s.get("seen_news_regular"))
        seen_news_cartoon = _set(s.get("seen_news_cartoon"))
        seen_quotes_today = _set(s.get("seen_quotes_today"))
        seen_facts_today = _set(s.get("seen_facts_today"))

        holiday_posted_today = s.get("holiday_posted_today", False)
        last_replied_comment_ids = _set(s.get("last_replied_comment_ids"))

        scenic_daily_places = s.get("scenic_daily_places", [])
        scenic_last_date = s.get("scenic_last_date")  # stored as "YYYY-MM-DD" string or None
        scenic_posted_places_today = _set(s.get("scenic_posted_places_today"))

        daily_posted_posts = s.get("daily_posted_posts", [])
        daily_summary_posted = s.get("daily_summary_posted", False)
        weekly_history = s.get("weekly_history", [])
        weekly_summary_posted_on = s.get("weekly_summary_posted_on")
        posted_poll_slots = _set(s.get("posted_poll_slots"))
        seen_polls_today = set(s.get("seen_polls_today", []))
        posted_video_slots = _set(s.get("posted_video_slots"))
        seen_video_topics = set(s.get("seen_video_topics", []))
        last_reset_date = s.get("last_reset_date")
        BOT_PAUSED = s.get("bot_paused", False)

        saved_categories = s.get("category_enabled")
        if saved_categories:
            for k in CATEGORY_ENABLED:
                CATEGORY_ENABLED[k] = saved_categories.get(k, CATEGORY_ENABLED[k])

        saved_grp = s.get("group_share_enabled")
        if saved_grp:
            for k in GROUP_SHARE_ENABLED:
                GROUP_SHARE_ENABLED[k] = saved_grp.get(k, GROUP_SHARE_ENABLED[k])

        saved_streaks = s.get("category_fail_streak")
        if saved_streaks:
            for k in category_fail_streak:
                category_fail_streak[k] = saved_streaks.get(k, category_fail_streak[k])

        log("♻️ Restored bot state from previous run.")
    except Exception as e:
        log(f"⚠️ load_state() failed, starting fresh: {e}")


def save_state():
    try:
        s = {
            "posted_slots": list(posted_slots),
            "posted_scenic_slots": list(posted_scenic_slots),
            "posted_cartoon_slots": list(posted_cartoon_slots),
            "posted_quote_slots": list(posted_quote_slots),
            "posted_fact_slots": list(posted_fact_slots),

            "seen_news_regular": list(seen_news_regular),
            "seen_news_cartoon": list(seen_news_cartoon),
            "seen_quotes_today": list(seen_quotes_today),
            "seen_facts_today": list(seen_facts_today),

            "holiday_posted_today": holiday_posted_today,
            "last_replied_comment_ids": list(last_replied_comment_ids),

            "scenic_daily_places": scenic_daily_places,
            "scenic_last_date": scenic_last_date,
            "scenic_posted_places_today": list(scenic_posted_places_today),

            "daily_posted_posts": daily_posted_posts,
            "daily_summary_posted": daily_summary_posted,
            "weekly_history": weekly_history,
            "weekly_summary_posted_on": weekly_summary_posted_on,
            "posted_poll_slots": list(posted_poll_slots),
            "seen_polls_today": list(seen_polls_today),
            "posted_video_slots": list(posted_video_slots),
            "seen_video_topics": list(seen_video_topics),
            "category_enabled": CATEGORY_ENABLED,
            "group_share_enabled": GROUP_SHARE_ENABLED,
            "last_reset_date": last_reset_date,
            "bot_paused": BOT_PAUSED,
            "category_fail_streak": category_fail_streak,
        }
        with open(STATE_FILE, "w") as f:
            json.dump(s, f)
    except Exception as e:
        log(f"⚠️ save_state() failed: {e}")


# ================= MONETIZATION SETTINGS =================
MONETIZATION_MODE = "off"

AFFILIATE_LINKS = [
    "https://your-affiliate-link-1.com",
    "https://your-affiliate-link-2.com",
    "https://your-affiliate-link-3.com"
]

SPONSORS = [
    "XYZ News Partner",
    "Global Media Sponsor",
    "Trending Ads Network"
]

# ================= HASHTAGS / AUTHENTIC ENGAGEMENT =================
# Meta has explicitly warned that excessive hashtags and coordinated/fake
# engagement can reduce distribution. Keep hashtags few, relevant and natural.
HASHTAG_POOL = [
    "#USNews", "#BreakingNews", "#America", "#NewsUpdate", "#Politics",
    "#Business", "#Technology", "#Science", "#Weather", "#WorldNews",
]

def pick_hashtags(n=3):
    return " ".join(random.sample(HASHTAG_POOL, min(n, len(HASHTAG_POOL))))

def _clean_hashtags(text, max_tags=3):
    tags = []
    for raw in str(text or "").split():
        raw = raw.strip(".,!?;:()[]{}")
        if not raw:
            continue
        if not raw.startswith("#"):
            raw = "#" + raw
        # Reject generic engagement/farming tags.
        if raw.lower() in {
            "#viral", "#fyp", "#explore", "#trending", "#like4like",
            "#follow4follow", "#share4share", "#comment", "#giveaway"
        }:
            continue
        if raw not in tags:
            tags.append(raw)
    return " ".join(tags[:max_tags])

def pick_hashtags_smart(context_text, n=3):
    """Return a small set of topic-specific hashtags, never a hashtag dump."""
    try:
        text = call_gemini(
            f"Give exactly {n} concise Facebook hashtags for this US news topic. "
            f"Use only tags genuinely relevant to the topic. Avoid #viral, #fyp, "
            f"#explore and engagement-farming tags. Return ONLY hashtags.\n\n"
            f"Topic: {context_text[:500]}",
            retries=1, label="hashtags_smart"
        )
        cleaned = _clean_hashtags(text, n)
        if len(cleaned.split()) >= 2:
            return cleaned
    except Exception:
        pass
    return pick_hashtags(n)

# One natural question is okay; avoid stacked like/share/tag instructions.
NATURAL_QUESTIONS = [
    "What do you think about this?",
    "How do you see this playing out?",
    "What stands out to you most?",
    "Do you think this will matter long-term?",
]
def pick_natural_question():
    return random.choice(NATURAL_QUESTIONS)

# Follow prompts are deliberately rare and non-demanding.
FOLLOW_REMINDERS = [
    "Follow for more US news and updates.",
    "Follow for more updates as this story develops.",
]
FOLLOW_REMINDER_CHANCE = 0.10

def maybe_add_follow_reminder(caption):
    if random.random() < FOLLOW_REMINDER_CHANCE:
        return f"{caption}\n\n{random.choice(FOLLOW_REMINDERS)}"
    return caption

# ================= FLASK =================
app = Flask(__name__)


@app.route("/")
def home():
    return "Bot Running"


# ================= POST ANALYSIS DASHBOARD (NEW) =================
# A read-only web page at /dashboard showing today's posts (with live
# likes/comments/shares pulled from the Graph API) plus the rolling 7-day
# history that daily_summary()/weekly_summary() already build. This only
# READS existing analytics state (daily_posted_posts / weekly_history) - it
# does not change posting logic, scheduling, or any existing route/behavior.
@app.route("/dashboard")
def dashboard():
    rows_html = ""
    by_type_today = {}
    for p in daily_posted_posts:
        by_type_today[p["type"]] = by_type_today.get(p["type"], 0) + 1
        eng = get_post_engagement(p["id"]) or {}
        try:
            t_disp = datetime.fromisoformat(p["time"]).strftime("%H:%M:%S")
        except Exception:
            t_disp = p["time"]
        rows_html += f"""
        <tr>
            <td>{t_disp}</td>
            <td><span class="badge">{p['type']}</span></td>
            <td><a href="https://facebook.com/{p['id']}" target="_blank">{p['id']}</a></td>
            <td>👍 {eng.get('likes', '-')}</td>
            <td>💬 {eng.get('comments', '-')}</td>
            <td>🔁 {eng.get('shares', '-')}</td>
        </tr>"""

    if not rows_html:
        rows_html = '<tr><td colspan="6" class="empty">No posts yet today.</td></tr>'

    type_badges_html = "".join(
        f'<div class="stat"><div class="stat-num">{c}</div><div class="stat-label">{t}</div></div>'
        for t, c in by_type_today.items()
    ) or '<div class="empty">Nothing posted yet today.</div>'

    weekly_rows_html = ""
    for d in reversed(weekly_history):
        by_type_str = ", ".join(f"{t}: {c}" for t, c in d.get("by_type", {}).items()) or "-"
        weekly_rows_html += f"""
        <tr>
            <td>{d.get('date', '-')}</td>
            <td>{d.get('total', 0)}</td>
            <td>{by_type_str}</td>
            <td>{d.get('best_type') or '-'}</td>
        </tr>"""
    if not weekly_rows_html:
        weekly_rows_html = '<tr><td colspan="4" class="empty">No weekly history yet.</td></tr>'

    total_today = len(daily_posted_posts)

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta http-equiv="refresh" content="60">
        <title>Post Analysis Dashboard</title>
        <style>
            body {{ font-family: -apple-system, Segoe UI, Roboto, Arial, sans-serif;
                    background: #0f1115; color: #e6e8eb; margin: 0; padding: 24px; }}
            h1 {{ font-size: 20px; margin-bottom: 4px; }}
            .sub {{ color: #9aa0a6; font-size: 13px; margin-bottom: 24px; }}
            .stats-row {{ display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 28px; }}
            .stat {{ background: #1a1d24; border: 1px solid #2a2e37; border-radius: 10px;
                     padding: 14px 20px; min-width: 90px; text-align: center; }}
            .stat-num {{ font-size: 22px; font-weight: 700; color: #4da3ff; }}
            .stat-label {{ font-size: 12px; color: #9aa0a6; margin-top: 4px; text-transform: capitalize; }}
            table {{ width: 100%; border-collapse: collapse; margin-bottom: 32px;
                     background: #1a1d24; border-radius: 10px; overflow: hidden; }}
            th {{ text-align: left; background: #22262f; color: #9aa0a6; font-size: 12px;
                  padding: 10px 12px; text-transform: uppercase; }}
            td {{ padding: 10px 12px; border-top: 1px solid #2a2e37; font-size: 13px; }}
            a {{ color: #4da3ff; text-decoration: none; }}
            .badge {{ background: #2a2e37; padding: 2px 8px; border-radius: 999px; font-size: 12px; }}
            .empty {{ color: #6b7078; text-align: center; padding: 16px; }}
            h2 {{ font-size: 15px; color: #cfd3d8; margin: 0 0 12px; }}
        </style>
    </head>
    <body>
        <h1>📊 Post Analysis Dashboard</h1>
        <div class="sub">Auto-refreshes every 60s · Today: {now().strftime('%Y-%m-%d')} · Total posts today: {total_today}</div>

        <h2>Today by type</h2>
        <div class="stats-row">{type_badges_html}</div>

        <h2>Today's posts</h2>
        <table>
            <tr><th>Time</th><th>Type</th><th>Post ID</th><th>Likes</th><th>Comments</th><th>Shares</th></tr>
            {rows_html}
        </table>

        <h2>Last 7 days</h2>
        <table>
            <tr><th>Date</th><th>Total</th><th>By type</th><th>Best type</th></tr>
            {weekly_rows_html}
        </table>
    </body>
    </html>
    """
    return html


def run_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)


# ================= TIME =================
tz = pytz.timezone(TIMEZONE_NAME)  # NEW: configurable via BOT_TIMEZONE env var, same default as before


def now():
    return datetime.now(tz)


def reset_time():
    t = now()
    return t.hour == 0 and t.minute < 5


# ================= TIME SLOTS =================
# FIX (root cause of "0 likes / 0 reach"): this used to fire 10+10+5+2+2 = 29
# posts EVERY SINGLE DAY from one Page. That volume is way past what a normal
# page posts, and it's exactly the pattern Facebook's spam/"inauthentic
# behavior" systems look for from API-posting bots - once flagged, the Page's
# organic reach gets throttled toward ~0 regardless of how good the content
# is, which matches what you're seeing (posts look fine, zero views/likes).
# Cut down to ~9 posts/day total, spread out, so posting behavior looks like
# a normal page instead of a bot. Old values kept below (commented) in case
# you want to revert or re-tune later.
# OLD: TIME_SLOTS = [(6,0),(8,0),(10,0),(11,42),(14,0),(16,0),(18,0),(20,0),(22,0),(23,30)]
# OLD: SCENIC_SLOTS = [(7,0),(9,0),(11,0),(13,0),(15,15),(17,0),(19,0),(21,0),(22,30),(23,45)]
# OLD: CARTOON_SLOTS = [(7,15),(12,15),(13,26),(16,30),(19,30)]
# OLD: QUOTE_SLOTS = [(9,45),(20,45)]
# OLD: FACT_SLOTS = [(12,45),(18,45)]
# Conservative daily mix: 2 news + 1 of each legacy/new category + 2 Reels = 9
# scheduled publishing opportunities. Exact minutes are randomized daily.
TIME_SLOTS = [(8, 0), (18, 0)]
SCENIC_SLOTS = [(10, 30)]
CARTOON_SLOTS = [(15, 30)]
QUOTE_SLOTS = [(9, 0)]
FACT_SLOTS = [(19, 30)]
POLL_SLOTS = [(16, 30)]

# Two US-audience windows. A different minute is chosen each day.
VIDEO_WINDOWS = [((12, 0), (14, 0)), ((20, 0), (22, 0))]
VIDEO_SLOTS = []

posted_slots = set()
posted_scenic_slots = set()
posted_cartoon_slots = set()
posted_quote_slots = set()   # NEW
posted_fact_slots = set()    # NEW
posted_poll_slots = set()    # NEW
posted_video_slots = set()   # NEW

seen_polls_today: set = set()   # track poll topics to avoid repeating same day
seen_video_topics: set = set()  # track video topics to avoid repeating same day

# ================= SLOT JITTER (NEW) =================
# Each slot gets a random 0-4 minute offset recomputed every midnight reset.
# Posts still fire at roughly the scheduled time but never at the EXACT same
# minute every single day, which reduces bot-pattern detection by Facebook.
def _jitter_slots(slots):
    """Apply a random 0-30 min offset to each (h, m) slot. Recomputed every midnight
    so posts never fire at the exact same minute two days in a row. All slot gaps
    in this bot are 5+ hours apart so 30-min jitter never causes slot collisions."""
    result = []
    for (h, m) in slots:
        offset = random.randint(0, 30)
        total = h * 60 + m + offset
        result.append((total // 60 % 24, total % 60))
    return result

_jittered_time_slots = _jitter_slots(TIME_SLOTS)
_jittered_scenic_slots = _jitter_slots(SCENIC_SLOTS)
_jittered_cartoon_slots = _jitter_slots(CARTOON_SLOTS)
_jittered_quote_slots = _jitter_slots(QUOTE_SLOTS)
_jittered_fact_slots = _jitter_slots(FACT_SLOTS)
_jittered_poll_slots = _jitter_slots(POLL_SLOTS)   # NEW
_last_video_slots = []

def _randomize_video_slots(previous=None):
    previous = previous or []
    chosen = []
    for start, end in VIDEO_WINDOWS:
        a = start[0] * 60 + start[1]
        b = end[0] * 60 + end[1]
        candidates = [m for m in range(a, b + 1)
                      if (m // 60, m % 60) not in previous]
        if not candidates:
            candidates = list(range(a, b + 1))
        chosen.append(random.choice(candidates))
    return [(m // 60, m % 60) for m in chosen]

_jittered_video_slots = _randomize_video_slots()

# ================= CATEGORY ON/OFF TOGGLES (NEW) =================
# Lets you turn each of the 5 post categories on/off from Telegram (buttons),
# without touching anything else - slot times, content generation, and
# posting logic all stay exactly the same. Persisted in bot_state.json so a
# restart remembers your choice.
CATEGORY_ENABLED = {
    "news": True,
    "scenic": True,
    "cartoon": True,
    "quote": True,
    "fact": True,
    "poll": True,
    "video": True,   # NEW: daily AI-generated video Reel
}

# Controls which post types get shared to FB groups.
# Scenic/Quote/Holiday off by default — groups prefer news/debate content.
GROUP_SHARE_ENABLED = {
    "news":    True,
    "cartoon": True,
    "fact":    True,
    "poll":    True,
    "video":   True,   # NEW
    "scenic":  False,
    "quote":   False,
    "holiday": False,
}
CATEGORY_LABELS = {
    "news":    "📰 News",
    "scenic":  "🏞️ Scenic",
    "cartoon": "🎨 Cartoon",
    "quote":   "💬 Quote",
    "fact":    "🧠 Fact",
    "poll":    "🗳️ Daily Poll",
    "video":   "🎬 Daily Video",
}

# ================= CATEGORY DOWN ALERT (NEW) =================
category_fail_streak = {"news": 0, "scenic": 0, "cartoon": 0, "quote": 0, "fact": 0, "poll": 0, "video": 0}
CATEGORY_DOWN_ALERT_THRESHOLD = 2  # days

seen_news_regular = set()
seen_news_cartoon = set()
seen_quotes_today = set()    # NEW
seen_facts_today = set()     # NEW

MAX_SEEN_NEWS = 500  # FIX: these sets grew forever (memory leak on long uptime). Cap them.
MAX_REPLIED_COMMENT_IDS = 3000  # FIX: same idea for replied-comment tracking (see below)


def remember_news(seen_set, title, desc=""):
    # Primary key: title. Secondary key: first 60 chars of description.
    # This catches the same story republished under a different headline.
    seen_set.add(title.strip().lower())
    if desc:
        seen_set.add(desc.strip().lower()[:60])
    if len(seen_set) > MAX_SEEN_NEWS:
        for t in list(seen_set)[: len(seen_set) - MAX_SEEN_NEWS]:
            seen_set.discard(t)


def _news_seen(seen_set, title, desc=""):
    """True if we've already posted this story (title OR description match)."""
    if title.strip().lower() in seen_set:
        return True
    if desc and desc.strip().lower()[:60] in seen_set:
        return True
    return False


# ================= HOLIDAY CONFIG =================
HOLIDAYS = {
    "07-04": "🎆 Happy Independence Day, America!",
    "10-31": "🎃 Happy Halloween! Stay spooky!",
    "12-25": "🎄 Merry Christmas! Wishing you joy and peace!",
    "01-01": "🎉 Happy New Year! Welcome 2026!",
    "02-14": "💘 Happy Valentine's Day! Spread the love!",
    "05-12": "👩 Happy Mother's Day!",
    "06-21": "👨 Happy Father's Day!",
}

holiday_posted_today = False

# NEW: analytics state
daily_posted_posts = []       # [{"id":..., "type":..., "time": iso_string}, ...] - resets daily
daily_summary_posted = False  # resets daily
weekly_history = []           # NEW: [{"date":..., "total":..., "by_type":{...}}, ...] rolling 7 days
weekly_summary_posted_on = None  # NEW: date string of last weekly digest, to avoid double-posting
last_reset_date = None  # FIX: date string of the last daily reset, so the reset block
                         # (and its Telegram log message) only fires ONCE per day instead
                         # of once every scheduler loop (~15x) during the 00:00-00:05 window


# ================= TELEGRAM NOTIFICATIONS (NEW - replaces Discord) =================
# Sends every log() message to your Telegram DM instead of a Discord webhook.
# Nicely formatted: a status emoji + bold category line + timestamp, using
# Telegram's HTML parse mode (safer than Markdown - no escaping surprises).
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"


def _telegram_format(msg):
    """Wrap the raw log message in a clean HTML card for Telegram."""
    if msg.startswith("✅"):
        label = "SUCCESS"
    elif msg.startswith("⚠️"):
        label = "WARNING"
    elif msg.startswith("❌") or msg.startswith("🔥"):
        label = "ERROR"
    elif msg.startswith("♻️") or msg.startswith("🔄") or msg.startswith("🛑"):
        label = "SYSTEM"
    else:
        label = "INFO"

    ts = now().strftime("%Y-%m-%d %H:%M:%S")
    safe_msg = (
        msg.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
    return f"<b>🤖 FB Auto-Bot — {label}</b>\n<code>{ts}</code>\n\n{safe_msg}"


def send_telegram_message(msg, retries=2):
    """Sends a message to Telegram, chunked to fit the 4096 char limit, with retries."""
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        return
    text = _telegram_format(msg)
    chunks = [text[i:i + 4000] for i in range(0, len(text), 4000)] or [text]
    for chunk in chunks:
        for attempt in range(1, retries + 1):
            try:
                r = requests.post(
                    TELEGRAM_API_URL,
                    json={
                        "chat_id": TELEGRAM_CHAT_ID,
                        "text": chunk,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": True,
                    },
                    timeout=REQUEST_TIMEOUT,
                )
                if r.status_code == 200:
                    break
                print(f"log() Telegram HTTP {r.status_code} (attempt {attempt}/{retries}): {r.text[:300]}")
            except Exception as e:
                print(f"log() failed to reach Telegram (attempt {attempt}/{retries}): {e}")
            time.sleep(2)


# ================= TELEGRAM PHOTO NOTIFICATIONS (NEW) =================
# Sends the actual uploaded photo to Telegram, with a details caption. Used
# only for the "full post details" notification below - never touches the
# existing text-only log()/send_telegram_message() path, so nothing about
# current notifications changes.
TELEGRAM_PHOTO_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"


def send_telegram_photo(image_bytes, caption, retries=2):
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        return False
    # Telegram caption limit is 1024 chars for photo messages.
    safe_caption = caption[:1024]
    for attempt in range(1, retries + 1):
        try:
            r = requests.post(
                TELEGRAM_PHOTO_API_URL,
                data={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "caption": safe_caption,
                    "parse_mode": "HTML",
                },
                files={"photo": ("post.jpg", image_bytes, "image/jpeg")},
                timeout=REQUEST_TIMEOUT,
            )
            if r.status_code == 200:
                return True
            print(f"send_telegram_photo HTTP {r.status_code} (attempt {attempt}/{retries}): {r.text[:300]}")
        except Exception as e:
            print(f"send_telegram_photo failed to reach Telegram (attempt {attempt}/{retries}): {e}")
        time.sleep(2)
    return False


# ================= TELEGRAM ON-DEMAND COMMANDS (NEW) =================
# Lets you ASK the bot for stats any time by texting it in Telegram, instead
# of only getting push notifications. Uses long-polling (getUpdates) - no
# webhook or public URL/port needed, so it works fine on a plain VPS. The
# offset is persisted in bot_state.json so a restart doesn't replay old
# messages. Only replies to messages from TELEGRAM_CHAT_ID (i.e. you).
TELEGRAM_GETUPDATES_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
telegram_update_offset = 0


# ================= LIVE CAMERA CONTROL =================
def _live_camera_configured(cam):
    return bool(cam.get("url"))


def _facebook_create_live(title, description=""):
    """Create a Facebook Live broadcast using the Page access token."""
    if not (FB_PAGE_ID and FB_ACCESS_TOKEN):
        return None
    try:
        r = requests.post(
            f"https://graph.facebook.com/v20.0/{FB_PAGE_ID}/live_videos",
            data={
                "status": "LIVE_NOW",
                "title": title[:200],
                "description": description[:5000],
                "access_token": FB_ACCESS_TOKEN,
            },
            timeout=REQUEST_TIMEOUT,
        )
        data = r.json()
        if r.status_code >= 400 or "error" in data:
            log(f"❌ Live camera Facebook create failed: {data}")
            return None
        return data
    except Exception as e:
        log(f"❌ Live camera Facebook create exception: {e}")
        return None


def _facebook_end_live(video_id):
    if not (video_id and FB_ACCESS_TOKEN):
        return
    try:
        r = requests.post(
            f"https://graph.facebook.com/v20.0/{video_id}",
            data={"end_live_video": "true", "access_token": FB_ACCESS_TOKEN},
            timeout=REQUEST_TIMEOUT,
        )
        if r.status_code >= 400:
            log(f"⚠️ Facebook live end returned HTTP {r.status_code}: {r.text[:300]}")
    except Exception as e:
        log(f"⚠️ Facebook live end failed: {e}")


def _stop_live_camera(reason="Stopped by Telegram"):
    global live_enabled, live_process, live_video_id, live_camera_index, live_started_at
    with live_state_lock:
        live_enabled = False
        proc = live_process
        video_id = live_video_id
        live_process = None
        live_video_id = None
        live_camera_index = None
        live_started_at = None
    if proc and proc.poll() is None:
        try:
            proc.terminate()
            proc.wait(timeout=8)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    if video_id:
        _facebook_end_live(video_id)
    send_telegram_message(f"🛑 Live camera stopped.\nReason: {reason}")


def _start_live_camera(index, automatic=False):
    global live_enabled, live_process, live_video_id, live_camera_index, live_started_at, live_monitor_thread
    if not (0 <= index < len(LIVE_CAMERAS)):
        return False
    cam = LIVE_CAMERAS[index]
    if not _live_camera_configured(cam):
        send_telegram_message(f"⚠️ {cam['name']} has no LIVE_CAM_{cam['id']}_URL configured.")
        return False
    if not FFMPEG_AVAILABLE:
        send_telegram_message("❌ FFmpeg is not installed; live camera cannot start.")
        return False

    with live_state_lock:
        already = live_process is not None and live_process.poll() is None
    if already:
        send_telegram_message("⚠️ A Facebook Live is already running. Stop it before selecting another camera.")
        return False

    title = f"{LIVE_CAM_TITLE_PREFIX} — {cam['name']}"
    description = f"Live view from {cam['location']}. Officially authorized source."
    fb = _facebook_create_live(title, description)
    if not fb:
        return False
    stream_url = fb.get("stream_url") or fb.get("secure_stream_url")
    video_id = fb.get("id")
    if not stream_url:
        log(f"❌ Facebook Live response had no stream URL: {fb}")
        if video_id:
            _facebook_end_live(video_id)
        send_telegram_message(f"❌ Could not start {cam['name']}: Facebook returned no stream URL.")
        return False

    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "warning",
        "-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5",
        "-i", cam["url"],
        "-vf", f"scale={LIVE_CAM_WIDTH}:{LIVE_CAM_HEIGHT}:force_original_aspect_ratio=decrease,pad={LIVE_CAM_WIDTH}:{LIVE_CAM_HEIGHT}:(ow-iw)/2:(oh-ih)/2",
        "-r", LIVE_CAM_FPS,
        "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
        "-b:v", LIVE_CAM_VIDEO_BITRATE, "-maxrate", LIVE_CAM_VIDEO_BITRATE,
        "-bufsize", "7000k", "-pix_fmt", "yuv420p", "-g", str(int(LIVE_CAM_FPS) * 2),
        "-c:a", "aac", "-b:a", LIVE_CAM_AUDIO_BITRATE, "-ar", "44100", "-ac", "2",
        "-f", "flv", stream_url,
    ]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    except Exception as e:
        if video_id:
            _facebook_end_live(video_id)
        send_telegram_message(f"❌ FFmpeg could not start: {e}")
        return False

    with live_state_lock:
        live_enabled = True
        live_process = proc
        live_video_id = video_id
        live_camera_index = index
        live_started_at = time.time()

    mode = "automatic fallback" if automatic else "manual"
    send_telegram_message(f"🔴 LIVE started\n📍 {cam['name']}\n🌎 {cam['location']}\n⏱️ Maximum: 2 hours\nMode: {mode}")
    live_monitor_thread = Thread(target=_monitor_live_camera, daemon=True)
    live_monitor_thread.start()
    return True


def _monitor_live_camera():
    global live_enabled, live_process, live_video_id, live_camera_index, live_started_at
    while True:
        with live_state_lock:
            proc = live_process
            started = live_started_at
            current = live_camera_index
            enabled = live_enabled
        if not enabled or proc is None:
            return
        elapsed = time.time() - started if started else 0
        if elapsed >= LIVE_CAM_MAX_SECONDS:
            _stop_live_camera("2-hour safety limit reached")
            return
        if proc.poll() is not None:
            with live_state_lock:
                live_enabled = False
                video_id = live_video_id
                failed_index = live_camera_index
                live_process = None
                live_video_id = None
                live_camera_index = None
                live_started_at = None
            if video_id:
                _facebook_end_live(video_id)
            failed_name = LIVE_CAMERAS[failed_index]["name"] if failed_index is not None else "selected camera"
            send_telegram_message(f"⚠️ Live camera failed/down: {failed_name}")
            if LIVE_CAM_AUTO_FALLBACK:
                for offset in range(1, len(LIVE_CAMERAS) + 1):
                    nxt = ((failed_index or 0) + offset) % len(LIVE_CAMERAS)
                    if _live_camera_configured(LIVE_CAMERAS[nxt]) and _start_live_camera(nxt, automatic=True):
                        return
            send_telegram_message("❌ No configured backup camera could be started.")
            return
        time.sleep(5)


def build_live_camera_keyboard():
    buttons = [[{"text": "🔴 STOP LIVE", "callback_data": "live_stop"}]]
    row = []
    for i, cam in enumerate(LIVE_CAMERAS):
        state = "🟢" if _live_camera_configured(cam) else "⚪"
        row.append({"text": f"{state} {cam['name']}", "callback_data": f"live_cam_{i}"})
        if len(row) == 2:
            buttons.append(row); row = []
    if row:
        buttons.append(row)
    buttons.append([{"text": "🔄 Refresh", "callback_data": "live_menu"}])
    return {"inline_keyboard": buttons}


def send_live_camera_menu():
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        return
    configured = sum(1 for c in LIVE_CAMERAS if _live_camera_configured(c))
    with live_state_lock:
        active = live_enabled
        active_name = LIVE_CAMERAS[live_camera_index]["name"] if live_camera_index is not None else "None"
    text = (
        "📡 *LIVE CAMERA CONTROL*\n\n"
        f"Configured: {configured}/6\n"
        f"Status: {'🔴 LIVE' if active else '⚪ OFF'}\n"
        f"Current: {active_name}\n\n"
        "Select an authorized camera to start Facebook Live.\n"
        "Maximum live duration: 2 hours.\n"
        "If a stream fails, the bot can automatically try the next configured camera."
    )
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown", "reply_markup": build_live_camera_keyboard()},
            timeout=REQUEST_TIMEOUT,
        )
    except Exception as e:
        log(f"⚠️ send_live_camera_menu failed: {e}")


def build_stats_text():
    """Live 'right now' snapshot of today's posts + engagement - separate
    from the once-a-day daily_summary(), for on-demand /stats checks."""
    if not daily_posted_posts:
        return "📊 Today so far: no posts yet."
    lines = [f"📊 Stats so far today ({now().strftime('%Y-%m-%d %H:%M')})",
             f"Total posts: {len(daily_posted_posts)}"]
    by_type = {}
    for p in daily_posted_posts:
        by_type[p["type"]] = by_type.get(p["type"], 0) + 1
    for t, c in by_type.items():
        lines.append(f"  - {t}: {c}")

    total_likes = total_comments = total_shares = 0
    any_data = False
    for p in daily_posted_posts:
        eng = get_post_engagement(p["id"])
        if eng:
            any_data = True
            total_likes += eng["likes"]
            total_comments += eng["comments"]
            total_shares += eng["shares"]
    if any_data:
        lines.append(f"👍 {total_likes}  💬 {total_comments}  🔁 {total_shares} (all of today's posts combined)")
    else:
        lines.append("ℹ️ Engagement data unavailable (check Page Insights permission on the FB token).")

    # Best posting hour from weekly history
    if weekly_history:
        hour_eng: dict = {}
        for day in weekly_history:
            for dp in day.get("posts", []):
                h = dp.get("hour")
                e = dp.get("engagement", 0)
                if h is not None:
                    hour_eng[h] = hour_eng.get(h, 0) + e
        if hour_eng:
            best_h = max(hour_eng, key=lambda h: hour_eng[h])
            lines.append(f"🕐 Best hour this week: {best_h:02d}:xx "
                         f"({hour_eng[best_h]} engagement)")

    return "\n".join(lines)


def build_settings_keyboard():
    """Unified settings keyboard — Post Categories + Group Sharing in one view."""
    buttons = []

    # Section header (non-clickable display row)
    buttons.append([{"text": "─── 📋 POST CATEGORIES ───", "callback_data": "noop"}])
    row = []
    for key, label in CATEGORY_LABELS.items():
        icon = "🟢" if CATEGORY_ENABLED.get(key, True) else "🔴"
        row.append({"text": f"{icon} {label}", "callback_data": f"cat_{key}"})
        if len(row) == 2:
            buttons.append(row); row = []
    if row: buttons.append(row)

    # Group share reminder section
    buttons.append([{"text": "─── 📤 GROUP SHARE REMINDERS ───", "callback_data": "noop"}])
    grp_row = []
    grp_labels = {"news": "📰 News", "cartoon": "🎨 Cartoon",
                  "fact": "🧠 Fact", "poll": "🗳️ Poll",
                  "video": "🎬 Video",
                  "scenic": "🏞️ Scenic", "quote": "💬 Quote"}
    for key, label in grp_labels.items():
        icon = "🟢" if GROUP_SHARE_ENABLED.get(key, False) else "🔴"
        grp_row.append({"text": f"{icon} {label}", "callback_data": f"grp_{key}"})
        if len(grp_row) == 2:
            buttons.append(grp_row); grp_row = []
    if grp_row: buttons.append(grp_row)

    # Bottom controls
    buttons.append([
        {"text": "⏸️ Pause Bot" if not BOT_PAUSED else "▶️ Resume Bot",
         "callback_data": "toggle_pause"},
    ])
    buttons.append([{"text": "📡 Live Cameras", "callback_data": "live_menu"}])
    return {"inline_keyboard": buttons}


def send_settings_message():
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": (
                    "⚙️ *Bot Settings*\n\n"
                    "📋 *POST CATEGORIES* — what gets posted daily\n"
                    "📤 *GROUP SHARE REMINDERS* — Telegram button appears after post → tap to share to groups\n\n"
                    "Tap to toggle ON🟢 / OFF🔴:"
                ),
                "parse_mode": "Markdown",
                "reply_markup": build_settings_keyboard(),
            },
            timeout=REQUEST_TIMEOUT,
        )
    except Exception as e:
        log(f"⚠️ send_settings_message failed: {e}")


def update_settings_message(chat_id, message_id):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/editMessageReplyMarkup",
            json={
                "chat_id": chat_id,
                "message_id": message_id,
                "reply_markup": build_settings_keyboard(),
            },
            timeout=REQUEST_TIMEOUT,
        )
    except Exception as e:
        log(f"⚠️ update_settings_message failed: {e}")


def build_categories_keyboard():
    """Legacy — keep for backward compat, routes to unified settings."""
    return build_settings_keyboard()


def send_categories_message():
    """Legacy — keep for backward compat."""
    send_settings_message()


def answer_callback_query(callback_query_id, text=""):
    """NEW: acknowledges a button tap so Telegram stops showing the loading spinner."""
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery",
            json={"callback_query_id": callback_query_id, "text": text},
            timeout=REQUEST_TIMEOUT,
        )
    except Exception as e:
        log(f"⚠️ answer_callback_query failed: {e}")


def update_categories_message(chat_id, message_id):
    """NEW: refreshes the button grid in place after a toggle, so the message
    always reflects the latest ON/OFF state instead of piling up new ones."""
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/editMessageReplyMarkup",
            json={
                "chat_id": chat_id,
                "message_id": message_id,
                "reply_markup": build_categories_keyboard(),
            },
            timeout=REQUEST_TIMEOUT,
        )
    except Exception as e:
        log(f"⚠️ update_categories_message failed: {e}")


def check_telegram_commands():
    """Polls Telegram for new messages/button taps sent TO the bot and replies
    to simple commands (/stats, /help, /categories, /reach, /pause, /resume)
    or toggles a category on/off. Safe to call repeatedly - it only looks at
    updates newer than telegram_update_offset."""
    global telegram_update_offset, BOT_PAUSED
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        return
    try:
        r = requests.get(
            TELEGRAM_GETUPDATES_URL,
            params={"offset": telegram_update_offset + 1, "timeout": 0},
            timeout=REQUEST_TIMEOUT,
        )
        data = r.json()
        if not data.get("ok"):
            return
        for update in data.get("result", []):
            telegram_update_offset = max(telegram_update_offset, update["update_id"])

            cb = update.get("callback_query")
            if cb:
                cb_chat_id = str(cb.get("message", {}).get("chat", {}).get("id", ""))
                if cb_chat_id != str(TELEGRAM_CHAT_ID):
                    continue
                cb_data = cb.get("data", "")
                message_id = cb.get("message", {}).get("message_id")

                if cb_data == "noop":
                    answer_callback_query(cb["id"], "")

                elif cb_data == "live_menu":
                    answer_callback_query(cb["id"], "Live camera menu")
                    send_live_camera_menu()

                elif cb_data == "live_stop":
                    answer_callback_query(cb["id"], "Stopping live...")
                    _stop_live_camera("Stopped from Telegram")

                elif cb_data.startswith("live_cam_"):
                    try:
                        idx = int(cb_data.split("_")[-1])
                    except ValueError:
                        idx = -1
                    answer_callback_query(cb["id"], "Starting live...")
                    _start_live_camera(idx)

                elif cb_data.startswith("cat_"):
                    key = cb_data[4:]
                    if key in CATEGORY_ENABLED:
                        CATEGORY_ENABLED[key] = not CATEGORY_ENABLED[key]
                        save_state()
                        state = "ON ✅" if CATEGORY_ENABLED[key] else "OFF ⛔"
                        answer_callback_query(cb["id"], f"{CATEGORY_LABELS.get(key, key)} {state}")
                        if message_id:
                            update_settings_message(cb_chat_id, message_id)

                elif cb_data.startswith("grp_"):
                    key = cb_data[4:]
                    if key in GROUP_SHARE_ENABLED:
                        GROUP_SHARE_ENABLED[key] = not GROUP_SHARE_ENABLED[key]
                        save_state()
                        state = "ON ✅" if GROUP_SHARE_ENABLED[key] else "OFF ⛔"
                        answer_callback_query(cb["id"], f"Group share {key} {state}")
                        if message_id:
                            update_settings_message(cb_chat_id, message_id)

                elif cb_data == "toggle_pause":
                    BOT_PAUSED = not BOT_PAUSED
                    save_state()
                    state = "PAUSED ⏸️" if BOT_PAUSED else "RESUMED ▶️"
                    answer_callback_query(cb["id"], f"Bot {state}")
                    if message_id:
                        update_settings_message(cb_chat_id, message_id)

                # Legacy support: old toggle_ callbacks still work
                elif cb_data.startswith("toggle_"):
                    key = cb_data[7:]
                    if key in CATEGORY_ENABLED:
                        CATEGORY_ENABLED[key] = not CATEGORY_ENABLED[key]
                        save_state()
                        state = "ON ✅" if CATEGORY_ENABLED[key] else "OFF ⛔"
                        answer_callback_query(cb["id"], f"{CATEGORY_LABELS.get(key, key)} {state}")
                        if message_id:
                            update_settings_message(cb_chat_id, message_id)
                    else:
                        answer_callback_query(cb["id"], "Unknown")
                continue

            msg = update.get("message", {})
            chat_id = str(msg.get("chat", {}).get("id", ""))
            text = (msg.get("text") or "").strip().lower()
            if chat_id != str(TELEGRAM_CHAT_ID):
                continue  # ignore anyone except you
            if text in ("/live", "/livecam", "/cameras"):
                send_live_camera_menu()
            elif text in ("/stoplive", "/stop_live"):
                _stop_live_camera("Stopped from Telegram command")
            elif text in ("/stats", "/status"):
                send_telegram_message(build_stats_text())
            elif text in ("/reach", "/why", "/diagnostics"):
                send_telegram_message(build_reach_report_text())
            elif text in ("/categories", "/settings", "/s"):
                send_settings_message()
            elif text == "/test":
                send_telegram_message("🧪 Generating test news post now...")
                news_list = get_news()
                if news_list:
                    news = random.choice(news_list)
                    ai = ai_generate(news["title"], news["desc"])
                    img = generate_image(ai["image_prompt"])
                    result = post_fb(ai["caption"], img, alt_text=news["title"], post_type="news")
                    if "id" in result:
                        send_telegram_message(f"✅ Test post published!\nhttps://facebook.com/{result['id']}")
                    else:
                        send_telegram_message(f"❌ Test post failed: {result}")
                else:
                    send_telegram_message("❌ No news available right now.")
            elif text == "/token":
                check_token_expiry(quiet=False)
            elif text == "/pause":
                BOT_PAUSED = True
                save_state()
                send_telegram_message("⏸️ Bot PAUSED. No new posts or comment replies until you send /resume.")
            elif text == "/resume":
                BOT_PAUSED = False
                save_state()
                send_telegram_message("▶️ Bot RESUMED. Back to normal posting schedule.")
            elif text == "/help":
                send_telegram_message(
                    "🤖 *Bot Commands*\n\n"
                    "/settings — ⚙️ All settings (categories + group sharing + pause)\n"
                    "/stats — 📊 Today's posts + engagement\n"
                    "/reach — 🔍 Why reach is low\n"
                    "/test — 🧪 Publish one news post now\n"
                    "/token — 🔑 Check FB token expiry\n"
                    "/pause — ⏸️ Pause bot\n"
                    "/resume — ▶️ Resume bot\n"
                    "/help — this list"
                )
    except Exception as e:
        log(f"⚠️ check_telegram_commands failed: {e}")


# ================= LOG =================
def log(msg):
    print(msg)
    try:
        _file_logger.info(msg)  # NEW: also persist to logs/bot.log for VPS debugging
    except Exception as e:
        print(f"log() failed to write to file: {e}")
    try:
        send_telegram_message(msg)
    except Exception as e:
        print(f"log() failed to reach Telegram: {e}")


# ================= STARTUP VALIDATION =================
def validate_config():
    missing = []
    if not FB_PAGE_ID:       missing.append("FB_PAGE_ID")
    if not FB_ACCESS_TOKEN:  missing.append("FB_ACCESS_TOKEN")
    if not GEMINI_API_KEY:   missing.append("GEMINI_API_KEY")
    if missing:
        log(f"⚠️ Missing required environment variables: {', '.join(missing)}. "
            f"The bot will run but posting/AI generation will fail until these are set.")
    else:
        log("✅ Config validated — all required env vars present.")

    if CF_ACCOUNT_ID and CF_API_TOKEN:
        log("🖼️ Image source: Cloudflare Workers AI (primary), pollinations.ai + Stable Horde as fallback.")
    else:
        log("🖼️ Image source: pollinations.ai (primary), Stable Horde as fallback. "
            "Set CF_ACCOUNT_ID + CF_API_TOKEN to switch to higher-quality Cloudflare Workers AI as primary.")


def register_telegram_commands():
    """Register Telegram slash commands and the chat menu on startup.

    Uses a small retry so a transient Telegram/API/network hiccup during PM2
    restart does not leave the command menu missing. This does not affect the
    Facebook posting scheduler.
    """
    if not TELEGRAM_BOT_TOKEN:
        return

    commands = [
        {"command": "settings", "description": "⚙️ All settings — categories, groups, pause"},
        {"command": "stats",    "description": "📊 Today's posts + engagement + best hour"},
        {"command": "reach",    "description": "🔍 Why reach/likes are low"},
        {"command": "test",     "description": "🧪 Publish one news post immediately"},
        {"command": "token",    "description": "🔑 Check Facebook token expiry"},
        {"command": "pause",    "description": "⏸️ Pause all posting"},
        {"command": "resume",   "description": "▶️ Resume posting"},
        {"command": "help",     "description": "📋 Show all commands"},
        {"command": "live",     "description": "📡 Live camera control"},
        {"command": "stoplive", "description": "🛑 Stop Facebook Live"},
    ]

    try:
        base = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
        last_error = None
        for attempt in range(2):
            try:
                r = requests.post(
                    f"{base}/setMyCommands",
                    json={"commands": commands},
                    timeout=10,
                )
                data = r.json()
                if data.get("ok"):
                    # Explicitly make Telegram show the commands menu for this chat.
                    # setChatMenuButton is harmless if the menu was already visible.
                    if TELEGRAM_CHAT_ID:
                        menu_r = requests.post(
                            f"{base}/setChatMenuButton",
                            json={
                                "chat_id": int(TELEGRAM_CHAT_ID),
                                "menu_button": {"type": "commands"},
                            },
                            timeout=10,
                        )
                        if not menu_r.json().get("ok"):
                            log(f"⚠️ Telegram setChatMenuButton failed: {menu_r.text[:200]}")
                    log("✅ Telegram command menu registered.")
                    return
                last_error = r.text[:200]
            except Exception as e:
                last_error = str(e)
            time.sleep(1)
        log(f"⚠️ Telegram command menu registration failed after retry: {last_error}")
    except Exception as e:
        log(f"⚠️ register_telegram_commands failed: {e}")


# ================= GEMINI CALL HELPER (new, replaces silent `except:` everywhere) =================

# ---- FREE AI FALLBACK (NEW) ----
# Pollinations.ai offers a completely free text generation API with NO API key
# required — the same service already used for image generation in this bot.
# This is called automatically inside call_gemini() whenever Gemini fails, so
# every single AI call in the bot is protected without touching any other code.
POLLINATIONS_TEXT_URL = "https://text.pollinations.ai/"
POLLINATIONS_TEXT_MODELS = ["openai-large", "openai", "mistral"]  # tried in order

def _call_pollinations_text(prompt, label="pollinations_text"):
    """
    Calls Pollinations.ai text API — zero API key, zero cost.
    Returns the response text string, or None if all models fail.
    Used as an automatic fallback inside call_gemini().
    """
    for model in POLLINATIONS_TEXT_MODELS:
        try:
            r = requests.post(
                POLLINATIONS_TEXT_URL,
                json={
                    "messages": [{"role": "user", "content": prompt}],
                    "model": model,
                    "private": True,   # don't appear in public feed
                    "seed": random.randint(1, 99999),
                },
                timeout=REQUEST_TIMEOUT + 15,  # text gen can be slower than images
            )
            if r.status_code == 200 and r.text.strip():
                return r.text.strip()
            # some models return non-200 silently — try next
        except Exception:
            pass
    return None


_gemini_call_times: list = []   # timestamps of recent calls — used by rate limiter
_gemini_lock = __import__("threading").Lock()
GEMINI_RPM_LIMIT = 12           # stay 3 under the 15 RPM free-tier ceiling


def _gemini_wait_for_slot():
    """Block until a Gemini call slot is available within the RPM limit.
    Thread-safe. Called automatically at the top of call_gemini()."""
    with _gemini_lock:
        while True:
            now_ts = time.time()
            # Drop timestamps older than 60 s
            while _gemini_call_times and now_ts - _gemini_call_times[0] >= 60:
                _gemini_call_times.pop(0)
            if len(_gemini_call_times) < GEMINI_RPM_LIMIT:
                _gemini_call_times.append(now_ts)
                return   # slot available — proceed
            # All slots used up: wait until the oldest call ages out
            wait_sec = 61 - (now_ts - _gemini_call_times[0])
            log(f"⏳ Gemini rate limit ({GEMINI_RPM_LIMIT} RPM): waiting {wait_sec:.1f}s...")
            time.sleep(max(wait_sec, 1))


# Google keeps deprecating/restricting model names for new API keys, and free
# daily quotas vary wildly by model (gemini-3.5-flash = only 20/day; the
# newer -lite variant of the same generation is usually much higher).
# This tries each model in order, moving to the next one on ANY failure
# (404 deprecated, 429 quota, 500 error, etc.) so the bot self-heals when
# Google changes things again, instead of needing a manual code edit every time.
GEMINI_MODEL_CHAIN = [
    "gemini-3.5-flash-lite",   # newest generation, lite = highest free quota
    "gemini-3.5-flash",        # newest generation, standard (20/day - as last resort)
    "gemini-2.0-flash",        # older generation, still active for many keys
]


def call_gemini(prompt, retries=3, label="gemini"):
    """Calls Gemini with automatic RPM rate limiting, multi-model fallback
    chain (self-heals when Google deprecates/restricts a model name), and
    Pollinations.ai text fallback if every Gemini model fails."""

    for model in GEMINI_MODEL_CHAIN:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"

        for attempt in range(1, retries + 1):
            _gemini_wait_for_slot()
            try:
                r = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=REQUEST_TIMEOUT)

                if r.status_code == 404:
                    # This model name is deprecated/unavailable for this key —
                    # no point retrying it, move straight to the next model.
                    log(f"⚠️ [{label}] Model '{model}' unavailable (404) — trying next model in chain...")
                    break

                if r.status_code == 429:
                    # Quota exhausted for this model specifically — try next
                    # model rather than burning retries on the same dead end.
                    log(f"⚠️ [{label}] Model '{model}' quota exceeded (429) — trying next model in chain...")
                    break

                if r.status_code != 200:
                    log(f"❌ [{label}] {model} HTTP {r.status_code} (attempt {attempt}/{retries}): {r.text[:300]}")
                    time.sleep(3)
                    continue

                data = r.json()

                if "candidates" not in data or not data["candidates"]:
                    reason = data.get("promptFeedback", data)
                    log(f"❌ [{label}] {model} returned no candidates (attempt {attempt}/{retries}): {json.dumps(reason)[:300]}")
                    time.sleep(3)
                    continue

                candidate = data["candidates"][0]
                finish_reason = candidate.get("finishReason")
                if finish_reason and finish_reason not in ("STOP", "MAX_TOKENS"):
                    log(f"⚠️ [{label}] {model} finishReason={finish_reason} (attempt {attempt}/{retries})")

                text = candidate["content"]["parts"][0]["text"]
                return text   # success — done, no need to try other models

            except Exception as e:
                log(f"❌ [{label}] {model} call exception (attempt {attempt}/{retries}): {e}")
                time.sleep(3)
        # retries exhausted (or 404/429 break) for this model — fall through
        # to the next model in GEMINI_MODEL_CHAIN

    # ---- FALLBACK: Pollinations.ai text (no API key needed) ----
    log(f"⚠️ [{label}] All Gemini models failed — trying Pollinations.ai text fallback...")
    fallback_text = _call_pollinations_text(prompt, label=label)
    if fallback_text:
        log(f"✅ [{label}] Pollinations.ai text fallback succeeded.")
        return fallback_text

    log(f"❌ [{label}] All AI sources failed (Gemini x{len(GEMINI_MODEL_CHAIN)} models + Pollinations). Returning None.")
    return None


def extract_json(text):
    """Pulls a JSON object out of a Gemini text response, tolerant of markdown fences."""
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1:
        text = text[start:end + 1]
    return json.loads(text.strip())


# ================= MONETIZATION =================
def apply_monetization(text):
    if MONETIZATION_MODE == "off":
        return text
    if MONETIZATION_MODE == "affiliate":
        link = random.choice(AFFILIATE_LINKS)
        return text + f"\n\n👉 Recommended Offer:\n{link}"
    if MONETIZATION_MODE == "sponsor":
        sponsor = random.choice(SPONSORS)
        return text + f"\n\nSponsored by {sponsor}"
    return text


# ================= NEWS =================
def get_news():
    global news_cache, news_last_fetch
    try:
        if time.time() - news_last_fetch > 300:
            all_entries = []
            seen_titles = set()
            for feed_url in [RSS_FEED_URL] + EXTRA_RSS_FEEDS:
                try:
                    feed = feedparser.parse(feed_url)
                    for e in feed.entries[:20]:
                        title = str(getattr(e, "title", "") or "").strip()
                        desc = str(getattr(e, "summary", "") or title).strip()
                        if not title or title.lower() in seen_titles:
                            continue
                        seen_titles.add(title.lower())
                        published = getattr(e, "published_parsed", None) or getattr(e, "updated_parsed", None)
                        published_ts = 0
                        if published:
                            try:
                                published_ts = time.mktime(published)
                            except Exception:
                                published_ts = 0
                        text = f"{title} {desc}".lower()
                        relevance = sum(w for k, w in US_NEWS_KEYWORDS.items() if k in text)
                        all_entries.append({
                            "title": title,
                            "desc": desc,
                            "_published_ts": published_ts,
                            "_us_relevance": relevance,
                        })
                except Exception as e:
                    log(f"⚠️ News feed failed: {e}")

            if all_entries:
                # Prefer fresh US-relevant stories, while keeping major non-US stories
                # available as a fallback when they are genuinely important.
                all_entries.sort(
                    key=lambda x: (x.get("_us_relevance", 0) > 0,
                                   x.get("_us_relevance", 0),
                                   x.get("_published_ts", 0)),
                    reverse=True
                )
                news_cache = all_entries[:60]
            news_last_fetch = time.time()
        return news_cache
    except Exception as e:
        log(f"⚠️ get_news() failed: {e}")
        return news_cache if news_cache else []


news_cache = []
news_last_fetch = 0


# ================= AI NEWS (ALGORITHM-UPGRADED) =================
# Caption structure now follows the proven viral formula:
#   LINE 1: HOOK — curiosity gap / shock / bold claim (shown before "See more")
#   LINE 2: CONTEXT — 2-3 sentences, the real story
#   LINE 3: EMOTION TRIGGER — why this matters / what people feel about it
#   LINE 4: CTA — specific, low-friction comment trigger
# This structure maximizes: time-on-post, comments, reactions, shares.
def ai_generate(title, desc):
    text = call_gemini(f"""
You are the editor of an original US news Facebook Page.
Create a concise, factual caption based ONLY on the supplied story details.

NEWS HEADLINE:
{title}

DETAILS:
{desc}

Rules:
- Write original wording; do not copy or closely mimic the source.
- Never invent names, numbers, quotes, dates or events.
- Do not use sensational or misleading clickbait.
- First line: a clear, interesting hook, max 12 words.
- Then 2-4 short factual sentences explaining what happened and why it matters.
- End with ONE natural question only.
- Do not ask for likes, shares, tags, follows, or reactions.
- Create a cinematic photojournalism image prompt specific to this story, with no text.
- Return exactly 3 relevant hashtags. No #viral, #fyp, #explore or engagement-farming tags.

Return ONLY JSON:
{{"caption":"[hook]\n\n[story]\n\n[natural question]",
  "image_prompt":"...",
  "hashtags":"#Tag1 #Tag2 #Tag3"}}
""", label="ai_generate")

    if text:
        try:
            result = extract_json(text)
            hashtags = _clean_hashtags(result.get("hashtags"), 3) or pick_hashtags(3)
            caption = f"{result['caption'].strip()}\n\n{hashtags}"
            result["caption"] = apply_monetization(caption)
            return result
        except Exception as e:
            log(f"❌ ai_generate JSON parse failed: {e} | raw: {text[:300]}")

    style = random.choice([
        "cinematic photojournalism style, natural lighting",
        "documentary news photography, realistic newsroom aesthetic",
    ])
    return {
        "caption": apply_monetization(
            f"📰 {title}\n\n{pick_natural_question()}\n\n{pick_hashtags(3)}"
        ),
        "image_prompt": f"{title}, {style}, highly detailed, realistic, no text"
    }


# ================= CARTOON =================
def cartoon_generate(title, desc):
    text = call_gemini(f"""
You are a viral Facebook content creator. Create an editorial cartoon post
for this news story that stops the scroll and drives comments.

NEWS:
{title}
{desc}

Requirements:
- caption: Follow this structure EXACTLY:
    LINE 1 (HOOK, max 8 words): Bold opinion or curiosity gap about this story.
      Techniques: "Nobody saw this coming...", "This is either genius or madness.",
      "The image says everything words can't."
    BLANK LINE
    LINE 2: 1-2 sentences giving sharp, opinionated context on the story.
    BLANK LINE
    LINE 3: One punchy "agree or disagree?" line that forces a reaction.
- image_prompt: Satirical editorial cartoon style. NO text in image.
- hashtags: 5 hashtags relevant to the story (# prefix included)

Return ONLY JSON:
{{"caption":"...","image_prompt":"...","hashtags":"#Tag1 #Tag2 #Tag3 #Tag4 #Tag5"}}
""", label="cartoon_generate")

    if text:
        try:
            result = extract_json(text)
            hashtags = result.get("hashtags") or pick_hashtags(5)
            caption = (
                f"🎨 {result['caption']}\n\n"
                f"{'─' * 24}\n"
                f"{pick_natural_question()}\n\n"
                f"{_clean_hashtags(hashtags, 3) or pick_hashtags(3)}"
            )
            result["caption"] = apply_monetization(caption.strip())
            return result
        except Exception as e:
            log(f"❌ cartoon_generate JSON parse failed: {e} | raw: {text[:300]}")

    style = random.choice([
        "satirical editorial cartoon, bold outlines, exaggerated expressions",
        "political cartoon style, sharp caricature, vivid colors",
        "single-panel newspaper cartoon, ink and watercolor style"
    ])
    return {
        "caption": apply_monetization(
            f"🎨 The image says what words can't.\n\n"
            f"📌 {title}\n\n"
            f"{pick_engagement_cta()}\n\n"
            f"{pick_hashtags()}"
        ),
        "image_prompt": f"{title}, {style}, highly detailed"
    }


# ================= HOLIDAY =================
def holiday_generate(holiday_title):
    text = call_gemini(f"""
You are a viral Facebook content creator. Create a highly shareable holiday post.

HOLIDAY: {holiday_title}

Requirements:
- caption structure:
    LINE 1 (HOOK, max 8 words): Warm but scroll-stopping opening. Use curiosity,
      nostalgia, or a bold universal feeling. NO generic "Happy [Holiday]!" openers.
      Examples: "This day means something different to everyone.",
                "Some holidays hit deeper than others. This is one of them.",
                "If this day brings you joy — you deserve it. ❤️"
    BLANK LINE
    LINE 2-3: 2-3 heartfelt sentences about the meaning of this specific holiday.
      Make it personal and emotionally resonant.
    BLANK LINE
    LINE 4: Tag prompt OR reflection question to drive comments.
      Examples: "Tag someone who makes this day special for you 👇",
                "What does {holiday_title} mean to YOU? Tell us below 💬"
- image_prompt: Dark cinematic artistic scene capturing the spirit of {holiday_title}.
  Dramatic lighting, ultra-detailed, highly emotional atmosphere.
  NO text, NO words, NO letters anywhere in the image.

Return ONLY JSON:
{{"caption":"...","image_prompt":"..."}}
""", label="holiday_generate")

    if text:
        try:
            result = extract_json(text)
            caption = (
                f"{result['caption']}\n\n"
                f"{pick_natural_question()}\n\n"
                f"#USA #Holiday #Celebration"
            )
            result["caption"] = apply_monetization(caption)
            return result
        except Exception as e:
            log(f"❌ holiday_generate JSON parse failed: {e} | raw: {text[:300]}")

    return {
        "caption": apply_monetization(
            f"This day means something different to everyone. ❤️\n\n"
            f"Wishing you all a wonderful {holiday_title}.\n\n"
            f"{pick_natural_question()}\n\n"
            f"#USA #Holiday #Celebration"
        ),
        "image_prompt": (
            f"Dark cinematic moody artistic scene representing {holiday_title}, "
            f"dramatic lighting, ultra-detailed, emotional atmosphere, no text"
        )
    }


# ================= QUOTE OF THE DAY (NEW) =================
# Purely additive content type - fills separate slots, never touches news/scenic/cartoon logic.
QUOTE_TOPICS = [
    "motivation and perseverance", "success and hard work", "life and happiness",
    "courage and self-belief", "growth and change", "gratitude and positivity",
    "dreams and ambition", "resilience and hope"
]


def quote_generate():
    topic = random.choice(QUOTE_TOPICS)
    text = call_gemini(f"""
Create an original, powerful inspirational quote about {topic}.
Must NOT copy any famous existing quote — write a brand new one.
Also write a 1-line "context sentence" that makes the quote feel personal
and creates a strong urge to share or tag someone.
Also create a matching cinematic BACKGROUND image prompt (mood/scenery only,
NO text, NO words, NO letters in the image — the quote is added as caption).

Context sentence rules:
- Make it personal and relatable: "This one hits different if you've been..."
- Or create reflection: "Does this resonate with you?"
- Never ask for likes, shares, tags or follows.

Return ONLY JSON:
{{"quote":"...","context":"...","image_prompt":"..."}}
""", label="quote_generate")

    quote_text = context = image_prompt = None
    if text:
        try:
            result = extract_json(text)
            quote_text  = result.get("quote")
            context     = result.get("context")
            image_prompt = result.get("image_prompt")
        except Exception as e:
            log(f"❌ quote_generate JSON parse failed: {e} | raw: {text[:300]}")

    if not quote_text:
        quote_text = "Every day is a new chance to become who you want to be."
    if not context:
        context = "Does this resonate with you?"
    if not image_prompt:
        image_prompt = (
            f"Cinematic minimalist background representing {topic}, soft dramatic "
            f"lighting, inspirational mood, ultra-detailed, 4k"
        )

    caption = (
        f"✨ {context}\n\n"
        f"💭 \"{quote_text}\"\n\n"
        f"{pick_natural_question()}\n\n"
        f"{pick_hashtags(3)}"
    )
    return {
        "caption": apply_monetization(caption),
        "image_prompt": image_prompt,
        "key": quote_text.strip().lower()
    }


# ================= FUN FACT (NEW) =================
FACT_TOPICS = [
    "space and astronomy", "the ocean and marine life", "human body and brain",
    "history and ancient civilizations", "animals and wildlife", "technology and science",
    "nature and the planet Earth"
]


def fact_generate():
    topic = random.choice(FACT_TOPICS)
    text = call_gemini(f"""
Share ONE surprising, true, viral-worthy fun fact about {topic}.
Also write a scroll-stopping HOOK line (max 8 words) that creates shock or
curiosity — this is the FIRST thing people see before "See more".
Hook should create curiosity without unverifiable statistics, fake urgency,
or claims that are not supported by the supplied fact.
Also create a matching image prompt (depicts the subject, NO text in image).

Return ONLY JSON:
{{"hook":"...","fact":"...","image_prompt":"..."}}
""", label="fact_generate")

    hook = fact_text = image_prompt = None
    if text:
        try:
            result = extract_json(text)
            hook        = result.get("hook")
            fact_text   = result.get("fact")
            image_prompt = result.get("image_prompt")
        except Exception as e:
            log(f"❌ fact_generate JSON parse failed: {e} | raw: {text[:300]}")

    if not hook:      hook      = "Most people never learn this in school."
    if not fact_text: fact_text = f"Did you know? {topic.capitalize()} still holds many mysteries scientists are exploring today."
    if not image_prompt:
        image_prompt = f"Realistic detailed photograph representing {topic}, high quality, 4k"

    caption = (
        f"🤯 {hook}\n\n"
        f"{fact_text}\n\n"
        f"{pick_natural_question()}\n\n"
        f"{pick_hashtags(3)}"
    )
    return {
        "caption": apply_monetization(caption),
        "image_prompt": image_prompt,
        "key": fact_text.strip().lower()
    }


# ================= DAILY REACTION POLL (NEW) =================
# Algorithm research summary:
#   Comments   → highest weight signal on Facebook (especially threads)
#   Reactions  → high weight (all 6 types, not just ❤️)
#   Shares     → medium-high weight (especially to Stories)
#   Return visits → medium weight (people coming back = quality signal)
#   Time-on-post  → medium weight (longer = better)
#
# This poll format stacks ALL of them simultaneously:
#   - Numbered comment voting (1️⃣/2️⃣) = lowest friction → max comments
#   - Reaction ask = reaction signal
#   - Tag prompt = organic reach to new users outside followers
#   - "Results tonight" = return visits = algorithm quality signal
#   - Curiosity-gap hook = stops scroll = time-on-post
#   - Share ask = viral coefficient
#   - Topic is AI-chosen from current US/NYC trends = always fresh

def poll_generate():
    today_str = now().strftime("%A, %B %d, %Y")

    text = call_gemini(f"""
Today is {today_str}.
You are the top viral content strategist for a major US Facebook page (millions of followers).

TASK: Create one algorithm-destroying daily poll for today.

STEP 1 — TOPIC SELECTION:
Pick a topic that is CURRENTLY being debated in America (NYC culture especially).
Think: seasonal moment, recent pop culture drop, sports season, food/lifestyle trend,
tech habit shift, generational divide, relationship norm in 2026, etc.
Avoid stale "coffee vs tea" generics. Be SPECIFIC and timely.

STEP 2 — POLL STRUCTURE optimized for Facebook's algorithm:
Facebook weights: Comments > Reactions > Shares > Time-on-post.
So the format must maximize ALL of these simultaneously.

Requirements:
- curiosity_hook: First 3 words must STOP the scroll mid-feed. Create a
  strong curiosity gap or bold statement. Max 8 words total. No emojis yet.
  (This is the most important line — it shows before "See more")
- subhook: One line that builds tension/intrigue after the hook. Max 12 words.
- question: The poll question. Short, punchy, makes people instantly feel an opinion. Max 10 words.
- option_1: Label for option 1️⃣ (max 5 words, no emoji)
- option_2: Label for option 2️⃣ (max 5 words, no emoji)
- tag_line: NOT USED. Do not ask users to tag/share/react.
- results_line: NOT USED.
- hashtags: exactly 3 topic-relevant hashtags.
- image_prompt: Cinematic VERSUS split-screen — LEFT half shows option 1 in its most
  iconic, vivid real-world setting; RIGHT half shows option 2 equally vivid.
  Strong color contrast between halves. Photorealistic, ultra-detailed, dramatic
  lighting, portrait orientation, NO TEXT, NO WORDS, NO LETTERS anywhere.
- topic_key: unique 3-word slug for dedup

Return ONLY valid JSON, no markdown, no fences:
{{
  "topic": "one-line topic description",
  "curiosity_hook": "...",
  "subhook": "...",
  "question": "...",
  "option_1": "...",
  "option_2": "...",
  "tag_line": "...",
  "results_line": "...",
  "hashtags": "#Tag1 #Tag2 #Tag3 #Tag4 #Tag5",
  "image_prompt": "...",
  "topic_key": "slug-here"
}}
""", label="poll_generate")

    # ── Parse JSON ──
    q = op1 = op2 = img = key = hook = subhook = tag_line = results_line = hashtags = None
    if text:
        try:
            r = extract_json(text)
            hook         = r.get("curiosity_hook")
            subhook      = r.get("subhook")
            q            = r.get("question")
            op1          = r.get("option_1")
            op2          = r.get("option_2")
            tag_line     = r.get("tag_line")
            results_line = r.get("results_line")
            hashtags     = r.get("hashtags")
            img          = r.get("image_prompt")
            key          = r.get("topic_key")
        except Exception as e:
            log(f"❌ poll_generate JSON parse failed: {e} | raw: {text[:300]}")

    # ── Safe fallbacks ──
    if not hook:         hook         = "Everyone is choosing a side right now."
    if not subhook:      subhook      = "Which team are YOU on? The comments don't lie."
    if not q:            q            = "Which would you choose?"
    if not op1:          op1          = "Option One"
    if not op2:          op2          = "Option Two"
    if not tag_line:     tag_line     = "Tag someone who would DEFINITELY pick 2️⃣"
    if not results_line: results_line = "We'll share the results tonight! 👀"
    if not hashtags:     hashtags     = "#Trending #USA #Opinion #Viral #YouDecide"
    if not key:          key          = f"poll-{now().strftime('%Y%m%d')}-{random.randint(1,999)}"
    if not img:
        img = (
            "Cinematic split-screen portrait: left half shows the first lifestyle option "
            "in its most iconic real-world setting with warm dramatic lighting; right half "
            "shows the contrasting option equally vivid with cool dramatic lighting; "
            "bold color contrast between both halves, ultra-detailed photorealistic, "
            "sharp focus, no text, no letters, no watermark"
        )

    # Keep the poll itself as the genuine reason to comment; no stacked
    # engagement instructions.
    caption = (
        f"🗳️ {hook}\n\n"
        f"{subhook}\n\n"
        f"{q}\n\n"
        f"1️⃣ {op1}\n"
        f"2️⃣ {op2}\n\n"
        f"If you want to weigh in, 1 or 2 is enough.\n\n"
        f"{_clean_hashtags(hashtags, 3) or pick_hashtags(3)}"
    )

    return {
        "caption": apply_monetization(caption),
        "image_prompt": img,
        "key": key,
    }


# ================= AUTO REPLY TO COMMENTS =================
last_replied_comment_ids = set()

# ================= BOT PAUSE STATE (NEW) =================
# Controlled via /pause and /resume Telegram commands.
# When paused, the scheduler skips posting and comment-reply but keeps
# running so /resume works instantly without restarting the process.
BOT_PAUSED = False


def get_recent_comments():
    try:
        # Fetch top-level comments AND their replies (nested).
        # Without replies{...} the bot never sees when someone replies to our
        # auto-reply — the conversation thread dies, hurting the algorithm signal.
        url = (
            f"https://graph.facebook.com/v20.0/{FB_PAGE_ID}/feed"
            f"?fields=id,comments{{id,message,created_time,from,"
            f"comments{{id,message,created_time,from}}}}"
            f"&access_token={FB_ACCESS_TOKEN}"
        )
        r = requests.get(url, timeout=REQUEST_TIMEOUT)
        data = r.json()
        if "error" in data:
            log(f"❌ get_recent_comments FB error: {data['error']}")
            return []
        comments = []
        cutoff = time.time() - (24 * 60 * 60)
        for post in data.get("data", []):
            for comment in post.get("comments", {}).get("data", []):
                for item in [comment] + comment.get("comments", {}).get("data", []):
                    if item.get("from", {}).get("id", "") == FB_PAGE_ID:
                        continue
                    created = item.get("created_time", "")
                    try:
                        created_ts = datetime.fromisoformat(created.replace("Z", "+00:00")).timestamp()
                    except Exception:
                        created_ts = time.time()
                    if created_ts >= cutoff:
                        comments.append(item)
        return comments
    except Exception as e:
        log(f"⚠️ get_recent_comments failed: {e}")
        return []


_classify_cache: dict = {}   # {comment_text_lower → result} — avoids re-classifying same text
MAX_CLASSIFY_CACHE = 500

# Common spam/scam patterns — detected without any Gemini call at all.
# Covers ~80% of actual spam, saving those RPM slots for real content generation.
_SPAM_PATTERNS = [
    "bit.ly/", "tinyurl.com", "t.me/", "wa.me/",
    "click here", "free money", "make $", "earn $",
    "whatsapp me", "dm me", "inbox me",
    "crypto investment", "bitcoin profit", "forex signal",
    "diet pill", "weight loss secret", "grow your account",
    "follow back", "i followed you", "follow for follow",
    "sub4sub", "like4like",
]

def classify_comment(comment_text):
    """Spam/abuse check before auto-reply.
    1. Keyword pre-filter (no Gemini call) — catches ~80% of spam instantly.
    2. Cache check — skips Gemini for repeated identical comments.
    3. Gemini call — only for genuinely ambiguous cases.
    """
    lowered = comment_text.strip().lower()

    # 1. Keyword pre-filter — zero Gemini cost
    for pattern in _SPAM_PATTERNS:
        if pattern in lowered:
            return {"flag": True, "reason": f"keyword match: {pattern}"}

    # 2. Cache check
    if lowered in _classify_cache:
        return _classify_cache[lowered]

    # 3. Gemini only for ambiguous cases
    text = call_gemini(
        f"Classify this Facebook comment. Reply with ONLY JSON:\n"
        f'{{\"flag\": true or false, \"reason\": \"short reason or empty\"}}\n\n'
        f"Flag TRUE only for: spam, scam/phishing links, unrelated ads, "
        f"hate speech, harassment, explicit content.\n"
        f"Flag FALSE for: normal comments, questions, opinions, disagreement.\n\n"
        f"Comment: {comment_text}",
        label="classify_comment"
    )

    result = {"flag": False, "reason": ""}
    if text:
        try:
            result = extract_json(text)
        except Exception:
            pass

    # Cache the result
    _classify_cache[lowered] = result
    if len(_classify_cache) > MAX_CLASSIFY_CACHE:
        # Drop oldest entries
        for k in list(_classify_cache.keys())[:50]:
            _classify_cache.pop(k, None)

    return result


def _is_emoji_only(text: str) -> bool:
    """Returns True when the entire comment is emoji characters (and whitespace).
    Used to decide whether to reply with emojis or normal text."""
    cleaned = text.strip().replace(" ", "")
    if not cleaned:
        return False
    for ch in cleaned:
        cp = ord(ch)
        # Accept emoji Unicode blocks + ZWJ + variation selectors + keycaps + flags
        if not (
            0x2194 <= cp <= 0x2BFF or   # misc symbols & arrows
            0x1F300 <= cp <= 0x1FBFF or  # emoticons, symbols, transport, flags …
            0x200D == cp or              # zero-width joiner (multi-part emoji)
            0xFE0F == cp or              # variation selector-16
            0x20E3 == cp or              # combining enclosing keycap
            0x1F1E0 <= cp <= 0x1F1FF    # regional indicator letters (flag pairs)
        ):
            return False
    return True


def auto_reply_to_comment(comment_id, comment_text):
    # ── EMOJI-ONLY COMMENT → reply with 1-2 fitting emojis only ──
    if _is_emoji_only(comment_text):
        text = call_gemini(
            f"Someone left this emoji reaction on a Facebook post: {comment_text}\n"
            "Reply with 1 or 2 emojis ONLY that best match the feeling or continue "
            "the vibe. Return ONLY the emoji characters, nothing else — no words, "
            "no punctuation, no explanation.",
            label="emoji_reply"
        )
        reply_text = (text or "").strip()
        # Safety guard: if Gemini sneaked in words, fall back to a single ❤️
        if reply_text and not _is_emoji_only(reply_text):
            reply_text = "❤️"
    else:
        # ── NORMAL TEXT COMMENT → friendly reply + follow-up question ──
        text = call_gemini(f"""
Reply to this Facebook comment in a friendly, engaging, and natural way.
Keep it short (1-2 sentences). Be helpful and warm.
IMPORTANT: Always end your reply with a short follow-up question to keep
the conversation going (e.g. "What do you think?", "Have you seen this?",
"What's your take on it?"). This is very important.

Comment: {comment_text}

Reply:
""", label="auto_reply")
        reply_text = (text or "").strip()

    if not reply_text:
        return

    try:
        reply_url = f"https://graph.facebook.com/v20.0/{comment_id}/comments"
        resp = requests.post(reply_url, data={
            "message": reply_text,
            "access_token": FB_ACCESS_TOKEN
        }, timeout=REQUEST_TIMEOUT).json()
        if "error" in resp:
            log(f"❌ Failed to reply to comment {comment_id}: {resp['error']}")
        else:
            log(f"✅ Replied to comment {comment_id}: {reply_text}")
    except Exception as e:
        log(f"⚠️ auto_reply_to_comment failed: {e}")


# ================= SELF-COMMENT HOOK (NEW) =================
# Immediately after a post goes live, the Page posts its own comment with a
# question. Facebook's algorithm treats ANY early engagement (including a Page
# commenting on its own post) as a "conversation started" signal, which pushes
# the post to more feeds in the first hour — the most critical window for reach.
def post_self_comment(post_id, topic):
    """Disabled intentionally: Facebook engagement should come from real users."""
    return


# ================= ENGAGEMENT REVIVE (NEW) =================
# 1 hour after each post, checks if engagement is very low (< 3 reactions
# total). If so, posts a fresh "revival comment" from the Page to re-trigger
# the algorithm's distribution window. Tracked per post_id so it only fires
# once per post and never double-revives.
_revive_checked_ids = set()
# Restart-safety guards: posts/comments that already existed when this process
# started must never trigger a Facebook comment just because PM2 restarted.
# New posts/comments created after startup continue to use the normal behavior.
_startup_existing_post_ids = set()
_startup_existing_comment_ids = set()
REVIVE_DELAY_SECONDS = 1800   # 30 min — golden window: first 30 min determines reach
REVIVE_LOW_THRESHOLD = 3      # total likes+comments+shares below this = revive


def maybe_revive_post(post_id, post_type, posted_at_iso):
    """Intentionally disabled: do not manufacture Page comments on low-engagement
    posts. Reach should come from content quality and genuine user interaction."""
    return


def process_auto_replies():
    # Conservative reply rate: answer genuine recent user comments without
    # creating a burst of automated Page activity.
    MAX_REPLIES_PER_LOOP = 2
    replies_sent = 0

    comments = get_recent_comments()
    for comment in comments:
        if replies_sent >= MAX_REPLIES_PER_LOOP:
            break
        cid = comment["id"]
        if cid not in last_replied_comment_ids:
            last_replied_comment_ids.add(cid)
            if len(last_replied_comment_ids) > MAX_REPLIED_COMMENT_IDS:
                for old_id in list(last_replied_comment_ids)[: len(last_replied_comment_ids) - MAX_REPLIED_COMMENT_IDS]:
                    last_replied_comment_ids.discard(old_id)
            message = comment.get("message", "")
            classification = classify_comment(message)
            if classification.get("flag"):
                log(f"🚩 Flagged comment {cid} for review: \"{message[:200]}\" "
                    f"(reason: {classification.get('reason', '')})")
                continue
            auto_reply_to_comment(cid, message)
            replies_sent += 1
            if replies_sent < MAX_REPLIES_PER_LOOP:
                time.sleep(2)  # small human-like pause between replies


# ================= SCENIC DAILY AI SYSTEM =================
scenic_daily_places = []
scenic_last_date = None
scenic_posted_places_today = set()


def get_daily_scenic_pool():
    global scenic_daily_places, scenic_last_date
    today = now().date()
    today_str = today.isoformat()

    if scenic_last_date != today_str or len(scenic_daily_places) == 0:
        text = call_gemini("""
Generate 10 UNIQUE viral scenic travel destinations for today.

Rules:
- Must be real-world places from AROUND THE WORLD
- Must be highly photogenic and breathtaking
- Must be diverse — different countries, continents, and types (mountains, beaches, cities, forests, deserts, waterfalls, historical sites, etc.)
- Do NOT repeat places that were suggested on previous days
- Each place must be uniquely beautiful and iconic in its own way
- Include the country name for each place

Return ONLY JSON array:
["Place Name, Country", "Place Name, Country", ...]
""", label="scenic_pool")

        parsed = None
        if text:
            try:
                t = text
                if "```json" in t:
                    t = t.split("```json")[1].split("```")[0]
                elif "```" in t:
                    t = t.split("```")[1].split("```")[0]
                start = t.find('[')
                end = t.rfind(']')
                if start != -1 and end != -1:
                    t = t[start:end + 1]
                parsed = json.loads(t.strip())
            except Exception as e:
                log(f"❌ scenic pool JSON parse failed: {e} | raw: {text[:300]}")

        scenic_daily_places = parsed if parsed else [
            "Santorini, Greece", "Banff National Park, Canada", "Maldives Beach",
            "Northern Lights, Iceland", "Mount Fuji, Japan", "Plitvice Lakes, Croatia",
            "Marble Caves, Chile", "Bora Bora, French Polynesia", "Taj Mahal, India",
            "Milford Sound, New Zealand"
        ]
        scenic_last_date = today_str
        scenic_posted_places_today.clear()

    return scenic_daily_places


def scenic_generate():
    pool = get_daily_scenic_pool()
    available = [p for p in pool if p not in scenic_posted_places_today]
    if not available:
        scenic_posted_places_today.clear()
        available = pool

    place = random.choice(available)
    scenic_posted_places_today.add(place)

    # MERGED into ONE Gemini call (was 2 separate calls = 2x RPM usage)
    scenic_result = call_gemini(f"""
Create a viral Facebook travel post for: {place}

Return ONLY JSON with these two fields:

"image_prompt": An ultra-detailed hyper-realistic photograph prompt for {place}.
Include: National Geographic style, golden hour or blue hour lighting, Phase One
IQ4 150MP camera, 35mm lens f/11, Fujifilm Velvia film simulation, dramatic
shadows, volumetric haze, rule of thirds, unique to {place} only.
End with "A flawless photorealistic masterpiece with breathtaking detail."
NO text, NO signs, NO writing in the image.

"caption": Scroll-stopping travel caption structured as:
LINE 1 (HOOK 8 words max): Awe/wonder/desire/curiosity — stop the scroll.
BLANK LINE
LINE 2-3: 2 sentences specific to {place}'s unique beauty.
BLANK LINE
LINE 4: Comment trigger ("Tag someone you'd bring here 👇" or "Drop 1️⃣ YES 2️⃣ somewhere else 👇")
LINE 5: 4-5 travel hashtags for {place}

{{"image_prompt":"...","caption":"..."}}
""", label="scenic_generate")

    image_prompt_text = None
    caption_text = None
    if scenic_result:
        try:
            parsed = extract_json(scenic_result)
            image_prompt_text = parsed.get("image_prompt")
            caption_text = parsed.get("caption")
        except Exception as e:
            log(f"❌ scenic_generate JSON parse failed: {e} | raw: {scenic_result[:300]}")

    if image_prompt_text and "```" in image_prompt_text:
        image_prompt_text = image_prompt_text.split("```")[0].strip()
    if caption_text and "```" in caption_text:
        caption_text = caption_text.split("```")[0].strip()

    if not image_prompt_text:
        image_prompt_text = (
            f"A hyper-realistic, award-winning National Geographic photograph of {place}. "
            f"Ultra-HD, 32k resolution, extreme sharpness, natural film grain. "
            f"Shot on a Phase One IQ4 150MP camera with a 35mm prime lens at f/11, 1/160s, ISO 100. "
            f"Cinematic golden hour lighting with long dramatic shadows, volumetric haze. "
            f"Fujifilm Velvia film simulation for rich vibrant natural colors. "
            f"Professional color grading, master-level composition. "
            f"Breathtaking detail in every element. "
            f"A flawless, pristine, highly photorealistic masterpiece."
        )
    if not caption_text:
        caption_text = (
            f"This place doesn't look real. But it is. 😍\n\n"
            f"✨ {place} — one of Earth's most breathtaking destinations.\n\n"
            f"Tag someone you'd bring here 👇\n"
            f"📌 Save this for your travel bucket list.\n\n"
            f"#Travel #{place.replace(' ','')} #NaturePhotography #Wanderlust #BucketList"
        )

    caption_final = (
        f"{caption_text.strip()}\n\n"
        f"📌 Save this to your travel list!\n"
        f"🔁 Share with someone who needs a travel dream today."
    )
    return {"caption": apply_monetization(caption_final), "image_prompt": image_prompt_text.strip()}


# ================= IMAGE =================
# FIX (root cause of "wrong photo for the caption"):
# The old code just built a pollinations.ai URL and handed it straight to
# Facebook as `url=...`. Facebook then fetches that URL itself at publish
# time - the bot never checked whether pollinations actually returned a real,
# matching image. If pollinations was slow, rate-limited for a moment, or
# returned a broken/blank/placeholder response (which free image APIs do
# occasionally), Facebook would still get "something" and the post would go
# out with a broken or unrelated picture next to a perfectly fine caption.
# On top of that, giant over-stuffed prompts (see the old scenic prompt) make
# the underlying model ignore half the instructions and drift off-topic.
#
# Fix: download the image ourselves, verify it is a real, reasonably-sized
# image, and retry across models/seeds before giving up. We keep BOTH the
# raw bytes (for a rock-solid direct upload to Facebook - no second fetch,
# no chance of Facebook getting something different than what we checked)
# and the URL (Instagram's API needs a public URL, not raw bytes).
IMAGE_MIN_BYTES = 15000          # a real 1024x1024 photo is always bigger than this;
                                  # broken/blank/error responses are almost always tiny
POLLINATIONS_MODELS = ["flux", "turbo"]   # flux = best quality/prompt-following on
                                           # pollinations right now; turbo = fast fallback
MAX_IMAGE_PROMPT_CHARS = 900     # generous cap - just guards against runaway/broken
                                  # prompts, without cutting well-formed detailed ones short

# ================= CLOUDFLARE WORKERS AI (NEW - PRIMARY IMAGE SOURCE) =================
# Free, generous (10,000 "neurons"/day - far more than this bot's handful of
# posts/day needs) and noticeably higher quality than pollinations.ai, since it
# runs the actual FLUX.1-schnell / Stable Diffusion XL models. Requires a free
# Cloudflare account (no credit card) - set CF_ACCOUNT_ID and CF_API_TOKEN as
# env vars. If those two aren't set, this is skipped entirely and the bot
# falls back to pollinations.ai exactly as before - nothing breaks for anyone
# who hasn't set them up yet.
CF_ACCOUNT_ID = os.getenv("CF_ACCOUNT_ID", "")
CF_API_TOKEN = os.getenv("CF_API_TOKEN", "")
CLOUDFLARE_MODELS = [
    "@cf/black-forest-labs/flux-1-schnell",           # best quality, fast
    "@cf/stabilityai/stable-diffusion-xl-base-1.0",   # secondary CF model
]


def _fetch_cloudflare_image(prompt, model):
    try:
        r = requests.post(
            f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/run/{model}",
            headers={"Authorization": f"Bearer {CF_API_TOKEN}", "Content-Type": "application/json"},
            json={"prompt": prompt},
            timeout=60,
        )
        content_type = r.headers.get("content-type", "")
        # Some Cloudflare image models return raw image bytes directly...
        if r.status_code == 200 and content_type.startswith("image/") and len(r.content) >= IMAGE_MIN_BYTES:
            return r.content
        # ...others return JSON with a base64-encoded image inside "result".
        if r.status_code == 200 and content_type.startswith("application/json"):
            data = r.json()
            if not data.get("success", True):
                log(f"⚠️ Cloudflare image gen failed (model={model}): {data.get('errors')}")
                return None
            b64 = data.get("result", {}).get("image")
            if b64:
                content = base64.b64decode(b64)
                if len(content) >= IMAGE_MIN_BYTES:
                    return content
            return None
        log(f"⚠️ Cloudflare image gen bad response (model={model}, status={r.status_code}, "
            f"content-type={content_type})")
        return None
    except Exception as e:
        log(f"⚠️ Cloudflare image gen request failed (model={model}): {e}")
        return None


def _fetch_pollinations_image(prompt, model):
    seed = random.randint(1, 999999999)
    encoded = urllib.parse.quote(prompt)
    # Portrait 9:16 (1080x1920) looks far better on mobile Facebook feeds than
    # square. enhance=true lets Pollinations apply automatic prompt improvement.
    url = (
        f"https://image.pollinations.ai/prompt/{encoded}"
        f"?width=1080&height=1920&seed={seed}&nologo=true&model={model}&enhance=true&private=true"
    )
    try:
        r = requests.get(url, timeout=60)
        content_type = r.headers.get("content-type", "")
        if r.status_code == 200 and content_type.startswith("image/") and len(r.content) >= IMAGE_MIN_BYTES:
            return r.content, url
        log(f"⚠️ generate_image: bad response (model={model}, status={r.status_code}, "
            f"content-type={content_type}, size={len(r.content) if r.content else 0} bytes)")
    except Exception as e:
        log(f"⚠️ generate_image: request failed (model={model}): {e}")
    return None, None


def generate_image(prompt):
    prompt = (prompt or "").strip()
    if len(prompt) > MAX_IMAGE_PROMPT_CHARS:
        prompt = prompt[:MAX_IMAGE_PROMPT_CHARS]
    # never let the image model try to render words - text-in-image is the
    # single biggest cause of garbled/obviously-wrong looking AI photos
    # Append quality boosters that push Flux/SDXL toward cinematic photography.
    # These specific tokens are well-understood by both FLUX and SDXL and
    # consistently lift output quality without overriding the subject.
    QUALITY_SUFFIX = (
        ", professional photography, cinematic lighting, dramatic atmosphere, "
        "ultra-detailed, 8k resolution, sharp focus, rich colors, "
        "National Geographic style, award-winning photo, no text, no words, "
        "no letters, no watermark, no logo"
    )
    prompt = f"{prompt}{QUALITY_SUFFIX}"

    # 1) PRIMARY: Cloudflare Workers AI - higher quality, generous free daily
    # budget. Cloudflare doesn't hand back a public image URL (only bytes), so
    # "url" is None for these - Instagram cross-posting (which needs a public
    # URL) is simply skipped for these images; the Facebook post itself is
    # completely unaffected.
    if CF_ACCOUNT_ID and CF_API_TOKEN:
        for model in CLOUDFLARE_MODELS:
            content = _fetch_cloudflare_image(prompt, model)
            if content:
                return {"bytes": content, "url": None}
        log("⚠️ generate_image: Cloudflare Workers AI failed, falling back to pollinations.ai...")

    # 2) SECONDARY: pollinations.ai (previous primary, kept as a fallback)
    for model in POLLINATIONS_MODELS:
        for attempt in range(2):
            content, url = _fetch_pollinations_image(prompt, model)
            if content:
                return {"bytes": content, "url": url}
            time.sleep(2)

    # 3) LAST RESORT: Stable Horde - only reached if both of the above failed
    log("⚠️ generate_image: pollinations.ai failed, trying Stable Horde backup...")
    content, url = _fetch_stablehorde_image(prompt)
    if content:
        log("✅ generate_image: Stable Horde backup succeeded")
        return {"bytes": content, "url": url}

    log("❌ generate_image: all attempts failed (including backups) - no valid image could be generated for this post")
    return None


# ================= AI VIDEO / REELS GENERATION (NEW) =================
# Fully automated pipeline, 100% free tools, no manual work:
#   1. Gemini writes a short narrated script (hook + 4-5 slides) for a topic
#   2. Each slide gets an AI image (reuses the same generate_image() pipeline
#      already used for photo posts — Cloudflare/Pollinations/Stable Horde)
#   3. edge-tts (Microsoft's free TTS, no API key) converts the script to a
#      natural-sounding voiceover
#   4. ffmpeg combines images (Ken Burns zoom/pan effect) + burned-in captions
#      + voiceover into a vertical 1080x1920 MP4 — ideal for Facebook Reels
#   5. Uploaded via Facebook's official Reels API (3-step resumable upload)
#
# Requires on the VPS (one-time setup, both free):
#   sudo apt install ffmpeg
#   pip install edge-tts --break-system-packages
# If either is missing, video slots are skipped with a clear log message —
# every other part of the bot is completely unaffected.

VIDEO_TEMP_DIR = "/tmp/fb_bot_video"
VIDEO_VOICE = "en-US-AriaNeural"    # free edge-tts voice, natural US English

# Common font locations across Debian/Ubuntu VPS distros — first one found
# is used for burned-in captions. If none exist, captions are skipped
# (voiceover + images still work fine without them).
_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
]
_VIDEO_FONT = next((f for f in _FONT_CANDIDATES if os.path.exists(f)), None)

VIDEO_TOPICS = [
    "US news explained", "American history fact", "US technology trend",
    "US science story", "US culture trend", "money and personal finance in America",
    "weather and climate in the US", "quick history moment", "did-you-know trivia",
]

def _pick_video_topic():
    try:
        stories = get_news()
        candidates = [x for x in stories if x.get("_us_relevance", 0) > 0]
        if candidates:
            return random.choice(candidates)["title"]
    except Exception:
        pass
    return random.choice(VIDEO_TOPICS)

def generate_video_script(topic_hint=None):
    """Asks Gemini for a short narrated video script: a hook + 4-5 slides,
    each with narration text (what the voice says) and an image_prompt
    (what that slide should show). Returns dict or None on failure."""
    topic = topic_hint or _pick_video_topic()
    text = call_gemini(f"""
You are a viral short-form video scriptwriter (like a TikTok/Reels creator).
Write a script for a 25-35 second faceless narrated video about: {topic}

Structure: 1 hook slide + 4 content slides = 5 slides total.

Rules:
- HOOK slide: max 12 words, must stop the scroll instantly (curiosity/shock)
- Content slides: each 1 short sentence (max 15 words), building on the hook
- Total narration should read naturally out loud in ~30 seconds
- Each slide needs a matching image_prompt: vivid, specific, cinematic,
  photorealistic, NO text/words/letters in the image
- caption: a short Facebook caption with the hook, useful context, ONE natural question, and 2-3 relevant hashtags. No like/share/tag/follow bait.
- topic_key: unique 3-word slug for this specific video (for dedup)

Return ONLY JSON:
{{
  "slides": [
    {{"narration": "hook line", "image_prompt": "..."}},
    {{"narration": "slide 2 line", "image_prompt": "..."}},
    {{"narration": "slide 3 line", "image_prompt": "..."}},
    {{"narration": "slide 4 line", "image_prompt": "..."}},
    {{"narration": "slide 5 line", "image_prompt": "..."}}
  ],
  "caption": "Facebook post caption with hashtags",
  "topic_key": "slug-here"
}}
""", label="video_script")

    if not text:
        return None
    try:
        result = extract_json(text)
        slides = result.get("slides", [])
        if len(slides) < 3:
            return None

        return result
    except Exception as e:
        log(f"❌ generate_video_script JSON parse failed: {e} | raw: {text[:300]}")
        return None


def _generate_voiceover(full_narration_text, out_path):
    """Uses edge-tts (free, no API key) to generate an MP3 voiceover."""
    if not EDGE_TTS_AVAILABLE:
        return False
    async def _run():
        communicate = edge_tts.Communicate(full_narration_text, VIDEO_VOICE)
        await communicate.save(out_path)
    try:
        asyncio.run(_run())
        return os.path.exists(out_path) and os.path.getsize(out_path) > 1000
    except Exception as e:
        log(f"⚠️ _generate_voiceover failed: {e}")
        return False


def _get_media_duration(path):
    """Returns duration in seconds via ffprobe, or a safe fallback."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=15
        )
        return max(float(result.stdout.strip()), 1.0)
    except Exception:
        return 6.0   # safe fallback duration per slide


def _escape_ffmpeg_text(text):
    """Escapes text for ffmpeg's drawtext filter (colons, quotes, etc.)."""
    return (text.replace("\\", "\\\\")
                .replace(":", "\\:")
                .replace("'", "\u2019")
                .replace("%", "\\%"))


def build_video_reel(slides, out_path):
    """
    Builds a vertical 1080x1920 MP4 from slide images + one combined
    voiceover, with Ken Burns zoom on each image and burned-in captions.
    slides = [{"image_bytes":..., "narration": "..."}] already generated.
    Returns True on success, False on any failure (never raises).
    """
    if not FFMPEG_AVAILABLE:
        log("⚠️ build_video_reel skipped: ffmpeg not installed on this server.")
        return False

    session_dir = os.path.join(VIDEO_TEMP_DIR, str(int(time.time())))
    os.makedirs(session_dir, exist_ok=True)

    try:
        # 1) Save each slide image to disk
        img_paths = []
        for i, slide in enumerate(slides):
            p = os.path.join(session_dir, f"slide_{i}.jpg")
            with open(p, "wb") as f:
                f.write(slide["image_bytes"])
            img_paths.append(p)

        # 2) Generate ONE combined voiceover for natural pacing across all slides
        full_narration = ". ".join(s["narration"] for s in slides)
        audio_path = os.path.join(session_dir, "voice.mp3")
        has_audio = _generate_voiceover(full_narration, audio_path)

        # 3) Work out how long each slide should be shown.
        if has_audio:
            total_duration = _get_media_duration(audio_path)
        else:
            total_duration = len(slides) * 4.0
        total_duration = max(5.0, min(total_duration, 55.0))
        per_slide = max(total_duration / len(slides), 2.5)

        # 4) Build one Ken-Burns zoom clip per slide, with caption burned in
        clip_paths = []
        for i, (img_path, slide) in enumerate(zip(img_paths, slides)):
            clip_path = os.path.join(session_dir, f"clip_{i}.mp4")
            frames = int(per_slide * 25)
            vf_parts = [
                "scale=1080:1920:force_original_aspect_ratio=increase",
                "crop=1080:1920",
                f"zoompan=z='min(zoom+0.0012,1.25)':d={frames}:s=1080x1920:fps=25",
            ]
            if _VIDEO_FONT:
                caption = _escape_ffmpeg_text(slide["narration"][:90])
                vf_parts.append(
                    f"drawtext=fontfile={_VIDEO_FONT}:text='{caption}':"
                    f"fontsize=54:fontcolor=white:box=1:boxcolor=black@0.55:"
                    f"boxborderw=24:x=(w-text_w)/2:y=h-380:line_spacing=8"
                )
            vf = ",".join(vf_parts)
            cmd = [
                "ffmpeg", "-y", "-loop", "1", "-i", img_path,
                "-vf", vf, "-t", str(per_slide),
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "25",
                clip_path,
            ]
            r = subprocess.run(cmd, capture_output=True, timeout=60)
            if r.returncode != 0 or not os.path.exists(clip_path):
                log(f"⚠️ ffmpeg slide {i} failed: {r.stderr.decode(errors='ignore')[:300]}")
                return False
            clip_paths.append(clip_path)

        # 5) Concatenate all slide clips into one silent video
        concat_list_path = os.path.join(session_dir, "concat.txt")
        with open(concat_list_path, "w") as f:
            for cp in clip_paths:
                f.write(f"file '{cp}'\n")
        silent_video_path = os.path.join(session_dir, "silent.mp4")
        r = subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list_path,
             "-c", "copy", silent_video_path],
            capture_output=True, timeout=60
        )
        if r.returncode != 0 or not os.path.exists(silent_video_path):
            log(f"⚠️ ffmpeg concat failed: {r.stderr.decode(errors='ignore')[:300]}")
            return False

        # 6) Merge voiceover audio (if we have it) with the concatenated video
        if has_audio:
            r = subprocess.run(
                ["ffmpeg", "-y", "-i", silent_video_path, "-i", audio_path,
                 "-c:v", "copy", "-c:a", "aac", "-shortest", out_path],
                capture_output=True, timeout=60
            )
            if r.returncode != 0 or not os.path.exists(out_path):
                log(f"⚠️ ffmpeg audio merge failed: {r.stderr.decode(errors='ignore')[:300]}")
                return False
        else:
            shutil.copy(silent_video_path, out_path)

        return True
    except Exception as e:
        log(f"⚠️ build_video_reel exception: {e}")
        return False
    finally:
        try:
            shutil.rmtree(session_dir, ignore_errors=True)
        except Exception:
            pass


def _cover_text_lines(text, max_words=8):
    """Short, readable two-line cover headline derived from the existing hook."""
    words = " ".join(str(text or "").split()).strip().split()[:max_words]
    if not words:
        return "WATCH THIS", ""
    if len(words) <= 4:
        return " ".join(words), ""
    split_at = (len(words) + 1) // 2
    line1 = " ".join(words[:split_at])
    line2 = " ".join(words[split_at:]).rstrip(".,!?;:") + "…"
    return line1, line2


def build_reel_cover(slides, cover_path):
    """
    Creates a separate 1080x1920 JPEG thumbnail from the existing hook image.
    No AI/image-generation API call is made. The first slide is intentionally
    the hook slide, so it is the deterministic, topic-matched cover choice.
    """
    if not FFMPEG_AVAILABLE or not slides:
        return False
    try:
        source_path = os.path.join(VIDEO_TEMP_DIR, f"cover_source_{int(time.time()*1000)}.jpg")
        with open(source_path, "wb") as f:
            f.write(slides[0]["image_bytes"])

        title_line1, title_line2 = _cover_text_lines(slides[0].get("narration", ""), 8)
        subtitle = _cover_text_lines(slides[1].get("narration", ""), 7)[0] if len(slides) > 1 else "Here’s what happens next"
        title_line1 = _escape_ffmpeg_text(title_line1[:60])
        title_line2 = _escape_ffmpeg_text(title_line2[:60])
        subtitle = _escape_ffmpeg_text(subtitle[:70])

        vf = [
            "scale=1080:1920:force_original_aspect_ratio=increase",
            "crop=1080:1920",
            "eq=brightness=-0.10:saturation=1.12:contrast=1.08",
            "vignette=PI/5",
            "drawbox=x=55:y=650:w=970:h=650:color=black@0.48:t=fill",
        ]
        if _VIDEO_FONT:
            vf.extend([
                f"drawtext=fontfile={_VIDEO_FONT}:text='YOU NEED TO SEE THIS':fontsize=38:fontcolor=white@0.92:x=(w-text_w)/2:y=735:borderw=1:bordercolor=black",
                f"drawtext=fontfile={_VIDEO_FONT}:text='{title_line1}':fontsize=70:fontcolor=white:x=(w-text_w)/2:y=825:borderw=3:bordercolor=black",
                f"drawtext=fontfile={_VIDEO_FONT}:text='{title_line2}':fontsize=70:fontcolor=white:x=(w-text_w)/2:y=925:borderw=3:bordercolor=black",
                f"drawtext=fontfile={_VIDEO_FONT}:text='{subtitle}':fontsize=40:fontcolor=white@0.94:x=(w-text_w)/2:y=1080:borderw=1:bordercolor=black",
            ])

        r = subprocess.run(
            ["ffmpeg", "-y", "-i", source_path, "-vf", ",".join(vf),
             "-frames:v", "1", "-q:v", "2", cover_path],
            capture_output=True, timeout=60
        )
        try:
            os.remove(source_path)
        except Exception:
            pass
        if r.returncode != 0 or not os.path.exists(cover_path):
            log(f"⚠️ Reel cover generation failed: {r.stderr.decode(errors='ignore')[:300]}")
            return False
        return True
    except Exception as e:
        log(f"⚠️ build_reel_cover exception: {e}")
        return False

def post_video_reel(video_path, caption, cover_path=None):
    """
    Uploads a video file to Facebook as a Reel using the official 3-step
    Reels API: start -> upload bytes to rupload.facebook.com -> finish/publish.
    Verified against Meta's official fbsamples Postman collection.
    Returns the Graph API result dict (with "id" on success).
    """
    GRAPH_VERSION = "v20.0"
    try:
        # Step 1: start the upload session — returns a video_id only
        # (there is NO "upload_url" field in the real response — the upload
        # target is always the fixed rupload.facebook.com endpoint below)
        start_resp = requests.post(
            f"https://graph.facebook.com/{GRAPH_VERSION}/{FB_PAGE_ID}/video_reels",
            data={"upload_phase": "start", "access_token": FB_ACCESS_TOKEN},
            timeout=REQUEST_TIMEOUT,
        ).json()
        if "video_id" not in start_resp:
            return {"error": {"message": f"Reel start failed: {start_resp}"}}

        video_id = start_resp["video_id"]

        # Step 2: upload the raw video bytes to the fixed rupload endpoint
        with open(video_path, "rb") as f:
            video_bytes = f.read()
        upload_resp = requests.post(
            f"https://rupload.facebook.com/video-upload/{GRAPH_VERSION}/{video_id}",
            headers={
                "Authorization": f"OAuth {FB_ACCESS_TOKEN}",
                "offset": "0",
                "file_size": str(len(video_bytes)),
                "Content-Type": "application/octet-stream",
            },
            data=video_bytes,
            timeout=REQUEST_TIMEOUT + 60,
        )
        if upload_resp.status_code not in (200, 201):
            return {"error": {"message": f"Reel upload failed: {upload_resp.text[:300]}"}}

        # Step 3: finish/publish the reel
        finish_resp = requests.post(
            f"https://graph.facebook.com/{GRAPH_VERSION}/{FB_PAGE_ID}/video_reels",
            data={
                "upload_phase": "finish",
                "video_id": video_id,
                "video_state": "PUBLISHED",
                "description": caption,
                "access_token": FB_ACCESS_TOKEN,
            },
            timeout=REQUEST_TIMEOUT,
        ).json()

        if finish_resp.get("success"):
            # Facebook's Reels publish endpoint does not expose a documented
            # cover_url field. Set the preferred video thumbnail through the
            # video /thumbnails edge as a best-effort post-publish step.
            # If the Page/Reel object does not allow custom thumbnails, keep
            # the Reel published rather than failing the existing upload flow.
            if cover_path and os.path.exists(cover_path):
                try:
                    with open(cover_path, "rb") as cover_file:
                        thumb_resp = requests.post(
                            f"https://graph.facebook.com/{GRAPH_VERSION}/{video_id}/thumbnails",
                            data={
                                "access_token": FB_ACCESS_TOKEN,
                                "is_preferred": "true",
                            },
                            files={"source": ("reel_cover.jpg", cover_file, "image/jpeg")},
                            timeout=REQUEST_TIMEOUT,
                        )
                    if thumb_resp.status_code not in (200, 201):
                        log(f"⚠️ Reel cover upload not accepted; Reel remains published: {thumb_resp.text[:300]}")
                    else:
                        thumb_json = thumb_resp.json() if thumb_resp.content else {}
                        if isinstance(thumb_json, dict) and thumb_json.get("error"):
                            log(f"⚠️ Reel cover upload rejected; Reel remains published: {thumb_json}")
                        else:
                            log(f"✅ Reel custom cover set for {video_id}")
                except Exception as e:
                    log(f"⚠️ Reel cover step failed; Reel remains published: {e}")
            return {"id": video_id}
        return {"error": {"message": f"Reel finish failed: {finish_resp}"}}

    except Exception as e:
        return {"error": {"message": str(e)}}


def generate_and_post_video(topic_hint=None):
    """
    Full pipeline: script -> images -> voiceover -> video file -> upload.
    Returns True on success, False otherwise. Never raises — any failure
    is logged and the bot continues normally (video slot just gets skipped
    for today, exactly like any other content-generation failure).
    """
    if not (FFMPEG_AVAILABLE and EDGE_TTS_AVAILABLE):
        missing = []
        if not FFMPEG_AVAILABLE: missing.append("ffmpeg (sudo apt install ffmpeg)")
        if not EDGE_TTS_AVAILABLE: missing.append("edge-tts (pip install edge-tts --break-system-packages)")
        log(f"⚠️ Video post skipped — missing: {', '.join(missing)}")
        return False

    script = None
    for _ in range(3):
        candidate = generate_video_script(topic_hint)
        if candidate and candidate.get("topic_key") not in seen_video_topics:
            script = candidate
            break
    if not script:
        script = generate_video_script(topic_hint)
    if not script:
        log("❌ generate_and_post_video: script generation failed.")
        return False

    seen_video_topics.add(script.get("topic_key", str(random.randint(1, 999999))))

    # Generate an image for every slide (reuses the same 3-tier image pipeline)
    slides = []
    for slide_data in script["slides"]:
        img = generate_image(slide_data["image_prompt"])
        if not img or not img.get("bytes"):
            log("⚠️ generate_and_post_video: a slide image failed, skipping this video today.")
            return False
        slides.append({"image_bytes": img["bytes"], "narration": slide_data["narration"]})

    os.makedirs(VIDEO_TEMP_DIR, exist_ok=True)
    stamp = int(time.time())
    out_path = os.path.join(VIDEO_TEMP_DIR, f"reel_{stamp}.mp4")
    cover_path = os.path.join(VIDEO_TEMP_DIR, f"reel_cover_{stamp}.jpg")

    # The cover is created from the already-generated hook image/text.
    # No extra Gemini or image-generation API call is made.
    cover_ok = build_reel_cover(slides, cover_path)

    if not build_video_reel(slides, out_path):
        log("❌ generate_and_post_video: video build failed.")
        try:
            if os.path.exists(cover_path):
                os.remove(cover_path)
        except Exception:
            pass
        return False

    caption = apply_monetization(script.get("caption", "🎬 Daily video"))
    result = post_video_reel(out_path, caption, cover_path if cover_ok else None)

    for cleanup_path in (out_path, cover_path):
        try:
            if os.path.exists(cleanup_path):
                os.remove(cleanup_path)
        except Exception:
            pass

    if "id" in result:
        log(f"✅ Video Reel posted: {result['id']}")
        track_posted_post(result["id"], "video")
        notify_post_to_telegram(
            {"id": result["id"]}, "video", caption, script.get("topic_key", "video"),
            {"url": None}
        )
        send_group_share_reminder(result["id"], "video", caption)
        return True
    else:
        log(f"❌ Video Reel upload failed: {result.get('error')}")
        return False


# ================= BACKUP IMAGE SOURCE (NEW) =================
# Stable Horde is a free, crowd-sourced Stable Diffusion API that works with
# the public anonymous key (no signup/API key needed) - slower and lower
# priority than a paid key, but it means an outage on pollinations.ai no
# longer causes that slot's post to be skipped for the whole day. Only ever
# called AFTER pollinations has fully failed - the normal/primary path never
# touches this.
STABLEHORDE_API_KEY = os.getenv("STABLEHORDE_API_KEY", "0000000000")  # anonymous key
STABLEHORDE_POLL_TIMEOUT = 90  # seconds - generous, since this only runs as a last resort


def _fetch_stablehorde_image(prompt):
    try:
        submit = requests.post(
            "https://stablehorde.net/api/v2/generate/async",
            headers={"apikey": STABLEHORDE_API_KEY, "Content-Type": "application/json"},
            json={
                "prompt": prompt,
                "params": {"width": 1024, "height": 1024, "steps": 25, "n": 1},
                "nsfw": False,
                "censor_nsfw": True,
            },
            timeout=REQUEST_TIMEOUT,
        )
        if submit.status_code not in (200, 202):
            log(f"⚠️ Stable Horde submit failed: HTTP {submit.status_code}")
            return None, None
        job_id = submit.json().get("id")
        if not job_id:
            return None, None

        waited = 0
        done = False
        while waited < STABLEHORDE_POLL_TIMEOUT:
            time.sleep(5)
            waited += 5
            check = requests.get(
                f"https://stablehorde.net/api/v2/generate/check/{job_id}", timeout=REQUEST_TIMEOUT
            ).json()
            if check.get("done"):
                done = True
                break
            if check.get("faulted"):
                log("⚠️ Stable Horde job faulted")
                return None, None
        if not done:
            log("⚠️ Stable Horde timed out waiting for image")
            return None, None

        status = requests.get(
            f"https://stablehorde.net/api/v2/generate/status/{job_id}", timeout=REQUEST_TIMEOUT
        ).json()
        generations = status.get("generations", [])
        if not generations:
            return None, None
        img_field = generations[0].get("img")
        if not img_field:
            return None, None

        if img_field.startswith("http"):
            img_resp = requests.get(img_field, timeout=60)
            content = img_resp.content if img_resp.status_code == 200 else None
            url = img_field
        else:
            try:
                content = base64.b64decode(img_field)
            except Exception:
                content = None
            url = None

        if content and len(content) >= IMAGE_MIN_BYTES:
            return content, url
        return None, None
    except Exception as e:
        log(f"⚠️ Stable Horde fallback failed: {e}")
        return None, None


# ================= POST =================
def _do_fb_post_request(caption, image_bytes, alt_text=None):
    # FIX: upload the exact bytes we already downloaded and validated in
    # generate_image(), instead of passing a URL for Facebook to fetch on its
    # own. This removes a second, unverified network hop that used to be the
    # main source of caption/photo mismatches.
    url = f"https://graph.facebook.com/v20.0/{FB_PAGE_ID}/photos"
    data = {
        "caption": caption,
        "access_token": FB_ACCESS_TOKEN
    }
    if alt_text:
        # FIX/new: alt text improves accessibility and Facebook's own reach/SEO signals.
        data["alt_text_custom"] = alt_text[:200]

    files = {"source": ("post_image.jpg", image_bytes, "image/jpeg")}
    return requests.post(url, data=data, files=files, timeout=REQUEST_TIMEOUT).json()


# ================= INSTAGRAM CROSS-POST (NEW, optional) =================
# Only runs if IG_ACCOUNT_ID is set in the environment. If it's not set, this
# function is never called and nothing changes about the Facebook-only flow.
# Uses the standard IG Graph API 2-step flow: create a media container from the
# public image URL, then publish it. Wrapped so a failure here NEVER affects the
# Facebook post that already succeeded.
def post_instagram(caption, image_url):
    if not IG_ACCOUNT_ID or not IG_ACCESS_TOKEN:
        return None
    try:
        create_url = f"https://graph.facebook.com/v20.0/{IG_ACCOUNT_ID}/media"
        create_resp = requests.post(create_url, data={
            "image_url": image_url,
            "caption": caption,
            "access_token": IG_ACCESS_TOKEN
        }, timeout=REQUEST_TIMEOUT).json()

        if "error" in create_resp:
            log(f"❌ Instagram container creation failed: {create_resp['error']}")
            return None

        creation_id = create_resp.get("id")
        if not creation_id:
            log(f"❌ Instagram container creation returned no id: {create_resp}")
            return None

        publish_url = f"https://graph.facebook.com/v20.0/{IG_ACCOUNT_ID}/media_publish"
        publish_resp = requests.post(publish_url, data={
            "creation_id": creation_id,
            "access_token": IG_ACCESS_TOKEN
        }, timeout=REQUEST_TIMEOUT).json()

        if "error" in publish_resp:
            log(f"❌ Instagram publish failed: {publish_resp['error']}")
            return None

        log(f"✅ Cross-posted to Instagram: {publish_resp.get('id')}")
        return publish_resp
    except Exception as e:
        log(f"⚠️ post_instagram exception (Facebook post was not affected): {e}")
        return None


# NEW: Facebook occasionally returns transient errors (rate limiting - codes like
# 4, 17, 32, 613, or a temporary 5xx). Before, a single hiccup meant that slot's
# post was silently lost for the whole day. This retries a few times with
# backoff ONLY for transient-looking errors, and gives up gracefully for real
# errors (bad token, permissions, etc.) exactly like before - so behavior for a
# normal successful post, or a genuine failure, is unchanged.
TRANSIENT_FB_ERROR_CODES = {4, 17, 32, 613}


# ================= GROUP SHARING — TELEGRAM BUTTON (NEW) =================
# Instead of Facebook API (publish_to_groups removed by Meta in 2020),
# sends a Telegram message with the direct post link + one-tap share buttons.
# Clicking the link on phone opens Facebook app directly on the post —
# user can share to groups in 2 taps. Per-category ON/OFF via /settings.
def send_group_share_reminder(post_id, post_type, caption_preview):
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        return
    if not GROUP_SHARE_ENABLED.get(post_type, False):
        return   # this category's share reminder is turned off

    post_url = f"https://www.facebook.com/{post_id}"
    # sharer.php opens Facebook's native share sheet directly (Feed/Story/
    # Group/Message picker) instead of just opening the post — one tap closer
    # to "select group and share" with zero manual steps.
    share_url = f"https://www.facebook.com/sharer/sharer.php?u={urllib.parse.quote(post_url, safe='')}"
    type_labels = {
        "news": "📰 News", "cartoon": "🎨 Cartoon",
        "fact": "🧠 Fact", "poll": "🗳️ Poll", "video": "🎬 Video",
        "scenic": "🏞️ Scenic", "quote": "💬 Quote",
    }
    label = type_labels.get(post_type, post_type)
    post_time = now().strftime("%I:%M %p")

    # Preview = first line of caption
    preview = caption_preview.strip().split("\n")[0][:80]

    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": (
                    f"👥 *Share to Groups — {label}*\n"
                    f"🕐 Posted at {post_time}\n\n"
                    f"_{preview}_\n\n"
                    f"Tap below → pick your group(s) → Share ✅"
                ),
                "parse_mode": "Markdown",
                "reply_markup": {
                    "inline_keyboard": [[
                        {"text": "📤 Share to Group", "url": share_url},
                    ]]
                },
            },
            timeout=REQUEST_TIMEOUT,
        )
    except Exception as e:
        log(f"⚠️ send_group_share_reminder failed: {e}")


def post_fb(caption, image, alt_text=None, post_type="news"):
    # FIX: `image` is now the dict returned by generate_image() -
    # {"bytes": ..., "url": ...} - or None if image generation totally failed
    # after all retries. Previously a failed/broken image generation still
    # got posted (as a broken picture); now we skip the post entirely and log
    # it loudly, so you see it in Discord instead of a bad post going live.
    if not image or not image.get("bytes"):
        log(f"⏭️ Skipped {post_type} post - could not generate a valid image for it (see errors above).")
        return {}

    caption = maybe_add_follow_reminder(caption)  # NEW: ~1 in 4 posts gets a follow/share nudge

    result = {}
    for attempt in range(1, 4):
        try:
            result = _do_fb_post_request(caption, image["bytes"], alt_text)

            if "error" not in result:
                # success -> track for analytics (NEW), then return exactly as before
                if "id" in result:
                    track_posted_post(result["id"], post_type)
                    if image.get("url"):
                        post_instagram(caption, image["url"])
                    notify_post_to_telegram(result, post_type, caption, alt_text, image)
                    # No automatic Page seed comment; keep engagement authentic.
                    send_group_share_reminder(result["id"], post_type, caption)
                return result

            err = result["error"]
            code = err.get("code")
            if code in TRANSIENT_FB_ERROR_CODES and attempt < 3:
                log(f"⚠️ post_fb transient error (attempt {attempt}/3), retrying: {err}")
                time.sleep(5 * attempt)
                continue

            log(f"❌ post_fb failed: {err}")
            return result

        except Exception as e:
            log(f"❌ post_fb exception (attempt {attempt}/3): {e}")
            time.sleep(5 * attempt)

    return result


# ================= FULL POST DETAILS -> TELEGRAM (NEW) =================
# For every post that actually goes live on Facebook, sends a single detailed
# Telegram message containing: what type of post it was, what it was based on
# (the news/holiday/topic title used as alt_text, when available), the exact
# caption that was published, a link to the live post, and the EXACT photo
# that was uploaded. This is purely a notification - it is called only after
# post_fb() has already succeeded, so it never changes what gets posted or
# how/when it gets posted.
def notify_post_to_telegram(result, post_type, caption, alt_text, image):
    try:
        post_id = result.get("id", "unknown")
        ts = now().strftime("%Y-%m-%d %H:%M:%S")

        def esc(t):
            return (t or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        details = (
            f"<b>🆕 New Facebook Post Published</b>\n"
            f"📌 <b>Post type:</b> {esc(post_type)}\n"
            f"📝 <b>Based on:</b> {esc(alt_text) if alt_text else 'N/A'}\n"
            f"🔗 <b>Link:</b> https://facebook.com/{post_id}\n"
            f"🕒 <b>Time:</b> <code>{ts}</code>\n\n"
            f"<b>Caption posted:</b>\n{esc(caption)}"
        )

        sent_as_photo = False
        if image and image.get("bytes"):
            sent_as_photo = send_telegram_photo(image["bytes"], details)

        # If it couldn't be sent as a photo (no image, or Telegram rejected it),
        # or the details were too long to fit in a photo caption (1024 char
        # limit), also/instead send the full details as a plain text message
        # so nothing is ever cut off or lost.
        if not sent_as_photo or len(details) > 1024:
            send_telegram_message(details)
    except Exception as e:
        log(f"⚠️ notify_post_to_telegram failed (Facebook post itself was not affected): {e}")


# ================= ANALYTICS (NEW) =================
def track_posted_post(post_id, post_type):
    daily_posted_posts.append({
        "id": post_id,
        "type": post_type,
        "time": now().isoformat(),
        "hour": now().hour,   # track for best-time analysis
    })


def get_post_engagement(post_id):
    """Fetch likes/comments/shares for a post, excluding comments made by the
    Page itself (self-comments, seed comments, revive comments) so the revive
    check measures REAL user engagement only."""
    try:
        url = (f"https://graph.facebook.com/v20.0/{post_id}"
               f"?fields=likes.summary(true),comments{{from,id}}.summary(true),shares"
               f"&access_token={FB_ACCESS_TOKEN}")
        r = requests.get(url, timeout=REQUEST_TIMEOUT).json()
        if "error" in r:
            return None
        likes = r.get("likes", {}).get("summary", {}).get("total_count", 0)
        # Count only comments NOT made by the Page itself
        all_comments = r.get("comments", {}).get("data", [])
        real_comments = sum(
            1 for c in all_comments
            if c.get("from", {}).get("id", "") != FB_PAGE_ID
        )
        shares = r.get("shares", {}).get("count", 0)
        reach = get_post_reach(post_id)
        return {"likes": likes, "comments": real_comments, "shares": shares, "reach": reach}
    except Exception as e:
        log(f"⚠️ get_post_engagement failed for {post_id}: {e}")
        return None


# ================= REACH / PAGE DIAGNOSTICS (NEW) =================
# Purely read-only informational additions - answers "did anyone actually SEE
# the post" (reach) separately from "did anyone like it" (engagement), and
# reports how many people even follow the Page. This never changes what gets
# posted or when; it only adds a way to see WHY engagement might be low.
def get_post_reach(post_id):
    """Returns unique reach (accounts that saw the post) if the Page has
    access to Page Insights, else None. Facebook only exposes this metric
    once a Page has enough followers/activity, so None is expected and
    normal for a brand-new Page - that itself is diagnostic information."""
    try:
        url = (f"https://graph.facebook.com/v20.0/{post_id}/insights"
               f"?metric=post_impressions_unique&access_token={FB_ACCESS_TOKEN}")
        r = requests.get(url, timeout=REQUEST_TIMEOUT).json()
        if "error" in r:
            return None
        data = r.get("data", [])
        if data and data[0].get("values"):
            return data[0]["values"][0].get("value")
        return None
    except Exception:
        return None


def get_page_diagnostics():
    """Returns the Page's current follower/like count, or None on failure.
    This is usually the single biggest factor behind '0 likes': a post can
    only be liked by people who (a) follow the Page and (b) are shown it by
    Facebook's algorithm - if fan_count is very low, 0 likes is expected
    regardless of content quality."""
    try:
        url = (f"https://graph.facebook.com/v20.0/{FB_PAGE_ID}"
               f"?fields=name,fan_count,followers_count,verification_status"
               f"&access_token={FB_ACCESS_TOKEN}")
        r = requests.get(url, timeout=REQUEST_TIMEOUT).json()
        if "error" in r:
            log(f"⚠️ get_page_diagnostics FB error: {r['error']}")
            return None
        return r
    except Exception as e:
        log(f"⚠️ get_page_diagnostics failed: {e}")
        return None


def build_reach_report_text():
    """NEW: builds the text for the /reach Telegram command - Page size plus
    reach/likes for today's posts, so you can see whether the issue is 'no
    followers yet' vs 'has followers but Facebook isn't showing them the
    posts' vs 'people see it but don't engage'."""
    lines = ["📡 Reach & Audience Report"]

    page = get_page_diagnostics()
    if page:
        name = page.get("name", "?")
        fans = page.get("fan_count")
        followers = page.get("followers_count")
        lines.append(f"Page: {name}")
        if fans is not None:
            lines.append(f"👥 Page likes (fan_count): {fans}")
        if followers is not None:
            lines.append(f"👤 Followers: {followers}")
        if (fans or 0) < 100 and (followers or 0) < 100:
            lines.append(
                "⚠️ Under ~100 followers: Facebook's algorithm rarely shows "
                "posts beyond your existing audience at this size, and some "
                "Insights metrics (reach) may not be available yet either. "
                "This alone fully explains 0 likes - it's not a content problem."
            )
    else:
        lines.append("⚠️ Could not fetch Page follower count (check token permissions).")

    if not daily_posted_posts:
        lines.append("\nNo posts today yet to report reach for.")
        return "\n".join(lines)

    lines.append("\nToday's posts:")
    any_reach = False
    for p in daily_posted_posts[-10:]:
        eng = get_post_engagement(p["id"]) or {}
        reach = eng.get("reach")
        if reach is not None:
            any_reach = True
        reach_str = reach if reach is not None else "n/a"
        lines.append(
            f"  [{p['type']}] 👀 reach: {reach_str}  👍 {eng.get('likes', '-')}  "
            f"💬 {eng.get('comments', '-')}  🔁 {eng.get('shares', '-')}"
        )
    if not any_reach:
        lines.append(
            "\nℹ️ Reach data isn't available (needs Page Insights access, and "
            "Facebook only unlocks it once a Page has enough followers/activity)."
        )
    return "\n".join(lines)


# ================= TOKEN EXPIRY CHECK (NEW) =================
# Facebook Page tokens expire after ~60 days. When they silently die, the
# bot keeps "running" but every post fails — very hard to notice without this.
# Checks weekly (Sunday) and on /token command. Sends an urgent alert if
# the token expires within 7 days, or a warning within 14 days.
def check_token_expiry(quiet=False):
    """
    Queries the Facebook token debug endpoint and returns days remaining.
    quiet=True → only logs if there's a problem (used for weekly auto-check).
    quiet=False → always logs result (used for on-demand /token command).
    """
    try:
        url = (
            f"https://graph.facebook.com/v20.0/debug_token"
            f"?input_token={FB_ACCESS_TOKEN}&access_token={FB_ACCESS_TOKEN}"
        )
        r = requests.get(url, timeout=REQUEST_TIMEOUT).json()
        data = r.get("data", {})

        if not data:
            log(f"❌ Token check failed — could not read token debug info: {r}")
            return None

        is_valid = data.get("is_valid", False)
        if not is_valid:
            error_msg = data.get("error", {}).get("message", "unknown reason")
            log(f"🚨 URGENT: Facebook access token is INVALID — {error_msg}. "
                f"Generate a new token NOW or all posting will fail!")
            return 0

        expires_at = data.get("expires_at", 0)
        if expires_at == 0:
            # Never-expiring token (e.g. long-lived Page token)
            if not quiet:
                log("✅ /token: Facebook access token is valid and never expires.")
            return 999

        days_left = max(0, int((expires_at - time.time()) / 86400))
        scopes = ", ".join(data.get("scopes", []))

        if days_left <= 7:
            log(f"🚨 URGENT: Facebook token expires in {days_left} day(s)! "
                f"Renew it immediately or posting will stop. Scopes: {scopes}")
        elif days_left <= 14:
            log(f"⚠️ Facebook token expires in {days_left} days — start renewal soon. "
                f"Scopes: {scopes}")
        else:
            if not quiet:
                log(f"✅ /token: Facebook access token is valid. "
                    f"Expires in {days_left} days. Scopes: {scopes}")

        return days_left

    except Exception as e:
        log(f"⚠️ check_token_expiry() failed: {e}")
        return None


def daily_summary():
    """Posts a short performance summary to Discord once a day, right before the
    midnight reset. Purely informational - never touches Facebook posting logic."""
    if not daily_posted_posts:
        log("📊 Daily summary: no posts were made today.")
        return

    total = len(daily_posted_posts)
    by_type = {}
    for p in daily_posted_posts:
        by_type[p["type"]] = by_type.get(p["type"], 0) + 1

    best = None
    best_score = -1
    any_engagement_data = False
    for p in daily_posted_posts:
        eng = get_post_engagement(p["id"])
        if eng is None:
            continue
        any_engagement_data = True
        score = eng["likes"] + eng["comments"] * 2 + eng["shares"] * 3
        if score > best_score:
            best_score = score
            best = {**p, **eng}

    lines = [f"📊 Daily Summary ({now().strftime('%Y-%m-%d')})",
             f"Total posts: {total}"]
    for t, c in by_type.items():
        lines.append(f"  - {t}: {c}")

    if any_engagement_data and best:
        lines.append(
            f"🏆 Best performing post: {best['type']} | "
            f"👍 {best['likes']} 💬 {best['comments']} 🔁 {best['shares']}"
        )
    else:
        lines.append("ℹ️ Engagement stats unavailable (check Page Insights permission on the FB token).")

    # NEW: surface WHY reach/likes might be low right in the daily summary,
    # instead of only via the on-demand /reach command - so you see the real
    # cause (page size) automatically every day without having to ask.
    page = get_page_diagnostics()
    if page:
        fans = page.get("fan_count")
        followers = page.get("followers_count")
        if fans is not None or followers is not None:
            lines.append(f"👥 Page size: {fans if fans is not None else '?'} likes / {followers if followers is not None else '?'} followers")
        if (fans or 0) < 100 and (followers or 0) < 100:
            lines.append("⚠️ Low follower count is likely why engagement is near 0 - send /reach for details.")

    log("\n".join(lines))

    # NEW: keep a rolling 7-day history for the weekly digest below
    # Include per-post hour+engagement for best-time analysis in /stats
    post_details = []
    for p in daily_posted_posts:
        eng = get_post_engagement(p["id"]) or {}
        score = eng.get("likes", 0) + eng.get("comments", 0) * 2 + eng.get("shares", 0) * 3
        post_details.append({"hour": p.get("hour"), "engagement": score})

    weekly_history.append({
        "date": now().strftime("%Y-%m-%d"),
        "total": total,
        "by_type": by_type,
        "best_score": best_score if best else 0,
        "best_type": best["type"] if best else None,
        "posts": post_details,   # NEW: for best-hour analysis
    })
    while len(weekly_history) > 7:
        weekly_history.pop(0)


def weekly_summary():
    """NEW: every Sunday, right after the daily summary, roll the last 7 days'
    stats into one Discord message. Purely informational, built only from data
    daily_summary() already collected - never touches posting logic."""
    global weekly_summary_posted_on
    if not weekly_history:
        return

    total = sum(d["total"] for d in weekly_history)
    by_type_totals = {}
    for d in weekly_history:
        for t, c in d.get("by_type", {}).items():
            by_type_totals[t] = by_type_totals.get(t, 0) + c

    best_day = max(weekly_history, key=lambda d: d.get("best_score", 0))

    lines = [f"📈 Weekly Summary (last {len(weekly_history)} days)",
             f"Total posts: {total}"]
    for t, c in by_type_totals.items():
        lines.append(f"  - {t}: {c}")
    if best_day.get("best_type"):
        lines.append(f"🏆 Best day: {best_day['date']} (top post type: {best_day['best_type']})")

    log("\n".join(lines))
    weekly_summary_posted_on = now().strftime("%Y-%m-%d")


# ================= SCHEDULER =================
def scheduler():
    global posted_slots, posted_scenic_slots, posted_cartoon_slots
    global posted_quote_slots, posted_fact_slots
    global seen_news_regular, seen_news_cartoon, seen_quotes_today, seen_facts_today
    global holiday_posted_today, last_replied_comment_ids
    global daily_posted_posts, daily_summary_posted, weekly_history, weekly_summary_posted_on
    global last_reset_date, BOT_PAUSED
    global _jittered_time_slots, _jittered_scenic_slots, _jittered_cartoon_slots
    global _jittered_quote_slots, _jittered_fact_slots, _jittered_poll_slots
    global _jittered_video_slots
    global _startup_existing_post_ids, _startup_existing_comment_ids
    global posted_poll_slots, seen_polls_today
    global posted_video_slots, seen_video_topics

    load_state()  # NEW: resume where we left off if the process restarted mid-day

    # Restart safety: snapshot everything that already existed before this
    # process started. Old posts/comments must not trigger fresh Facebook
    # comments merely because PM2 restarted the bot. New activity after this
    # snapshot is still handled normally.
    _startup_existing_post_ids.update(
        str(p.get("id")) for p in daily_posted_posts if p.get("id")
    )
    try:
        startup_comments = get_recent_comments()
        _startup_existing_comment_ids.update(
            str(c.get("id")) for c in startup_comments if c.get("id")
        )
        last_replied_comment_ids.update(_startup_existing_comment_ids)
        if _startup_existing_comment_ids:
            save_state()
        log(f"🛡️ Restart safety: ignored {len(_startup_existing_post_ids)} existing post(s) "
            f"and {len(_startup_existing_comment_ids)} existing comment(s) for this run.")
    except Exception as e:
        log(f"⚠️ Restart-safety comment snapshot failed: {e}")

    while True:
        try:
            if reset_time() and last_reset_date != now().strftime("%Y-%m-%d"):
                # NEW: before wiping today's posted-slot tracking, check whether
                # any ENABLED category posted absolutely nothing today (image
                # gen kept failing, API key expired, etc.) and warn if it's been
                # happening for multiple days in a row.
                for cat, posted_set in [
                    ("news", posted_slots), ("scenic", posted_scenic_slots),
                    ("cartoon", posted_cartoon_slots), ("quote", posted_quote_slots),
                    ("fact", posted_fact_slots), ("poll", posted_poll_slots),
                ]:
                    if not CATEGORY_ENABLED.get(cat, True):
                        category_fail_streak[cat] = 0  # OFF on purpose - not a failure
                        continue
                    if len(posted_set) == 0:
                        category_fail_streak[cat] = category_fail_streak.get(cat, 0) + 1
                        if category_fail_streak[cat] >= CATEGORY_DOWN_ALERT_THRESHOLD:
                            log(
                                f"🚨 {CATEGORY_LABELS.get(cat, cat)} hasn't posted anything for "
                                f"{category_fail_streak[cat]} day(s) in a row despite being ON - "
                                f"check logs/errors for that category."
                            )
                    else:
                        category_fail_streak[cat] = 0

                posted_slots = set()
                posted_scenic_slots = set()
                posted_cartoon_slots = set()
                posted_quote_slots = set()
                posted_fact_slots = set()
                seen_news_regular = set()
                seen_news_cartoon = set()
                seen_quotes_today = set()
                seen_facts_today = set()
                posted_poll_slots.clear()
                seen_polls_today.clear()
                posted_video_slots.clear()
                seen_video_topics.clear()
                daily_posted_posts = []
                daily_summary_posted = False
                last_reset_date = now().strftime("%Y-%m-%d")  # FIX: marks today as already reset,
                                                                # so this block runs once, not ~15x
                # NEW: recompute per-day random jitter for all slot types
                _jittered_time_slots = _jitter_slots(TIME_SLOTS)
                _jittered_scenic_slots = _jitter_slots(SCENIC_SLOTS)
                _jittered_cartoon_slots = _jitter_slots(CARTOON_SLOTS)
                _jittered_quote_slots = _jitter_slots(QUOTE_SLOTS)
                _jittered_fact_slots = _jitter_slots(FACT_SLOTS)
                _jittered_poll_slots = _jitter_slots(POLL_SLOTS)    # NEW
                _jittered_video_slots = _randomize_video_slots(_jittered_video_slots)
                log("🔄 Daily reset done.")

            # ===== TELEGRAM ON-DEMAND COMMANDS (NEW) =====
            check_telegram_commands()

            # ===== PAUSE GUARD (NEW) =====
            # When paused via /pause, skip all posting and replies but keep
            # the loop alive so /resume works without restarting.
            if BOT_PAUSED:
                time.sleep(20)
                continue

            # ===== AUTO REPLY TO COMMENTS =====
            process_auto_replies()

            # ===== NO AUTOMATED ENGAGEMENT REVIVE =====
            # Real users' comments are handled by process_auto_replies() only.

            # ===== HOLIDAY POST =====
            today_str = now().strftime("%m-%d")
            if today_str in HOLIDAYS and not holiday_posted_today and now().hour == 7 and now().minute < 2:
                holiday_title = HOLIDAYS[today_str]
                holiday_data = holiday_generate(holiday_title)
                img = generate_image(holiday_data["image_prompt"])
                result = post_fb(holiday_data["caption"], img, alt_text=holiday_title, post_type="holiday")
                if "id" in result:
                    holiday_posted_today = True
                    log(f"✅ Holiday post uploaded: {holiday_title}")
                else:
                    log(f"⚠️ Holiday post for {holiday_title} did not go out - will retry next loop.")

            # ===== REGULAR NEWS POSTS =====
            news_list = get_news()

            for i, (h, m) in enumerate(_jittered_time_slots):
                if not CATEGORY_ENABLED["news"]:
                    continue
                if i in posted_slots:
                    continue
                t = now()
                if t.hour == h and t.minute == m:
                    shuffled = news_list[:]
                    random.shuffle(shuffled)
                    posted = False
                    for news in shuffled:
                        if not _news_seen(seen_news_regular, news["title"], news.get("desc", "")):
                            remember_news(seen_news_regular, news["title"], news.get("desc", ""))
                            ai = ai_generate(news["title"], news["desc"])
                            img = generate_image(ai["image_prompt"])
                            result = post_fb(ai["caption"], img, alt_text=news["title"], post_type="news")
                            if "id" in result:
                                posted_slots.add(i)
                                posted = True
                            break
                    if not posted and news_list:
                        news = random.choice(news_list)
                        ai = ai_generate(news["title"], news["desc"])
                        img = generate_image(ai["image_prompt"])
                        result = post_fb(ai["caption"], img, alt_text=news["title"], post_type="news")
                        if "id" in result:
                            posted_slots.add(i)

            # ===== SCENIC POSTS =====
            for i, (h, m) in enumerate(_jittered_scenic_slots):
                if not CATEGORY_ENABLED["scenic"]:
                    continue
                if i in posted_scenic_slots:
                    continue
                t = now()
                if t.hour == h and t.minute == m:
                    ai = scenic_generate()
                    img = generate_image(ai["image_prompt"])
                    result = post_fb(ai["caption"], img, post_type="scenic")
                    if "id" in result:
                        posted_scenic_slots.add(i)

            # ===== CARTOON POSTS =====
            for i, (h, m) in enumerate(_jittered_cartoon_slots):
                if not CATEGORY_ENABLED["cartoon"]:
                    continue
                if i in posted_cartoon_slots:
                    continue
                t = now()
                if t.hour == h and t.minute == m:
                    shuffled = news_list[:]
                    random.shuffle(shuffled)
                    posted = False
                    for news in shuffled:
                        if not _news_seen(seen_news_cartoon, news["title"]):
                            remember_news(seen_news_cartoon, news["title"])
                            ai = cartoon_generate(news["title"], news["desc"])
                            img = generate_image(ai["image_prompt"])
                            result = post_fb(ai["caption"], img, alt_text=news["title"], post_type="cartoon")
                            if "id" in result:
                                posted_cartoon_slots.add(i)
                                posted = True
                            break
                    if not posted and news_list:
                        news = random.choice(news_list)
                        ai = cartoon_generate(news["title"], news["desc"])
                        img = generate_image(ai["image_prompt"])
                        result = post_fb(ai["caption"], img, alt_text=news["title"], post_type="cartoon")
                        if "id" in result:
                            posted_cartoon_slots.add(i)

            # ===== QUOTE OF THE DAY POSTS (NEW) =====
            for i, (h, m) in enumerate(_jittered_quote_slots):
                if not CATEGORY_ENABLED["quote"]:
                    continue
                if i in posted_quote_slots:
                    continue
                t = now()
                if t.hour == h and t.minute == m:
                    ai = None
                    for _ in range(3):
                        candidate = quote_generate()
                        if candidate["key"] not in seen_quotes_today:
                            seen_quotes_today.add(candidate["key"])
                            ai = candidate
                            break
                    if ai is None:
                        ai = quote_generate()
                    img = generate_image(ai["image_prompt"])
                    result = post_fb(ai["caption"], img, post_type="quote")
                    if "id" in result:
                        posted_quote_slots.add(i)

            # ===== FUN FACT POSTS (NEW) =====
            for i, (h, m) in enumerate(_jittered_fact_slots):
                if not CATEGORY_ENABLED["fact"]:
                    continue
                if i in posted_fact_slots:
                    continue
                t = now()
                if t.hour == h and t.minute == m:
                    ai = None
                    for _ in range(3):
                        candidate = fact_generate()
                        if candidate["key"] not in seen_facts_today:
                            seen_facts_today.add(candidate["key"])
                            ai = candidate
                            break
                    if ai is None:
                        ai = fact_generate()
                    img = generate_image(ai["image_prompt"])
                    result = post_fb(ai["caption"], img, post_type="fact")
                    if "id" in result:
                        posted_fact_slots.add(i)

            # ===== DAILY REACTION POLL (NEW) =====
            for i, (h, m) in enumerate(_jittered_poll_slots):
                if not CATEGORY_ENABLED["poll"]:
                    continue
                if i in posted_poll_slots:
                    continue
                t = now()
                if t.hour == h and t.minute == m:
                    ai = None
                    for _ in range(3):
                        candidate = poll_generate()
                        if candidate["key"] not in seen_polls_today:
                            seen_polls_today.add(candidate["key"])
                            ai = candidate
                            break
                    if ai is None:
                        ai = poll_generate()
                    img = generate_image(ai["image_prompt"])
                    result = post_fb(ai["caption"], img, post_type="poll")
                    if "id" in result:
                        posted_poll_slots.add(i)

            # ===== DAILY AI VIDEO REEL (NEW) =====
            # Runs the full script -> images -> voiceover -> video -> Reels
            # upload pipeline. Any failure (missing ffmpeg/edge-tts, image
            # gen failure, upload error) is logged and the slot is simply
            # skipped for today — never crashes the scheduler.
            for i, (h, m) in enumerate(_jittered_video_slots):
                if not CATEGORY_ENABLED["video"]:
                    continue
                if i in posted_video_slots:
                    continue
                t = now()
                if t.hour == h and t.minute == m:
                    if generate_and_post_video():
                        posted_video_slots.add(i)

            # ===== DAILY PERFORMANCE SUMMARY (NEW) =====
            t = now()
            if t.hour == 23 and t.minute >= 55 and not daily_summary_posted:
                daily_summary()
                daily_summary_posted = True
                # NEW: Sunday (weekday() == 6) also gets a rolled-up weekly digest
                today_key = t.strftime("%Y-%m-%d")
                if t.weekday() == 6 and weekly_summary_posted_on != today_key:
                    weekly_summary()
                    check_token_expiry(quiet=True)  # NEW: weekly token health check

            save_state()  # NEW: persist progress every loop so a restart can resume safely
            time.sleep(20)

        except Exception as e:
            log(f"🔥 Scheduler loop crashed: {e}")
            time.sleep(5)


# ================= GRACEFUL SHUTDOWN (NEW) =================
# On Railway the platform mostly just kills the process; on a VPS with systemd
# (systemctl stop/restart) it sends SIGTERM first. This saves state before exit
# so a manual restart on a VPS resumes exactly like the auto-restart-after-crash
# case already does.
def _handle_shutdown(signum, frame):
    log(f"🛑 Received shutdown signal ({signum}), saving state and exiting...")
    try:
        _stop_live_camera("Bot process shutting down")
    except Exception as e:
        log(f"⚠️ Failed to stop live camera cleanly: {e}")
    try:
        save_state()
    except Exception as e:
        log(f"⚠️ Failed to save state on shutdown: {e}")
    sys.exit(0)


signal.signal(signal.SIGTERM, _handle_shutdown)
signal.signal(signal.SIGINT, _handle_shutdown)

# ================= RUN =================
if __name__ == "__main__":
    validate_config()
    register_telegram_commands()   # sets up Telegram '/' menu on startup
    Thread(target=run_server, daemon=True).start()
    scheduler()
