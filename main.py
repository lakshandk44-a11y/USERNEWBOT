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
post_queue = []
seen_titles = set()
replied_comments = set()

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

def is_start_time():
    t = now()
    return t.hour == 9 and t.minute == 03

def reset_time():
    t = now()
    return t.hour == 0 and t.minute < 5

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
            title = getattr(e, "title", "No Title")

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

        payload = {
            "contents": [{"parts": [{"text": prompt}]}]
        }

        r = requests.post(url, json=payload, timeout=30)
        data = r.json()

        text = data["candidates"][0]["content"]["parts"][0]["text"]

        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]

        return json.loads(text.strip())

    except Exception as e:
        log(f"AI error: {e}")
        return {
            "caption": f"🔥 Breaking: {title}",
            "image_prompt": "news illustration"
        }

# ================= IMAGE (SAFE FIX) =================
def generate_image(prompt):
    # Facebook-safe approach: stable public image generator
    safe = urllib.parse.quote(prompt[:120])

    return f"https://dummyimage.com/1080x1080/000/fff.png&text={safe}"

# ================= FACEBOOK POST FIXED =================
def post_fb(caption, image_url):
    try:
        # FIX: use feed instead of /photos (avoids image validation error)
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

# ================= SAFETY =================
def is_safe(text):
    bad_words = ["death", "kill", "terror", "rape"]
    return not any(b in text.lower() for b in bad_words)

# ================= QUEUE =================
def build_queue():
    news = get_news()
    for n in news:
        if is_safe(n["title"] + n["desc"]):
            post_queue.append(n)

# ================= WORKER =================
def worker():
    while True:
        try:
            if not post_queue:
                time.sleep(10)
                continue

            item = post_queue.pop(0)

            content = ai_generate(item["title"], item["desc"])
            img = generate_image(content["image_prompt"])

            res = post_fb(content["caption"], img)

            if "id" in res:
                log(f"POST SUCCESS: {res['id']}")
            else:
                log(f"POST FAILED: {res}")

            time.sleep(random.randint(3600, 7200))

        except Exception as e:
            log(f"Worker error: {e}")
            time.sleep(5)

# ================= COMMENT BOT =================
def comment_loop():
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

                    if cid in replied_comments:
                        continue

                    replied_comments.add(cid)

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
            log(f"Comment error: {e}")

        time.sleep(60)

# ================= SCHEDULER =================
def scheduler():
    running = False

    while True:
        try:
            if reset_time():
                running = False

            if is_start_time() and not running:
                running = True
                log("New York Cycle Started")
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
