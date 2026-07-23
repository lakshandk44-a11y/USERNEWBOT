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
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

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
TIME_SLOTS = [(6, 0), (8, 0), (10, 0), (11, 42), (14, 0), (16, 0), (18, 0), (20, 0), (22, 0), (23, 30)]
SCENIC_SLOTS = [(7, 0), (9, 0), (11, 0), (13, 0), (15, 15), (17, 0), (19, 0), (21, 0), (22, 30), (23, 45)]
CARTOON_SLOTS = [(7, 15), (12, 15), (13, 26), (16, 30), (19, 30)]

# NEW: two extra content types in their own slots, so nothing existing shifts or gets crowded out.
QUOTE_SLOTS = [(9, 45), (20, 45)]
FACT_SLOTS = [(12, 45), (18, 45)]

posted_slots = set()
posted_scenic_slots = set()
posted_cartoon_slots = set()
posted_quote_slots = set()   # NEW
posted_fact_slots = set()    # NEW

seen_news_regular = set()
seen_news_cartoon = set()
seen_quotes_today = set()    # NEW
seen_facts_today = set()     # NEW

MAX_SEEN_NEWS = 500  # FIX: these sets grew forever (memory leak on long uptime). Cap them.


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


# ================= LOG =================
def log(msg):
    print(msg)
    try:
        _file_logger.info(msg)  # NEW: also persist to logs/bot.log for VPS debugging
    except Exception as e:
        print(f"log() failed to write to file: {e}")
    try:
        if DISCORD_WEBHOOK_URL:
            requests.post(DISCORD_WEBHOOK_URL, json={"content": msg[:1900]}, timeout=REQUEST_TIMEOUT)
    except Exception as e:
        print(f"log() failed to reach Discord: {e}")


# ================= STARTUP VALIDATION (new) =================
def validate_config():
    missing = []
    if not FB_PAGE_ID: missing.append("FB_PAGE_ID")
    if not FB_ACCESS_TOKEN: missing.append("FB_ACCESS_TOKEN")
    if not GEMINI_API_KEY: missing.append("GEMINI_API_KEY")
    if missing:
        log(f"⚠️ Missing required environment variables: {', '.join(missing)}. "
            f"The bot will run but posting/AI generation will fail until these are set on Railway.")


# ================= GEMINI CALL HELPER (new, replaces silent `except:` everywhere) =================
def call_gemini(prompt, retries=3, label="gemini"):
    """
    Calls Gemini and returns the raw text response, or None on failure.
    Unlike before, this LOGS THE REAL REASON for failure (bad key, quota,
    safety block, empty candidates, etc.) instead of swallowing it silently.
    This was the actual root cause of the bug where every post fell back
    to a generic "News Update" caption + generic image.
    """
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"

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
Create viral Facebook caption + image prompt JSON.

NEWS:
{title}
{desc}

Return:
{{"caption":"...","image_prompt":"..."}}
""", label="ai_generate")

    if text:
        try:
            result = extract_json(text)
            caption = f"{result['caption']}\n\n{pick_hashtags_smart(title)}"
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
        "caption": apply_monetization(f"📰 {title}\n\n{pick_hashtags()}"),
        "image_prompt": f"{title}, {style}, highly detailed, 4k"
    }


# ================= CARTOON =================
def cartoon_generate(title, desc):
    text = call_gemini(f"""
Editorial cartoon news illustration.

NEWS:
{title}
{desc}

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
Also create a matching cinematic image prompt for a background image.

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

    caption = f"💭 \"{quote_text}\"\n\n{pick_hashtags()}"
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
Keep it short and fascinating. Also create a matching realistic image prompt.

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

    caption = f"🤯 Fun Fact:\n{fact_text}\n\n{pick_hashtags()}"
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
def generate_image(prompt):
    # FIX: pollinations.ai caches/returns the same image for an identical prompt.
    # Previously, whenever the fallback text ("news illustration" etc.) was used,
    # EVERY post got the exact same cached picture. Adding a random seed + fixed
    # dimensions guarantees a fresh image every single time, even if the prompt
    # text itself repeats.
    seed = random.randint(1, 999999999)
    encoded = urllib.parse.quote(prompt)
    return f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&seed={seed}&nologo=true"


# ================= POST =================
def _do_fb_post_request(caption, image_url, alt_text=None):
    url = f"https://graph.facebook.com/v20.0/{FB_PAGE_ID}/photos"
    payload = {
        "url": image_url,
        "caption": caption,
        "access_token": FB_ACCESS_TOKEN
    }
    if alt_text:
        # FIX/new: alt text improves accessibility and Facebook's own reach/SEO signals.
        payload["alt_text_custom"] = alt_text[:200]

    return requests.post(url, data=payload, timeout=REQUEST_TIMEOUT).json()


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


def post_fb(caption, image_url, alt_text=None, post_type="news"):
    result = {}
    for attempt in range(1, 4):
        try:
            result = _do_fb_post_request(caption, image_url, alt_text)

            if "error" not in result:
                # success -> track for analytics (NEW), then return exactly as before
                if "id" in result:
                    track_posted_post(result["id"], post_type)
                    post_instagram(caption, image_url)  # NEW: no-op unless IG_ACCOUNT_ID is set
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
        return {"likes": likes, "comments": comments, "shares": shares}
    except Exception as e:
        log(f"⚠️ get_post_engagement failed for {post_id}: {e}")
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

    load_state()  # NEW: resume where we left off if the process restarted mid-day

    while True:
        try:
            if reset_time():
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
                last_replied_comment_ids = set()
                daily_posted_posts = []
                daily_summary_posted = False
                log("🔄 Daily reset done.")

            # ===== AUTO REPLY TO COMMENTS =====
            process_auto_replies()

            # ===== HOLIDAY POST =====
            today_str = now().strftime("%m-%d")
            if today_str in HOLIDAYS and not holiday_posted_today and now().hour == 7 and now().minute < 2:
                holiday_title = HOLIDAYS[today_str]
                holiday_data = holiday_generate(holiday_title)
                img = generate_image(holiday_data["image_prompt"])
                post_fb(holiday_data["caption"], img, alt_text=holiday_title, post_type="holiday")
                holiday_posted_today = True
                log(f"✅ Holiday post uploaded: {holiday_title}")

            # ===== REGULAR NEWS POSTS =====
            news_list = get_news()

            for i, (h, m) in enumerate(TIME_SLOTS):
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
