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
    "https://example.com/deal1",
    "https://example.com/deal2",
    "https://example.com/deal3"
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
CARTOON_SLOTS = [(9,59),(10,30),(13,30),(16,30),(19,30)]

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
        return text + f"\n\n👉 Recommended: {link}"

    if MONETIZATION_MODE == "sponsor":
        sponsor = random.choice(SPONSORS)
        return f"{text}\n\nSponsored by {sponsor}"

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
            "caption": apply_monetization(title),
            "image_prompt": "news illustration"
        }

# ================= CARTOON AI (UPDATED STYLE SYSTEM) =================
def cartoon_generate(title, desc):
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"

        text = (title + " " + desc).lower()

        # dynamic character logic (unchanged idea, improved variety)
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

        # 🔥 YOUR STYLE PROMPT (ENHANCED + DYNAMIC)
        prompt = f"""
Create a grotesque, highly detailed cartoon illustration in a hyper-exaggerated editorial news style.

NEWS:
{title}
{desc}

CHARACTER:
{character}

STYLE REQUIREMENTS:
- Extreme facial expression (wide eyes, fear, shock)
- Close-up framing like breaking news reaction shot
- Seated at cluttered news desk with microphone
- News ticker visible with related text about the event
- Desaturated, sickly green/grey tone palette
- Thick bold ink line art, editorial cartoon style
- Dramatic lighting, high emotional intensity

IMPORTANT STYLE REFERENCE:
"A grotesque, highly detailed cartoon illustration in a hyper-exaggerated animation style. Close-up terrified expression, news desk, microphone, breaking news ticker, sickly green tone, thick line art, extreme emotion."

Return JSON only:
{{"caption":"viral caption","image_prompt":"detailed prompt"}}
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
            "caption": apply_monetization("Cartoon News"),
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

# ================= RUNNER (UNCHANGED LOGIC) =================
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

            # NEWS
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
                        res = post_fb(ai["caption"], img)

                        if "id" in res:
                            posted_slots.add(i)
                        break

            # SCENIC
            for i,(h,m) in enumerate(SCENIC_SLOTS):
                if i in posted_scenic_slots:
                    continue

                t = now()
                if t.hour == h and abs(t.minute - m) <= 1:

                    place = random.choice(SCENIC_PLACES)
                    img = generate_image("Ultra realistic cinematic photo of " + place)
                    res = post_fb("✨ " + place, img)

                    if "id" in res:
                        posted_scenic_slots.add(i)

            # CARTOON (UNCHANGED LOGIC)
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
                        res = post_fb(ai["caption"], img)

                        if "id" in res:
                            posted_cartoon_slots.add(i)
                        break

            time.sleep(20)

        except Exception as e:
            log(str(e))
            time.sleep(5)

# ================= START =================
if __name__ == "__main__":
    Thread(target=run_server, daemon=True).start()
    scheduler()
