#!/usr/bin/env python3
"""
2050 Sri Lanka - Facebook Auto-Post Bot
Powered by Gemini API (google-genai SDK) & Facebook Graph API
Author: HackerAI
"""

import os
import json
import time
import random
import logging
import base64
import io
import schedule
import requests
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from pathlib import Path
from PIL import Image

# ============================================================
# 1. LIBRARY INSTALLATION (Run once)
# ============================================================
"""
pip install --upgrade google-genai requests schedule python-dotenv Pillow
"""

# ============================================================
# 2. CONFIGURATION
# ============================================================

# --- API Keys (Set as environment variables or use .env file) ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY_HERE")
FACEBOOK_PAGE_ACCESS_TOKEN = os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN", "YOUR_FACEBOOK_PAGE_TOKEN_HERE")
FACEBOOK_PAGE_ID = os.getenv("FACEBOOK_PAGE_ID", "YOUR_FACEBOOK_PAGE_ID_HERE")

# --- Paths ---
BASE_DIR = Path(__file__).parent
IMAGES_DIR = BASE_DIR / "generated_images"
POSTED_LOG = BASE_DIR / "posted_log.json"
SCHEDULE_LOG = BASE_DIR / "schedule_log.json"

# --- Ensure directories exist ---
IMAGES_DIR.mkdir(exist_ok=True)

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(BASE_DIR / "bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ============================================================
# 3. GEMINI API INTEGRATION (UPDATED - google-genai SDK)
# ============================================================

from google import genai as google_genai
from google.genai import types

class GeminiGenerator:
    """Handles all Gemini API interactions via google-genai SDK (Interactions API)"""

    def __init__(self, api_key: str):
        self.client = google_genai.Client(api_key=api_key)

    def generate_category_image(self, category: str) -> Tuple[Optional[bytes], Optional[str]]:
        """
        Generate a highly realistic, possible future image of Sri Lanka in 2050
        using Gemini 3.1 Flash Image model.
        Returns: (image_bytes, caption_with_hashtags)
        """
        image_prompt = f"""
        Generate a photorealistic, ultra-high quality image of Sri Lanka in the year 2050.

        Category: {category}

        The image MUST show something that is GENUINELY POSSIBLE and scientifically realistic
        for Sri Lanka by 2050. No science fiction. No fantasy elements.

        Scene requirements:
        - Ultra realistic photography style - must look like a REAL photograph
        - 8K resolution quality, sharp details
        - Cinematic lighting with natural golden hour or bright daylight
        - Clear blue water reflecting the sky with fluffy white clouds
        - Lush tropical vegetation (palm trees, local flora)
        - Sri Lankan landscape elements (mountains, beaches, or urban settings as appropriate)
        - Clean, modern infrastructure that could realistically exist by 2050

        For this category '{category}', here are realistic possibilities:
        - ආර්ථිකය (Economy): Modern Colombo skyline with green buildings, solar panels on roofs
        - අධ්‍යාපනය (Education): Digital classrooms with AR/VR, students using tablets under trees
        - තාක්ෂණික දියුණුව (Tech): Smart farming with drones over paddy fields
        - හරිත නගර (Green Cities): Colombo with vertical gardens, electric tuk-tuks
        - පුනර්ජනනීය බලශක්තිය (Renewable Energy): Solar farms in Hambantota, wind turbines
        - සංස්කෘතිය (Culture): Virtual Perahera with holographic elements
        - ප්‍රවාහනය (Transport): Electric railway along coast, modern highways with EV charging
        - කෘෂිකර්මය (Agriculture): Vertical farming, drone-monitored paddy fields
        - සෞඛ්‍ය සේවා (Healthcare): Modern hospital with telemedicine, AI diagnostics
        - සංචාරක කර්මාන්තය (Tourism): Eco-friendly resorts, smart heritage sites

        DO NOT add any text overlays, watermarks, or labels on the image.
        """

        caption_prompt = f"""
        Write a SINGLE engaging Facebook post caption in Sinhala language for an image
        showing '{category}' in Sri Lanka in 2050.

        Requirements:
        - Write ONLY the caption text, no explanations
        - 3-5 sentences describing the image and its future vision
        - Inspiring and positive tone
        - At the end, include 8-10 relevant hashtags in both Sinhala and English
        - Hashtags should include: #SriLanka2050 #FutureSriLanka #{category.split('(')[1].split(')')[0].replace(' ', '') if '(' in category else category.replace(' ', '')} and relevant others
        - Make it emotional and thought-provoking for Sri Lankan audience
        - DO NOT use any markdown formatting like ** or ##
        - Use simple, flowing Sinhala language
        """

        try:
            # Generate image using Gemini 3.1 Flash Image model
            logger.info(f"🎨 Generating image for category: {category}")
            interaction_img = self.client.interactions.create(
                model="gemini-3.1-flash-image",
                input=image_prompt,
                response_format={
                    "type": "image",
                    "aspect_ratio": "16:9",
                    "image_size": "4K"
                }
            )

            if not interaction_img.output_image:
                logger.error(f"No image generated for category: {category}")
                return None, None

            image_bytes = base64.b64decode(interaction_img.output_image.data)
            logger.info(f"✅ Image generated: {len(image_bytes)} bytes")

            # Generate caption using Gemini 2.5 Flash (text model)
            logger.info(f"📝 Generating caption for category: {category}")
            interaction_cap = self.client.interactions.create(
                model="gemini-2.5-flash",
                input=caption_prompt
            )

            caption = interaction_cap.output_text.strip() if interaction_cap.output_text else f"2050 දී ශ්‍රී ලංකාවේ {category} #SriLanka2050 #FutureSriLanka"

            return image_bytes, caption

        except Exception as e:
            logger.error(f"Gemini error for {category}: {e}")
            return None, None

    def generate_historical_future_images(self, place: str, place_en: str) -> Tuple[Optional[bytes], Optional[bytes], Optional[bytes], Optional[str]]:
        """
        Generate 3 images for a famous Sri Lankan place using Gemini 3.1 Flash Image:
        1. Historically accurate past view
        2. Future possible view (2050)
        3. Environmental destruction view (due to human negligence)
        Returns: (past_img, future_img, destruction_img, caption)
        """
        
        # --- PROMPT 1: Historical Past ---
        past_prompt = f"""
        Generate a photorealistic, historically accurate photograph of {place} ({place_en}), Sri Lanka
        as it would have appeared in its original/early golden age period.

        CRITICAL - Must look like a REAL historical photograph:
        - Historically accurate architecture, structures, and surroundings
        - Natural lighting, clear blue sky with fluffy white clouds
        - 8K cinematic quality photography, National Geographic documentary style
        - Show the ORIGINAL glory and authentic appearance in its prime
        - What it REALLY looked like during its peak period
        - Lush greenery, natural environment typical of that era
        - Clean water features (ponds, moats, lakes) reflecting the sky
        - No modern constructions, no electricity, no vehicles, no tourists in modern clothes
        - Ultra realistic - as if photographed during that period with vintage film quality
        - Golden hour warm sunlight creating dramatic shadows
        - DO NOT add any text overlays, watermarks, or labels
        """

        # --- PROMPT 2: Future 2050 ---
        future_prompt = f"""
        Generate a photorealistic, highly possible image of {place} ({place_en}), Sri Lanka
        in the year 2050 after significant sustainable development and preservation.

        CRITICAL - Must be SCIENTIFICALLY POSSIBLE by 2050:
        - The heritage site is PRESERVED and protected
        - Modern sustainable development around the site
        - Solar-powered visitor centers (discreetly placed)
        - Electric autonomous shuttles for visitors (no fossil fuel vehicles)
        - Smart preservation systems (drones monitoring structural health)
        - AR/VR information displays for educational tourism
        - Clear blue water features, reflecting the sky
        - Fluffy white clouds, cinematic golden hour lighting
        - 8K ultra realistic photography quality
        - Green technology integrated with heritage preservation
        - Reforested surrounding areas with native plants
        - Rainwater harvesting visible in landscape design
        - NO science fiction elements, no flying cars, no cyberpunk
        - Happy visitors from diverse backgrounds using eco-friendly facilities
        - Overall feeling: hopeful, sustainable, harmonious
        - DO NOT add any text overlays, watermarks, or labels
        """

        # --- PROMPT 3: Environmental Destruction ---
        destruction_prompt = f"""
        Generate a photorealistic, emotionally devastating photograph of {place} ({place_en}), Sri Lanka
        showing ENVIRONMENTAL DESTRUCTION caused by human negligence and carelessness.

        CRITICAL - This MUST look like a REAL news photograph of environmental disaster:
        - The {place_en} site is VISIBLE but SURROUNDED by destruction and decay
        - FOREGROUND: Massive piles of plastic waste, garbage, empty bottles, food wrappers
        - Ancient water features are DRY with cracked mud, filled with trash
        - Toxic green algae blooms in any remaining stagnant water
        - Graffiti spray-painted on ancient stone walls (vandalism)
        - Broken stonework, chipped structures from human damage
        - Erosion gullies on structures from acid rain and pollution
        - Dead brown trees, tree stumps, invasive weeds everywhere
        - Rusted collapsed safety railings, broken concrete pathways
        - Discarded plastic bags caught in bushes and trees
        - Cigarette butts, food wrappers scattered everywhere
        - Overcast, polluted grey sky with haze (NOT clear blue sky)
        - Muted, desaturated colors - no vibrant greens or blues
        - Wide angle lens showing the FULL SCALE of destruction
        - Ultra photorealistic, 8K quality, like a Pulitzer Prize winning photo
        - Photojournalism style - like a National Geographic environmental disaster photo
        - The image should make the viewer FEEL sadness, anger, and urgency
        - DO NOT add any text overlays, watermarks, or labels
        - DO NOT show any people
        """

        # --- Caption Prompt ---
        caption_prompt = f"""
        Write a Facebook post caption in Sinhala language about {place} ({place_en}) in Sri Lanka.

        The post includes 3 images showing:
        1. The place in its original/historical glory
        2. How it could look in 2050 with proper sustainable development
        3. Environmental destruction if humans remain negligent

        Requirements:
        - Write ONLY the caption text, no introductions or explanations
        - 5-7 sentences in flowing, emotional Sinhala
        - Explain the dramatic contrast between the three images
        - Raise awareness about protecting Sri Lanka's cultural heritage
        - Strong call to action for heritage preservation
        - Emotional, inspiring, educational tone
        - At the end, include 8-10 hashtags
        - Include: #HeritageProtection #{place_en.replace(' ', '')} #SriLanka #FutureVsDestruction #EnvironmentalAwareness #CulturalHeritage
        - DO NOT use markdown formatting like ** or ##
        - Make it shareable, emotional, and thought-provoking
        """

        try:
            logger.info(f"🏛️ Generating 3 images for: {place} ({place_en})")

            # --- Generate Image 1: Past ---
            logger.info(f"[1/3] Generating historical past view...")
            interaction_past = self.client.interactions.create(
                model="gemini-3.1-flash-image",
                input=past_prompt,
                response_format={
                    "type": "image",
                    "aspect_ratio": "16:9",
                    "image_size": "4K"
                }
            )
            past_bytes = base64.b64decode(interaction_past.output_image.data) if interaction_past.output_image else None
            if past_bytes:
                logger.info(f"✅ Past image generated: {len(past_bytes)} bytes")
            else:
                logger.error("❌ Past image generation failed")

            # --- Generate Image 2: Future 2050 ---
            logger.info(f"[2/3] Generating future 2050 view...")
            interaction_future = self.client.interactions.create(
                model="gemini-3.1-flash-image",
                input=future_prompt,
                response_format={
                    "type": "image",
                    "aspect_ratio": "16:9",
                    "image_size": "4K"
                }
            )
            future_bytes = base64.b64decode(interaction_future.output_image.data) if interaction_future.output_image else None
            if future_bytes:
                logger.info(f"✅ Future image generated: {len(future_bytes)} bytes")
            else:
                logger.error("❌ Future image generation failed")

            # --- Generate Image 3: Destruction ---
            logger.info(f"[3/3] Generating environmental destruction view...")
            interaction_destruction = self.client.interactions.create(
                model="gemini-3.1-flash-image",
                input=destruction_prompt,
                response_format={
                    "type": "image",
                    "aspect_ratio": "16:9",
                    "image_size": "4K"
                }
            )
            destruction_bytes = base64.b64decode(interaction_destruction.output_image.data) if interaction_destruction.output_image else None
            if destruction_bytes:
                logger.info(f"✅ Destruction image generated: {len(destruction_bytes)} bytes")
            else:
                logger.error("❌ Destruction image generation failed")

            # --- Generate Caption ---
            logger.info(f"📝 Generating Sinhala caption...")
            interaction_cap = self.client.interactions.create(
                model="gemini-2.5-flash",
                input=caption_prompt
            )
            caption = interaction_cap.output_text.strip() if interaction_cap.output_text else f"{place} - අතීතය, 2050 අනාගතය, සහ විනාශය #HeritageProtection #SriLanka"

            return past_bytes, future_bytes, destruction_bytes, caption

        except Exception as e:
            logger.error(f"Gemini generation error for {place}: {e}")
            return None, None, None, None


# ============================================================
# 4. FACEBOOK GRAPH API INTEGRATION
# ============================================================

class FacebookPublisher:
    """Handles all Facebook Page posting via Graph API"""

    def __init__(self, page_id: str, access_token: str):
        self.page_id = page_id
        self.access_token = access_token
        self.api_base = "https://graph.facebook.com/v19.0"

    def post_single_image(self, image_bytes: bytes, caption: str) -> bool:
        """
        Post a single image to Facebook Page with caption and hashtags.
        Uses the Graph API photo endpoint.
        """
        try:
            url = f"{self.api_base}/{self.page_id}/photos"
            
            # Save image temporarily for upload
            temp_path = IMAGES_DIR / f"temp_post_{int(time.time())}.jpg"
            
            # Convert PNG bytes to JPG for smaller size
            try:
                img = Image.open(io.BytesIO(image_bytes))
                img = img.convert("RGB")
                img.save(temp_path, "JPEG", quality=95)
            except:
                # If conversion fails, save as-is
                with open(temp_path, "wb") as f:
                    f.write(image_bytes)

            with open(temp_path, "rb") as image_file:
                response = requests.post(
                    url,
                    params={"access_token": self.access_token},
                    files={"source": image_file},
                    data={
                        "caption": caption,
                        "published": "true"
                    }
                )

            # Clean up temp file
            temp_path.unlink(missing_ok=True)

            if response.status_code == 200:
                result = response.json()
                logger.info(f"✅ Image posted successfully! Post ID: {result.get('id', 'N/A')}")
                return True
            else:
                logger.error(f"❌ Facebook API error: {response.status_code} - {response.text}")
                return False

        except Exception as e:
            logger.error(f"Facebook post error: {e}")
            return False

    def post_multi_image(self, image_bytes_list: List[bytes], caption: str) -> bool:
        """
        Post multiple images (up to 3) as a single Facebook post with caption.
        Uses Graph API batch upload and then creates a published post.
        """
        try:
            if not image_bytes_list:
                logger.error("No images to post")
                return False

            # Step 1: Upload each image to get media IDs
            media_ids = []
            temp_files = []

            for i, img_bytes in enumerate(image_bytes_list):
                if not img_bytes:
                    continue

                temp_path = IMAGES_DIR / f"temp_multi_{int(time.time())}_{i}.jpg"
                
                # Convert PNG bytes to JPG for smaller size
                try:
                    img = Image.open(io.BytesIO(img_bytes))
                    img = img.convert("RGB")
                    img.save(temp_path, "JPEG", quality=95)
                except:
                    with open(temp_path, "wb") as f:
                        f.write(img_bytes)
                
                temp_files.append(temp_path)

                upload_url = f"{self.api_base}/{self.page_id}/photos"
                with open(temp_path, "rb") as img_file:
                    upload_resp = requests.post(
                        upload_url,
                        params={
                            "access_token": self.access_token,
                            "published": "false"
                        },
                        files={"source": img_file}
                    )

                if upload_resp.status_code == 200:
                    media_id = upload_resp.json().get("id")
                    if media_id:
                        media_ids.append(media_id)
                        logger.info(f"✅ Uploaded image {i+1}, media ID: {media_id}")
                else:
                    logger.error(f"Upload failed for image {i+1}: {upload_resp.text}")

            # Clean up temp files
            for tp in temp_files:
                tp.unlink(missing_ok=True)

            if not media_ids:
                logger.error("No media IDs obtained")
                return False

            # Step 2: Create published post with attached media
            post_url = f"{self.api_base}/{self.page_id}/feed"
            
            # For multiple images, we use the `attached_media` parameter
            media_data = [{"media_fbid": mid} for mid in media_ids]

            post_data = {
                "access_token": self.access_token,
                "message": caption,
                "attached_media": json.dumps(media_data),
                "published": "true"
            }

            response = requests.post(post_url, data=post_data)

            if response.status_code == 200:
                result = response.json()
                logger.info(f"✅ Multi-image post published! Post ID: {result.get('id', 'N/A')}")
                return True
            else:
                logger.error(f"❌ Post creation error: {response.status_code} - {response.text}")
                return False

        except Exception as e:
            logger.error(f"Multi-image Facebook post error: {e}")
            return False


# ============================================================
# 5. SCHEDULING & POST MANAGEMENT
# ============================================================

class PostScheduler:
    """Manages the daily schedule and prevents duplicate posts"""

    def __init__(self):
        self.log_file = POSTED_LOG
        self.schedule_file = SCHEDULE_LOG
        self.posted_log = self._load_json(self.log_file, {})
        self.schedule_data = self._load_json(self.schedule_file, {})

    def _load_json(self, filepath: Path, default):
        try:
            if filepath.exists():
                with open(filepath, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            logger.warning(f"Could not load {filepath}: {e}")
        return default

    def _save_json(self, data, filepath: Path):
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Could not save {filepath}: {e}")

    def mark_posted(self, post_type: str, identifier: str):
        """Mark a post as completed for today"""
        today = datetime.now().strftime("%Y-%m-%d")
        if today not in self.posted_log:
            self.posted_log[today] = {"category": [], "historical": []}
        
        if post_type == "category":
            if identifier not in self.posted_log[today]["category"]:
                self.posted_log[today]["category"].append(identifier)
        elif post_type == "historical":
            if identifier not in self.posted_log[today]["historical"]:
                self.posted_log[today]["historical"].append(identifier)
        
        self._save_json(self.posted_log, self.log_file)

    def is_posted_today(self, post_type: str, identifier: str) -> bool:
        """Check if this post was already done today"""
        today = datetime.now().strftime("%Y-%m-%d")
        if today not in self.posted_log:
            return False
        
        if post_type == "category":
            return identifier in self.posted_log[today].get("category", [])
        elif post_type == "historical":
            return identifier in self.posted_log[today].get("historical", [])
        return False

    def get_daily_category_schedule(self) -> List[str]:
        """
        Generate 10 random times for category posts today.
        Times are spread between 7:00 AM and 10:00 PM.
        """
        today = datetime.now().strftime("%Y-%m-%d")
        
        if today in self.schedule_data and "category_times" in self.schedule_data[today]:
            return self.schedule_data[today]["category_times"]
        
        base_hours = list(range(7, 22))
        random.shuffle(base_hours)
        
        if len(base_hours) > 10:
            base_hours = base_hours[:10]
        
        schedule_times = []
        for hour in sorted(base_hours):
            minute = random.randint(0, 59)
            time_str = f"{hour:02d}:{minute:02d}"
            schedule_times.append(time_str)
        
        if today not in self.schedule_data:
            self.schedule_data[today] = {}
        self.schedule_data[today]["category_times"] = schedule_times
        self._save_json(self.schedule_data, self.schedule_file)
        
        return schedule_times

    def get_daily_historical_schedule(self) -> List[str]:
        """
        Generate 3 random times for the historical place post today.
        """
        today = datetime.now().strftime("%Y-%m-%d")
        
        if today in self.schedule_data and "historical_times" in self.schedule_data[today]:
            return self.schedule_data[today]["historical_times"]
        
        time_slots = [
            f"{random.randint(8, 11):02d}:{random.randint(0, 59):02d}",
            f"{random.randint(13, 16):02d}:{random.randint(0, 59):02d}",
            f"{random.randint(18, 21):02d}:{random.randint(0, 59):02d}",
        ]
        
        if today not in self.schedule_data:
            self.schedule_data[today] = {}
        self.schedule_data[today]["historical_times"] = sorted(time_slots)
        self._save_json(self.schedule_data, self.schedule_file)
        
        return sorted(time_slots)

    def get_pending_summary(self, categories: list, historical_places: list) -> str:
        """Return a summary of today's schedule and pending posts"""
        today = datetime.now().strftime("%Y-%m-%d")
        now = datetime.now()
        
        cat_times = self.get_daily_category_schedule()
        hist_times = self.get_daily_historical_schedule()
        
        summary_parts = []
        summary_parts.append(f"\n📅 අද ({today}) වේලාසටහන:")
        summary_parts.append(f"{'='*50}")
        
        # Category times
        summary_parts.append(f"\n📸 Category Posts (10):")
        for i, time_str in enumerate(cat_times):
            scheduled_time = datetime.strptime(time_str, "%H:%M").time()
            cat_name = categories[i] if i < len(categories) else f"Category {i+1}"
            posted = self.is_posted_today("category", categories[i]) if i < len(categories) else False
            
            if scheduled_time > now.time() and not posted:
                status = "⏳ බලා සිටී"
            elif posted:
                status = "✅ පළ කළා"
            else:
                status = "⏳ බලා සිටී"
            
            summary_parts.append(f"   {time_str} - {cat_name} {status}")
        
        # Historical times
        summary_parts.append(f"\n🏛️ Historical Posts (3 වතාවක්):")
        for time_str in hist_times:
            scheduled_time = datetime.strptime(time_str, "%H:%M").time()
            
            # Check if any historical place already posted
            any_posted = False
            for place_si, place_en in historical_places:
                if self.is_posted_today("historical", f"{place_si} ({place_en})"):
                    any_posted = True
                    break
            
            if scheduled_time > now.time() and not any_posted:
                status = "⏳ බලා සිටී"
            elif any_posted:
                status = "✅ පළ කළා"
            else:
                status = "⏳ බලා සිටී"
            
            summary_parts.append(f"   {time_str} - Historical Place Post {status}")
        
        summary_parts.append(f"\n{'='*50}")
        
        return "\n".join(summary_parts)


# ============================================================
# 6. MAIN BOT ENGINE
# ============================================================

class SriLanka2050Bot:
    """Main bot orchestrating all components"""

    def __init__(self):
        self.gemini = GeminiGenerator(GEMINI_API_KEY)
        self.facebook = FacebookPublisher(FACEBOOK_PAGE_ID, FACEBOOK_PAGE_ACCESS_TOKEN)
        self.scheduler = PostScheduler()
        
        # === 10 CATEGORIES (Non-political) ===
        self.categories = [
            "ආර්ථිකය (Economy)",
            "අධ්‍යාපනය (Education)",
            "තාක්ෂණික දියුණුව (Technology)",
            "හරිත නගර (Green Cities)",
            "පුනර්ජනනීය බලශක්තිය (Renewable Energy)",
            "සංස්කෘතිය (Culture)",
            "ප්‍රවාහනය (Transportation)",
            "කෘෂිකර්මය (Agriculture)",
            "සෞඛ්‍ය සේවා (Healthcare)",
            "සංචාරක කර්මාන්තය (Tourism)"
        ]
        
        # === 10 FAMOUS SRI LANKAN PLACES ===
        self.historical_places = [
            ("සීගිරිය", "Sigiriya"),
            ("ගාල්ල කොටුව", "Galle Fort"),
            ("ශ්‍රී මහා බෝධිය", "Sri Maha Bodhiya"),
            ("යාපනය බලකොටුව", "Jaffna Fort"),
            ("මිහින්තලය", "Mihintale"),
            ("දඹුල්ල රජ මහා විහාරය", "Dambulla Cave Temple"),
            ("කැළණිය රජ මහා විහාරය", "Kelaniya Temple"),
            ("පොළොන්නරුව", "Polonnaruwa"),
            ("කොළඹ වරාය", "Colombo Port"),
            ("නුවරඑළිය", "Nuwara Eliya")
        ]

    def run_category_post(self, category_index: int):
        """Generate and post ONE category image"""
        if category_index < 0 or category_index >= len(self.categories):
            logger.error(f"Invalid category index: {category_index}")
            return False

        category = self.categories[category_index]
        
        if self.scheduler.is_posted_today("category", category):
            logger.info(f"⏭️ Already posted category '{category}' today. Skipping.")
            return False

        logger.info(f"🎯 Generating category post: {category}")
        
        image_bytes, caption = self.gemini.generate_category_image(category)
        
        if not image_bytes:
            logger.error(f"❌ Failed to generate image for {category}")
            return False
        
        if not caption:
            caption = f"2050 දී ශ්‍රී ලංකාවේ {category} #SriLanka2050 #FutureSriLanka"
        
        success = self.facebook.post_single_image(image_bytes, caption)
        
        if success:
            self.scheduler.mark_posted("category", category)
            logger.info(f"✅ Successfully posted category: {category}")
        
        return success

    def run_historical_post(self, place_index: int):
        """Generate and post ONE historical place with 3 images"""
        if place_index < 0 or place_index >= len(self.historical_places):
            logger.error(f"Invalid place index: {place_index}")
            return False

        place_si, place_en = self.historical_places[place_index]
        identifier = f"{place_si} ({place_en})"
        
        if self.scheduler.is_posted_today("historical", identifier):
            logger.info(f"⏭️ Already posted historical '{identifier}' today. Skipping.")
            return False

        logger.info(f"🏛️ Generating historical post: {identifier}")
        
        past_img, future_img, destruction_img, caption = self.gemini.generate_historical_future_images(place_si, place_en)
        
        images = [img for img in [past_img, future_img, destruction_img] if img is not None]
        
        if len(images) < 2:
            logger.error(f"❌ Not enough images generated for {identifier}")
            
            # Save whatever images we got for debugging
            for i, img in enumerate([past_img, future_img, destruction_img]):
                if img:
                    debug_path = IMAGES_DIR / f"debug_{place_en}_{i}.png"
                    with open(debug_path, "wb") as f:
                        f.write(img)
                    logger.info(f"Saved debug image: {debug_path}")
            
            return False
        
        if not caption:
            caption = f"{place_si} - අතීතය, 2050 අනාගතය, සහ විනාශය #HeritageProtection #SriLanka"
        
        success = self.facebook.post_multi_image(images, caption)
        
        if success:
            self.scheduler.mark_posted("historical", identifier)
            logger.info(f"✅ Successfully posted historical: {identifier}")
        
        return success

    def run_full_category_cycle(self):
        """Run all category posts that haven't been posted today yet."""
        today = datetime.now().strftime("%Y-%m-%d")
        logger.info(f"===== Starting Category Post Cycle: {today} =====")
        
        for i, category in enumerate(self.categories):
            if not self.scheduler.is_posted_today("category", category):
                logger.info(f"Posting category {i+1}/10: {category}")
                self.run_category_post(i)
                time.sleep(random.randint(30, 90))
            else:
                logger.info(f"Category already posted today: {category}")
        
        logger.info(f"===== Category Post Cycle Complete: {today} =====")

    def run_full_historical_cycle(self):
        """Post the next historical place that hasn't been posted."""
        today = datetime.now().strftime("%Y-%m-%d")
        
        for i, (place_si, place_en) in enumerate(self.historical_places):
            identifier = f"{place_si} ({place_en})"
            if not self.scheduler.is_posted_today("historical", identifier):
                logger.info(f"🏛️ Posting historical place: {identifier}")
                self.run_historical_post(i)
                return
        
        logger.info("✅ All historical places posted for today!")


# ============================================================
# 7. SCHEDULE SETUP & MAIN LOOP
# ============================================================

def setup_schedules(bot: SriLanka2050Bot):
    """Set up the daily schedule."""
    
    def check_and_run_category():
        now = datetime.now().strftime("%H:%M")
        scheduled_times = bot.scheduler.get_daily_category_schedule()
        
        if now in scheduled_times:
            for i, cat in enumerate(bot.categories):
                if not bot.scheduler.is_posted_today("category", cat):
                    logger.info(f"⏰ Scheduled time reached: {now}")
                    bot.run_category_post(i)
                    return
            logger.info(f"All categories posted for today at {now}")

    def check_and_run_historical():
        now = datetime.now().strftime("%H:%M")
        scheduled_times = bot.scheduler.get_daily_historical_schedule()
        
        if now in scheduled_times:
            logger.info(f"⏰ Scheduled historical time reached: {now}")
            for i, (place_si, place_en) in enumerate(bot.historical_places):
                identifier = f"{place_si} ({place_en})"
                if not bot.scheduler.is_posted_today("historical", identifier):
                    bot.run_historical_post(i)
                    return
            logger.info(f"All historical places posted for today at {now}")

    schedule.every(5).minutes.do(check_and_run_category)
    schedule.every(5).minutes.do(check_and_run_historical)
    
    check_and_run_category()
    check_and_run_historical()

    logger.info("✅ Schedule system initialized")
    
    # Print the daily schedule with times
    logger.info(bot.scheduler.get_pending_summary(bot.categories, bot.historical_places))


# ============================================================
# 8. ENTRY POINT
# ============================================================

def main():
    """Main entry point"""
    logger.info("=" * 60)
    logger.info("🚀 2050 Sri Lanka Facebook Auto-Post Bot Starting...")
    logger.info("=" * 60)
    
    if "YOUR_GEMINI_API_KEY_HERE" in GEMINI_API_KEY:
        logger.error("❌ Please set your GEMINI_API_KEY environment variable!")
        logger.error("   Get your free API key: https://aistudio.google.com/app/apikey")
        logger.error("   Then run: export GEMINI_API_KEY='your-key-here'")
        return
    
    if "YOUR_FACEBOOK_PAGE_TOKEN_HERE" in FACEBOOK_PAGE_ACCESS_TOKEN:
        logger.error("❌ Please set your FACEBOOK_PAGE_ACCESS_TOKEN!")
        return
    
    if "YOUR_FACEBOOK_PAGE_ID_HERE" in FACEBOOK_PAGE_ID:
        logger.error("❌ Please set your FACEBOOK_PAGE_ID!")
        return
    
    bot = SriLanka2050Bot()
    setup_schedules(bot)
    
    logger.info("""
    📋 BOT SCHEDULE SUMMARY:
    ========================
    📸 Category Posts: 10 per day (random times between 7AM-10PM)
      - 10 non-political categories about Sri Lanka 2050
      - Each post: 1 image + Sinhala caption + hashtags
    
    🏛️ Historical Place Posts: 1 place per day × 3 times
      - 3 images per post (Past / Future 2050 / Destruction)
      - Sinhala caption explaining the contrast
      - Awareness about heritage protection
    
    ⏰ Check interval: Every 5 minutes for pending posts
    
    🎨 Image Model: Gemini 3.1 Flash Image (Nano Banana 2)
    💬 Text Model: Gemini 2.5 Flash
    """)
    
    # Main loop
    try:
        while True:
            schedule.run_pending()
            time.sleep(30)
    except KeyboardInterrupt:
        logger.info("👋 Bot stopped by user (Ctrl+C)")
    except Exception as e:
        logger.error(f"💥 Unexpected error: {e}")
        raise


# ============================================================
# 9. MANUAL RUN OPTIONS (For testing)
# ============================================================

def manual_test_category(bot: SriLanka2050Bot, index: int = 0):
    """Manually test a single category post"""
    logger.info(f"🧪 Manual test: Category {index}")
    bot.run_category_post(index)

def manual_test_historical(bot: SriLanka2050Bot, index: int = 0):
    """Manually test a single historical place post"""
    logger.info(f"🧪 Manual test: Historical {index}")
    bot.run_historical_post(index)


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        bot = SriLanka2050Bot()
        
        if sys.argv[1] == "--test-category":
            index = int(sys.argv[2]) if len(sys.argv) > 2 else 0
            manual_test_category(bot, index)
        elif sys.argv[1] == "--test-historical":
            index = int(sys.argv[2]) if len(sys.argv) > 2 else 0
            manual_test_historical(bot, index)
        elif sys.argv[1] == "--full-category":
            bot.run_full_category_cycle()
        elif sys.argv[1] == "--full-historical":
            bot.run_full_historical_cycle()
        elif sys.argv[1] == "--schedule":
            # Just show today's schedule
            bot = SriLanka2050Bot()
            print(bot.scheduler.get_pending_summary(bot.categories, bot.historical_places))
        else:
            print("Usage:")
            print("  python bot.py                    # Run scheduled bot")
            print("  python bot.py --test-category 0  # Test category 0")
            print("  python bot.py --test-historical 0 # Test historical 0")
            print("  python bot.py --full-category    # Post all categories now")
            print("  python bot.py --full-historical  # Post next historical now")
            print("  python bot.py --schedule         # Show today's schedule")
    else:
        main()
