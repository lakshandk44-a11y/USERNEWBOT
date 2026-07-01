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
seen_titles = set()
post_queue = []

# ================= FLASK =================
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot Running"

def run_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

# ================= TIME (NEW YORK) =================
tz = pytz.timezone("America/New_York")

def now():
    return datetime.now(tz)

def is_start_time():
    t = now()
    return t.hour == 6 and t.minute < 5

def reset_time():
    t = now()
    return t.hour == 0 and t.minute < 5

# ================= LOG =================
def log(msg):
    print(msg)
    try:
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

        for e in feed.entries[:30]:
            title = e.title

            if title in seen_titles:
                continue

            seen_titles.add(title)

            items.append({
                "title": title,
                "desc": getattr(e, "summary", title)
            })

        return items

    except Exception as e:
        log(f"News error: {e}")
        return []

# ================= AI =================
def ai_generate(title, desc):
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={GEMINI_API_KEY}"

        prompt = f"""
Create viral Facebook caption + image prompt.

News:
{title}
{desc}

Return ONLY JSON:
{{
 "caption": "...",
 "image_prompt": "cinematic dramatic news style"
}}
"""

        r = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]})
        text = r.json()['candidates'][0]['content']['parts'][0]['text']

        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]

        return json.loads(text.strip())

    except Exception as e:
        log(f"AI error: {e}")
        return {
            "caption": f"🔥 Breaking: {title}",
            "image_prompt": "dark cinematic news"
        }

# ================= IMAGE =================
def generate_image(prompt):
    return f"https://image.pollinations.ai/p/{urllib.parse.quote(prompt)}?width=1080&height=1080&nologo=true&seed={random.randint(1,999999)}"

# ================= FACEBOOK POST =================
def post_fb(caption, image_url):
    try:
        url = f"https://graph.facebook.com/v20.0/{FB_PAGE_ID}/photos"

        res = requests.post(url, data={
            "caption": caption,
            "url": image_url,
            "access_token": FB_ACCESS_TOKEN
        }).json()

        return res

    except Exception as e:
        log(f"FB error: {e}")
        return {"error": str(e)}

# ================= SAFE FILTER =================
def is_safe(text):
    bad_words = ["death", "kill", "terror", "rape"]
    return not any(b in text.lower() for b in bad_words)

# ================= QUEUE BUILDER =================
def build_queue():
    global post_queue

    news = get_news()

    for n in news:
        if is_safe(n["title"] + n["desc"]):
            post_queue.append(n)

# ================= WORKER =================
def worker():
    global latest_post_id, post_queue

    while True:
        try:
            if len(post_queue) == 0:
                time.sleep(10)
                continue

            item = post_queue.pop(0)

            content = ai_generate(item["title"], item["desc"])
            img = generate_image(content["image_prompt"])

            res = post_fb(content["caption"], img)

            if "id" in res:
                latest_post_id = res["id"]
                log(f"Posted: {content['caption']}")
            else:
                log(f"Failed: {res}")

            time.sleep(random.randint(3600, 7200))  # 1–2 hours delay

        except Exception as e:
            log(f"Worker error: {e}")
            time.sleep(5)

# ================= COMMENT BOT =================
def comment_loop():
    global latest_post_id

    while True:
        try:
            if latest_post_id:
                requests.post(
                    f"https://graph.facebook.com/v20.0/{latest_post_id}/comments",
                    data={
                        "message": random.choice([
                            "Thanks 🙌",
                            "Interesting!",
                            "Good update 👍",
                            "What do you think?"
                        ]),
                        "access_token": FB_ACCESS_TOKEN
                    }
                )
        except:
            pass

        time.sleep(900)

# ================= SCHEDULER =================
def scheduler():
    running = False

    while True:
        try:
            if reset_time():
                running = False

            if is_start_time() and not running:
                running = True
                log("🚀 New York Cycle Started")
                build_queue()

        except Exception as e:
            log(f"Scheduler error: {e}")

        time.sleep(30)

# ================= START =================
if __name__ == "__main__":
    Thread(target=run_server, daemon=True).start()
    Thread(target=comment_loop, daemon=True).start()
    Thread(target=worker, daemon=True).start()
    scheduler()
