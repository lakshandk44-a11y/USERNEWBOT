# -*- coding: utf-8 -*-

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

TIME_SLOTS = [(6,0),(8,0),(10,45),(12,0),(14,0),(16,0),(18,0),(20,0),(22,0),(23,30)]
SCENIC_SLOTS = [(7,0),(9,0),(10,47),(13,0),(15,15),(17,0),(19,0),(21,0),(22,30),(23,45)]

posted_slots = set()
posted_scenic_slots = set()

def clean_text(text: str) -> str:
    if not text:
        return ""
    try:
        return text.encode("utf-8", "ignore").decode("utf-8")
    except:
        return text

def log(msg):
    print(msg)
    try:
        if DISCORD_WEBHOOK_URL:
            requests.post(DISCORD_WEBHOOK_URL, json={"content": clean_text(msg)})
    except:
        pass

def generate_image(prompt):
    # 🔥 IMPORTANT FIX: force realistic AI image style
    final_prompt = (
        prompt +
        ", ultra realistic, 2050 future prediction, real architecture, "
        "plausible urban design, natural environment, no fantasy, no impossible structures, "
        "photorealistic, high detail"
    )
    return "https://image.pollinations.ai/prompt/" + urllib.parse.quote(final_prompt)

def post_fb(caption, image_url):
    caption = clean_text(caption)

    url = f"https://graph.facebook.com/v20.0/{FB_PAGE_ID}/photos"
    return requests.post(url, data={
        "url": image_url,
        "caption": caption,
        "access_token": FB_ACCESS_TOKEN
    }).json()

def gemini(prompt):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"

    payload = {
        "contents": [{
            "parts": [{"text": prompt}]
        }]
    }

    r = requests.post(url, json=payload)
    text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
    return clean_text(text)

TOPICS = [
    "2050 ශ්‍රී ලංකාවේ අධ්‍යාපනය",
    "2050 ප්‍රවාහනය",
    "2050 සෞඛ්‍යය",
    "2050 කෘෂිකර්මය",
    "2050 බලශක්තිය",
    "2050 ස්මාර්ට් නගර",
    "2050 පරිසරය",
    "2050 සංචාරක කර්මාන්තය",
    "2050 තාක්ෂණය",
    "2050 ජන ජීවිතය"
]

SCENIC_PLACES = [
    "Sigiriya future 2050 Sri Lanka realistic conservation site",
    "Sri Pada eco tourism 2050 smart infrastructure",
    "Galle Fort restored coastal protection 2050",
    "Ruwanwelisaya heritage site modern lighting system",
    "Nuwara Eliya climate adapted agriculture 2050",
    "Yala wildlife reserve AI monitoring system",
    "Dambulla cultural zone sustainable tourism 2050",
    "Polonnaruwa archaeological preservation future tech",
    "Horton Plains eco conservation observation deck",
    "Ella railway smart transport bridge 2050"
]

used = set()

def safe_json(text):
    try:
        text = text.strip()

        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]

        return json.loads(text)
    except:
        return None

def generate_topic():
    topic = random.choice(TOPICS)

    prompt = (
        "Return ONLY valid JSON.\n"
        "No explanation.\n"
        "Language: Sinhala caption required.\n"
        "Format: {\"caption\":\"...\",\"image_prompt\":\"...\"}\n"
        "IMPORTANT: image must be realistic 2050 prediction, no fantasy.\n"
        "Topic: " + topic
    )

    text = gemini(prompt)
    data = safe_json(text)

    if data:
        return data

    return {
        "caption": f"{topic} 🇱🇰 #SriLanka2050",
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
        "Return ONLY valid JSON.\n"
        "Sinhala viral caption required.\n"
        "{\"caption\":\"...\",\"image_prompt\":\"...\"}\n"
        "IMPORTANT: image must be realistic, no sci-fi fantasy.\n"
        "Place: " + place
    )

    text = gemini(prompt)
    data = safe_json(text)

    if data:
        return data

    return {
        "caption": f"{place} 🇱🇰 #SriLanka2050",
        "image_prompt": place
    }

def scheduler():
    global posted_slots, posted_scenic_slots

    while True:
        try:
            for i, (h, m) in enumerate(TIME_SLOTS):
                if i not in posted_slots:
                    t = now()
                    if t.hour == h and abs(t.minute - m) <= 1:
                        data = generate_topic()
                        img = generate_image(data["image_prompt"])
                        post_fb(data["caption"], img)
                        posted_slots.add(i)

            for i, (h, m) in enumerate(SCENIC_SLOTS):
                if i not in posted_scenic_slots:
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
