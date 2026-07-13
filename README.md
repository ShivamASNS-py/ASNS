🌌 Ambient Space Notification System (ASNS)
Ever been sitting at your desk and wondered what's happening in space right now? Most of us don't check NASA's website every hour — and if you do, that's honestly impressive.
ASNS is a desk companion that quietly keeps you connected to space. A wall-mounted LED strip runs subtle ambient lighting behind your desk, and shifts into short notification animations when something real happens — a solar flare, an ISS pass overhead, a shift in Earth's weather systems. No app to check, no feed to scroll. Just a glance at your wall.
A compact control unit sits on the desk — a 3D-printed, rounded 11.7 × 10.5 × 6 cm box housing the brains of the system, connected to the LED strip via JST connectors.

# How it works

ESP32-WROVER-IE polls Nova, the AI backend, over HTTPS for space event data.
Nova (built on Groq's llama-3.3-70b-versatile) runs as a hosted web service, pulling from NASA (DONKI, EONET, image library), N2YO (live satellite/ISS telemetry), and Le Système Solaire (planetary data), then deciding what's actually worth surfacing — since raw satellite data alone updates constantly, and without filtering it would drown out every other signal.
A lightweight on-device filter also runs directly on the ESP32, recognizing ~25–50 major satellites (ISS, Hubble, Starlink, etc.) so simple, high-value events — like "ISS visible in 5 minutes!" — can trigger a notification animation without waiting on a full AI round-trip.
When nothing's happening, the WS2812B strip (5m, 300 LEDs) runs a user-selected ambient pattern — Deep Space, Starfield, Moonlight, Aurora, Mars Glow, Solar Wind — in warm, low-brightness tones so it's easy to leave running while working or studying.

When something happens, the strip pauses ambient mode, plays a short notification animation for the relevant category (Mars, Earth, Moon, Sun, Saturn, Satellites), then fades back.
Control unit
The desk unit has a 3.2" IPS display (LVGL UI) and 5 capacitive touch buttons:
Button
Function
◀
Previous (ambient color / notification) or Back
●
Select / Confirm
▶
Next (ambient color / notification)
☰
Menu — Settings, Brightness, Wi-Fi, Sleep, About
⌂
Home — return to main screen instantly
Ambient color is chosen manually from a scrollable bar of 10+ named colors (e.g. Aurora Green). Everything is currently user-selected rather than automatic — you choose what mode you're in.
Hardware
Full parts list with vendors, prices, and photos in BOM.md.
ESP32-WROVER-IE
WS2812B 5V LED strip (5m, 60 LEDs/m — 300 LEDs)
WaveShare 3.2" HDMI IPS Display
TTP223 capacitive touch sensors (×5 active, extras as spares)
74AHCT125 logic level shifter
Mini-360 buck converters
5V/10A SMPS (dedicated LED power rail, separate from control unit power)
Supporting passives (capacitors, resistors, JST connectors)
Enclosure is 3D printed (material TBD — likely PLA or acrylic-finish print), designed to sit unobtrusively on a desk. Wiring diagrams and enclosure sketches/renders are in hardware/.
Software
Firmware (/firmware) — ESP32 C++ code: LVGL UI, LED strip control, on-device satellite filter, communication with Nova.
Backend (/backend) — Nova, the AI layer. Python, ~800+ lines, built on Groq's llama-3.3-70b-versatile. Wrapped as a small web service and hosted on a free-tier cloud platform, so the ESP32 can reach it over HTTPS at all times without relying on a phone or laptop staying on.
APIs used
API
Purpose
Groq (Llama 3.3 70B)
Core reasoning/filtering brain
NASA (DONKI, EONET, image library)
Sun activity, Earth events, imagery
N2YO
Live satellite/ISS telemetry, real-time position
Unsplash
Supplementary imagery for AI responses
Le Système Solaire
Static planetary data (gravity, mass, moons) — no key required
Project status
✅ Backend (Nova) — functionally complete
🔧 Firmware — in progress (on-device filter design, ESP32↔Nova integration pending)
🔧 Hardware — wiring diagrams and enclosure design in progress
🔧 UI/UX — LVGL implementation pending
Known limitation: Nova is being migrated from a manually-run local script to a lightweight hosted web API (free-tier cloud deployment), so it can be reached by the ESP32 over HTTPS at any time. This wrapping/deployment step is in progress.

Setup
Create a .env file in /backend with:
GROQ_API_KEY=
NASA_API_KEY=
UNSPLASH_API_KEY=
N2YO_API_KEY=

Built by a 15-year-old learning PCB design, embedded programming, API integration, AI, and product design — one debug session at a time. Submitted for the Hack Club Macondo grant.