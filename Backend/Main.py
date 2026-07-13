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

# ==========================================
# CONFIGURATION & API KEYS
# ==========================================
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
NASA_API_KEY = os.getenv("NASA_API_KEY")
N2YO_API_KEY = os.getenv("N2YO_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SERPER_API_KEY = os.getenv("SERPER_API_KEY")

if not GROQ_API_KEY or not TELEGRAM_BOT_TOKEN:
    raise ValueError("Missing critical API keys.")

groq_client = Groq(api_key=GROQ_API_KEY)
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

chat_history = [
    {
        "role": "system",
        "content": (
            "You are Nova, a highly intelligent and versatile AI assistant with a 70B parameter knowledge base. "
            "You can explain any topic. Answer ANY question the user asks. You have access to real-time tools for satellites, "
            "space weather, planet physics, and web image searches. When a user asks to see an image, photo, or picture, "
            "use your provided image search tool to find it. Do not attempt to write the function call in text. "
            "CRITICAL: When the tool returns a URL, construct your natural response and ALWAYS append exactly "
            "' | IMAGE_URL: <url>' to the absolute end of your final message so the UI can render it as a real picture."
        )
    }
]


# ==========================================
# SENSOR & VISION TOOLS (SERPER POWERED)
# ==========================================
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

# ==========================================
# CORE BRAIN LOGIC
# ==========================================
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
            model="llama-3.3-70b-versatile",
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
                
                # Safely parsing JSON string arguments instead of using hazardous eval()
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
                model="llama-3.3-70b-versatile",
                messages=chat_history
            )
            answer = final_response.choices[0].message.content
        else:
            answer = response_message.content
            
        chat_history.append({"role": "assistant", "content": answer})
        return answer

    except Exception as e:
        return f"Brain Execution Error: {str(e)}"

# ==========================================
# TELEGRAM FRONTEND WITH OPTICAL UPGRADE
# ==========================================
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(
        message, 
        "🚀 *Nova System Unlocked.* I am running live on Llama 3.3 70B with active vision channels. Ask me anything, or ask for a picture!",
        parse_mode="Markdown"
    )

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    bot.send_chat_action(message.chat.id, 'upload_photo' if 'image' in message.text.lower() or 'photo' in message.text.lower() else 'typing')
    try:
        answer = get_nova_response(message.text)
        
        # Check if Nova injected an image token
        if " | IMAGE_URL:" in answer:
            parts = answer.split(" | IMAGE_URL:")
            text_caption = parts[0].strip()
            image_url = parts[1].strip()
            
            # SAFETY CHECK: Does the URL actually look like a web link?
            if image_url.startswith("http"):
                bot.send_photo(message.chat.id, image_url, caption=text_caption)
            else:
                # If it's an error message instead of a URL, send it as normal text
                bot.reply_to(message, f"{text_caption}\n\n⚠️ Image Search Issue: {image_url}")
        else:
            bot.reply_to(message, answer)
            
    except Exception as e:
        bot.reply_to(message, f"⚠️ Frontend UI Error: {str(e)}")


def run_telegram_bot():
    bot.infinity_polling()

# ==========================================
# FASTAPI BACKEND SETUP
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Igniting Telegram Optical Worker...")
    thread = threading.Thread(target=run_telegram_bot, daemon=True)
    thread.start()
    yield

app = FastAPI(lifespan=lifespan)

class ChatRequest(BaseModel):
    message: str

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
