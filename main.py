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

# ================= MONETIZATION SETTINGS =================
MONETIZATION_MODE = "affiliate"

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
TIME_SLOTS = [(6,0),(8,0),(10,0),(12,0),(14,0),(16,0),(18,0),(20,0),(22,0),(23,30)]
SCENIC_SLOTS = [(7,0),(9,0),(11,0),(13,0),(15,15),(17,0),(19,0),(21,0),(22,30),(23,45)]
CARTOON_SLOTS = [(7,15),(12,15),(13,26),(16,30),(19,30)]

posted_slots = set()
posted_scenic_slots = set()
posted_cartoon_slots = set()
seen_news = set()

# ================= SCENIC DAILY SYSTEM =================
scenic_daily_places = []
scenic_used_today = set()
scenic_last_date = None

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
            requests.post(DISCORD_WEBHOOK_URL, json={"content": msg})
    except:
        pass

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
    try:
        feed = feedparser.parse(
            "https://news.google.com/rss/headlines/section/topic/WORLD?hl=en-US&gl=US&ceid=US:en"
        )
        return [{"title":e.title,"desc":getattr(e,"summary",e.title)} for e in feed.entries[:20]]
    except:
        return []

# ================= AI NEWS =================
def ai_generate(title, desc):
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"

        prompt = f"""
Create viral Facebook caption + image prompt JSON.

NEWS:
{title}
{desc}

Return:
{{"caption":"...","image_prompt":"..."}}
"""

        r = requests.post(url, json={"contents":[{"parts":[{"text":prompt}]}]})
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"]

        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]

        result = json.loads(text)
        result["caption"] = apply_monetization(result["caption"])
        return result

    except:
        return {
            "caption": apply_monetization("News Update"),
            "image_prompt": "news illustration"
        }

# ================= VIRAL CAPTION =================
def make_viral_caption(text):
    hooks = ["🚨 BREAKING:", "😱 SHOCKING:", "🔥 JUST IN:", "⚠️ ALERT:"]
    suffix = [
        "People are reacting strongly!",
        "This is going viral right now!",
        "You won't believe this!",
        "What is your opinion?"
    ]
    return f"{random.choice(hooks)} {text}\n\n{random.choice(suffix)}"

# ================= CARTOON =================
def cartoon_generate(title, desc):
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"

        prompt = f"""
Editorial cartoon news illustration.

NEWS:
{title}
{desc}

Return JSON:
{{"caption":"...","image_prompt":"..."}}
"""

        r = requests.post(url, json={"contents":[{"parts":[{"text":prompt}]}]})
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"]

        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]

        result = json.loads(text)

        caption = f"""🖼 {result["caption"]}

📌 {title}

💬 What do you think?

#BreakingNews #Cartoon #Viral #Trending
"""

        result["caption"] = apply_monetization(caption.strip())
        return result

    except:
        return {
            "caption": apply_monetization("News Update"),
            "image_prompt": "editorial cartoon"
        }

# ================= SCENIC DAILY AI SYSTEM (OPTIMIZED) =================
def get_daily_scenic_pool():
    global scenic_daily_places, scenic_last_date

    today = now().date()

    if scenic_last_date != today or len(scenic_daily_places) == 0:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"

            prompt = """
Generate 10 UNIQUE viral scenic travel destinations for today.

Rules:
- Must be real-world places
- Must be highly photogenic
- Must be different from common repeats

Return ONLY JSON array:
["place1","place2",...]
"""

            r = requests.post(url, json={"contents":[{"parts":[{"text":prompt}]}]})
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]

            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]

            scenic_daily_places = json.loads(text)
            scenic_last_date = today
            scenic_used_today.clear()

        except:
            scenic_daily_places = random.sample(SCENIC_PLACES, 10)
            scenic_last_date = today
            scenic_used_today.clear()

    return scenic_daily_places

def scenic_generate():
    pool = get_daily_scenic_pool()

    available = [p for p in pool if p not in scenic_used_today]

    if not available:
        scenic_used_today.clear()
        available = pool

    place = random.choice(available)
    scenic_used_today.add(place)

    return {
        "caption": f"""✨ {place}

🌍 Experience the beauty of this breathtaking destination.

🔥 Travel inspiration for your bucket list!

#Travel #Nature #Wanderlust #Explore #Scenic #BeautifulPlaces #TravelGram""",
        "image_prompt": f"Ultra realistic cinematic drone photography, golden hour lighting, highly detailed travel photo of {place}"
    }

# ================= IMAGE =================
def generate_image(prompt):
    return "https://image.pollinations.ai/prompt/" + urllib.parse.quote(prompt)

# ================= POST =================
def post_fb(caption, image_url):
    url = f"https://graph.facebook.com/v20.0/{FB_PAGE_ID}/photos"
    return requests.post(url, data={
        "url": image_url,
        "caption": caption,
        "access_token": FB_ACCESS_TOKEN
    }).json()

# ================= SCHEDULER =================
def scheduler():
    global posted_slots, posted_scenic_slots, posted_cartoon_slots, seen_news

    while True:
        try:
            if reset_time():
                posted_slots=set()
                posted_scenic_slots=set()
                posted_cartoon_slots=set()
                seen_news=set()

            news_list = get_news()

            for i,(h,m) in enumerate(TIME_SLOTS):
                if i in posted_slots:
                    continue
                t = now()
                if t.hour == h and abs(t.minute - m) <= 1:
                    random.shuffle(news_list)
                    for news in news_list:
                        if news["title"] in seen_news:
                            continue
                        seen_news.add(news["title"])
                        ai = ai_generate(news["title"], news["desc"])
                        img = generate_image(ai["image_prompt"])
                        post_fb(ai["caption"], img)
                        posted_slots.add(i)
                        break

            for i,(h,m) in enumerate(SCENIC_SLOTS):
                if i in posted_scenic_slots:
                    continue
                t = now()
                if t.hour == h and abs(t.minute - m) <= 1:
                    ai = scenic_generate()
                    img = generate_image(ai["image_prompt"])
                    post_fb(ai["caption"], img)
                    posted_scenic_slots.add(i)

            for i,(h,m) in enumerate(CARTOON_SLOTS):
                if i in posted_cartoon_slots:
                    continue
                t = now()
                if t.hour == h and abs(t.minute - m) <= 1:
                    random.shuffle(news_list)
                    for news in news_list:
                        if news["title"] in seen_news:
                            continue
                        seen_news.add(news["title"])
                        ai = cartoon_generate(news["title"], news["desc"])
                        img = generate_image(ai["image_prompt"])
                        post_fb(ai["caption"], img)
                        posted_cartoon_slots.add(i)
                        break

            time.sleep(20)

        except Exception as e:
            log(str(e))
            time.sleep(5)

# ================= RUN =================
if __name__ == "__main__":
    Thread(target=run_server, daemon=True).start()
    scheduler()
