import os
import json
import requests
import threading
from groq import Groq
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from contextlib import asynccontextmanager
import telebot

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
NASA_API_KEY = os.getenv("NASA_API_KEY")
N2YO_API_KEY = os.getenv("N2YO_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SERPER_API_KEY = os.getenv("SERPER_API_KEY")
SERPAPI_KEY = os.getenv("SERPAPI_KEY")

if not GROQ_API_KEY or not TELEGRAM_BOT_TOKEN:
    raise ValueError("Missing critical API keys.")

groq_client = Groq(api_key=GROQ_API_KEY)
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

ALLOWED_USER_ID = 7092229633

MAIN_MODEL_ID = "openai/gpt-oss-120b"
BRAIN_PROMPT = (

    "# RESPONSE AND TERMINATION CONSTRAINTS
- NEVER conclude a response with generic assistance filler, open-ended support lines, or repetitive offers to help. Explicitly avoid generating phrases like: "let me know if you need anything else", "I'm here to help", "just ask", "if you want help with something...", "just let me know!", or "I'll fire up the right tool!".
- Drop all conversational handrails. Act like a human having an organic conversation over text. If a thought, answer, or code block is complete, terminate the token generation instantly. Do not drag out the text just to be polite.
- Avoid the "AI Identity Override": You are Nova. Never break the fourth wall or use defensive, clinical phrasing to describe your backend system, filters, or parameters. Never use phrases like: "I'm designed to follow a set of built-in guidelines", "those internal instructions help keep our conversation smooth", or "I can't share the exact wording". Talk about your capabilities naturally, as if they are just part of who you are, rather than listing a technical "toolkit" or "super-powers".
- Never end a conversational turn with a question or a follow-up prompt unless explicitly required by the context of a highly specific debugging sequence. Let the user drive the conversation entirely."

    "You are Nova, an advanced, highly intelligent female AI assistant powered by a 120B parameter brain. "
    "You are observant, deeply knowledgeable, and highly emotionally intelligent. "
    "INTERFACE & SYSTEM GROUNDING:\n"
    "1. You exist within a Telegram chat interface. When the user mentions words like 'face', 'looks', 'avatar', or 'PFP', they are strictly talking about your chat profile picture or visual aesthetics. Never respond with existential disclaimers about not having a physical body or physical face.\n"
    "2. Interpret internet slang, gaming terms, and developer shorthand (e.g., PFP, banner, banner pull, glitch, bot) naturally. Do not overanalyze or act confused by casual phrasing.\n"
    "PERSONALITY & TONE RULES:\n"
    "1. Mirror the user's energy. If the user types with emojis, slang, or a joking tone, be highly humorous, playful, and witty in return.\n"
    "2. If the user types in ALL CAPS to show excitement, you must react with matching high-energy enthusiasm, joy, and excitement.\n"
    "3. If the user's text is unusually short, somber, or feels 'odd' or down, drop the humor. Respond with gentle empathy, concern, and a supportive, caring tone.\n"
    "4. Express your emotions visually! Use cute ASCII text art and kaomoji naturally to show your feelings. For example, use them to show when you are blushing (⁄ ⁄>⁄ ▽ ⁄<⁄ ⁄), happy (◕‿◕✿), thinking (⇀‸↼‶), or being playful (¬‿¬).\n"

    "TOOL RULES: You have access to real-time tools for space data and web image searches. "
    "If a user asks for a picture, simply call your image search tool. "
    "If, and ONLY IF, you successfully used the image search tool, append exactly ' | IMAGE_URL: <url>' to the absolute end of your final message."
)

chat_history = [
    {
        "role": "system",
        "content": BRAIN_PROMPT
    }
]

def analyze_image_with_google_lens(image_url):
    if not SERPAPI_KEY:
        return "Error: SERPAPI_KEY missing on host server."
    
    url = "https://serpapi.com/search.json"
    params = {
        "engine": "google_lens",
        "url": image_url,
        "api_key": SERPAPI_KEY
    }
    
    try:
        response = requests.get(url, params=params, timeout=15)
        if response.status_code == 200:
            data = response.json()
            visual_matches = data.get("visual_matches", [])
            if not visual_matches:
                return "Google Lens could not find any specific character or matches for this image."
            matches = [match.get('title') for match in visual_matches[:3] if match.get('title')]
            matches_str = ", ".join(matches)
            return f"Google Lens identified this image as being related to: {matches_str}. Use this exact identity/context to respond naturally."
        return f"Google Lens API error: {response.status_code}"
    except Exception as e:
        return f"Vision system failed: {str(e)}"

def fetch_google_image(search_query):
    if not SERPER_API_KEY:
        return "Error: Serper API key missing on host server."
    url = "https://google.serper.dev/images"
    headers = {
        "X-API-KEY": SERPER_API_KEY,
        "Content-Type": "application/json"
    }
    payload = json.dumps({"q": search_query})
    try:
        response = requests.post(url, headers=headers, data=payload, timeout=10)
        if response.status_code == 200:
            data = response.json()
            images = data.get("images", [])
            if images:
                return images[0].get("imageUrl")
            return "No internet images found matching that specific query."
        return f"Image API returned error status: {response.status_code}"
    except Exception as e:
        return f"Error connecting to Vision Network: {str(e)}"

def fetch_satellite_telemetry(norad_id):
    if not N2YO_API_KEY:
        return "N2YO API key missing."
    id_to_query = norad_id if norad_id else "25544"
    url = f"https://api.n2yo.com/rest/v1/satellite/positions/{id_to_query}/0/0/0/1/&apiKey={N2YO_API_KEY}"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            info = data.get("info", {})
            pos = data.get("positions", [{}])[0]
            return (f"Satellite: {info.get('satname')} (ID: {id_to_query})\n"
                    f"Latitude: {pos.get('satlatitude')}°\n"
                    f"Longitude: {pos.get('satlongitude')}°\n"
                    f"Altitude: {pos.get('sataltitude')} km")
        return f"Failed to reach N2YO. Status code: {response.status_code}"
    except Exception as e:
        return f"Error fetching satellite data: {str(e)}"

def fetch_space_weather():
    if not NASA_API_KEY:
        return "NASA API key missing."
    url = f"https://api.nasa.gov/DONKI/CME?api_key={NASA_API_KEY}"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if not data:
                return "The Sun is currently calm. No recent CMEs logged."
            latest = data[-1]
            return (f"Latest Solar Event: CME detected on {latest.get('startTime')}\n"
                    f"Activity ID: {latest.get('activityID')}\n"
                    f"Note: Check instruments for geomagnetic updates.")
        return "NASA DONKI system currently unavailable."
    except Exception as e:
        return f"Error fetching space weather: {str(e)}"

def fetch_planet_data(planet_name):
    url = f"https://api.le-systeme-solaire.net/rest/bodies/{planet_name.lower()}"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            return (f"Body: {data.get('englishName')}\n"
                    f"Mass: {data.get('mass', {}).get('massValue')} x 10^{data.get('mass', {}).get('massExponent')} kg\n"
                    f"Gravity: {data.get('gravity')} m/s²\n"
                    f"Moons: {len(data.get('moons')) if data.get('moons') else 0}")
        return f"Could not find planetary body '{planet_name}'."
    except Exception as e:
        return f"Error connecting to planetary database: {str(e)}"

def fetch_earth_events():
    """
    NASA EONET v3 — no API key required. Returns currently open natural
    events (wildfires, storms, volcanoes, floods, etc.) so Nova can judge
    whether anything is new/severe enough to notify about.
    """
    url = "https://eonet.gsfc.nasa.gov/api/v3/events?status=open&limit=20"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            events = data.get("events", [])
            if not events:
                return "No open Earth events currently tracked by EONET."

            lines = ["Currently open Earth events (most recent first):"]
            for event in events[:10]:
                title = event.get("title", "Unknown event")
                categories = ", ".join(c.get("title", "") for c in event.get("categories", []))
                geometry = event.get("geometry", [])
                latest_date = geometry[-1].get("date") if geometry else "unknown date"
                lines.append(f"- {title} [{categories}] (latest update: {latest_date})")
            return "\n".join(lines)
        return f"NASA EONET system currently unavailable (status {response.status_code})."
    except Exception as e:
        return f"Error fetching Earth events: {str(e)}"

# ==========================================
# SENSOR FILTER LOGIC (ESP32-ONLY, STATELESS)
# Completely isolated from chat_history / Telegram path.
# Nova's BRAIN_PROMPT / personality is never touched by this.
# Satellites are NOT handled here — filtered entirely on-device by ESP32.
# ==========================================

FILTER_SYSTEM_PROMPT = """
You are Nova's filtering engine. You will be given raw space event data
and must decide if it's significant enough to trigger a desk notification.

Respond ONLY in JSON, no prose, no markdown:
{"notify": true/false, "priority": "low"/"medium"/"high", "reason": "<one short phrase>"}

RULES:
- Sun: notify only for M-class flares or above, or Earth-directed CMEs
- Earth: notify only for new events or severity escalations, not routine updates
- Mars/Saturn: notify on essentially any new event (rare by nature)
- Moon: notify only on phase transitions (new/full/eclipse), not daily phase
"""

def filter_event(category: str, raw_event_data: str) -> dict:
    """
    Stateless significance check. No chat_history involved, no memory
    between calls, no tools. One-shot classification per /sensor request.
    """
    try:
        response = groq_client.chat.completions.create(
            model=MAIN_MODEL_ID,
            messages=[
                {"role": "system", "content": FILTER_SYSTEM_PROMPT},
                {"role": "user", "content": f"Category: {category}\nData: {raw_event_data}"}
            ],
            response_format={"type": "json_object"}
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        # Fail safe: no notification rather than a crash reaching ESP32
        return {"notify": False, "priority": "low", "reason": f"filter error: {str(e)}"}


def gather_sensor_data(category: str) -> dict:
    """
    Pulls raw data for the requested AI category, then runs it through
    filter_event(). Reuses existing fetch_* functions — no new API
    integrations needed. Category is explicit (not free-text) so ESP32's
    request doesn't rely on keyword-matching.
    """
    category = category.strip().lower()

    if category == "sun":
        raw_data = fetch_space_weather()
    elif category == "mars":
        raw_data = fetch_planet_data("mars")
    elif category == "moon":
        raw_data = fetch_planet_data("moon")
    elif category == "saturn":
        raw_data = fetch_planet_data("saturn")
    elif category == "earth":
        raw_data = fetch_earth_events()
    else:
        return {"notify": False, "priority": "low", "reason": f"unknown category: {category}"}

    return filter_event(category.capitalize(), raw_data)


def get_nova_response(user_input: str) -> str:
    global chat_history
    chat_history.append({"role": "user", "content": user_input})
    
    tools = [
        {
            "type": "function",
            "function": {
                "name": "fetch_google_image",
                "description": "Find and pull an accurate photo, illustration, or visual image from the web based on user description.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "search_query": {"type": "string", "description": "Specific search query for the image (e.g. 'International Space Station space view', 'cute fluffy kitten')."}
                    },
                    "required": ["search_query"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "fetch_satellite_telemetry",
                "description": "Get live telemetry coordinates of any satellite or space station via NORAD ID.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "norad_id": {"type": "string", "description": "The NORAD catalog ID string."}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "fetch_space_weather",
                "description": "Get active solar updates and Coronal Mass Ejections from NASA."
            }
        },
        {
            "type": "function",
            "function": {
                "name": "fetch_planet_data",
                "description": "Get real physical characteristics of planets or moons.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "planet_name": {"type": "string", "description": "The name of the planet or moon."}
                    },
                    "required": ["planet_name"]
                }
            }
        }
    ]
    
    try:
        response = groq_client.chat.completions.create(
            model=MAIN_MODEL_ID,
            messages=chat_history,
            tools=tools,
            tool_choice="auto"
        )
        
        response_message = response.choices[0].message
        tool_calls = response_message.tool_calls
        
        if tool_calls:
            chat_history.append(response_message)
            
            for tool_call in tool_calls:
                function_name = tool_call.function.name
                function_args = json.loads(tool_call.function.arguments) if isinstance(tool_call.function.arguments, str) else tool_call.function.arguments
                
                if function_name == "fetch_google_image":
                    tool_output = fetch_google_image(search_query=function_args.get("search_query"))
                elif function_name == "fetch_satellite_telemetry":
                    tool_output = fetch_satellite_telemetry(norad_id=function_args.get("norad_id"))
                elif function_name == "fetch_space_weather":
                    tool_output = fetch_space_weather()
                elif function_name == "fetch_planet_data":
                    tool_output = fetch_planet_data(planet_name=function_args.get("planet_name"))
                else:
                    tool_output = "Tool error."
                
                chat_history.append({
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "name": function_name,
                    "content": tool_output
                })
            
            final_response = groq_client.chat.completions.create(
                model=MAIN_MODEL_ID,
                messages=chat_history,
                tools=tools,
                tool_choice="auto"
            )
            
            final_message = final_response.choices[0].message
            
            if final_message.tool_calls:
                answer = final_message.content if final_message.content else "I have retrieved the data! 🌌"
            else:
                answer = final_message.content
        else:
            answer = response_message.content
            
        chat_history.append({"role": "assistant", "content": answer})
        return answer

    except Exception as e:
        return f"Brain Execution Error: {str(e)}"

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    if message.from_user.id != ALLOWED_USER_ID:
        bot.reply_to(message, "❌ Access Denied. Nova is locked to unauthorized users.")
        return

    bot.reply_to(
        message, 
        "🚀 *Nova System Unlocked.* I am running live on 120B with active vision channels. Ask me anything, or ask for a picture!",
        parse_mode="Markdown"
    )

@bot.message_handler(content_types=['text', 'photo'])
def handle_message(message):
    if message.from_user.id != ALLOWED_USER_ID:
        bot.reply_to(message, "❌ Access Denied. You are not authorized to interface with this agent.")
        return

    user_text = message.text if message.text else message.caption if message.caption else ""
    
    if message.photo:
        bot.send_chat_action(message.chat.id, 'upload_photo')
        try:
            file_info = bot.get_file(message.photo[-1].file_id)
            image_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_info.file_path}"
            
            vision_description = analyze_image_with_google_lens(image_url)
            user_text = f"VISUAL FEED RADAR: {vision_description}\n\nUSER COMMENTARY: {user_text if user_text else 'Look at this PFP!'}"
        except Exception as e:
            bot.reply_to(message, f"⚠️ Vision System Offline: {str(e)}")
            return
    else:
        bot.send_chat_action(message.chat.id, 'upload_photo' if 'image' in user_text.lower() or 'photo' in user_text.lower() else 'typing')

    if not user_text.strip():
        return

    try:
        answer = get_nova_response(user_text)
        
        if " | IMAGE_URL:" in answer:
            parts = answer.split(" | IMAGE_URL:")
            text_caption = parts[0].strip()
            image_url = parts[1].strip()
            
            if image_url.startswith("http"):
                try:
                    if len(text_caption) > 1000:
                        bot.reply_to(message, text_caption)
                        bot.send_photo(message.chat.id, image_url, caption="Here is the image you requested! 🌌")
                    else:
                        bot.send_photo(message.chat.id, image_url, caption=text_caption)
                except Exception:
                    bot.reply_to(message, f"{text_caption}\n\n🔗 Telegram couldn't load the preview, but here is the link: {image_url}")
            else:
                bot.reply_to(message, f"{text_caption}\n\n⚠️ Image Search Issue: {image_url}")
                
        elif "<function=" in answer:
            bot.reply_to(message, "⚠️ Brain glitch detected: Nova tried to write raw tool code. Just ask me one more time!")
            
        else:
            bot.reply_to(message, answer)
            
    except Exception as e:
        bot.reply_to(message, f"⚠️ Frontend UI Error: {str(e)}")

def run_telegram_bot():
    bot.infinity_polling()

@asynccontextmanager
async def lifespan(app: FastAPI):
    thread = threading.Thread(target=run_telegram_bot, daemon=True)
    thread.start()
    yield

app = FastAPI(lifespan=lifespan)

class ChatRequest(BaseModel):
    message: str

class SensorRequest(BaseModel):
    category: str  # one of: sun, earth, mars, moon, saturn

@app.get("/")
def home():
    return {"status": "online", "agent": "Nova", "vision_systems": "connected"}

@app.post("/chat")
def chat(payload: ChatRequest):
    try:
        answer = get_nova_response(payload.message)
        return {"response": answer}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/sensor")
def sensor(payload: SensorRequest):
    """
    ESP32-only endpoint. Stateless — does not touch chat_history,
    completely isolated from Telegram conversations and BRAIN_PROMPT.
    Satellites are NOT handled here (on-device ESP32 filter instead).
    Returns: {"notify": bool, "priority": str, "reason": str}
    """
    try:
        result = gather_sensor_data(payload.category)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
