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
    (8, 0),
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

# ================= SCENIC IMAGE SLOTS =================
SCENIC_SLOTS = [
    (7, 0),
    (9, 0),
    (11, 0),
    (14, 52),
    (15, 0),
    (17, 0),
    (19, 0),
    (21, 0),
    (22, 30),
    (23, 45),
]

posted_scenic_slots = set()

SCENIC_PLACES = [
    "Grand Canyon, USA",
    "Yellowstone National Park",
    "Yosemite National Park",
    "Golden Gate Bridge, San Francisco",
    "New York City skyline at night",
    "Hawaii tropical beach sunset",
    "Alaska snowy mountains landscape",
    "Antelope Canyon glowing light beams",
    "Route 66 desert road cinematic view",
    "Chicago skyline reflections on river"
]

# ================= LOG =================
def log(msg):
    print(msg)
    try:
        if DISCORD_WEBHOOK_URL:
            requests.post(DISCORD_WEBHOOK_URL, json={
                "content": f"""
🚀 **FACEBOOK BOT UPDATE**

🧠 Status:
{msg}

⏰ Time: {now().strftime('%Y-%m-%d %H:%M:%S')}
"""
            })
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

# ================= GEMINI NEWS AI =================
def ai_generate(title, desc):
    for attempt in range(2):
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"

            prompt = f"""
Create viral Facebook news caption + image prompt.

Return JSON:
{{
 "caption": "...",
 "image_prompt": "..."
}}

News:
{title}
{desc}
"""

            r = requests.post(url, json={
                "contents": [{"parts": [{"text": prompt}]}]
            }, timeout=30)

            data = r.json()

            if "candidates" not in data:
                continue

            text = data["candidates"][0]["content"]["parts"][0]["text"]

            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]

            result = json.loads(text.strip())

            return result

        except:
            time.sleep(1)

    return fallback(title)

def fallback(title):
    return {
        "caption": f"🚨 Breaking Update: {title}\n\n#BreakingNews #WorldNews",
        "image_prompt": "dark cinematic news photography, ultra realistic"
    }

# ================= SCENIC AI GENERATOR =================
def scenic_generate():
    place = random.choice(SCENIC_PLACES)

    captions = [
        f"✨ Discover the breathtaking beauty of {place}",
        f"🌍 Nature’s masterpiece: {place}",
        f"📍 A stunning view of {place}",
        f"🔥 Experience the magic of {place}"
    ]

    hashtags = "#Travel #Nature #USA #BeautifulPlaces #Photography #Explore"

    prompt = f"""
Ultra realistic cinematic photo of {place},
golden hour lighting, 8k, professional photography, breathtaking view
"""

    return {
        "caption": random.choice(captions) + "\n\n" + hashtags,
        "image_prompt": prompt
    }

# ================= IMAGE =================
def generate_image(prompt):
    safe = urllib.parse.quote(
        prompt + ", ultra realistic, cinematic, 4k, professional photography"
    )
    return f"https://image.pollinations.ai/prompt/{safe}"

# ================= FACEBOOK POST =================
def post_fb(caption, image_url):
    try:
        url = f"https://graph.facebook.com/v20.0/{FB_PAGE_ID}/photos"

        res = requests.post(url, data={
            "url": image_url,
            "caption": caption,
            "access_token": FB_ACCESS_TOKEN
        })

        return res.json()

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
                        "Interesting 👍",
                        "Good point 👀",
                        "Appreciate it ❤️"
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

# ================= SCHEDULER =================
def scheduler():
    global posted_slots, posted_scenic_slots

    while True:
        try:
            if reset_time():
                posted_slots = set()
                posted_scenic_slots = set()
                log("NEW DAY RESET")

            # -------- NEWS POSTS --------
            for i in range(len(TIME_SLOTS)):
                if i in posted_slots:
                    continue

                h, m = TIME_SLOTS[i]
                if now().hour == h and now().minute == m:

                    news = get_news()
                    if not news:
                        continue

                    pick = random.choice(news)
                    ai = ai_generate(pick["title"], pick["desc"])
                    img = generate_image(ai["image_prompt"])

                    res = post_fb(ai["caption"], img)

                    if "id" in res:
                        posted_slots.add(i)
                        log(f"NEWS POST SLOT {i+1}")

            # -------- SCENIC POSTS --------
            for i in range(len(SCENIC_SLOTS)):
                if i in posted_scenic_slots:
                    continue

                h, m = SCENIC_SLOTS[i]
                if now().hour == h and now().minute == m:

                    scenic = scenic_generate()
                    img = generate_image(scenic["image_prompt"])

                    res = post_fb(scenic["caption"], img)

                    if "id" in res:
                        posted_scenic_slots.add(i)
                        log(f"SCENIC POST SLOT {i+1}")

            time.sleep(20)

        except Exception as e:
            log(f"SCHEDULER ERROR: {e}")
            time.sleep(5)

# ================= START =================
if __name__ == "__main__":
    Thread(target=run_server, daemon=True).start()
    Thread(target=comment_bot, daemon=True).start()
    scheduler()
