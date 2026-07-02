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
CARTOON_SLOTS = [(7,50),(10,30),(13,30),(16,30),(19,30)]

posted_slots = set()
posted_scenic_slots = set()
posted_cartoon_slots = set()
seen_news = set()

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
        return text + f"\n\n👉 Recommended Offer: {link}"

    if MONETIZATION_MODE == "sponsor":
        sponsor = random.choice(SPONSORS)
        return text + f"\n\nSponsored by {sponsor}"

    return text


# ================= 🔥 VIRAL CAPTION UPGRADE (ONLY ADDITION) =================
def make_viral_caption(text):
    hooks = [
        "🚨 BREAKING:",
        "😱 SHOCKING:",
        "⚠️ ALERT:",
        "🔥 JUST IN:",
        "💥 VIRAL UPDATE:"
    ]
    suffix = [
        "People are reacting strongly!",
        "This is going viral right now!",
        "You won't believe this!",
        "Social media is exploding!",
        "What do you think?"
    ]
    return f"{random.choice(hooks)} {text}\n\n{random.choice(suffix)}"


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

        # 🔥 VIRAL CAPTION APPLIED
        caption = make_viral_caption(result["caption"])
        result["caption"] = apply_monetization(caption)

        return result

    except:
        return {
            "caption": apply_monetization(make_viral_caption("News Update")),
            "image_prompt": "news illustration"
        }

# ================= CARTOON AI =================
def cartoon_generate(title, desc):
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"

        text = (title + " " + desc).lower()

        if any(k in text for k in ["war","attack","military","bomb"]):
            character = "terrified soldier screaming in chaos"
        elif any(k in text for k in ["money","bank","stock","economy","crash"]):
            character = "panic-stricken businessman at collapsing stock market screen"
        elif any(k in text for k in ["president","government","politics"]):
            character = "shocked politician sweating under press lights"
        elif any(k in text for k in ["sports","cricket","football"]):
            character = "exhausted athlete collapsing after dramatic moment"
        else:
            character = "horrified news reporter in breaking news studio"

        prompt = f"""
Create grotesque editorial cartoon style news illustration.

NEWS:
{title}
{desc}

Character:
{character}

Return JSON:
{{"caption":"viral caption","image_prompt":"detailed prompt"}}
"""

        r = requests.post(url, json={"contents":[{"parts":[{"text":prompt}]}]})
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"]

        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]

        result = json.loads(text)

        # 🔥 VIRAL CAPTION APPLIED
        caption = make_viral_caption(result["caption"])
        result["caption"] = apply_monetization(caption)

        return result

    except:
        return {
            "caption": apply_monetization(make_viral_caption("Cartoon News")),
            "image_prompt": "editorial cartoon breaking news illustration"
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

# ================= SCHEDULER (UNCHANGED) =================
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
                    place = random.choice(SCENIC_PLACES)
                    img = generate_image("Ultra realistic cinematic photo of " + place)
                    post_fb("✨ " + place, img)
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
