import requests
import json
import time
import urllib.parse
import random
import feedparser
import pytz
from datetime import datetime
from flask import Flask
from threading import Thread

# ================= CONFIG (YOUR DATA) =================
FB_PAGE_ID = "1243828092139012"
FB_ACCESS_TOKEN = "EAF40ZBiCgXTQBR6CeFVpHaubM4U9stvPlvBhKFsH57MMT3py3dq8d4Xs9uttevBqwvy99cuvBL4tpmUnxCrjcf14cg4qtSsKJj8bZCizbdhF8sLlWZABkIcZC9Qk6hB6FeduLjNnBhgTlaHi99L09sNGEcIQ8wywZAqNSZAx6bI1xqKvNqUrvYRVAx9d7F0lXBfjg8PmaT"

GEMINI_API_KEY = "AQ.Ab8RN6KbzrhhZ0gfAfBDFeWzsUuECcEcVAu7JkRFW6-sVh9CoQ"

DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1521532656825929911/r_p09BIeETgtrGdk3QsdHb5WglQNSqwKrHTWpCtvmA7n-HyTGKhQWZOz65Zpf0OE58iu"

# ================= FLASK =================
app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 FULL AUTO BOT ONLINE"

def run_server():
    app.run(host="0.0.0.0", port=8080)

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

# ================= VIRAL SCORE =================
def score(text):
    keys = ["war", "breaking", "crisis", "trump", "china", "nasa", "shock", "explosion"]
    return sum(2 for k in keys if k in text.lower()) + len(text)/120

def pick_top(news):
    return sorted(news, key=lambda x: score(x["title"] + x["desc"]), reverse=True)[:10]

# ================= AI =================
def ai_generate(title, desc):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={GEMINI_API_KEY}"

    prompt = f"""
Create viral Facebook caption + cinematic image prompt.

News:
{title}
{desc}

Return ONLY JSON:
{{
 "caption": "...",
 "image_prompt": "dark cinematic ultra realistic dramatic lighting"
}}
"""

    try:
        r = requests.post(url, json={"contents":[{"parts":[{"text":prompt}]}]})
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

# ================= DISCORD =================
def log(title, msg):
    try:
        requests.post(https://discord.com/api/webhooks/1521532656825929911/r_p09BIeETgtrGdk3QsdHb5WglQNSqwKrHTWpCtvmA7n-HyTGKhQWZOz65Zpf0OE58iu, json={
            "embeds":[{"title":title,"description":msg[:3000],"color":3447003}]
        })
    except:
        pass

# ================= FACEBOOK =================
def post_fb(caption, image_url):
    url = f"https://graph.facebook.com/v20.0/{1243828092139012}/photos"

    return requests.post(url, data={
        "caption": caption,
        "url": image_url,
        "access_token": EAF40ZBiCgXTQBR6CeFVpHaubM4U9stvPlvBhKFsH57MMT3py3dq8d4Xs9uttevBqwvy99cuvBL4tpmUnxCrjcf14cg4qtSsKJj8bZCizbdhF8sLlWZABkIcZC9Qk6hB6FeduLjNnBhgTlaHi99L09sNGEcIQ8wywZAqNSZAx6bI1xqKvNqUrvYRVAx9d7F0lXBfjg8PmaT
    }).json()

# ================= COMMENT BOT =================
def comment(post_id):
    try:
        r = requests.get(
            f"https://graph.facebook.com/v20.0/{post_id}/comments",
            params={"access_token": EAF40ZBiCgXTQBR6CeFVpHaubM4U9stvPlvBhKFsH57MMT3py3dq8d4Xs9uttevBqwvy99cuvBL4tpmUnxCrjcf14cg4qtSsKJj8bZCizbdhF8sLlWZABkIcZC9Qk6hB6FeduLjNnBhgTlaHi99L09sNGEcIQ8wywZAqNSZAx6bI1xqKvNqUrvYRVAx9d7F0lXBfjg8PmaT}
        ).json()

        if "data" not in r:
            return

        replies = [
            "🔥 Interesting",
            "What do you think?",
            "Crazy 👀",
            "This is trending",
            "Wow"
        ]

        for c in r["data"][:2]:
            cid = c["id"]

            requests.post(
                f"https://graph.facebook.com/v20.0/{cid}/comments",
                data={
                    "message": random.choice(replies),
                    "access_token": EAF40ZBiCgXTQBR6CeFVpHaubM4U9stvPlvBhKFsH57MMT3py3dq8d4Xs9uttevBqwvy99cuvBL4tpmUnxCrjcf14cg4qtSsKJj8bZCizbdhF8sLlWZABkIcZC9Qk6hB6FeduLjNnBhgTlaHi99L09sNGEcIQ8wywZAqNSZAx6bI1xqKvNqUrvYRVAx9d7F0lXBfjg8PmaT
                }
            )

            time.sleep(25)

    except:
        pass

# ================= SLOTS =================
def slots():
    return [7*3600,9*3600,11*3600,13*3600,15*3600,17*3600,19*3600,21*3600,22*3600,23*3600]

# ================= MAIN =================
def run_bot():
    running = False

    while True:
        t = now()

        if reset_time():
            running = False

        if is_6am() and not running:
            running = True
            log("🚀 START", "Bot started")

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
                    pid = res["id"]
                    log("✅ POSTED", content["caption"])
                    comment(pid)
                else:
                    log("❌ FAILED", str(res))

                time.sleep(60)

            log("🏁 DONE", "Cycle finished")

        time.sleep(30)

# ================= START =================
if __name__ == "__main__":
    Thread(target=run_server, daemon=True).start()
    run_bot()
