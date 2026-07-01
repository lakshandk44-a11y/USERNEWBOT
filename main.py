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

# ================= AI CAPTION =================
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
 "image_prompt": "..."
}}
"""

        r = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]})
        text = r.json()['candidates'][0]['content']['parts'][0]['text']

        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]

        return json.loads(text.strip())

    except:
        return {
            "caption": f"🔥 Breaking: {title}",
            "image_prompt": "news scene"
        }

# ================= 🎨 IMPROVED IMAGE GENERATOR =================
def generate_image(prompt):
    enhanced_prompt = f"""
ultra cinematic news illustration, high quality AI artwork,
dramatic lighting, depth of field, emotional storytelling,
slightly stylized realistic digital art (not cartoon),
4k ultra detail, magazine cover quality, modern news visualization,

Scene: {prompt}
"""

    return f"https://image.pollinations.ai/p/{urllib.parse.quote(enhanced_prompt)}?width=1080&height=1080&nologo=true&seed={random.randint(1,999999)}"

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

# ================= QUEUE =================
def build_queue():
    global post_queue

    news = get_news()

    for n in news:
        if is_safe(n["title"] + n["desc"]):
            post_queue.append(n)

# ================= WORKER =================
def worker():
    global post_queue

    while True:
        try:
            if len(post_queue) == 0:
                time.sleep(10)
                continue

            item = post_queue.pop(0)

            content = ai_generate(item["title"], item["desc"])
            img = generate_image(content["image_prompt"])

            post_fb(content["caption"], img)

            log(f"Posted: {content['caption']}")

            time.sleep(random.randint(3600, 7200))

        except Exception as e:
            log(f"Worker error: {e}")
            time.sleep(5)

# ================= COMMENT BOT =================
def comment_loop():
    global replied_comments

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

                    time.sleep(10)

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
