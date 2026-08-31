#!/usr/bin/env python3
"""
screen_translate.py
====================
Background screen-capture translation tool.

  F7                      -> interactive "freeze & snip" capture
  Ctrl + F7               -> instant capture of the saved preset box
  Ctrl + Alt + Shift + F7 -> interactive box selection to set & save preset area

Overlay Controls:
  - Left Mouse Drag: Select region
  - Right Mouse Click / ESC: Cancel

Config:
  - Position, window size, preset coordinates, and font size are stored
    in 'config.json' next to the script.
"""

import os
import sys
import json
import queue
import warnings
import threading
import traceback
from dataclasses import dataclass, field
from typing import Optional, Tuple, List

# Suppress SDK Automatic Function Calling (AFC) warning
warnings.filterwarnings("ignore", message=".*Direct use of automatic function calling.*")

# Load .env file if available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    _env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(_env_path):
        with open(_env_path, "r", encoding="utf-8") as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    _k, _v = _line.split("=", 1)
                    os.environ.setdefault(_k.strip(), _v.strip("'\" "))

import tkinter as tk
from tkinter import ttk, scrolledtext
from PIL import Image, ImageGrab, ImageTk, ImageDraw, ImageFont

try:
    import keyboard
except ImportError:
    keyboard = None

try:
    from google import genai
    from google.genai import types
    try:
        from google.genai.models import Models
        Models._logged_afc_warning = True
    except Exception:
        pass
except ImportError:
    genai = None
    types = None

try:
    import mss
except ImportError:
    mss = None

try:
    import pystray
except ImportError:
    pystray = None


# ==========================================================================
# CONFIGURATION & PERSISTENCE (config.json)
# ==========================================================================
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
LEGACY_PRESET_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "preset_coords.json")

def load_persistent_config() -> dict:
    default_config = {
        "preset_coords": {"x1": 100, "y1": 100, "x2": 500, "y2": 300},
        "result_window": {"width": 580, "height": 360, "x": None, "y": None},
        "result_font_size": 12,
    }
    target_file = CONFIG_FILE if os.path.exists(CONFIG_FILE) else (
        LEGACY_PRESET_FILE if os.path.exists(LEGACY_PRESET_FILE) else None
    )
    if target_file:
        try:
            with open(target_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "x1" in data and "x2" in data:  # Legacy preset format migration
                    default_config["preset_coords"] = data
                else:
                    if "preset_coords" in data and isinstance(data["preset_coords"], dict):
                        default_config["preset_coords"].update(data["preset_coords"])
                    if "result_window" in data and isinstance(data["result_window"], dict):
                        default_config["result_window"].update(data["result_window"])
                    if "result_font_size" in data and isinstance(data["result_font_size"], (int, float)):
                        default_config["result_font_size"] = int(data["result_font_size"])
        except Exception as e:
            print(f"[WARN] Error loading config: {e}")

    # Ensure config.json is created
    if not os.path.exists(CONFIG_FILE):
        save_persistent_config(default_config)
    return default_config

def save_persistent_config(data: dict):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"[WARN] Failed to save config to disk: {e}")


PERSISTENT_CONFIG = load_persistent_config()


@dataclass
class Config:
    GEMINI_API_KEY: str = field(
        default_factory=lambda: os.environ.get(
            "GEMINI_API_KEY", "APIKEYHERE"
        )
    )

    GEMINI_MODELS: List[str] = field(default_factory=lambda: [
        "gemini-flash-lite-latest",
        "gemini-3.1-flash-lite",
        "gemini-flash-latest",
        "gemini-3.5-flash",
        "gemini-3-flash-preview",
    ])

    PRESET_COORDS: dict = field(default_factory=lambda: PERSISTENT_CONFIG["preset_coords"])

    # Hotkeys
    HOTKEY_SNIP: str = "f7"
    HOTKEY_PRESET: str = "ctrl+f7"
    HOTKEY_SET_PRESET: str = "ctrl+alt+shift+f7"

    SYSTEM_PROMPT: str = (
        "You are a strict OCR + translation engine. Look at the image, "
        "find any foreign-language text or chat content in it, and "
        "translate it directly into natural English. "
        "Output ONLY the translated text. "
        "Do not include the original text, explanations, labels, "
        "markdown formatting, code fences, or any conversational filler. "
        "If there is no legible text in the image, output exactly: "
        "[No text detected]"
    )

    OVERLAY_SELECTION_COLOR: str = "#00c8ff"
    OVERLAY_PRESET_COLOR: str = "#ff9800"


CONFIG = Config()


def setup_dpi_awareness():
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                import ctypes
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except Exception:
                try:
                    import ctypes
                    ctypes.windll.user32.SetProcessDPIAware()
                except Exception:
                    pass


# ==========================================================================
# GEMINI TRANSLATION WORKER
# ==========================================================================
class GeminiTranslator:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.client = None

    def _ensure_configured(self):
        if genai is None:
            raise RuntimeError(
                "google-genai is not installed. "
                "Run: pip install google-genai"
            )
        if self.client is None:
            if not self.cfg.GEMINI_API_KEY or "YOUR_GEMINI_API_KEY" in self.cfg.GEMINI_API_KEY:
                raise RuntimeError(
                    "No valid Gemini API key set. Set the GEMINI_API_KEY "
                    "environment variable or edit CONFIG.GEMINI_API_KEY."
                )
            self.client = genai.Client(api_key=self.cfg.GEMINI_API_KEY)

    def translate_image(self, image: Image.Image) -> str:
        self._ensure_configured()

        last_error: Optional[Exception] = None
        for model_name in self.cfg.GEMINI_MODELS:
            try:
                print(f"[Gemini] Sending image to {model_name}...")
                gen_config = (
                    types.GenerateContentConfig(
                        temperature=0.1,
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                    )
                    if types
                    else None
                )
                response = self.client.models.generate_content(
                    model=model_name,
                    contents=[self.cfg.SYSTEM_PROMPT, image],
                    config=gen_config,
                )
                text = (getattr(response, "text", "") or "").strip()
                if text:
                    print(f"[Gemini] Success with model: {model_name}")
                    return text
                else:
                    raise ValueError("Empty response text")
            except Exception as e:
                print(f"[Gemini] Model '{model_name}' failed: {e}")
                last_error = e
                continue

        raise RuntimeError(f"All Gemini models failed. Last error: {last_error}")


# ==========================================================================
# SCREEN CAPTURE BACKEND
# ==========================================================================
class ScreenCapture:
    @staticmethod
    def grab_fullscreen() -> Image.Image:
        if mss is not None:
            with mss.mss() as sct:
                monitor = sct.monitors[0]
                shot = sct.grab(monitor)
                return Image.frombytes("RGB", shot.size, shot.rgb)
        return ImageGrab.grab(all_screens=True)

    @staticmethod
    def grab_region(bbox: Tuple[int, int, int, int]) -> Image.Image:
        x1, y1, x2, y2 = bbox
        if mss is not None:
            with mss.mss() as sct:
                region = {
                    "left": x1, "top": y1,
                    "width": max(1, x2 - x1), "height": max(1, y2 - y1),
                }
                shot = sct.grab(region)
                return Image.frombytes("RGB", shot.size, shot.rgb)
        return ImageGrab.grab(bbox=bbox, all_screens=True)


# ==========================================================================
# SNIP OVERLAY
# ==========================================================================
class SnipOverlay:
    def __init__(self, root: tk.Tk, on_complete, on_cancel, mode: str = "translate"):
        self.root = root
        self.on_complete = on_complete
        self.on_cancel = on_cancel
        self.mode = mode
        self._closed = False

        self.screenshot = ScreenCapture.grab_fullscreen()

        self.start_x = None
        self.start_y = None
        self.rect_id = None
        self.label_id = None

        self._build_window()

    def _build_window(self):
        self.win = tk.Toplevel(self.root)
        self.win.attributes("-fullscreen", True)
        try:
            self.win.attributes("-topmost", True)
        except tk.TclError:
            pass
        self.win.configure(cursor="crosshair")

        self.canvas = tk.Canvas(self.win, highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)

        self.win.update_idletasks()
        win_w = self.win.winfo_width()
        win_h = self.win.winfo_height()
        if win_w <= 1 or win_h <= 1:
            win_w = self.win.winfo_screenwidth()
            win_h = self.win.winfo_screenheight()

        self._scale_x = self.screenshot.width / win_w
        self._scale_y = self.screenshot.height / win_h

        if abs(self.screenshot.width - win_w) <= 2 and abs(self.screenshot.height - win_h) <= 2:
            display_img = self.screenshot
        else:
            display_img = self.screenshot.resize((win_w, win_h), Image.LANCZOS)

        self.tk_img = ImageTk.PhotoImage(display_img)
        self.canvas.create_image(0, 0, image=self.tk_img, anchor="nw")

        is_preset = (self.mode == "preset")
        bar_text = (
            "SET PRESET REGION: Drag box to save  |  Right-click or ESC to cancel"
            if is_preset else
            "DRAG TO SELECT REGION  |  Right-click or ESC to cancel"
        )
        bar_color = CONFIG.OVERLAY_PRESET_COLOR if is_preset else CONFIG.OVERLAY_SELECTION_COLOR

        self.canvas.create_rectangle(0, 0, win_w, 36, fill="#121212", outline="")
        self.canvas.create_text(
            win_w // 2, 18, text=bar_text, fill=bar_color,
            font=("Segoe UI", 11, "bold")
        )

        # Drag selection
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)

        # Right-click cancels capture without passing event down
        self.canvas.bind("<ButtonPress-3>", self._swallow_event)
        self.win.bind("<ButtonPress-3>", self._swallow_event)
        self.canvas.bind("<ButtonRelease-3>", self._on_right_click)
        self.win.bind("<ButtonRelease-3>", self._on_right_click)

        # ESC key cancels capture
        self.win.bind("<Escape>", self._on_escape)
        self.win.protocol("WM_DELETE_WINDOW", self._on_escape)
        self.win.focus_force()

    def _swallow_event(self, event=None):
        return "break"

    def _on_right_click(self, event=None):
        self._close()
        self.on_cancel()
        return "break"

    def _on_press(self, event):
        self.start_x, self.start_y = event.x, event.y
        if self.rect_id:
            self.canvas.delete(self.rect_id)
        if self.label_id:
            self.canvas.delete(self.label_id)

        color = CONFIG.OVERLAY_PRESET_COLOR if self.mode == "preset" else CONFIG.OVERLAY_SELECTION_COLOR
        self.rect_id = self.canvas.create_rectangle(
            self.start_x, self.start_y, self.start_x, self.start_y,
            outline=color, width=2
        )
        self.label_id = self.canvas.create_text(
            self.start_x + 8, self.start_y + 14,
            text="0 x 0", fill=color, anchor="nw",
            font=("Segoe UI", 10, "bold")
        )

    def _on_drag(self, event):
        if self.rect_id is not None:
            self.canvas.coords(self.rect_id, self.start_x, self.start_y, event.x, event.y)
            w = abs(event.x - self.start_x)
            h = abs(event.y - self.start_y)
            lx = min(self.start_x, event.x) + 8
            ly = max(self.start_y, event.y) - 22 if max(self.start_y, event.y) - 22 > 0 else max(self.start_y, event.y) + 8
            self.canvas.coords(self.label_id, lx, ly)
            self.canvas.itemconfig(self.label_id, text=f"{w} x {h} px")

    def _on_release(self, event):
        if self.start_x is None:
            return
        end_x, end_y = event.x, event.y
        x1, x2 = sorted([self.start_x, end_x])
        y1, y2 = sorted([self.start_y, end_y])

        self._close()

        if (x2 - x1) < 4 or (y2 - y1) < 4:
            self.on_cancel()
            return

        sx1 = int(x1 * self._scale_x)
        sy1 = int(y1 * self._scale_y)
        sx2 = int(x2 * self._scale_x)
        sy2 = int(y2 * self._scale_y)

        cropped = self.screenshot.crop((sx1, sy1, sx2, sy2))
        coords = {"x1": sx1, "y1": sy1, "x2": sx2, "y2": sy2}
        self.on_complete(cropped, coords)

    def _on_escape(self, event=None):
        self._close()
        self.on_cancel()
        return "break"

    def _close(self):
        if self._closed:
            return
        self._closed = True
        try:
            self.win.destroy()
        except tk.TclError:
            pass


# ==========================================================================
# RESULT POPUP WINDOW (Remember Position & Size + Font from Config)
# ==========================================================================
class ResultWindow:
    def __init__(self, root: tk.Tk, text: str, is_error: bool = False):
        self.root = root
        self.win = tk.Toplevel(root)
        self.win.title("Translation Result - Error" if is_error else "Translation Result")
        self.win.minsize(300, 180)
        try:
            self.win.attributes("-topmost", True)
        except tk.TclError:
            pass
        self.win.configure(bg="#181818")

        # Load position & size from config
        win_cfg = PERSISTENT_CONFIG.get("result_window", {})
        w = win_cfg.get("width", 580)
        h = win_cfg.get("height", 360)
        x = win_cfg.get("x")
        y = win_cfg.get("y")

        if x is not None and y is not None:
            geom_str = f"{w}x{h}+{x}+{y}".replace("+-", "-")
            self.win.geometry(geom_str)
        else:
            self.win.geometry(f"{w}x{h}")

        self._last_w = w
        self._last_h = h
        self._last_x = x
        self._last_y = y

        # Track movements & resizes
        self.win.bind("<Configure>", self._on_configure)

        # Dynamic font size (reads directly from config)
        font_size = PERSISTENT_CONFIG.get("result_font_size", 12)

        # Text area fills almost 100% of the window
        text_fg = "#f28b82" if is_error else "#f0f0f0"
        self.text_area = scrolledtext.ScrolledText(
            self.win,
            wrap="word",
            font=("Segoe UI", font_size),
            bg="#222222",
            fg=text_fg,
            insertbackground="#ffffff",
            relief="flat",
            padx=12,
            pady=10,
            spacing1=2,
            spacing2=4,
            spacing3=2,
        )
        self.text_area.pack(fill="both", expand=True, padx=10, pady=(10, 8))
        self.text_area.insert("1.0", text)
        self.text_area.configure(state="disabled")

        # Slim Bottom Action Bar
        btn_frame = tk.Frame(self.win, bg="#181818")
        btn_frame.pack(fill="x", padx=10, pady=(0, 10))

        self.copy_btn = tk.Button(
            btn_frame,
            text="Copy",
            command=self._copy,
            bg="#007acc",
            fg="#ffffff",
            activebackground="#005999",
            activeforeground="#ffffff",
            font=("Segoe UI", 9, "bold"),
            relief="flat",
            padx=14,
            pady=3,
            cursor="hand2",
        )
        self.copy_btn.pack(side="left")

        self.copy_status_label = tk.Label(
            btn_frame, text="", fg="#81c995", bg="#181818", font=("Segoe UI", 9, "italic")
        )
        self.copy_status_label.pack(side="left", padx=8)

        close_btn = tk.Button(
            btn_frame,
            text="Close (Esc)",
            command=self._close,
            bg="#333333",
            fg="#cccccc",
            activebackground="#444444",
            activeforeground="#ffffff",
            font=("Segoe UI", 9),
            relief="flat",
            padx=12,
            pady=3,
            cursor="hand2",
        )
        close_btn.pack(side="right")

        self.win.bind("<Escape>", lambda e: self._close())
        self.win.protocol("WM_DELETE_WINDOW", self._close)

        self.win.lift()
        self.win.focus_force()

    def _on_configure(self, event):
        if event.widget == self.win and self.win.state() == "normal":
            w = self.win.winfo_width()
            h = self.win.winfo_height()
            x = self.win.winfo_x()
            y = self.win.winfo_y()
            if w > 100 and h > 100:
                self._last_w = w
                self._last_h = h
                self._last_x = x
                self._last_y = y

    def _copy(self):
        content = self.text_area.get("1.0", "end").strip()
        self.win.clipboard_clear()
        self.win.clipboard_append(content)
        self.copy_status_label.configure(text="Copied!")
        self.win.after(1400, lambda: self.copy_status_label.configure(text=""))

    def _close(self):
        if self._last_w and self._last_h and self._last_x is not None and self._last_y is not None:
            PERSISTENT_CONFIG["result_window"] = {
                "width": self._last_w,
                "height": self._last_h,
                "x": self._last_x,
                "y": self._last_y,
            }
            save_persistent_config(PERSISTENT_CONFIG)
        try:
            self.win.destroy()
        except tk.TclError:
            pass


# ==========================================================================
# SYSTEM TRAY
# ==========================================================================
def _build_tray_icon_image() -> Image.Image:
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((2, 2, size - 2, size - 2), radius=16, fill="#1e1e1e")
    draw.rounded_rectangle((2, 2, size - 2, size - 2), radius=16, outline="#00c8ff", width=3)
    try:
        font = ImageFont.truetype("arial.ttf", 32)
    except Exception:
        font = ImageFont.load_default()
    text = "T"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((size - tw) / 2 - bbox[0], (size - th) / 2 - bbox[1]), text,
               fill="#00c8ff", font=font)
    return img


class TrayIcon:
    def __init__(self, app: "ScreenTranslateApp"):
        self.app = app
        self.icon: Optional["pystray.Icon"] = None

    def _on_snip(self, icon, item):
        self.app.event_queue.put(("start_interactive_snip", None))

    def _on_preset(self, icon, item):
        self.app.event_queue.put(("start_preset_snip", None))

    def _on_set_preset(self, icon, item):
        self.app.event_queue.put(("start_set_preset", None))

    def _on_quit(self, icon, item):
        self.app.event_queue.put(("quit", None))
        icon.stop()

    def start(self):
        if pystray is None:
            return
        image = _build_tray_icon_image()
        menu = pystray.Menu(
            pystray.MenuItem(
                f"Snip now  ({self.app.cfg.HOTKEY_SNIP.upper()})", self._on_snip
            ),
            pystray.MenuItem(
                f"Preset capture  ({self.app.cfg.HOTKEY_PRESET.upper()})", self._on_preset
            ),
            pystray.MenuItem(
                f"Set preset area  ({self.app.cfg.HOTKEY_SET_PRESET.upper()})", self._on_set_preset
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._on_quit),
        )
        self.icon = pystray.Icon("screen_translate", image, "Screen Translate", menu)
        self.icon.run()

    def stop(self):
        if self.icon is not None:
            try:
                self.icon.stop()
            except Exception:
                pass


# ==========================================================================
# MAIN APPLICATION
# ==========================================================================
class ScreenTranslateApp:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.translator = GeminiTranslator(cfg)

        self.root = tk.Tk()
        self.root.withdraw()

        self.event_queue: "queue.Queue[Tuple[str, object]]" = queue.Queue()
        self._snip_in_progress = False
        self._active_snip = None

        self._setup_hotkeys()

        self.tray = TrayIcon(self)
        if pystray is not None:
            threading.Thread(target=self.tray.start, daemon=True).start()
            print("[Tray] System tray icon active.")

        self.root.after(50, self._poll_queue)

    def _setup_hotkeys(self):
        if keyboard is None:
            print("[WARN] 'keyboard' library not installed - global hotkeys disabled.")
            return

        keyboard.add_hotkey(self.cfg.HOTKEY_SNIP, self._request_interactive_snip)
        keyboard.add_hotkey(self.cfg.HOTKEY_PRESET, self._request_preset_snip)
        keyboard.add_hotkey(self.cfg.HOTKEY_SET_PRESET, self._request_set_preset)

        print(f"[Hotkeys] '{self.cfg.HOTKEY_SNIP}' -> interactive snip")
        print(f"[Hotkeys] '{self.cfg.HOTKEY_PRESET}' -> preset region capture")
        print(f"[Hotkeys] '{self.cfg.HOTKEY_SET_PRESET}' -> set preset region")
        print("[Hotkeys] Ready.")

    def _request_interactive_snip(self):
        self.event_queue.put(("start_interactive_snip", None))

    def _request_preset_snip(self):
        self.event_queue.put(("start_preset_snip", None))

    def _request_set_preset(self):
        self.event_queue.put(("start_set_preset", None))

    def _poll_queue(self):
        try:
            while True:
                event_name, payload = self.event_queue.get_nowait()
                self._handle_event(event_name, payload)
        except queue.Empty:
            pass
        finally:
            self.root.after(50, self._poll_queue)

    def _handle_event(self, event_name: str, payload):
        if event_name == "start_interactive_snip":
            self._start_interactive_snip()
        elif event_name == "start_preset_snip":
            self._start_preset_snip()
        elif event_name == "start_set_preset":
            self._start_set_preset()
        elif event_name == "translation_result":
            text, is_error = payload
            ResultWindow(self.root, text=text, is_error=is_error)
        elif event_name == "quit":
            print("[App] Quit requested.")
            self.root.quit()

    def _start_interactive_snip(self):
        if self._snip_in_progress:
            if self._active_snip:
                self._active_snip._close()
            self._snip_in_progress = False

        self._snip_in_progress = True

        def on_complete(image: Image.Image, coords: dict):
            self._snip_in_progress = False
            self._active_snip = None
            self._begin_translation(image)

        def on_cancel():
            self._snip_in_progress = False
            self._active_snip = None
            print("[Snip] Cancelled.")

        self._active_snip = SnipOverlay(
            self.root, on_complete=on_complete, on_cancel=on_cancel, mode="translate"
        )

    def _start_set_preset(self):
        if self._snip_in_progress:
            if self._active_snip:
                self._active_snip._close()
            self._snip_in_progress = False

        self._snip_in_progress = True

        def on_complete(image: Image.Image, coords: dict):
            self._snip_in_progress = False
            self._active_snip = None
            self.cfg.PRESET_COORDS = coords
            PERSISTENT_CONFIG["preset_coords"] = coords
            save_persistent_config(PERSISTENT_CONFIG)
            print(f"[Preset] Saved new preset box: {coords}")

        def on_cancel():
            self._snip_in_progress = False
            self._active_snip = None
            print("[Preset] Cancelled.")

        self._active_snip = SnipOverlay(
            self.root, on_complete=on_complete, on_cancel=on_cancel, mode="preset"
        )

    def _start_preset_snip(self):
        coords = PERSISTENT_CONFIG.get("preset_coords", self.cfg.PRESET_COORDS)
        bbox = (coords["x1"], coords["y1"], coords["x2"], coords["y2"])
        try:
            image = ScreenCapture.grab_region(bbox)
        except Exception as e:
            print(f"[ERROR] Preset capture failed: {e}")
            return
        self._begin_translation(image)

    def _begin_translation(self, image: Image.Image):
        def worker():
            try:
                text = self.translator.translate_image(image)
                self.event_queue.put(("translation_result", (text, False)))
            except Exception as e:
                traceback.print_exc()
                error_text = f"Translation failed:\n{e}"
                self.event_queue.put(("translation_result", (error_text, True)))

        threading.Thread(target=worker, daemon=True).start()

    def run(self):
        try:
            self.root.mainloop()
        finally:
            if keyboard is not None:
                keyboard.unhook_all_hotkeys()
            self.tray.stop()


# ==========================================================================
# ENTRY POINT
# ==========================================================================
def main():
    setup_dpi_awareness()

    required_missing = []
    if keyboard is None:
        required_missing.append("keyboard")
    if genai is None:
        required_missing.append("google-genai")
    if required_missing:
        print(
            "[WARN] Missing required dependencies: "
            + ", ".join(required_missing)
            + "\n       Install with: pip install " + " ".join(required_missing)
        )

    app = ScreenTranslateApp(CONFIG)
    app.run()


if __name__ == "__main__":
    main()