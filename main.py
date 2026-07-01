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

# ================= GLOBAL =================
latest_post_id = None

# ================= FLASK =================
app = Flask(__name__)

@app.route("/")
def home():
    return "🤖 Bot is Running"

def run_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

# ================= TIME =================
tz = pytz.timezone("America/New_York")

def now():
    return datetime.now(tz)

def is_6am():
    t = now()
    return t.hour == 6 and t.minute < 5

def reset_time():
    t = now()
    return t.hour == 0 and t.minute < 5

# ================= NEWS =================
def get_news():
    feed = feedparser.parse(
        "https://news.google.com/rss/headlines/section/topic/WORLD?hl=en-US&gl=US&ceid=US:en"
    )
    return [
        {"title": e.title, "desc": getattr(e, "summary", e.title)}
        for e in feed.entries[:20]
    ]

# ================= SCORE =================
def score(text):
    keys = ["war", "breaking", "crisis", "trump", "china", "nasa", "shock", "explosion"]
    return sum(2 for k in keys if k in text.lower()) + len(text) / 120

def pick_top(news):
    return sorted(news, key=lambda x: score(x["title"] + x["desc"]), reverse=True)[:10]

# ================= AI =================
def ai_generate(title, desc):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={GEMINI_API_KEY}"

    prompt = f"""
Create viral Facebook caption + image prompt.

News:
{title}
{desc}

Return ONLY JSON:
{{
 "caption": "...",
 "image_prompt": "dark cinematic news style"
}}
"""

    try:
        r = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]})
        text = r.json()['candidates'][0]['content']['parts'][0]['text']

        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]

        return json.loads(text.strip())

    except:
        return {
            "caption": f"🔥 Breaking News: {title}",
            "image_prompt": "dark cinematic news scene"
        }

# ================= IMAGE =================
def generate_image(prompt):
    return f"https://image.pollinations.ai/p/{urllib.parse.quote(prompt)}?width=1080&height=1080&nologo=true&seed={random.randint(1,999999)}"

# ================= LOG =================
def log(msg):
    try:
        requests.post(DISCORD_WEBHOOK_URL, json={"content": msg})
    except:
        pass

# ================= FACEBOOK POST =================
def post_fb(caption, image_url):
    url = f"https://graph.facebook.com/v20.0/{FB_PAGE_ID}/photos"

    return requests.post(url, data={
        "caption": caption,
        "url": image_url,
        "access_token": FB_ACCESS_TOKEN
    }).json()

# ================= COMMENT BOT =================
def comment(post_id):
    try:
        r = requests.get(
            f"https://graph.facebook.com/v20.0/{post_id}/comments",
            params={"access_token": FB_ACCESS_TOKEN}
        ).json()

        if "data" not in r:
            return

        replies = [
            "Thanks for sharing your thoughts! 🙌",
            "That's an interesting point.",
            "We appreciate your comment ❤️",
            "Thanks for joining the discussion!",
            "Glad to hear your opinion."
        ]

        for c in r["data"][:2]:
            cid = c["id"]

            requests.post(
                f"https://graph.facebook.com/v20.0/{cid}/comments",
                data={
                    "message": random.choice(replies),
                    "access_token": FB_ACCESS_TOKEN
                }
            )

            time.sleep(20)

    except:
        pass

# ================= COMMENT LOOP =================
def comment_loop():
    global latest_post_id

    while True:
        if latest_post_id:
            try:
                comment(latest_post_id)
            except Exception as e:
                log(f"Comment Error: {e}")

        time.sleep(900)

# ================= SLOTS =================
def slots():
    return [
        0, 2 * 3600, 4 * 3600, 6 * 3600,
        8 * 3600, 10 * 3600, 12 * 3600,
        14 * 3600, 16 * 3600, 17 * 3600,
    ]

# ================= MAIN BOT =================
def run_bot():
    global latest_post_id

    running = False

    while True:
        try:
            t = now()

            if reset_time():
                running = False

            if is_6am() and not running:
                running = True
                log("🚀 Bot Started")

                news = pick_top(get_news())
                base = time.time()
                s = slots()

                for i, n in enumerate(news):

                    while time.time() < base + s[i]:
                        time.sleep(20)

                    content = ai_generate(n["title"], n["desc"])
                    img = generate_image(content["image_prompt"])

                    res = post_fb(content["caption"], img)

                    if "id" in res:
                        latest_post_id = res["id"]
                        log(f"✅ Posted: {content['caption']}")
                    else:
                        log(f"❌ Failed: {res}")

                    time.sleep(60)

                log("🏁 Cycle Completed")

        except Exception as e:
            log(f"❌ Error: {str(e)}")
            time.sleep(10)

        time.sleep(30)

# ================= START =================
if __name__ == "__main__":
    Thread(target=run_server, daemon=True).start()
    Thread(target=comment_loop, daemon=True).start()
    run_bot()
