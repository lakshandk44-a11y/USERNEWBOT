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

# ================= 1. ඔයාගේ සියලුම විස්තර (KEYS & IDS) =================
FB_PAGE_ID = "1243828092139012"
FB_ACCESS_TOKEN = "EAF40ZBiCgXTQBR6Gn58BUa62mZBKZB9HpCfUiEHDahWC0YyaWk0AR5ru9ZASUODhqpZAwKHwCI2nl6rXx3e7E29CZAMUVWqqYrikTWqpHZAgE1b9G8zSQn40KBlnOTLpcpXZC8HuU6pd5Pw2mZBjaf0WQdkTkmV8OUIhZBRm2wrDHhWtZAZA4VEzbXNM3vsZCLBJRWlVXsniNG3UgdODD6TpxVu08r2FQOq3OMmUKbwKD"
GEMINI_API_KEY = "AQ.Ab8RN6JeHF0PPAGjOnAKkp6MQpVMrmpQ8FJwabdQ7r_Gjd7UUw"
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1521532656825929911/r_p09BIeETgtrGdk3QsdHb5WglQNSqwKrHTWpCtvmA7n-HyTGKhQWZOz65Zpf0OE58iu"
# =====================================================================

app = Flask('')

@app.route('/')
def home():
    return "🤖 Prompting America Bot is Online and Running 24/7 on Railway!"

def run_flask():
    app.run(host='0.0.0.0', port=8080)

def get_us_time():
    """ ඇමරිකාවේ (New York/EST) වත්මන් වෙලාව ලබා ගැනීම """
    us_tz = pytz.timezone('America/New_York')
    return datetime.now(us_tz)

def fetch_top_us_trends():
    """ Google News RSS හරහා අන්ලිමිටඩ් පුවත් ලබා ගැනීම """
    rss_url = "https://news.google.com/rss/headlines/section/topic/WORLD?hl=en-US&gl=US&ceid=US:en"
    feed = feedparser.parse(rss_url)
    trends_list = []
    # පුවත් 10ක් ලබා ගැනීම
    for entry in feed.entries[:10]:
        trends_list.append({"title": entry.title, "description": entry.summary or entry.title})
    return trends_list

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
        print(f"Gemini Error: {e}")
        return {
            "caption": f"🔥 TRENDING NOW:\n\n{news_title}\n\n#PromptingAmerica #USNews",
            "image_prompt": f"Cinematic realistic photo representing: {news_title}"
        }

def get_ai_image_url(prompt):
    """ Pollinations AI එක හරහා පින්තූරයේ ලින්ක් එක සෑදීම """
    encoded_prompt = urllib.parse.quote(prompt)
    return f"[https://image.pollinations.ai/p/](https://image.pollinations.ai/p/){encoded_prompt}?width=1080&height=1080&nologo=true&seed={random.randint(1,1000000)}"

def send_discord_notification(title, desc, img_url=None):
    """ Discord එකට Notification එකක් යැවීම """
    payload = {
        "embeds": [{
            "title": title[:250],
            "description": desc[:4000],
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
    """ ෆේස්බුක් පේජ් එකට පින්තූරය සහ විස්තරය පෝස්ට් කිරීම """
    url = f"https://graph.facebook.com/v20.0/{FB_PAGE_ID}/photos"
    params = {
        'url': image_url,
        'caption': message,
        'access_token': FB_ACCESS_TOKEN
    }
    try:
        response = requests.post(url, params=params)
        return response.json()
    except Exception as e:
        return {"error": str(e)}

def job():
    """ බොට්ගේ ප්‍රධාන කාර්යය """
    print(">>> පුවත් එකතු කිරීම ආරම්භ විය")
    send_discord_notification("🚀 බොට් ක්‍රියාත්මක විය!", "අලුත්ම පුවත් ලබාගෙන පෝස්ට් සකසමින් පවතී...")
    
    trends = fetch_top_us_trends()
    if not trends:
        send_discord_notification("⚠️ දෝෂයක්!", "පුවත් මූලාශ්‍රය වෙතින් තොරතුරු ලැබුණේ නැත.")
        return

    for i, trend in enumerate(trends):
        if i >= 10: break 
        
        try:
            ai_content = generate_ai_content(trend['title'], trend['description'])
            image_url = get_ai_image_url(ai_content['image_prompt'])
            fb_response = post_to_facebook(ai_content['caption'], image_url)
            
            if 'id' in fb_response:
                fb_url = f"[https://facebook.com/](https://facebook.com/){fb_response['id']}"
                send_discord_notification(f"✅ පෝස්ට් අංක {i+1} සාර්ථකයි!", f"ලින්ක් එක: {fb_url}", image_url)
            else:
                send_discord_notification(f"❌ පෝස්ට් අංක {i+1} අසාර්ථකයි!", str(fb_response))
            
            time.sleep(90) # ෆේස්බුක් එකේ අවුලක් නොවීමට කාලය
        except Exception as e:
            send_discord_notification(f"⚠️ ක්‍රෑෂ් විය!", str(e))
            time.sleep(30)

if __name__ == "__main__":
    Thread(target=run_flask).start()
    
    while True:
        us_now = get_us_time()
        # වේලාව පරීක්ෂා කිරීම (උදේ 6ට)
        if True: 
            job()
            time.sleep(82800) # දවසකට පසු ක්‍රියාත්මක වීමට
        time.sleep(600)
