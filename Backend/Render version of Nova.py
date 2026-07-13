import os
import requests
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
NASA_API_KEY = os.getenv("NASA_API_KEY")
N2YO_API_KEY = os.getenv("N2YO_API_KEY")

if not GROQ_API_KEY:
    raise ValueError("Missing GROQ_API_KEY. Please set it in your environment variables.")

groq_client = Groq(api_key=GROQ_API_KEY)

chat_history = [
    {
        "role": "system",
        "content": "You are Nova, an advanced space and astronomy assistant. You have access to real-time tools for satellites, space weather, and planet physics. Keep responses sharp, accurate, and engaging."
    }
]

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

def process_nova_response(user_input):
    global chat_history
    
    chat_history.append({"role": "user", "content": user_input})
    
    tools = [
        {
            "type": "function",
            "function": {
                "name": "fetch_satellite_telemetry",
                "description": "Get the live latitude, longitude, and altitude coordinates of any satellite or space station using its NORAD ID.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "norad_id": {"type": "string", "description": "The NORAD catalog ID string (e.g., '25544' for ISS)."}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "fetch_space_weather",
                "description": "Get current solar activity updates, flares, and Coronal Mass Ejections (CMEs) from NASA."
            }
        },
        {
            "type": "function",
            "function": {
                "name": "fetch_planet_data",
                "description": "Get real physical characteristics of planets or moons, such as gravity, mass, and moon counts.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "planet_name": {"type": "string", "description": "The name of the planet or moon (e.g., 'mars', 'jupiter')."}
                    },
                    "required": ["planet_name"]
                }
            }
        }
    ]
    
    try:
        response = groq_client.chat.completions.create(
            model="llama3-70b-8192",
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
                function_args = eval(tool_call.function.arguments) if isinstance(tool_call.function.arguments, str) else tool_call.function.arguments
                
                print(f"--- [SYSTEM]: Nova's brain invoked tool: {function_name} ---")
                
                if function_name == "fetch_satellite_telemetry":
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
                model="llama3-70b-8192",
                messages=chat_history
            )
            answer = final_response.choices[0].message.content
        else:
            answer = response_message.content
            
        chat_history.append({"role": "assistant", "content": answer})
        return answer

    except Exception as e:
        return f"Brain Execution Error: {str(e)}"

if __name__ == "__main__":
    print("==================================================")
    print("  NOVA HEADLESS ENGINE ONLINE (Terminal Test mode) ")
    print("==================================================")
    print("Type 'exit' to turn off the brain.\n")
    
    while True:
        query = input("You: ")
        if query.lower() == 'exit':
            break
        
        reply = process_nova_response(query)
        print(f"\nNova: {reply}\n")
