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
from logging.handlers import RotatingFileHandler
from datetime import datetime
from flask import Flask
from threading import Thread

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

# NEW: Telegram notifications (replaces the old Discord webhook logger).
# Defaults are set to the bot/chat you gave me, but can still be overridden
# via env vars on Railway/VPS without touching code.
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
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
    "https://news.google.com/rss/headlines/section/topic/WORLD?hl=en-US&gl=US&ceid=US:en"
)
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
    global CATEGORY_ENABLED
    global last_reset_date

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
        telegram_update_offset = s.get("telegram_update_offset", 0)
        last_reset_date = s.get("last_reset_date")

        saved_categories = s.get("category_enabled")
        if saved_categories:
            for k in CATEGORY_ENABLED:
                CATEGORY_ENABLED[k] = saved_categories.get(k, CATEGORY_ENABLED[k])

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
            "telegram_update_offset": telegram_update_offset,
            "category_enabled": CATEGORY_ENABLED,
            "last_reset_date": last_reset_date,
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

# ================= HASHTAG POOL (new) =================
# Rotated automatically into news/cartoon captions so every post doesn't
# reuse the exact same 4 hashtags -> better reach / less "spammy" pattern.
HASHTAG_POOL = [
    "#BreakingNews", "#WorldNews", "#Trending", "#Viral", "#NewsUpdate",
    "#Today", "#StayInformed", "#GlobalNews", "#MustSee", "#Explore"
]


def pick_hashtags(n=4):
    return " ".join(random.sample(HASHTAG_POOL, min(n, len(HASHTAG_POOL))))


# ================= ENGAGEMENT CTA (NEW) =================
# Cartoon posts already ended with "💬 What do you think?" - this gives
# News/Quote/Fact posts the same kind of comment-inviting line (rotated so it
# doesn't look copy-pasted every time). More comments = more reach signal to
# Facebook's algorithm. Purely additive - nothing existing is modified.
ENGAGEMENT_CTAS = [
    "💬 What do you think?",
    "💬 Let us know in the comments!",
    "💬 Agree or disagree? Tell us below!",
    "💬 Share your thoughts in the comments!",
]


def pick_engagement_cta():
    return random.choice(ENGAGEMENT_CTAS)


# ================= FOLLOW/SHARE REMINDER (NEW) =================
# Occasionally (not every post - that would look spammy) reminds people to
# follow/share the Page. Applied centrally in post_fb() so it works for every
# category automatically without editing each content generator.
FOLLOW_REMINDERS = [
    "👉 Follow this Page for more!",
    "🔔 Hit Follow so you don't miss the next one!",
    "❤️ Like & Share if you enjoyed this!",
]
FOLLOW_REMINDER_CHANCE = 0.25  # roughly 1 in 4 posts


def maybe_add_follow_reminder(caption):
    if random.random() < FOLLOW_REMINDER_CHANCE:
        return f"{caption}\n\n{random.choice(FOLLOW_REMINDERS)}"
    return caption


def pick_hashtags_smart(context_text, n=4):
    """NEW: same static hashtags as before, PLUS one extra hashtag generated from
    the actual news topic when possible (better reach/relevance than the static
    pool alone). If the Gemini call fails for any reason, this quietly falls back
    to the exact old pick_hashtags() output - so captions never break."""
    base = pick_hashtags(n)
    try:
        text = call_gemini(
            f'Give ONE single relevant Facebook hashtag (just the word, with # in front, '
            f'no explanation) for this news topic: "{context_text}"',
            retries=1,
            label="dynamic_hashtag"
        )
        if text:
            tag = text.strip().split()[0]
            if tag.startswith("#") and tag not in base:
                return f"{base} {tag}"
    except Exception:
        pass
    return base


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
TIME_SLOTS = [(8, 0), (13, 0), (18, 0), (21, 0)]
SCENIC_SLOTS = [(10, 30), (16, 0)]
CARTOON_SLOTS = [(14, 30)]
QUOTE_SLOTS = [(9, 0)]
FACT_SLOTS = [(19, 30)]

posted_slots = set()
posted_scenic_slots = set()
posted_cartoon_slots = set()
posted_quote_slots = set()   # NEW
posted_fact_slots = set()    # NEW

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
}
CATEGORY_LABELS = {
    "news": "📰 News",
    "scenic": "🏞️ Scenic",
    "cartoon": "🎨 Cartoon",
    "quote": "💬 Quote",
    "fact": "🧠 Fact",
}

# ================= CATEGORY DOWN ALERT (NEW) =================
# Tracks, per category, how many consecutive days it was ON but posted
# NOTHING (e.g. image generation kept failing, API key expired, etc.) so you
# get warned instead of silently losing a whole category for days.
category_fail_streak = {"news": 0, "scenic": 0, "cartoon": 0, "quote": 0, "fact": 0}
CATEGORY_DOWN_ALERT_THRESHOLD = 2  # days

seen_news_regular = set()
seen_news_cartoon = set()
seen_quotes_today = set()    # NEW
seen_facts_today = set()     # NEW

MAX_SEEN_NEWS = 500  # FIX: these sets grew forever (memory leak on long uptime). Cap them.
MAX_REPLIED_COMMENT_IDS = 3000  # FIX: same idea for replied-comment tracking (see below)


def remember_news(seen_set, title):
    seen_set.add(title)
    if len(seen_set) > MAX_SEEN_NEWS:
        # drop oldest-ish half (sets aren't ordered, so just trim arbitrarily)
        for t in list(seen_set)[: len(seen_set) - MAX_SEEN_NEWS]:
            seen_set.discard(t)


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
    return "\n".join(lines)


def build_categories_keyboard():
    """NEW: builds the inline on/off button grid for the 5 post categories,
    showing the current ON/OFF state on each button."""
    buttons = []
    for key, label in CATEGORY_LABELS.items():
        state = "🟢 ON" if CATEGORY_ENABLED.get(key, True) else "🔴 OFF"
        buttons.append([{
            "text": f"{label} — {state}",
            "callback_data": f"toggle_{key}",
        }])
    return {"inline_keyboard": buttons}


def send_categories_message():
    """NEW: sends the /categories message with the on/off button keyboard."""
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": "🎛️ Post category controls — tap to toggle ON/OFF:",
                "reply_markup": build_categories_keyboard(),
            },
            timeout=REQUEST_TIMEOUT,
        )
    except Exception as e:
        log(f"⚠️ send_categories_message failed: {e}")


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
    to simple commands (/stats, /help, /categories, /reach) or toggles a
    category on/off. Safe to call repeatedly - it only looks at updates newer
    than telegram_update_offset."""
    global telegram_update_offset
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

            # NEW: handle button taps (callback queries) for category on/off toggles
            cb = update.get("callback_query")
            if cb:
                cb_chat_id = str(cb.get("message", {}).get("chat", {}).get("id", ""))
                if cb_chat_id != str(TELEGRAM_CHAT_ID):
                    continue  # ignore anyone except you
                cb_data = cb.get("data", "")
                if cb_data.startswith("toggle_"):
                    key = cb_data[len("toggle_"):]
                    if key in CATEGORY_ENABLED:
                        CATEGORY_ENABLED[key] = not CATEGORY_ENABLED[key]
                        save_state()
                        state_word = "ON ✅" if CATEGORY_ENABLED[key] else "OFF ⛔"
                        answer_callback_query(cb["id"], f"{CATEGORY_LABELS[key]} turned {state_word}")
                        message_id = cb.get("message", {}).get("message_id")
                        if message_id:
                            update_categories_message(cb_chat_id, message_id)
                    else:
                        answer_callback_query(cb["id"], "Unknown category")
                continue

            msg = update.get("message", {})
            chat_id = str(msg.get("chat", {}).get("id", ""))
            text = (msg.get("text") or "").strip().lower()
            if chat_id != str(TELEGRAM_CHAT_ID):
                continue  # ignore anyone except you
            if text in ("/stats", "/status"):
                send_telegram_message(build_stats_text())
            elif text in ("/reach", "/why", "/diagnostics"):
                send_telegram_message(build_reach_report_text())  # NEW: see below - explains WHY reach/likes are low
            elif text in ("/categories", "/settings"):
                send_categories_message()
            elif text == "/help":
                send_telegram_message(
                    "🤖 Commands:\n"
                    "/stats - today's posts + engagement so far\n"
                    "/reach - WHY reach/likes are low (page size, real reach data)\n"
                    "/categories - on/off buttons for each post category\n"
                    "/help - this message"
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


# ================= STARTUP VALIDATION (new) =================
def validate_config():
    missing = []
    if not FB_PAGE_ID: missing.append("FB_PAGE_ID")
    if not FB_ACCESS_TOKEN: missing.append("FB_ACCESS_TOKEN")
    if not GEMINI_API_KEY: missing.append("GEMINI_API_KEY")
    if missing:
        log(f"⚠️ Missing required environment variables: {', '.join(missing)}. "
            f"The bot will run but posting/AI generation will fail until these are set on Railway.")

    # NEW: one-time startup note (not per-post, so no log spam) about which
    # image source is active - helps you confirm Cloudflare picked up your
    # CF_ACCOUNT_ID/CF_API_TOKEN correctly after setting them.
    if CF_ACCOUNT_ID and CF_API_TOKEN:
        log("🖼️ Image source: Cloudflare Workers AI (primary), pollinations.ai + Stable Horde as fallback.")
    else:
        log("🖼️ Image source: pollinations.ai (primary), Stable Horde as fallback. "
            "Set CF_ACCOUNT_ID + CF_API_TOKEN to switch to higher-quality Cloudflare Workers AI as primary.")


# ================= GEMINI CALL HELPER (new, replaces silent `except:` everywhere) =================
def call_gemini(prompt, retries=3, label="gemini"):
    """
    Calls Gemini and returns the raw text response, or None on failure.
    Unlike before, this LOGS THE REAL REASON for failure (bad key, quota,
    safety block, empty candidates, etc.) instead of swallowing it silently.
    This was the actual root cause of the bug where every post fell back
    to a generic "News Update" caption + generic image.
    """
    # FIX: gemini-2.5-flash now returns HTTP 404 ("no longer available to new
    # users") for any API key/project that didn't already use it before -
    # Google restricted it. gemini-3.5-flash is the current, active model
    # with a free tier, confirmed working for new keys.
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={GEMINI_API_KEY}"

    for attempt in range(1, retries + 1):
        try:
            r = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=REQUEST_TIMEOUT)

            if r.status_code != 200:
                log(f"❌ [{label}] Gemini HTTP {r.status_code} (attempt {attempt}/{retries}): {r.text[:500]}")
                time.sleep(3)
                continue

            data = r.json()

            if "candidates" not in data or not data["candidates"]:
                # Common cause: prompt blocked by safety filters, or quota/response shape changed.
                reason = data.get("promptFeedback", data)
                log(f"❌ [{label}] Gemini returned no candidates (attempt {attempt}/{retries}): {json.dumps(reason)[:500]}")
                time.sleep(3)
                continue

            candidate = data["candidates"][0]
            finish_reason = candidate.get("finishReason")
            if finish_reason and finish_reason not in ("STOP", "MAX_TOKENS"):
                log(f"⚠️ [{label}] Gemini finishReason={finish_reason} (attempt {attempt}/{retries})")

            text = candidate["content"]["parts"][0]["text"]
            return text

        except Exception as e:
            log(f"❌ [{label}] Gemini call exception (attempt {attempt}/{retries}): {e}")
            time.sleep(3)

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
            feed = feedparser.parse(RSS_FEED_URL)  # NEW: configurable via RSS_FEED_URL env var, same default as before
            news_cache = [{"title": e.title, "desc": getattr(e, "summary", e.title)} for e in feed.entries[:20]]
            news_last_fetch = time.time()
        return news_cache
    except Exception as e:
        log(f"⚠️ get_news() failed: {e}")
        return news_cache if news_cache else []


news_cache = []
news_last_fetch = 0


# ================= AI NEWS =================
def ai_generate(title, desc):
    text = call_gemini(f"""
Create a viral Facebook caption + a matching image prompt for this news story.

NEWS:
{title}
{desc}

Rules for image_prompt:
- Describe a CONCRETE real-world scene that directly matches the specific
  people, place, objects, or event in this news story - not a vague/generic
  "news illustration"
- Photojournalism style, realistic, highly detailed
- Do NOT ask for any text, headlines, captions, logos, or writing to appear
  in the image - text-in-image always renders broken

Return:
{{"caption":"...","image_prompt":"..."}}
""", label="ai_generate")

    if text:
        try:
            result = extract_json(text)
            caption = f"{result['caption']}\n\n{pick_engagement_cta()}\n\n{pick_hashtags_smart(title)}"
            result["caption"] = apply_monetization(caption)
            return result
        except Exception as e:
            log(f"❌ ai_generate JSON parse failed: {e} | raw: {text[:300]}")

    # FIX: fallback now uses the REAL news title + a randomized style,
    # instead of the same static "News Update" / "news illustration" every time.
    style = random.choice([
        "cinematic photojournalism style, dramatic lighting",
        "modern flat-design news graphic, bold colors",
        "detailed digital painting, moody atmosphere",
        "high-contrast newspaper front-page illustration"
    ])
    return {
        "caption": apply_monetization(f"📰 {title}\n\n{pick_engagement_cta()}\n\n{pick_hashtags()}"),
        "image_prompt": f"{title}, {style}, highly detailed, 4k"
    }


# ================= CARTOON =================
def cartoon_generate(title, desc):
    text = call_gemini(f"""
Editorial cartoon news illustration for this story.

NEWS:
{title}
{desc}

Rules for image_prompt:
- Depict the specific subject/situation of this news story, not a generic
  newsroom scene
- Satirical editorial cartoon style, bold outlines, exaggerated expressions
- Do NOT ask for any text, speech bubbles, captions, or writing in the image -
  text-in-image always renders broken/garbled

Return JSON:
{{"caption":"...","image_prompt":"..."}}
""", label="cartoon_generate")

    if text:
        try:
            result = extract_json(text)
            caption = f"""🖼 {result["caption"]}

📌 {title}

💬 What do you think?

{pick_hashtags_smart(title)}
"""
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
        "caption": apply_monetization(f"🖼 {title}\n\n💬 What do you think?\n\n{pick_hashtags()}"),
        "image_prompt": f"{title}, {style}, highly detailed"
    }


# ================= HOLIDAY =================
def holiday_generate(holiday_title):
    text = call_gemini(f"""
Generate a beautiful, artistic, cinematic greeting post for this holiday:

{holiday_title}

Rules:
- Caption must be warm, heartfelt, and viral-friendly
- Dark, moody, cinematic aesthetic
- Unique artistic style — not generic stock photo
- image_prompt must NOT ask for any text, words, or writing to appear in the
  image - text-in-image always renders broken

Return ONLY JSON:
{{"caption":"...","image_prompt":"..."}}
""", label="holiday_generate")

    if text:
        try:
            return extract_json(text)
        except Exception as e:
            log(f"❌ holiday_generate JSON parse failed: {e} | raw: {text[:300]}")

    return {
        "caption": holiday_title,
        "image_prompt": f"Dark cinematic moody artistic illustration, {holiday_title}, highly detailed, dramatic lighting"
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
Create an original, powerful, short inspirational quote about {topic}.
It must NOT be a copy of any famous existing quote - write a brand new one.
Also create a matching cinematic BACKGROUND image prompt (mood/scenery only).
The image_prompt must NOT ask for the quote text, any words, letters, or
writing to appear in the image itself - the quote is added as a caption
separately, and text rendered inside AI images always comes out broken.

Return ONLY JSON:
{{"quote":"...","author_style":"Original","image_prompt":"..."}}
""", label="quote_generate")

    quote_text = None
    image_prompt = None
    if text:
        try:
            result = extract_json(text)
            quote_text = result.get("quote")
            image_prompt = result.get("image_prompt")
        except Exception as e:
            log(f"❌ quote_generate JSON parse failed: {e} | raw: {text[:300]}")

    if not quote_text:
        quote_text = "Every day is a new chance to become who you want to be."
    if not image_prompt:
        image_prompt = (
            f"Cinematic minimalist background representing {topic}, soft dramatic lighting, "
            f"inspirational mood, highly detailed, 4k"
        )

    caption = f"💭 \"{quote_text}\"\n\n{pick_engagement_cta()}\n\n{pick_hashtags()}"
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
Keep it short and fascinating. Also create a matching realistic image prompt
that depicts the subject of the fact itself (no text/words/writing in the
image - the fact is shown as a caption separately).

Return ONLY JSON:
{{"fact":"...","image_prompt":"..."}}
""", label="fact_generate")

    fact_text = None
    image_prompt = None
    if text:
        try:
            result = extract_json(text)
            fact_text = result.get("fact")
            image_prompt = result.get("image_prompt")
        except Exception as e:
            log(f"❌ fact_generate JSON parse failed: {e} | raw: {text[:300]}")

    if not fact_text:
        fact_text = f"Did you know? {topic.capitalize()} still holds many mysteries scientists are exploring today."
    if not image_prompt:
        image_prompt = f"Realistic detailed photograph representing {topic}, high quality, 4k"

    caption = f"🤯 Fun Fact:\n{fact_text}\n\n{pick_engagement_cta()}\n\n{pick_hashtags()}"
    return {
        "caption": apply_monetization(caption),
        "image_prompt": image_prompt,
        "key": fact_text.strip().lower()
    }


# ================= AUTO REPLY TO COMMENTS =================
last_replied_comment_ids = set()


def get_recent_comments():
    try:
        url = f"https://graph.facebook.com/v20.0/{FB_PAGE_ID}/feed?fields=id,comments{{id,message,created_time}}&access_token={FB_ACCESS_TOKEN}"
        r = requests.get(url, timeout=REQUEST_TIMEOUT)
        data = r.json()
        if "error" in data:
            log(f"❌ get_recent_comments FB error: {data['error']}")
            return []
        comments = []
        for post in data.get("data", []):
            if "comments" in post:
                for comment in post["comments"].get("data", []):
                    comments.append(comment)
        return comments
    except Exception as e:
        log(f"⚠️ get_recent_comments failed: {e}")
        return []


def classify_comment(comment_text):
    """NEW: lightweight spam/abuse check so the bot doesn't cheerfully auto-reply to
    scam links or hate speech, and so YOU get alerted to review it. This never
    deletes or hides anything automatically - it only skips the auto-reply for
    flagged comments and pings Discord so a human can decide."""
    text = call_gemini(f"""
Classify this Facebook comment. Reply with ONLY JSON:
{{"flag": true or false, "reason": "short reason or empty string"}}

Flag it true only if it is spam, a scam/phishing link, an ad for an unrelated
product/service, hate speech, harassment, or explicit content. Normal comments,
questions, disagreement, or negative opinions about the post's topic should be
flag: false.

Comment: {comment_text}
""", label="classify_comment")

    if not text:
        return {"flag": False, "reason": ""}
    try:
        return extract_json(text)
    except Exception:
        return {"flag": False, "reason": ""}


def auto_reply_to_comment(comment_id, comment_text):
    text = call_gemini(f"""
Reply to this Facebook comment in a friendly, engaging, and natural way.
Keep it short (1-2 sentences). Be helpful and warm.

Comment: {comment_text}

Reply:
""", label="auto_reply")

    if not text:
        return

    reply_text = text.strip()
    try:
        reply_url = f"https://graph.facebook.com/v20.0/{comment_id}/replies"
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


def process_auto_replies():
    comments = get_recent_comments()
    for comment in comments:
        cid = comment["id"]
        if cid not in last_replied_comment_ids:
            last_replied_comment_ids.add(cid)
            # FIX: previously this set got wiped every midnight, which meant a
            # comment already replied to yesterday (but still visible in the
            # feed today) could get a SECOND auto-reply. Now it's never reset -
            # instead it's capped like seen_news, so memory still can't grow
            # forever, but "already replied" is remembered permanently.
            if len(last_replied_comment_ids) > MAX_REPLIED_COMMENT_IDS:
                for old_id in list(last_replied_comment_ids)[: len(last_replied_comment_ids) - MAX_REPLIED_COMMENT_IDS]:
                    last_replied_comment_ids.discard(old_id)
            message = comment.get("message", "")

            # NEW: check for spam/abuse before replying. On any classification
            # failure this defaults to flag=False, so normal replies keep working
            # exactly as before.
            classification = classify_comment(message)
            if classification.get("flag"):
                log(f"🚩 Flagged comment {cid} for review: \"{message[:200]}\" "
                    f"(reason: {classification.get('reason', '')})")
                continue  # skip auto-reply for flagged comments; a human should review

            auto_reply_to_comment(cid, message)


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

    image_prompt_text = call_gemini(f"""
Generate a SINGLE, EXTREMELY DETAILED, ULTRA-HIGH-QUALITY image prompt for generating a stunning hyper-realistic photograph of this specific destination.

Destination: {place}

CRITICAL RULES (follow ALL strictly):
- Must be the absolute HIGHEST QUALITY image prompt possible — describe EVERY visual detail
- Hyper-realistic, ultra-HD, cinematic quality, award-winning National Geographic style photography
- Describe the unique natural beauty, colors, lighting, atmosphere, textures, and mood specific to {place}
- Include professional camera metadata: 32k resolution, extreme sharpness, natural film grain, Phase One IQ4 150MP camera, 35mm prime lens at f/11, 1/160s shutter, ISO 100
- Cinematic golden hour lighting (or blue hour if that fits better) with long dramatic shadows, volumetric haze, god rays where applicable
- Fujifilm Velvia film simulation for rich, vibrant, natural colors
- Professional color grading, master-level composition, rule of thirds
- Include specific weather/seasonal conditions that make {place} look its absolute best
- Do NOT mention any other place names — ONLY describe {place}
- Make it UNIQUE to {place} — not a generic description that could fit anywhere
- Do NOT ask for any text, signs, labels, or writing to appear in the image
- End with: "A flawless, pristine, highly photorealistic masterpiece with breathtaking detail"

Return ONLY a single plain text string (NO JSON, NO markdown formatting, NO code blocks — just the prompt text):
""", label="scenic_image_prompt")

    caption_text = call_gemini(f"""
Create a short, viral, engaging Facebook caption for this travel destination.

Destination: {place}

Rules:
- 3-4 lines maximum
- Include a sense of wonder and adventure
- Ask an engaging question at the end
- Include relevant hashtags (4-5 max)
- Make it feel unique to {place} — not generic

Return ONLY the caption text (no JSON, no markdown):
""", label="scenic_caption")

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
        caption_text = f"✨ {place}\n\n🌍 Nature's masterpiece awaits.\n\nHave you ever dreamed of visiting here?\n\n{pick_hashtags()}"

    return {"caption": caption_text.strip(), "image_prompt": image_prompt_text.strip()}


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
    url = (
        f"https://image.pollinations.ai/prompt/{encoded}"
        f"?width=1024&height=1024&seed={seed}&nologo=true&model={model}&enhance=true"
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
    prompt = f"{prompt}, no text, no words, no letters, no watermark, no logo"

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
                        post_instagram(caption, image["url"])  # NEW: no-op unless IG_ACCOUNT_ID is set
                    notify_post_to_telegram(result, post_type, caption, alt_text, image)  # NEW: full details + photo to Telegram
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
        "time": now().isoformat()
    })


def get_post_engagement(post_id):
    """Fetch likes/comments/shares for a post. Returns None if insights aren't available
    (e.g. missing permission) - daily_summary() handles that gracefully."""
    try:
        url = (f"https://graph.facebook.com/v20.0/{post_id}"
               f"?fields=likes.summary(true),comments.summary(true),shares"
               f"&access_token={FB_ACCESS_TOKEN}")
        r = requests.get(url, timeout=REQUEST_TIMEOUT).json()
        if "error" in r:
            return None
        likes = r.get("likes", {}).get("summary", {}).get("total_count", 0)
        comments = r.get("comments", {}).get("summary", {}).get("total_count", 0)
        shares = r.get("shares", {}).get("count", 0)
        reach = get_post_reach(post_id)  # NEW: actual "how many people saw it" figure
        return {"likes": likes, "comments": comments, "shares": shares, "reach": reach}
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
    weekly_history.append({
        "date": now().strftime("%Y-%m-%d"),
        "total": total,
        "by_type": by_type,
        "best_score": best_score if best else 0,
        "best_type": best["type"] if best else None,
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
    global last_reset_date

    load_state()  # NEW: resume where we left off if the process restarted mid-day

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
                    ("fact", posted_fact_slots),
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
                holiday_posted_today = False
                daily_posted_posts = []
                daily_summary_posted = False
                last_reset_date = now().strftime("%Y-%m-%d")  # FIX: marks today as already reset,
                                                                # so this block runs once, not ~15x
                log("🔄 Daily reset done.")

            # ===== TELEGRAM ON-DEMAND COMMANDS (NEW) =====
            check_telegram_commands()

            # ===== AUTO REPLY TO COMMENTS =====
            process_auto_replies()

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

            for i, (h, m) in enumerate(TIME_SLOTS):
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
                        if news["title"] not in seen_news_regular:
                            remember_news(seen_news_regular, news["title"])
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
            for i, (h, m) in enumerate(SCENIC_SLOTS):
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
            for i, (h, m) in enumerate(CARTOON_SLOTS):
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
                        if news["title"] not in seen_news_cartoon:
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
            for i, (h, m) in enumerate(QUOTE_SLOTS):
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
            for i, (h, m) in enumerate(FACT_SLOTS):
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

            # ===== DAILY PERFORMANCE SUMMARY (NEW) =====
            t = now()
            if t.hour == 23 and t.minute >= 55 and not daily_summary_posted:
                daily_summary()
                daily_summary_posted = True
                # NEW: Sunday (weekday() == 6) also gets a rolled-up weekly digest
                today_key = t.strftime("%Y-%m-%d")
                if t.weekday() == 6 and weekly_summary_posted_on != today_key:
                    weekly_summary()

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
        save_state()
    except Exception as e:
        log(f"⚠️ Failed to save state on shutdown: {e}")
    sys.exit(0)


signal.signal(signal.SIGTERM, _handle_shutdown)
signal.signal(signal.SIGINT, _handle_shutdown)

# ================= RUN =================
if __name__ == "__main__":
    validate_config()
    Thread(target=run_server, daemon=True).start()
    scheduler()
