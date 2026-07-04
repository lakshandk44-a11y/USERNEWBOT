
import requests
import json
import time
import urllib.parse
import random
import pytz
import os
from datetime import datetime
from flask import Flask
from threading import Thread

FB_PAGE_ID = os.getenv("FB_PAGE_ID")
FB_ACCESS_TOKEN = os.getenv("FB_ACCESS_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot Running"

def run_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

tz = pytz.timezone("Asia/Colombo")

def now():
    return datetime.now(tz)

TIME_SLOTS = [(6,0),(8,0),(10,13),(12,0),(14,0),(16,0),(18,0),(20,0),(22,0),(23,30)]
SCENIC_SLOTS = [(7,0),(9,0),(10,15),(13,0),(15,15),(17,0),(19,0),(21,0),(22,30),(23,45)]

posted_slots = set()
posted_scenic_slots = set()

def log(msg):
    print(msg)
    try:
        if DISCORD_WEBHOOK_URL:
            requests.post(DISCORD_WEBHOOK_URL, json={"content": msg})
    except:
        pass

def generate_image(prompt):
    return "https://image.pollinations.ai/prompt/" + urllib.parse.quote(prompt)

def post_fb(caption, image_url):
    url = f"https://graph.facebook.com/v20.0/{FB_PAGE_ID}/photos"
    return requests.post(url, data={
        "url": image_url,
        "caption": caption,
        "access_token": FB_ACCESS_TOKEN
    }).json()

def gemini(prompt):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    r = requests.post(url, json={"contents":[{"parts":[{"text":prompt}]}]})
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]

TOPICS = [
    "2050 à¶¯à·“ à·à·Šâ€à¶»à·“ à¶½à¶‚à¶šà·à·€à·š à¶…à¶°à·Šâ€à¶ºà·à¶´à¶±à¶º",
    "2050 à¶¯à·“ à¶´à·Šâ€à¶»à·€à·à·„à¶±à¶º",
    "2050 à¶¯à·“ à·ƒà·žà¶›à·Šâ€à¶ºà¶º",
    "2050 à¶¯à·“ à¶šà·˜à·‚à·’à¶šà¶»à·Šà¶¸à¶º",
    "2050 à¶¯à·“ à¶¶à¶½à·à¶šà·Šà¶­à·’à¶º",
    "2050 à¶¯à·“ à·ƒà·Šà¶¸à·à¶»à·Šà¶§à·Š à¶±à¶œà¶»",
    "2050 à¶¯à·“ à¶´à¶»à·’à·ƒà¶»à¶º",
    "2050 à¶¯à·“ à·ƒà¶‚à¶ à·à¶»à¶š à¶šà¶»à·Šà¶¸à·à¶±à·Šà¶­à¶º",
    "2050 à¶¯à·“ à¶­à·à¶šà·Šà·‚à¶«à¶º",
    "2050 à¶¯à·“ à¶¢à¶± à¶¢à·“à·€à·’à¶­à¶º"
]

SCENIC_PLACES = [
    "Sigiriya futuristic 2050 Sri Lanka",
    "Sri Pada future smart city",
    "Galle Fort cyber future",
    "Ruwanwelisaya hologram glow",
    "Nuwara Eliya eco 2050",
    "Yala AI wildlife reserve",
    "Dambulla future lights",
    "Polonnaruwa restored 2050",
    "Horton Plains sky deck",
    "Ella sky train bridge"
]

used = set()

def generate_topic():
    topic = random.choice(TOPICS)
    prompt = (
        "Create viral Facebook post about Sri Lanka 2050.\n"
        "Topic: " + topic + "\n"
        "Return JSON with keys caption and image_prompt in Sinhala."
    )
    try:
        text = gemini(prompt)
        if "json" in text:
            text = text.split("json")[-1]
        return json.loads(text)
    except:
        return {
            "caption": topic + " #SriLanka2050",
            "image_prompt": topic
        }

def generate_scenic():
    global used
    available = [p for p in SCENIC_PLACES if p not in used]
    if not available:
        used.clear()
        available = SCENIC_PLACES

    place = random.choice(available)
    used.add(place)

    prompt = (
        "Create Sri Lanka 2050 scenic post.\n"
        "Place: " + place + "\n"
        "Return JSON caption and image_prompt in Sinhala."
    )

    try:
        text = gemini(prompt)
        if "json" in text:
            text = text.split("json")[-1]
        return json.loads(text)
    except:
        return {
            "caption": place + " #SriLanka2050",
            "image_prompt": place
        }

def scheduler():
    global posted_slots, posted_scenic_slots

    while True:
        try:
            for i,(h,m) in enumerate(TIME_SLOTS):
                if i in posted_slots:
                    continue
                t = now()
                if t.hour == h and abs(t.minute - m) <= 1:
                    data = generate_topic()
                    img = generate_image(data["image_prompt"])
                    post_fb(data["caption"], img)
                    posted_slots.add(i)

            for i,(h,m) in enumerate(SCENIC_SLOTS):
                if i in posted_scenic_slots:
                    continue
                t = now()
                if t.hour == h and abs(t.minute - m) <= 1:
                    data = generate_scenic()
                    img = generate_image(data["image_prompt"])
                    post_fb(data["caption"], img)
                    posted_scenic_slots.add(i)

            time.sleep(20)

        except Exception as e:
            log(str(e))
            time.sleep(5)

if __name__ == "__main__":
    Thread(target=run_server, daemon=True).start()
    scheduler()
