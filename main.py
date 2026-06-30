import requests
import json
import time
import urllib.parse
from datetime import datetime
import pytz
from flask import Flask
from threading import Thread
import random
import feedparser

# ================= විස්තර =================
FB_PAGE_ID = "1243828092139012"
FB_ACCESS_TOKEN = "EAF40ZBiCgXTQBR8EXNVLqyFZCsWBxESSP7N2ytSTOEMAp2BQ1FvJzS8SVwFB0SwKXmJH8Ww0ZCF8CXWYKZAbzrUtaXWGwZBsSfjRL8P1iZCfN7bM6ZBYZCrUZAE6J4P7smCEK0wrLFgJzhMPJFJPj0ijhlQhnqKkJ2ZBElSHZBlgCMZBXHoGYoVyXsBya5ZBCnHZBZCd7QG7xCtV4f71mQwPh6xZBBZBRAgUMWF2lcKT1IJmQ"
GEMINI_API_KEY = "AQ.Ab8RN6JeHF0PPAGjOnAKkp6MQpVMrmpQ8FJwabdQ7r_Gjd7UUw"
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1521532656825929911/r_p09BIeETgtrGdk3QsdHb5WglQNSqwKrHTWpCtvmA7n-HyTGKhQWZOz65Zpf0OE58iu"

app = Flask('')

@app.route('/')
def home():
    return "🤖 Prompting America Bot is Online!"

def run_flask():
    app.run(host='0.0.0.0', port=8080)

def fetch_top_us_trends():
    """Google News RSS මගින් පුවත් ලබා ගැනීම"""
    rss_url = "https://news.google.com/rss/headlines/section/topic/WORLD?hl=en-US&gl=US&ceid=US:en"
    feed = feedparser.parse(rss_url)
    trends_list = []
    for entry in feed.entries[:10]:
        trends_list.append({"title": entry.title, "description": entry.summary or entry.title})
    return trends_list

def generate_ai_content(news_title, news_desc):
    """Gemini AI මගින් පෝස්ට් එක සකස් කිරීම"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={GEMINI_API_KEY}"
    prompt = f"Title: {news_title}. Desc: {news_desc}. Write a viral FB caption and an AI image prompt in JSON format."
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    try:
        res = requests.post(url, headers={'Content-Type': 'application/json'}, json=payload)
        text = res.json()['candidates'][0]['content']['parts'][0]['text']
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        return json.loads(text)
    except Exception as e:
        print(f"Gemini Error: {e}")
        return {"caption": f"🔥 Latest Update: {news_title}", "image_prompt": news_title}

def get_ai_image_url(prompt):
    """AI පින්තූර ජනනය"""
    encoded_prompt = urllib.parse.quote(prompt)
    return f"[https://image.pollinations.ai/p/](https://image.pollinations.ai/p/){encoded_prompt}?width=1080&height=1080&nologo=true&seed={random.randint(1,1000000)}"

def send_discord_notification(title, desc, img_url=None):
    """Discord දැනුම්දීම"""
    payload = {"embeds": [{"title": title[:250], "description": desc[:4000], "color": 3447003}]}
    if img_url:
        payload["embeds"][0]["image"] = {"url": img_url}
    requests.post(DISCORD_WEBHOOK_URL, json=payload)

def post_to_facebook(message, image_url):
    """Facebook වෙත පින්තූරය පෝස්ට් කිරීම"""
    url = f"[https://graph.facebook.com/v20.0/](https://graph.facebook.com/v20.0/){FB_PAGE_ID}/photos"
    params = {
        'url': image_url,
        'caption': message,
        'access_token': FB_ACCESS_TOKEN
    }
    return requests.post(url, data=params).json()

def job():
    """බොට්ගේ ප්‍රධාන ක්‍රියාවලිය"""
    send_discord_notification("🚀 බොට් පටන් ගත්තා!", "පුවත් සකස් කරමින් පවතී...")
    trends = fetch_top_us_trends()
    if not trends:
        send_discord_notification("⚠️ දෝෂයක්!", "පුවත් ලැබුණේ නැත.")
        return
        
    for i, trend in enumerate(trends):
        try:
            content = generate_ai_content(trend['title'], trend['description'])
            img = get_ai_image_url(content['image_prompt'])
            fb = post_to_facebook(content['caption'], img)
            
            if 'id' in fb:
                send_discord_notification(f"✅ පෝස්ට් {i+1} සාර්ථකයි!", content['caption'][:100], img)
            else:
                send_discord_notification(f"❌ පෝස්ට් {i+1} අසාර්ථකයි!", str(fb))
            
            time.sleep(120)
        except Exception as e:
            send_discord_notification("❌ Error", str(e))

if __name__ == "__main__":
    Thread(target=run_flask).start()
    while True:
        # දිනකට වරක් ක්‍රියාත්මක වීම (තත්පර 86400)
        job()
        time.sleep(86400)
