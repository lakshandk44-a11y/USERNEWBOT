import requests
import json
import time
import urllib.parse
from datetime import datetime
import pytz
from flask import Flask
from threading import Thread

# ================= 1. ඔයාගේ සියලුම විස්තර (KEYS & IDS) =================
FB_PAGE_ID = "1243828092139012"
FB_ACCESS_TOKEN = "EAF40ZBiCgXTQBR6Gn58BUa62mZBKZB9HpCfUiEHDahWC0YyaWk0AR5ru9ZASUODhqpZAwKHwCI2nl6rXx3e7E29CZAMUVWqqYrikTWqpHZAgE1b9G8zSQn40KBlnOTLpcpXZC8HuU6pd5Pw2mZBjaf0WQdkTkmV8OUIhZBRm2wrDHhWtZAZA4VEzbXNM3vsZCLBJRWlVXsniNG3UgdODD6TpxVu08r2FQOq3OMmUKbwKD"
NEWS_API_KEY = "1c45116489b84fad981d82235f306a33"
GEMINI_API_KEY = "AQ.Ab8RN6JeHF0PPAGjOnAKkp6MQpVMrmpQ8FJwabdQ7r_Gjd7UUw"

# ඔයා එවපු අලුත්ම DISCORD WEBHOOK URL එක මෙන්න 👇
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1521532656825929911/r_p09BIeETgtrGdk3QsdHb5WglQNSqwKrHTWpCtvmA7n-HyTGKhQWZOz65Zpf0OE58iu"
# =====================================================================

app = Flask('')

@app.route('/')
def home():
    return "🤖 Prompting America Bot is Online and Running 24/7 on Render VPS!"

def run_flask():
    app.run(host='0.0.0.0', port=8080)

def get_us_time():
    """ ඇමරිකාවේ (New York/EST) වත්මන් වෙලාව ලබා ගැනීම """
    us_tz = pytz.timezone('America/New_York')
    return datetime.now(us_tz)

def generate_ai_content(news_title, news_desc):
    """ Gemini AI එක ලවා නිවුස් එකට ගැලපෙන කැප්ෂන් එකක් සහ ඉමේජ් ප්‍රොම්ප්ට් එකක් හැදීම """
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={GEMINI_API_KEY}"
    
    prompt = f"""
    You are the manager of the Facebook page 'Prompting America'. 
    Analyze this US Trending News:
    Title: {news_title}
    Description: {news_desc}
    
    Tasks:
    1. Write an engaging, viral Facebook caption in English with relevant emojis and hashtags. Do not use generic corporate language.
    2. Write a highly detailed AI Image Generation prompt (1 sentence) to generate a cinematic, realistic 4K photo representing this news.
    
    Provide your response strictly in the following JSON format:
    {{
        "caption": "your facebook caption here",
        "image_prompt": "your image generation prompt here"
    }}
    """
    
    headers = {'Content-Type': 'application/json'}
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    
    try:
        res = requests.post(url, headers=headers, json=payload)
        response_text = res.json()['candidates'][0]['content']['parts'][0]['text']
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0].strip()
        return json.loads(response_text)
    except Exception as e:
        return {
            "caption": f"🔥 TRENDING NOW IN US:\n\n{news_title}\n\n#PromptingAmerica #USNews",
            "image_prompt": f"Cinematic realistic photo representing: {news_title}"
        }

def get_ai_image_url(prompt):
    """ Pollinations AI එක හරහා පින්තූරයේ ලින්ක් එක සෑදීම """
    encoded_prompt = urllib.parse.quote(prompt)
    return f"[https://image.pollinations.ai/p/](https://image.pollinations.ai/p/){encoded_prompt}?width=1080&height=1080&nologo=true"

def fetch_top_us_trends():
    """ US වල මේ වෙලාවේ තියෙන Top News 10ක් ලබා ගැනීම """
    url = f"[https://newsapi.org/v2/top-headlines?country=us&pageSize=10&apiKey=](https://newsapi.org/v2/top-headlines?country=us&pageSize=10&apiKey=){NEWS_API_KEY}"
    try:
        response = requests.get(url)
        articles = response.json().get("articles", [])
        trends_list = []
        for art in articles:
            if art.get("title") and art.get("description"):
                trends_list.append({"title": art["title"], "description": art["description"]})
        return trends_list
    except Exception as e:
        return []

def send_discord_notification(title, desc, img_url=None):
    """ Discord එකට Notification එකක් යැවීම """
    payload = {
        "embeds": [{
            "title": title,
            "description": desc,
            "color": 3447003,
            "timestamp": datetime.utcnow().isoformat()
        }]
    }
    if img_url:
        payload["embeds"][0]["image"] = {"url": img_url}
    try:
        requests.post(DISCORD_WEBHOOK_URL, json=payload)
    except Exception as e:
        print("Discord Error:", e)

def post_to_facebook(message, image_url):
    """ ෆේස්බුක් පේජ් එකට පින්තූරය සහ විස්තරය පෝස්ට්
