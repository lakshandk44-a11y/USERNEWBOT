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
TIME_SLOTS = [(6,0),(8,0),(10,0),(12,0),(14,0),(16,0),(18,0),(20,0),(22,0),(23,30)]
SCENIC_SLOTS = [(7,0),(9,0),(11,0),(13,0),(15,15),(17,0),(19,0),(21,0),(22,30),(23,45)]
CARTOON_SLOTS = [(23,37),(10,30),(13,30),(16,30),(19,30)]

posted_slots = set()
posted_scenic_slots = set()
posted_cartoon_slots = set()
seen_comments = set()

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

# ================= NEWS =================
def get_news():
    try:
        feed = feedparser.parse("https://news.google.com/rss/headlines/section/topic/WORLD?hl=en-US&gl=US&ceid=US:en")
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

        return json.loads(text)
    except:
        return {"caption":title,"image_prompt":"news illustration"}

# ================= CARTOON AI (DYNAMIC) =================
def cartoon_generate(title, desc):
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"

        text = (title + " " + desc).lower()

        if any(k in text for k in ["war","attack","military","bomb"]):
            character = "a frightened soldier in uniform"
        elif any(k in text for k in ["money","bank","stock","economy","crash"]):
            character = "a stressed businessman in suit"
        elif any(k in text for k in ["president","election","government","politics"]):
            character = "a shocked politician at a news desk"
        elif any(k in text for k in ["sports","cricket","football","match"]):
            character = "an exhausted athlete reacting emotionally"
        else:
            character = "a terrified news reporter"

        prompt = f"""
Turn news into editorial cartoon.

NEWS:
{title}
{desc}

Character MUST be:
{character}

Return JSON:
{{"caption":"simple viral caption","image_prompt":"ignored"}}
"""

        r = requests.post(url, json={"contents":[{"parts":[{"text":prompt}]}]})
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"]

        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]

        result = json.loads(text)

        result["image_prompt"] = f"""
A grotesque hand-drawn editorial cartoon. {character} in extreme close-up, exaggerated facial expression, sitting at news desk with microphone. thick ink sketch style, minimal background, sickly green tone. News ticker about: {title}
"""

        return result
    except:
        return {"caption":"Cartoon news","image_prompt":"editorial cartoon sketch"}

# ================= SCENIC =================
def scenic_generate():
    place = random.choice(SCENIC_PLACES)
    return {
        "caption": f"✨ {place}\n#Travel",
        "image_prompt": f"Ultra realistic cinematic photo of {place}"
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

# ================= CARTOON SCHEDULER =================
def cartoon_scheduler():
    global posted_cartoon_slots
    while True:
        try:
            for i,(h,m) in enumerate(CARTOON_SLOTS):
                if i in posted_cartoon_slots:
                    continue
                if now().hour==h and now().minute==m:

                    news = random.choice(get_news())
                    data = cartoon_generate(news["title"], news["desc"])

                    img = generate_image(data["image_prompt"])
                    res = post_fb(data["caption"], img)

                    if "id" in res:
                        posted_cartoon_slots.add(i)
                        log(f"CARTOON SLOT {i+1}")

            time.sleep(20)
        except Exception as e:
            log(str(e))
            time.sleep(5)

# ================= MAIN SCHEDULER =================
def scheduler():
    global posted_slots, posted_scenic_slots

    while True:
        try:
            if reset_time():
                posted_slots=set()
                posted_scenic_slots=set()

            # NEWS
            for i,(h,m) in enumerate(TIME_SLOTS):
                if i in posted_slots: continue
                if now().hour==h and now().minute==m:
                    news=random.choice(get_news())
                    ai=ai_generate(news["title"],news["desc"])
                    img=generate_image(ai["image_prompt"])
                    res=post_fb(ai["caption"],img)
                    if "id" in res:
                        posted_slots.add(i)

            # SCENIC
            for i,(h,m) in enumerate(SCENIC_SLOTS):
                if i in posted_scenic_slots: continue
                if now().hour==h and now().minute==m:
                    sc=scenic_generate()
                    img=generate_image(sc["image_prompt"])
                    res=post_fb(sc["caption"],img)
                    if "id" in res:
                        posted_scenic_slots.add(i)

            time.sleep(20)

        except Exception as e:
            log(str(e))
            time.sleep(5)

# ================= START =================
if __name__=="__main__":
    Thread(target=run_server,daemon=True).start()
    Thread(target=cartoon_scheduler,daemon=True).start()
    scheduler()
