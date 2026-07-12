import os
import re
import io
import json
import random
import threading
import time
import requests
from PIL import Image
import customtkinter as ctk
from tkinter import messagebox
from groq import Groq

# ============================================================================
# API KEYS (Paste yours here)
# ============================================================================
GROQ_API_KEY = "Paste_Here"
UNSPLASH_API_KEY = "Paste_Here"
NASA_API_KEY = "Paste_Here"
N2YO_API_KEY = "Paste_Here"

MODEL_NAME = "llama-3.3-70b-versatile"
MAX_HISTORY_TURNS = 10
HISTORY_FILE = "nova_history.json"

# The expanded multi-tool brain
SYSTEM_PROMPT = """You are Nova AI, an advanced Space Dashboard assistant.
You have access to live databases. Trigger tools by appending a secret tag at the end of your response.

IMAGE TOOLS:
1. [IMAGE_NASA: search_term] - For NASA pictures.
2. [IMAGE_UNSPLASH: search_term] - For general pictures.

DATA TOOLS (Use these if the user asks for LIVE stats, weather, or tracking):
3. [DATA_PLANET: planet_name] - For gravity, moons, and physical stats of planets/moons (e.g., Saturn, Earth, Moon).
4. [DATA_SUN] - For live Space Weather (Coronal Mass Ejections) from NASA DONKI.
5. [DATA_EARTH] - For live Earth events (Wildfires, Volcanoes) from NASA EONET.
6. [DATA_SATELLITE: norad_id] - For live satellite tracking. MUST use the 5-digit NORAD ID (e.g., ISS is 25544, Hubble is 20580).

Example response: "The ISS orbits Earth at high speeds. [DATA_SATELLITE: 25544] [IMAGE_NASA: ISS]"
You can combine ONE data tool and ONE image tool per response. Do not use tags if not needed."""

GREETINGS = {"hi", "hello", "hey", "yo", "hiya", "good morning", "good evening"}
MATH_PATTERN = re.compile(r"^\s*-?\d+(\.\d+)?\s*([+\-*/])\s*-?\d+(\.\d+)?\s*$")
BANNED_TERMS = ["explosive_synthesis", "malware_payload"]

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

def route_intent(text: str) -> str:
    t = text.lower().strip()
    if t.rstrip("!?.") in GREETINGS:
        return "greeting"
    if MATH_PATTERN.match(t):
        return "math"
    return "chat"

def safe_eval_math(expr: str) -> str:
    match = re.match(r"^\s*(-?\d+(?:\.\d+)?)\s*([+\-*/])\s*(-?\d+(?:\.\d+)?)\s*$", expr)
    if not match:
        return "I couldn't parse that as simple arithmetic."
    a, op, b = float(match.group(1)), match.group(2), float(match.group(3))
    try:
        if op == "+": result = a + b
        elif op == "-": result = a - b
        elif op == "*": result = a * b
        elif op == "/":
            if b == 0: return "Division by zero is undefined."
            result = a / b
        if result == int(result): result = int(result)
        return f"{expr.strip()} = {result}"
    except Exception as e:
        return f"Math error: {e}"

def run_safety_filter(text: str) -> bool:
    flagged = [term for term in BANNED_TERMS if term in text.lower()]
    return len(flagged) == 0

class NovaApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Nova AI")
        self.geometry("1080x2400")
        self.configure(fg_color="#0D0D0D")

        self.screen_width = self.winfo_screenwidth()
        self.bubble_width = int(self.screen_width * 0.75)
        self.image_width = int(self.screen_width * 0.70)

        self.master_history = {}
        self.current_chat_id = None
        self.chat_started = False
        self.stop_requested = False
        self.sidebar_open = False
        
        self.is_thinking = False
        self.thinking_frame = None
        self.thinking_label = None
        
        self._drag_state = {"active": False, "last_y": 0, "canvas": None}

        if GROQ_API_KEY == "PASTE_YOUR_GROQ_KEY_HERE" or not GROQ_API_KEY:
            messagebox.showerror("Configuration Error", "Please insert your Groq API key in the code.")
            self.destroy()
            return
            
        try:
            self.client = Groq(api_key=GROQ_API_KEY)
        except Exception as e:
            messagebox.showerror("API Error", f"Failed to initialize Groq: {e}")
            self.destroy()
            return

        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._load_master_history()
        self._build_header()
        self._build_welcome_screen()
        self._build_chat_display()
        self._build_input_area()
        self._build_sidebar()
        
        if self.master_history:
            most_recent_id = list(self.master_history.keys())[-1]
            self.load_chat_by_id(most_recent_id)
        else:
            self._start_new_chat_session()

    # ========================================================================
    # Touch Scrolling
    # ========================================================================
    def _bind_touch_scroll(self, widget):
        widget.bind("<ButtonPress-1>", self._on_drag_start, add="+")
        widget.bind("<B1-Motion>", self._on_drag_motion, add="+")
        widget.bind("<ButtonRelease-1>", self._on_drag_end, add="+")

    def _on_drag_start(self, event):
        self._drag_state["active"] = True
        self._drag_state["last_y"] = event.y_root
        
        parent = event.widget
        while parent:
            if isinstance(parent, ctk.CTkScrollableFrame):
                self._drag_state["canvas"] = parent._parent_canvas
                break
            try:
                parent = parent.master
            except AttributeError:
                break

    def _on_drag_motion(self, event):
        if not self._drag_state["active"] or self._drag_state["canvas"] is None:
            return
        delta_y = event.y_root - self._drag_state["last_y"]
        self._drag_state["last_y"] = event.y_root
        if delta_y != 0:
            self._drag_state["canvas"].yview_scroll(int(-delta_y / 2), "units")

    def _on_drag_end(self, event):
        self._drag_state["active"] = False
        self._drag_state["canvas"] = None

    # ========================================================================
    # UI Builders & Sidebar
    # ========================================================================
    def _build_header(self):
        self.header_frame = ctk.CTkFrame(self, fg_color="#0D0D0D", height=80, corner_radius=0)
        self.header_frame.grid(row=0, column=0, sticky="ew")
        
        self.menu_btn = ctk.CTkButton(
            self.header_frame, text="≡", width=60, height=60, fg_color="transparent", 
            hover_color="#1a1a1a", text_color="white", font=("Segoe UI", 50),
            command=self.toggle_sidebar
        )
        self.menu_btn.pack(side="left", padx=10, pady=10)
        
        self.header_title = ctk.CTkLabel(
            self.header_frame, text="Nova AI", font=("Segoe UI", 36, "bold"), text_color="white"
        )
        self.header_title.pack(side="left", padx=20)

    def _build_sidebar(self):
        self.sidebar_frame = ctk.CTkFrame(self, fg_color="#1a1a1a", width=800, corner_radius=0)
        sb_header = ctk.CTkFrame(self.sidebar_frame, fg_color="transparent")
        sb_header.pack(fill="x", padx=20, pady=20)
        
        close_btn = ctk.CTkButton(
            sb_header, text="✕", width=50, height=50, fg_color="transparent", 
            hover_color="#333333", text_color="white", font=("Segoe UI", 35),
            command=self.toggle_sidebar
        )
        close_btn.pack(side="right")
        
        new_chat_btn = ctk.CTkButton(
            self.sidebar_frame, text="+ New Chat", height=70, fg_color="#0056b3", 
            hover_color="#004494", text_color="white", font=("Segoe UI", 32, "bold"),
            command=self.handle_new_chat
        )
        new_chat_btn.pack(fill="x", padx=20, pady=10)
        
        self.chat_list_frame = ctk.CTkScrollableFrame(self.sidebar_frame, fg_color="transparent")
        self.chat_list_frame.pack(fill="both", expand=True, padx=10, pady=10)
        self._bind_touch_scroll(self.chat_list_frame._parent_canvas)
        self._bind_touch_scroll(self.chat_list_frame._parent_frame)

    def _build_welcome_screen(self):
        self.welcome_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.welcome_frame.grid(row=1, column=0, sticky="nsew", padx=20, pady=20)
        self.welcome_frame.grid_columnconfigure((0, 1), weight=1)

        logo_label = ctk.CTkLabel(self.welcome_frame, text="✨", font=("Segoe UI", 150))
        logo_label.grid(row=0, column=0, columnspan=2, pady=(150, 20))

        welcome_label = ctk.CTkLabel(
            self.welcome_frame, text="How can I help you today?",
            font=("Segoe UI", 40, "bold"), text_color="white"
        )
        welcome_label.grid(row=1, column=0, columnspan=2, pady=(0, 60))

        suggestions = [
            ("Track the ISS", 2, 0), ("Live Earth Events", 2, 1),
            ("Gravity of Mars", 3, 0), ("Picture of Saturn", 3, 1)
        ]

        for text, r, c in suggestions:
            btn = ctk.CTkButton(
                self.welcome_frame, text=text, fg_color="transparent",
                border_width=1.5, border_color="#333333", text_color="#dddddd",
                hover_color="#1a1a1a", corner_radius=30, height=70,
                font=("Segoe UI", 35),
                command=lambda t=text: self._suggestion_clicked(t)
            )
            btn.grid(row=r, column=c, padx=10, pady=10, sticky="ew")

    def _build_chat_display(self):
        self.chat_display = ctk.CTkScrollableFrame(self, fg_color="transparent", bg_color="transparent")
        self._bind_touch_scroll(self.chat_display._parent_canvas)
        self._bind_touch_scroll(self.chat_display._parent_frame)

    def _build_input_area(self):
        self.input_frame = ctk.CTkFrame(self, fg_color="#1a1a1a", corner_radius=40)
        self.input_frame.grid(row=2, column=0, sticky="ew", padx=20, pady=(0, 30))
        self.input_frame.grid_columnconfigure(0, weight=1)

        self.entry = ctk.CTkEntry(
            self.input_frame, placeholder_text="Message Nova AI...",
            border_width=0, fg_color="transparent", text_color="white",
            font=("Segoe UI", 40), height=80
        )
        self.entry.grid(row=0, column=0, padx=(30, 10), pady=10, sticky="ew")
        self.entry.bind("<Return>", lambda event: self.handle_send())

        self.send_btn = ctk.CTkButton(
            self.input_frame, text="↑", width=70, height=70, corner_radius=35,
            fg_color="#333333", hover_color="#555555", text_color="white",
            font=("Segoe UI", 32, "bold"), command=self.handle_send
        )
        self.send_btn.grid(row=0, column=1, padx=(0, 15), pady=10)

    def toggle_sidebar(self):
        if not self.sidebar_open:
            self.sidebar_frame.place(relx=0, rely=0, relheight=1, relwidth=0.75)
            self._refresh_sidebar_list()
            self.sidebar_open = True
        else:
            self.sidebar_frame.place_forget()
            self.sidebar_open = False

    def _refresh_sidebar_list(self):
        for widget in self.chat_list_frame.winfo_children():
            widget.destroy()
            
        for chat_id in reversed(list(self.master_history.keys())):
            title = self.master_history[chat_id].get("title", "New Chat")
            
            row_frame = ctk.CTkFrame(self.chat_list_frame, fg_color="transparent")
            row_frame.pack(fill="x", pady=2, padx=5)

            btn = ctk.CTkButton(
                row_frame, text=title, height=60, fg_color="transparent", 
                hover_color="#2a2a2a", text_color="#dddddd", font=("Segoe UI", 30),
                anchor="w", command=lambda cid=chat_id: self.load_chat_by_id(cid)
            )
            btn.pack(side="left", fill="x", expand=True)

            opt_btn = ctk.CTkButton(
                row_frame, text="⋮", width=50, height=60, fg_color="transparent", 
                hover_color="#444444", text_color="#aaaaaa", font=("Segoe UI", 30, "bold"),
                command=lambda cid=chat_id: self.open_chat_options(cid)
            )
            opt_btn.pack(side="right", padx=(5, 0))

            self._bind_touch_scroll(btn)
            self._bind_touch_scroll(opt_btn)
            self._bind_touch_scroll(row_frame)

    def open_chat_options(self, chat_id):
        options_window = ctk.CTkToplevel(self)
        options_window.title("Options")
        options_window.geometry("700x450")
        options_window.configure(fg_color="#1a1a1a")
        options_window.transient(self)
        options_window.grab_set()

        lbl = ctk.CTkLabel(options_window, text="Chat Options", font=("Segoe UI", 35, "bold"), text_color="white")
        lbl.pack(pady=40)

        ren_btn = ctk.CTkButton(
            options_window, text="Rename Chat", height=70, font=("Segoe UI", 32), 
            command=lambda: self.rename_chat(chat_id, options_window)
        )
        ren_btn.pack(fill="x", padx=60, pady=15)

        del_btn = ctk.CTkButton(
            options_window, text="Delete Chat", height=70, fg_color="#cc0000", hover_color="#ff3333", 
            font=("Segoe UI", 32), command=lambda: self.delete_chat(chat_id, options_window)
        )
        del_btn.pack(fill="x", padx=60, pady=15)

        can_btn = ctk.CTkButton(
            options_window, text="Cancel", height=70, fg_color="transparent", border_width=2, 
            border_color="#555", font=("Segoe UI", 32), command=options_window.destroy
        )
        can_btn.pack(fill="x", padx=60, pady=15)

    def rename_chat(self, chat_id, window):
        window.destroy()
        dialog = ctk.CTkInputDialog(text="Enter new name for this chat:", title="Rename Chat")
        new_name = dialog.get_input()
        
        if new_name and new_name.strip():
            self.master_history[chat_id]["title"] = new_name.strip()
            if self.current_chat_id == chat_id:
                self.header_title.configure(text=new_name.strip())
            self._save_master_history()
            self._refresh_sidebar_list()

    def delete_chat(self, chat_id, window):
        window.destroy()
        if chat_id in self.master_history:
            del self.master_history[chat_id]
            self._save_master_history()
            self._refresh_sidebar_list()
            
            if self.current_chat_id == chat_id:
                if self.master_history:
                    next_id = list(self.master_history.keys())[-1]
                    self.load_chat_by_id(next_id)
                else:
                    self._start_new_chat_session()

    def _start_new_chat_session(self):
        self._remove_thinking_bubble()
        self.current_chat_id = str(int(time.time()))
        self.master_history[self.current_chat_id] = {"title": "New Chat", "history": []}
        self.header_title.configure(text="Nova AI")
        self._clear_chat_display()
        self.chat_display.grid_forget()
        self.welcome_frame.grid(row=1, column=0, sticky="nsew", padx=20, pady=20)
        self.chat_started = False

    def handle_new_chat(self):
        self.toggle_sidebar()
        self._start_new_chat_session()

    def load_chat_by_id(self, chat_id):
        self._remove_thinking_bubble()
        self.current_chat_id = chat_id
        chat_data = self.master_history[chat_id]
        
        self.header_title.configure(text=chat_data["title"])
        self._clear_chat_display()
        self.welcome_frame.grid_forget()
        self.chat_display.grid(row=1, column=0, sticky="nsew", padx=10, pady=(20, 10))
        self.chat_started = True
        
        for msg in chat_data["history"]:
            clean_content = msg["content"]
            # Clean ALL tags from history display
            clean_content = re.sub(r"\[.*?\]", "", clean_content).strip()

            if msg["role"] == "user":
                self.add_user_bubble(clean_content)
            elif msg["role"] == "assistant":
                _, bot_label = self.add_bot_bubble()
                bot_label.configure(text=clean_content)
                
        self.after(100, self._scroll_to_bottom)
        if self.sidebar_open:
            self.toggle_sidebar()

    def _clear_chat_display(self):
        for widget in self.chat_display.winfo_children():
            widget.destroy()

    def _suggestion_clicked(self, text):
        self.entry.delete(0, "end")
        self.entry.insert(0, text)
        self.handle_send()

    def _scroll_to_bottom(self):
        self.chat_display._parent_canvas.yview_moveto(1.0)

    # ========================================================================
    # Visual Bubbles & Animations
    # ========================================================================
    def add_user_bubble(self, message):
        row_frame = ctk.CTkFrame(self.chat_display, fg_color="transparent")
        row_frame.pack(fill="x", pady=10, padx=10)

        bubble = ctk.CTkFrame(row_frame, fg_color="#2f2f2f", corner_radius=25)
        bubble.pack(side="right", anchor="e", padx=(50, 0))

        msg_label = ctk.CTkLabel(
            bubble, text=message, text_color="#ffffff", font=("Segoe UI", 40),
            wraplength=self.bubble_width, justify="left"
        )
        msg_label.pack(padx=25, pady=20)

        self._bind_touch_scroll(row_frame)
        self._bind_touch_scroll(bubble)
        self._bind_touch_scroll(msg_label)
        self._scroll_to_bottom()

    def add_bot_bubble(self):
        row_frame = ctk.CTkFrame(self.chat_display, fg_color="transparent")
        row_frame.pack(fill="x", pady=15, padx=10)

        bubble = ctk.CTkFrame(row_frame, fg_color="transparent")
        bubble.pack(side="left", anchor="w", padx=(0, 10))

        msg_label = ctk.CTkLabel(
            bubble, text="", text_color="#e5e5e5", font=("Segoe UI", 45),
            wraplength=self.bubble_width, justify="left", width=self.bubble_width, anchor="nw"
        )
        msg_label.pack(padx=10, pady=5)

        self._bind_touch_scroll(row_frame)
        self._bind_touch_scroll(bubble)
        self._bind_touch_scroll(msg_label)
        self._scroll_to_bottom()

        return bubble, msg_label

    def _add_thinking_bubble(self):
        self.thinking_frame = ctk.CTkFrame(self.chat_display, fg_color="transparent")
        self.thinking_frame.pack(fill="x", pady=15, padx=10)

        bubble = ctk.CTkFrame(self.thinking_frame, fg_color="#222222", corner_radius=25)
        bubble.pack(side="left", anchor="w", padx=(0, 10))

        self.thinking_label = ctk.CTkLabel(
            bubble, text="✨ Thinking.", text_color="#aaaaaa", font=("Segoe UI", 40)
        )
        self.thinking_label.pack(padx=20, pady=15)
        
        self._scroll_to_bottom()

    def _animate_thinking(self, dot_count):
        if not self.is_thinking or not self.thinking_label or not self.thinking_label.winfo_exists():
            return
        
        dots = "." * dot_count
        self.thinking_label.configure(text=f"✨ Thinking{dots}")
        
        next_count = dot_count + 1 if dot_count < 3 else 1
        self.after(400, self._animate_thinking, next_count)

    def _remove_thinking_bubble(self):
        self.is_thinking = False
        if self.thinking_frame and self.thinking_frame.winfo_exists():
            self.thinking_frame.destroy()
        self.thinking_label = None
        self.thinking_frame = None

    def _inject_error_to_ui(self, parent_frame, error_text):
        err_label = ctk.CTkLabel(parent_frame, text=error_text, text_color="#ff5555", font=("Segoe UI", 35, "italic"))
        err_label.pack(padx=10, pady=10, anchor="w")
        self._bind_touch_scroll(err_label)
        self._scroll_to_bottom()

    def _inject_data_card(self, parent_frame, text):
        """Creates a beautiful blue dashboard card inside the chat bubble"""
        card = ctk.CTkFrame(parent_frame, fg_color="#004488", corner_radius=15)
        card.pack(padx=10, pady=(5, 15), anchor="w")
        
        lbl = ctk.CTkLabel(
            card, text=text, text_color="white", font=("Segoe UI", 35), justify="left"
        )
        lbl.pack(padx=20, pady=20, anchor="w")
        
        self._bind_touch_scroll(card)
        self._bind_touch_scroll(lbl)
        self._scroll_to_bottom()

    # ========================================================================
    # Logic & Interception 
    # ========================================================================
    def handle_send(self):
        user_message = self.entry.get().strip()
        if not user_message:
            return
            
        if not self.master_history[self.current_chat_id]["history"]:
            title = user_message[:25] + "..." if len(user_message) > 25 else user_message
            self.master_history[self.current_chat_id]["title"] = title
            self.header_title.configure(text=title)

        if not self.chat_started:
            self.welcome_frame.grid_forget()
            self.chat_display.grid(row=1, column=0, sticky="nsew", padx=10, pady=(20, 10))
            self.chat_started = True

        self.stop_requested = False
        self.entry.delete(0, "end")
        self.entry.configure(state='disabled')
        self.send_btn.configure(text="■", fg_color="#cc0000", hover_color="#ff3333", command=self.handle_stop)

        self.add_user_bubble(user_message)
        
        self.is_thinking = True
        self._add_thinking_bubble()
        self._animate_thinking(1)
        
        threading.Thread(target=self.process_message, args=(user_message,), daemon=True).start()

    def handle_stop(self):
        self.stop_requested = True
        self._remove_thinking_bubble()
        self._reset_input_ui()

    def _reset_input_ui(self):
        self.entry.configure(state='normal')
        self.send_btn.configure(text="↑", fg_color="#333333", hover_color="#555555", command=self.handle_send)
        self.entry.focus()

    def process_message(self, user_message):
        intent = route_intent(user_message)
        
        img_tool = None
        img_query = None
        data_tool = None
        data_query = None

        if intent == "greeting":
            final_response = "Hello! How can I help you today?"
        elif intent == "math":
            final_response = safe_eval_math(user_message)
        else:
            final_response = self.call_groq(user_message)

            # Check for Images
            match_img_nasa = re.search(r"\[IMAGE_NASA:\s*(.*?)\]", final_response)
            match_img_unsplash = re.search(r"\[IMAGE_UNSPLASH:\s*(.*?)\]", final_response)
            if match_img_nasa:
                img_query = match_img_nasa.group(1).strip()
                img_tool = "nasa"
            elif match_img_unsplash:
                img_query = match_img_unsplash.group(1).strip()
                img_tool = "unsplash"

            # Check for Data Dashboards
            match_data_planet = re.search(r"\[DATA_PLANET:\s*(.*?)\]", final_response)
            match_data_sun = re.search(r"\[DATA_SUN\]", final_response)
            match_data_earth = re.search(r"\[DATA_EARTH\]", final_response)
            match_data_sat = re.search(r"\[DATA_SATELLITE:\s*(.*?)\]", final_response)

            if match_data_planet:
                data_query = match_data_planet.group(1).strip()
                data_tool = "planet"
            elif match_data_sun:
                data_tool = "sun"
            elif match_data_earth:
                data_tool = "earth"
            elif match_data_sat:
                data_query = match_data_sat.group(1).strip()
                data_tool = "satellite"

            # Scrub all tags from the text so the user doesn't see them
            final_response = re.sub(r"\[.*?\]", "", final_response).strip()

        if not run_safety_filter(final_response):
            final_response = "I can't share that."

        if self.stop_requested:
            return

        self.after(0, self._start_typewriter, final_response, img_tool, img_query, data_tool, data_query)

    def _start_typewriter(self, full_text, img_tool, img_query, data_tool, data_query):
        self._remove_thinking_bubble()
        bubble_frame, bot_label = self.add_bot_bubble()

        # Start API Fetchers in Background
        if img_tool == "nasa":
            threading.Thread(target=self._search_and_inject_image_nasa, args=(img_query, bubble_frame), daemon=True).start()
        elif img_tool == "unsplash":
            threading.Thread(target=self._search_and_inject_image_unsplash, args=(img_query, bubble_frame), daemon=True).start()

        if data_tool:
            threading.Thread(target=self._fetch_and_inject_data, args=(data_tool, data_query, bubble_frame), daemon=True).start()

        self._type_character(bot_label, full_text, 0)

    def _type_character(self, label, full_text, current_index):
        if self.stop_requested:
            return

        if current_index < len(full_text):
            chunk_size = random.randint(6, 12)
            next_index = current_index + chunk_size
            label.configure(text=full_text[:next_index])
            
            delay = random.randint(10, 25)
            self.after(delay, self._type_character, label, full_text, next_index)
        else:
            self._reset_input_ui()
            self._scroll_to_bottom()

    # ========================================================================
    # Image API Fetchers
    # ========================================================================
    def _search_and_inject_image_nasa(self, search_term, parent_frame):
        try:
            headers = {'User-Agent': 'NovaAI/1.0 (Python App)'}
            clean_term = re.sub(r'[^\w\s]', '', search_term)
            query = requests.utils.quote(clean_term)
            
            search_url = f"https://images-api.nasa.gov/search?q={query}&media_type=image"
            response = requests.get(search_url, headers=headers, timeout=30)
            
            if response.status_code != 200:
                self.after(0, self._inject_error_to_ui, parent_frame, f"[NASA Image API Error: HTTP {response.status_code}]")
                return

            search_data = response.json()
            items = search_data.get("collection", {}).get("items", [])
            
            if not items:
                self.after(0, self._inject_error_to_ui, parent_frame, f"[No NASA images found for '{clean_term}']")
                return

            img_url = items[0]["links"][0]["href"]
            
            img_response = requests.get(img_url, headers=headers, timeout=30)
            img_data = img_response.content
            image = Image.open(io.BytesIO(img_data))
            
            w_percent = (self.image_width / float(image.size[0]))
            h_size = int((float(image.size[1]) * float(w_percent)))
            image = image.resize((self.image_width, h_size), Image.LANCZOS)
            ctk_img = ctk.CTkImage(light_image=image, dark_image=image, size=(self.image_width, h_size))

            if not self.stop_requested:
                self.after(0, self._inject_image_to_ui, parent_frame, ctk_img)
        except Exception as e:
            self.after(0, self._inject_error_to_ui, parent_frame, f"[NASA Image Error: {str(e)}]")

    def _search_and_inject_image_unsplash(self, search_term, parent_frame):
        try:
            if UNSPLASH_API_KEY == "PASTE_UNSPLASH_KEY_HERE" or not UNSPLASH_API_KEY:
                self.after(0, self._inject_error_to_ui, parent_frame, "[Error: Unsplash API key missing]")
                return

            headers = {'User-Agent': 'NovaAI/1.0', 'Authorization': f'Client-ID {UNSPLASH_API_KEY}'}
            clean_term = re.sub(r'[^\w\s]', '', search_term)
            query = requests.utils.quote(clean_term)
            
            search_url = f"https://api.unsplash.com/search/photos?query={query}&per_page=1"
            response = requests.get(search_url, headers=headers, timeout=30)
            
            if response.status_code != 200:
                self.after(0, self._inject_error_to_ui, parent_frame, f"[Unsplash API Error: HTTP {response.status_code}]")
                return

            results = response.json().get("results", [])
            if not results:
                self.after(0, self._inject_error_to_ui, parent_frame, f"[No Unsplash images found for '{clean_term}']")
                return

            img_url = results[0]["urls"]["regular"]
            img_response = requests.get(img_url, headers=headers, timeout=30)
            img_data = img_response.content

            image = Image.open(io.BytesIO(img_data))
            w_percent = (self.image_width / float(image.size[0]))
            h_size = int((float(image.size[1]) * float(w_percent)))
            image = image.resize((self.image_width, h_size), Image.LANCZOS)
            ctk_img = ctk.CTkImage(light_image=image, dark_image=image, size=(self.image_width, h_size))

            if not self.stop_requested:
                self.after(0, self._inject_image_to_ui, parent_frame, ctk_img)
        except Exception as e:
            self.after(0, self._inject_error_to_ui, parent_frame, f"[Unsplash Image Error: {str(e)}]")

    def _inject_image_to_ui(self, parent_frame, ctk_img):
        img_label = ctk.CTkLabel(parent_frame, image=ctk_img, text="", corner_radius=15)
        img_label.pack(padx=10, pady=15, anchor="w")
        self._bind_touch_scroll(img_label)
        self._scroll_to_bottom()

    # ========================================================================
    # Data API Fetchers (NEW)
    # ========================================================================
    def _fetch_and_inject_data(self, tool, query, parent_frame):
        try:
            if tool == "planet":
                url = f"https://api.le-systeme-solaire.net/rest/bodies/{query.lower().strip()}"
                res = requests.get(url, timeout=10)
                if res.status_code == 200:
                    data = res.json()
                    moons = len(data.get('moons', [])) if data.get('moons') else 0
                    grav = data.get('gravity', 'N/A')
                    mass_val = data.get('mass', {}).get('massValue', 'N/A')
                    mass_exp = data.get('mass', {}).get('massExponent', '')
                    info = f"🪐 {data.get('englishName', 'Planet')} Database\nGravity: {grav} m/s²\nMoons: {moons}\nMass: {mass_val}x10^{mass_exp} kg"
                    self.after(0, self._inject_data_card, parent_frame, info)
                else:
                    self.after(0, self._inject_error_to_ui, parent_frame, f"[Planet Database Error: Not Found]")

            elif tool == "sun":
                if NASA_API_KEY == "PASTE_NASA_KEY_HERE":
                    self.after(0, self._inject_error_to_ui, parent_frame, "[Error: NASA API Key Missing]")
                    return
                url = f"https://api.nasa.gov/DONKI/CME?api_key={NASA_API_KEY}"
                res = requests.get(url, timeout=10)
                if res.status_code == 200:
                    data = res.json()
                    if data:
                        latest = data[-1]
                        date = latest.get("startTime", "Unknown").split("T")[0]
                        note = latest.get("note", "No note available.").split(".")[0]
                        info = f"☀️ Space Weather (DONKI)\nLatest CME: {date}\n{note}."
                        self.after(0, self._inject_data_card, parent_frame, info)
                else:
                    self.after(0, self._inject_error_to_ui, parent_frame, f"[DONKI Error: HTTP {res.status_code}]")

            elif tool == "earth":
                url = "https://eonet.gsfc.nasa.gov/api/v3/events?limit=3"
                res = requests.get(url, timeout=10)
                if res.status_code == 200:
                    data = res.json()
                    events = [ev.get('title', '') for ev in data.get('events', [])]
                    ev_str = "\n".join([f"• {e}" for e in events])
                    info = f"🌍 Live Earth Events (EONET)\n{ev_str}"
                    self.after(0, self._inject_data_card, parent_frame, info)
                else:
                    self.after(0, self._inject_error_to_ui, parent_frame, f"[EONET Error: HTTP {res.status_code}]")

            elif tool == "satellite":
                if N2YO_API_KEY == "PASTE_N2YO_KEY_HERE":
                    self.after(0, self._inject_error_to_ui, parent_frame, "[Error: N2YO API Key Missing]")
                    return
                url = f"https://api.n2yo.com/rest/v1/satellite/positions/{query.strip()}/0/0/0/1/&apiKey={N2YO_API_KEY}"
                res = requests.get(url, timeout=10)
                if res.status_code == 200:
                    data = res.json()
                    name = data.get('info', {}).get('satname', 'Unknown')
                    pos = data.get('positions', [{}])[0]
                    lat = pos.get('satlatitude', 'N/A')
                    lng = pos.get('satlongitude', 'N/A')
                    alt = pos.get('sataltitude', 'N/A')
                    info = f"🛰️ Live Tracker: {name}\nLatitude: {lat}\nLongitude: {lng}\nAltitude: {alt} km"
                    self.after(0, self._inject_data_card, parent_frame, info)
                else:
                    self.after(0, self._inject_error_to_ui, parent_frame, f"[N2YO Error: HTTP {res.status_code}]")

        except Exception as e:
            self.after(0, self._inject_error_to_ui, parent_frame, f"[Data Fetch Error: {str(e)}]")

    # ========================================================================
    # Core LLM Call
    # ========================================================================
    def call_groq(self, user_message: str) -> str:
        try:
            chat_hist = self.master_history[self.current_chat_id]["history"]
            messages_payload = [{"role": "system", "content": SYSTEM_PROMPT}] + chat_hist + [{"role": "user", "content": user_message}]

            chat_completion = self.client.chat.completions.create(
                messages=messages_payload,
                model=MODEL_NAME
            )
            response = chat_completion.choices[0].message.content.strip()

            chat_hist.append({"role": "user", "content": user_message})
            chat_hist.append({"role": "assistant", "content": response})

            if len(chat_hist) > MAX_HISTORY_TURNS * 2:
                self.master_history[self.current_chat_id]["history"] = chat_hist[-MAX_HISTORY_TURNS * 2:]
            
            self._save_master_history()
            return response
        except Exception as e:
            return f"[API Error: {e}]"

    def _save_master_history(self):
        try:
            with open(HISTORY_FILE, "w") as f:
                json.dump(self.master_history, f)
        except:
            pass

    def _load_master_history(self):
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, "r") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        self.master_history = {str(int(time.time())): {"title": "Old Chat", "history": data}}
                    else:
                        self.master_history = data
            except:
                self.master_history = {}
        else:
            self.master_history = {}

if __name__ == "__main__":
    app = NovaApp()
    app.mainloop()
