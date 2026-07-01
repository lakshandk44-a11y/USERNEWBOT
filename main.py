import requests
import json
import time
import urllib.parse
import random
import feedparser
import pytz
import os
from datetime import datetime
from flask import Flask
from threading import Thread

# ================= CONFIG =================
FB_PAGE_ID = os.getenv("FB_PAGE_ID")
FB_ACCESS_TOKEN = os.getenv("FB_ACCESS_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

# ================= FLASK =================
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot Running"

def run_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

# ================= TIME =================
tz = pytz.timezone("America/New_York")

def now():
    return datetime.now(tz)

def reset_time():
    t = now()
    return t.hour == 0 and t.minute < 5

# ================= TIME SLOTS =================
TIME_SLOTS = [
    (6, 0),
    (9, 37),
    (10, 0),
    (12, 0),
    (14, 0),
    (16, 0),
    (18, 0),
    (20, 0),
    (22, 0),
    (23, 30),
]

posted_slots = set()
seen_comments = set()

# ================= LOG =================
def log(msg):
    print(msg)
    try:
        if DISCORD_WEBHOOK_URL:
            requests.post(DISCORD_WEBHOOK_URL, json={"content": msg})
    except:
        pass

# ================= NEWS =================
def get_news():
    try:
        feed = feedparser.parse(
            "https://news.google.com/rss/headlines/section/topic/WORLD?hl=en-US&gl=US&ceid=US:en"
        )

        items = []
        for e in feed.entries[:20]:
            items.append({
                "title": e.title,
                "desc": getattr(e, "summary", e.title)
            })

        return items

    except Exception as e:
        log(f"News error: {e}")
        return []

# ================= AI (SAFE) =================
def ai_generate(title, desc):
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"

        prompt = f"""
Create viral Facebook caption + image prompt.

News:
{title}
{desc}

Return ONLY JSON:
{{
 "caption": "...",
 "image_prompt": "..."
}}
"""

        r = requests.post(url, json={
            "contents": [{"parts": [{"text": prompt}]}]
        }, timeout=30)

        data = r.json()

        if "candidates" not in data:
            log(f"AI FAIL: {data}")
            return fallback(title)

        text = data["candidates"][0]["content"]["parts"][0]["text"]

        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]

        return json.loads(text.strip())

    except Exception as e:
        log(f"AI ERROR: {e}")
        return fallback(title)

# ================= FALLBACK =================
def fallback(title):
    return {
        "caption": f"🔥 Breaking News: {title}",
        "image_prompt": "cinematic news illustration"
    }

# ================= IMAGE =================
def generate_image(prompt):
    safe = urllib.parse.quote(prompt[:120])
    return f"https://dummyimage.com/1080x1080/000/fff.png&text={safe}"

# ================= FACEBOOK POST =================
def post_fb(caption, image_url):
    try:
        url = f"https://graph.facebook.com/v20.0/{FB_PAGE_ID}/feed"

        res = requests.post(url, data={
            "message": caption + "\n\n" + image_url,
            "access_token": FB_ACCESS_TOKEN
        })

        result = res.json()
        log(f"FB RESPONSE: {result}")
        return result

    except Exception as e:
        log(f"FB ERROR: {e}")
        return {"error": str(e)}

# ================= COMMENT BOT =================
def comment_bot():
    while True:
        try:
            posts = requests.get(
                f"https://graph.facebook.com/v20.0/{FB_PAGE_ID}/posts",
                params={"access_token": FB_ACCESS_TOKEN}
            ).json()

            if "data" not in posts:
                time.sleep(30)
                continue

            for post in posts["data"][:5]:
                post_id = post["id"]

                comments = requests.get(
                    f"https://graph.facebook.com/v20.0/{post_id}/comments",
                    params={"access_token": FB_ACCESS_TOKEN}
                ).json()

                if "data" not in comments:
                    continue

                for c in comments["data"]:
                    cid = c["id"]

                    if cid in seen_comments:
                        continue

                    seen_comments.add(cid)

                    reply = random.choice([
                        "Thanks 🙌",
                        "Interesting!",
                        "Good point 👍",
                        "Nice view ❤️",
                        "Appreciate it!"
                    ])

                    requests.post(
                        f"https://graph.facebook.com/v20.0/{cid}/comments",
                        data={
                            "message": reply,
                            "access_token": FB_ACCESS_TOKEN
                        }
                    )

                    time.sleep(5)

        except Exception as e:
            log(f"COMMENT ERROR: {e}")

        time.sleep(60)

# ================= SLOT CHECK =================
def should_post(slot):
    t = now()
    h, m = TIME_SLOTS[slot]
    return t.hour == h and t.minute == m

# ================= MAIN SCHEDULER =================
def scheduler():
    global posted_slots

    while True:
        try:
            if reset_time():
                posted_slots = set()
                log("NEW DAY RESET")

            for i in range(len(TIME_SLOTS)):
                if i in posted_slots:
                    continue

                if should_post(i):
                    news = get_news()
                    if not news:
                        continue

                    pick = random.choice(news)

                    ai = ai_generate(pick["title"], pick["desc"])
                    img = generate_image(ai["image_prompt"])

                    res = post_fb(ai["caption"], img)

                    if "id" in res:
                        log(f"POST DONE SLOT {i+1}")
                        posted_slots.add(i)
                    else:
                        log(f"POST FAIL SLOT {i+1}: {res}")

            time.sleep(20)

        except Exception as e:
            log(f"SCHEDULER ERROR: {e}")
            time.sleep(5)

# ================= START =================
if __name__ == "__main__":
    Thread(target=run_server, daemon=True).start()
    Thread(target=comment_bot, daemon=True).start()
    scheduler()
