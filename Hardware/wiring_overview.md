## Wiring Diagram

The full wiring diagram (`Wiring_Diagram.png`) covers the complete electrical setup for the ASNS control unit, including:

1. **Power input** — 5V 10A SMPS feeding the system via JST connector
2. **Buck converter** — Mini-360 DC-DC converter providing a stable 5V rail
3. **Power distribution** — 5V/GND bus feeding the ESP32, display, level shifter, touch sensors, and LED output capacitor
4. **Display** — 3.5" SPI TFT (ILI9488) connected directly to ESP32 GPIOs
5. **Level shifter & LED output** — 74AHCT125 stepping the ESP32's data line up for the WS2812B strip, plus a smoothing capacitor near the LED output connector
6. **LED strip power injection** — dual injection points (start and far end of the 5m strip) to prevent voltage drop across the run
7. **GPIO pin summary** — full mapping of ESP32 pins to display, touch sensors, and LED data
8. **JST connector pinouts** — power input and LED strip output
9. **General wiring notes** — common grounding, wire gauge, and brightness-limiting guidance

This diagram was AI-generated based on my BOM and finalized pin assignments, since I don't have access to diagramming software on mobile. I reviewed it against my actual components and confirmed it matches the hardware I'm using.
