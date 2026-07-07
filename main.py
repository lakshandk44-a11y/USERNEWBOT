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
MONETIZATION_MODE = "off"

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
TIME_SLOTS = [(6,0),(8,0),(10,0),(11,42),(14,0),(16,0),(18,0),(20,0),(22,0),(23,30)]
SCENIC_SLOTS = [(7,0),(9,0),(11,0),(13,0),(15,15),(17,0),(19,0),(21,0),(22,30),(23,45)]
CARTOON_SLOTS = [(7,15),(12,15),(13,26),(16,30),(19,30)]

posted_slots = set()
posted_scenic_slots = set()
posted_cartoon_slots = set()
seen_news_regular = set()
seen_news_cartoon = set()

# ================= HOLIDAY CONFIG =================
HOLIDAYS = {
    "07-04": "🎆 Happy Independence Day, America!",
    "10-31": "🎃 Happy Halloween! Stay spooky!",
    "12-25": "🎄 Merry Christmas! Wishing you joy and peace!",
    "01-01": "🎉 Happy New Year! Welcome 2026!",
    "02-14": "💘 Happy Valentine's Day! Spread the love!",
    "05-12": "👩 Happy Mother's Day!",
    "06-21": "👨 Happy Father's Day!",
}

holiday_posted_today = False

def holiday_generate(holiday_title):
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"

        prompt = f"""
Generate a beautiful, artistic, cinematic greeting post for this holiday:

{holiday_title}

Rules:
- Caption must be warm, heartfelt, and viral-friendly
- Dark, moody, cinematic aesthetic
- Unique artistic style — not generic stock photo

Return ONLY JSON:
{{"caption":"...","image_prompt":"..."}}
"""

        r = requests.post(url, json={"contents":[{"parts":[{"text":prompt}]}]})
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"]

        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1:
            text = text[start:end+1]

        result = json.loads(text.strip())
        return result
    except:
        return {
            "caption": holiday_title,
            "image_prompt": f"Dark cinematic moody artistic illustration, {holiday_title}, highly detailed, dramatic lighting"
        }

# ================= AUTO REPLY TO COMMENTS =================
last_replied_comment_ids = set()

def get_recent_comments():
    try:
        url = f"https://graph.facebook.com/v20.0/{FB_PAGE_ID}/feed?fields=id,comments{{id,message,created_time}}&access_token={FB_ACCESS_TOKEN}"
        r = requests.get(url)
        data = r.json()

        comments = []
        for post in data.get("data", []):
            if "comments" in post:
                for comment in post["comments"].get("data", []):
                    comments.append(comment)
        return comments
    except:
        return []

def auto_reply_to_comment(comment_id, comment_text):
    try:
        prompt = f"""
Reply to this Facebook comment in a friendly, engaging, and natural way.
Keep it short (1-2 sentences). Be helpful and warm.

Comment: {comment_text}

Reply:
"""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
        r = requests.post(url, json={"contents":[{"parts":[{"text":prompt}]}]})
        reply_text = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()

        reply_url = f"https://graph.facebook.com/v20.0/{comment_id}/replies"
        requests.post(reply_url, data={
            "message": reply_text,
            "access_token": FB_ACCESS_TOKEN
        })
        log(f"Replied to comment {comment_id}: {reply_text}")
    except:
        pass

def process_auto_replies():
    global last_replied_comment_ids
    comments = get_recent_comments()
    for comment in comments:
        cid = comment["id"]
        if cid not in last_replied_comment_ids:
            last_replied_comment_ids.add(cid)
            auto_reply_to_comment(cid, comment.get("message", ""))

# ================= SCENIC DAILY SYSTEM =================
scenic_daily_places = []
scenic_last_date = None
scenic_posted_places_today = set()

# ================= NEWS CACHE =================
news_cache = []
news_last_fetch = 0

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
    global news_cache, news_last_fetch
    try:
        if time.time() - news_last_fetch > 300:
            feed = feedparser.parse(
                "https://news.google.com/rss/headlines/section/topic/WORLD?hl=en-US&gl=US&ceid=US:en"
            )
            news_cache = [{"title":e.title,"desc":getattr(e,"summary",e.title)} for e in feed.entries[:20]]
            news_last_fetch = time.time()
        return news_cache
    except:
        return news_cache if news_cache else []

# ================= AI NEWS =================
def ai_generate(title, desc):
    for attempt in range(3):
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
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]
            start = text.find('{')
            end = text.rfind('}')
            if start != -1 and end != -1:
                text = text[start:end+1]

            result = json.loads(text.strip())
            result["caption"] = apply_monetization(result["caption"])
            return result

        except Exception as e:
            log(f"ai_generate attempt {attempt+1} failed: {str(e)}")
            time.sleep(3)

    return {
        "caption": apply_monetization("News Update"),
        "image_prompt": "news illustration"
    }

# ================= CARTOON =================
def cartoon_generate(title, desc):
    for attempt in range(3):
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
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]
            start = text.find('{')
            end = text.rfind('}')
            if start != -1 and end != -1:
                text = text[start:end+1]

            result = json.loads(text.strip())

            caption = f"""🖼 {result["caption"]}

📌 {title}

💬 What do you think?

#BreakingNews #Cartoon #Viral #Trending
"""

            result["caption"] = apply_monetization(caption.strip())
            return result

        except Exception as e:
            log(f"cartoon_generate attempt {attempt+1} failed: {str(e)}")
            time.sleep(3)

    return {
        "caption": apply_monetization("News Update"),
        "image_prompt": "editorial cartoon"
    }

# ================= SCENIC DAILY AI SYSTEM (UPGRADED) =================
def get_daily_scenic_pool():
    global scenic_daily_places, scenic_last_date

    today = now().date()

    if scenic_last_date != today or len(scenic_daily_places) == 0:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"

            prompt = """
Generate 10 UNIQUE viral scenic travel destinations for today.

Rules:
- Must be real-world places from AROUND THE WORLD
- Must be highly photogenic and breathtaking
- Must be diverse — different countries, continents, and types (mountains, beaches, cities, forests, deserts, waterfalls, historical sites, etc.)
- Do NOT repeat places that were suggested on previous days
- Each place must be uniquely beautiful and iconic in its own way
- Include the country name for each place

Return ONLY JSON array:
["Place Name, Country", "Place Name, Country", ...]
"""

            r = requests.post(url, json={"contents":[{"parts":[{"text":prompt}]}]})
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]

            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]
            start = text.find('[')
            end = text.rfind(']')
            if start != -1 and end != -1:
                text = text[start:end+1]

            scenic_daily_places = json.loads(text.strip())
            scenic_last_date = today
            scenic_posted_places_today.clear()

        except:
            scenic_daily_places = [
                "Santorini, Greece",
                "Banff National Park, Canada",
                "Maldives Beach",
                "Northern Lights, Iceland",
                "Mount Fuji, Japan",
                "Plitvice Lakes, Croatia",
                "Marble Caves, Chile",
                "Bora Bora, French Polynesia",
                "Taj Mahal, India",
                "Milford Sound, New Zealand"
            ]
            scenic_last_date = today
            scenic_posted_places_today.clear()

    return scenic_daily_places

def scenic_generate():
    pool = get_daily_scenic_pool()

    available = [p for p in pool if p not in scenic_posted_places_today]

    if not available:
        scenic_posted_places_today.clear()
        available = pool

    place = random.choice(available)
    scenic_posted_places_today.add(place)

    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"

        prompt_text = f"""
Generate a SINGLE, EXTREMELY DETAILED, ULTRA-HIGH-QUALITY image prompt for generating a stunning hyper-realistic photograph of this specific destination.

Destination: {place}

CRITICAL RULES (follow ALL strictly):
- Must be the absolute HIGHEST QUALITY image prompt possible — describe EVERY visual detail
- Hyper-realistic, ultra-HD, cinematic quality, award-winning National Geographic style photography
- Describe the unique natural beauty, colors, lighting, atmosphere, textures, and mood specific to {place}
- Include professional camera metadata: 32k resolution, extreme sharpness, natural film grain, Phase One IQ4 150MP camera, 35mm prime lens at f/11, 1/160s shutter, ISO 100
- Cinematic golden hour lighting (or blue hour if that fits better) with long dramatic shadows, volumetric haze, god rays where applicable
- Photographed in stunning natural light that best captures the essence of {place}
- Fujifilm Velvia film simulation for rich, vibrant, natural colors
- Professional color grading, master-level composition, rule of thirds
- Include specific weather/seasonal conditions that make {place} look its absolute best
- Do NOT mention any other place names — ONLY describe {place}
- Make it UNIQUE to {place} — not a generic description that could fit anywhere
- End with: "A flawless, pristine, highly photorealistic masterpiece with breathtaking detail"

Return ONLY a single plain text string (NO JSON, NO markdown formatting, NO code blocks — just the prompt text):
"""

        r = requests.post(url, json={"contents":[{"parts":[{"text":prompt_text}]}]})
        image_prompt = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()

        if "```" in image_prompt:
            image_prompt = image_prompt.split("```")[0].strip()

        caption_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"

        caption_prompt = f"""
Create a short, viral, engaging Facebook caption for this travel destination.

Destination: {place}

Rules:
- 3-4 lines maximum
- Include a sense of wonder and adventure
- Ask an engaging question at the end
- Include relevant hashtags (4-5 max)
- Make it feel unique to {place} — not generic

Return ONLY the caption text (no JSON, no markdown):
"""

        r2 = requests.post(caption_url, json={"contents":[{"parts":[{"text":caption_prompt}]}]})
        caption_text = r2.json()["candidates"][0]["content"]["parts"][0]["text"].strip()

        if "```" in caption_text:
            caption_text = caption_text.split("```")[0].strip()

    except:
        image_prompt = (
            f"A hyper-realistic, award-winning National Geographic photograph of {place}. "
            f"Ultra-HD, 32k resolution, extreme sharpness, natural film grain. "
            f"Shot on a Phase One IQ4 150MP camera with a 35mm prime lens at f/11, 1/160s, ISO 100. "
            f"Cinematic golden hour lighting with long dramatic shadows, volumetric haze. "
            f"Fujifilm Velvia film simulation for rich vibrant natural colors. "
            f"Professional color grading, master-level composition. "
            f"Breathtaking detail in every element. "
            f"A flawless, pristine, highly photorealistic masterpiece."
        )
        caption_text = f"✨ {place}\n\n🌍 Nature's masterpiece awaits.\n\nHave you ever dreamed of visiting here?"

    return {
        "caption": caption_text,
        "image_prompt": image_prompt
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
    global posted_slots, posted_scenic_slots, posted_cartoon_slots, seen_news_regular, seen_news_cartoon, holiday_posted_today, last_replied_comment_ids

    while True:
        try:
            if reset_time():
                posted_slots=set()
                posted_scenic_slots=set()
                posted_cartoon_slots=set()
                seen_news_regular=set()
                seen_news_cartoon=set()
                holiday_posted_today = False
                last_replied_comment_ids=set()

            # ===== AUTO REPLY TO COMMENTS =====
            process_auto_replies()

            # ===== HOLIDAY POST =====
            today_str = now().strftime("%m-%d")
            if today_str in HOLIDAYS and not holiday_posted_today and now().hour == 7 and now().minute < 2:
                holiday_title = HOLIDAYS[today_str]
                holiday_data = holiday_generate(holiday_title)
                img = generate_image(holiday_data["image_prompt"])
                post_fb(holiday_data["caption"], img)
                holiday_posted_today = True
                log(f"Holiday post uploaded: {holiday_title}")

            # ===== REGULAR NEWS POSTS =====
            news_list = get_news()

            for i,(h,m) in enumerate(TIME_SLOTS):
                if i in posted_slots:
                    continue
                t = now()
                if t.hour == h and t.minute == m:
                    random.shuffle(news_list)
                    posted = False
                    for news in news_list:
                        if news["title"] not in seen_news_regular:
                            seen_news_regular.add(news["title"])
                            ai = ai_generate(news["title"], news["desc"])
                            img = generate_image(ai["image_prompt"])
                            result = post_fb(ai["caption"], img)
                            if "id" in result:
                                posted_slots.add(i)
                                posted = True
                            break
                    if not posted and news_list:
                        news = random.choice(news_list)
                        ai = ai_generate(news["title"], news["desc"])
                        img = generate_image(ai["image_prompt"])
                        result = post_fb(ai["caption"], img)
                        if "id" in result:
                            posted_slots.add(i)

            # ===== SCENIC POSTS =====
            for i,(h,m) in enumerate(SCENIC_SLOTS):
                if i in posted_scenic_slots:
                    continue
                t = now()
                if t.hour == h and t.minute == m:
                    ai = scenic_generate()
                    img = generate_image(ai["image_prompt"])
                    result = post_fb(ai["caption"], img)
                    if "id" in result:
                        posted_scenic_slots.add(i)

            # ===== CARTOON POSTS =====
            for i,(h,m) in enumerate(CARTOON_SLOTS):
                if i in posted_cartoon_slots:
                    continue
                t = now()
                if t.hour == h and t.minute == m:
                    random.shuffle(news_list)
                    posted = False
                    for news in news_list:
                        if news["title"] not in seen_news_cartoon:
                            seen_news_cartoon.add(news["title"])
                            ai = cartoon_generate(news["title"], news["desc"])
                            img = generate_image(ai["image_prompt"])
                            result = post_fb(ai["caption"], img)
                            if "id" in result:
                                posted_cartoon_slots.add(i)
                                posted = True
                            break
                    if not posted and news_list:
                        news = random.choice(news_list)
                        ai = cartoon_generate(news["title"], news["desc"])
                        img = generate_image(ai["image_prompt"])
                        result = post_fb(ai["caption"], img)
                        if "id" in result:
                            posted_cartoon_slots.add(i)

            time.sleep(20)

        except Exception as e:
            log(str(e))
            time.sleep(5)

# ================= RUN =================
if __name__ == "__main__":
    Thread(target=run_server, daemon=True).start()
    scheduler()
