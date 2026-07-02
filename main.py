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
CARTOON_SLOTS = [(7,15),(12,15),(13,30),(16,30),(19,30)]

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

        result["caption"] = apply_monetization(make_viral_caption(result["caption"]))

        return result

    except:
        return {
            "caption": apply_monetization(make_viral_caption("News Update")),
            "image_prompt": "news illustration"
        }

# ================= 🔥 VIRAL CAPTION SYSTEM =================
def make_viral_caption(text):
    hooks = ["🚨 BREAKING:", "😱 SHOCKING:", "🔥 JUST IN:", "⚠️ ALERT:"]
    suffix = [
        "People are reacting strongly!",
        "This is going viral right now!",
        "You won't believe this!",
        "What is your opinion?"
    ]
    return f"{random.choice(hooks)} {text}\n\n{random.choice(suffix)}"


# ================= CARTOON AI (IMF-STYLE FULL UPGRADE ONLY HERE) =================
def cartoon_generate(title, desc):
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"

        text = (title + " " + desc).lower()

        # ================= CATEGORY DETECTION =================
        if any(k in text for k in ["war","attack","military","bomb","conflict"]):
            category = "war"
            metaphor = "two forces struggling over a nation-shaped object"
            characters = "soldiers in opposing sides"
            background = "battlefield chaos with smoke"
        elif any(k in text for k in ["money","bank","stock","economy","loan","imf","debt"]):
            category = "finance"
            metaphor = "financial institutions squeezing a country shaped figure"
            characters = "IMF suited figure and local representative"
            background = "global finance charts and money flow"
        elif any(k in text for k in ["politics","government","president","election"]):
            category = "politics"
            metaphor = "political leaders controlling a puppet nation"
            characters = "politicians in suits with labels"
            background = "parliament or press room"
        elif any(k in text for k in ["sports","cricket","football"]):
            category = "sports"
            metaphor = "teams fighting for a trophy shaped symbol"
            characters = "athletes in action"
            background = "stadium crowd"
        else:
            category = "general"
            metaphor = "media influencing public perception"
            characters = "news reporter and crowd"
            background = "breaking news studio"

        # ================= IMF STYLE PROMPT =================
        prompt = f"""
A detailed editorial cartoon, stylistically identical to structured political cartoons.

NEWS:
{title}
{desc}

CATEGORY:
{category}

CHARACTERS:
{characters}

MAIN METAPHOR:
{metaphor}

BACKGROUND:
{background}

VISUAL RULES:
- Editorial cartoon style
- Symbolic storytelling instead of literal scene
- Bold ink outlines
- Flat color palette
- Strong emotional exaggeration
- Newspaper political illustration style

IMPORTANT:
Convert news into symbolic cartoon composition like IMF-style editorial metaphor illustrations.

Return JSON:
{{"caption":"viral caption","image_prompt":"detailed prompt"}}
"""

        r = requests.post(url, json={"contents":[{"parts":[{"text":prompt}]}]})
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"]

        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]

        result = json.loads(text)

        caption = make_viral_caption(result["caption"])
        caption = apply_monetization(caption)

        tags = {
            "war": "#War #BreakingNews #World",
            "finance": "#Economy #IMF #Finance #Breaking",
            "politics": "#Politics #News #Breaking",
            "sports": "#Sports #Live",
            "general": "#News #Viral"
        }

        caption += "\n\n" + tags.get(category, "#News")

        result["caption"] = caption

        return result

    except:
        return {
            "caption": apply_monetization(make_viral_caption("Breaking News")) + "\n\n#News",
            "image_prompt": "editorial cartoon illustration"
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
