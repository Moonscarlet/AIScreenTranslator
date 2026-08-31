# 🌐 Screen Translate

A lightweight, background screen-capture OCR and translation tool powered by Google's Gemini Vision API. 

Freeze your screen, drag a box over any foreign language text (or trigger a preset capture zone), and receive a clean, natural English translation in a minimal always-on-top popup.

---

## ✨ Features

- **Interactive Freeze & Snip (`F7`):** Freeze your screen and drag a selection rectangle. Right-click or press `Esc` to cancel cleanly without clicking through to windows underneath.
- **Preset Quick Capture (`Ctrl + F7`):** Instant capture and translation of a fixed screen region (e.g., in-game chat logs, fixed subtitles, subtitles box).
- **Interactive Preset Selector (`Ctrl + Alt + Shift + F7`):** Drag to define a new preset capture zone and automatically save it for future quick captures.
- **Smart Window Memory:** Remembers your popup window size, screen position, and coordinates across restarts.
- **Clean & Distraction-Free:** Popups appear only when the translation is ready—no intermediate flashing windows or unnecessary headers.
- **Powered by `google-genai`:** Uses the latest Google GenAI SDK with fallback model support, prioritizing fast, lightweight models like `gemini-flash-lite-latest`.
- **Background Tray App:** Supports running silently with a system tray icon via `pystray` and `pythonw.exe`.
- **Configurable via JSON:** Easily adjust font size, window geometry, and preset boxes manually via `config.json`.

---

## ⌨️ Hotkeys & Controls

| Shortcut / Action | Function |
| :--- | :--- |
| **`F7`** | Freeze screen & start interactive snip selection |
| **`Ctrl + F7`** | Instantly capture & translate the preset area |
| **`Ctrl + Alt + Shift + F7`** | Drag to define and save a new preset capture box |
| **`Right-Click` / `Esc`** | Cancel active snip (safely absorbs clicks) |
| **`Esc`** (in popup) | Instantly close the translation result window |

---

## 📦 Installation

### 1. Clone the repository
```bash
git clone https://github.com/your-username/screen-translate.git
cd screen-translate
```

### 2. Install dependencies
```bash
pip install google-genai keyboard pillow mss pystray python-dotenv
```

> **Optional Dependencies:**
> - `mss`: Recommended for multi-monitor support and faster screen grabbing.
> - `pystray`: Enables system tray icon and background menu.

---

## 🔑 Setup API Key

Get a free Gemini API key from [Google AI Studio](https://aistudio.google.com/).

### Option A: Using `.env` (Recommended)
Create a `.env` file in the root directory:
```env
GEMINI_API_KEY=your_gemini_api_key_here
```

### Option B: System Environment Variable
- **Windows (PowerShell):**
  ```powershell
  [System.Environment]::SetEnvironmentVariable('GEMINI_API_KEY', 'your_key_here', 'User')
  ```
- **Linux / macOS:**
  ```bash
  export GEMINI_API_KEY="your_key_here"
  ```

---

## 🚀 How to Run

### Standard Launch
```bash
python screen_translate.py
```

### Run Silently in Background (Windows Only)
To launch with no command prompt window, launch using `pythonw.exe`:
```bash
pythonw.exe screen_translate.py
```
*(Right-click the **T** icon in your system tray to access actions or quit).*

> ⚠️ **Important (Administrator Privileges on Windows):**  
> If you have elevated applications in focus (e.g. **Task Manager**, **Discord**, or games running as Administrator), Windows **UIPI** blocks non-admin programs from reading global hotkeys.  
> **Solution:** Run your terminal or shortcut as **Administrator**.

---

## ⚙️ Configuration (`config.json`)

On the first run, a `config.json` file is automatically created in the root directory:

```json
{
  "preset_coords": {
    "x1": 100,
    "y1": 100,
    "x2": 500,
    "y2": 300
  },
  "result_window": {
    "width": 580,
    "height": 360,
    "x": 420,
    "y": 250
  },
  "result_font_size": 12
}
```

- **`preset_coords`**: Bounding box for the `Ctrl + F7` preset snip.
- **`result_window`**: Saved window dimensions and desktop coordinates (automatically updated whenever you move/resize the popup).
- **`result_font_size`**: Change the text display font size (e.g., `14`, `16`) directly in the JSON.

---

## 🛠️ Model Fallback Chain

The app tries the following models in sequence if rate-limited or unavailable:
1. `gemini-flash-lite-latest`
2. `gemini-3.1-flash-lite`
3. `gemini-flash-latest`
4. `gemini-2.5-flash`
5. `gemini-2.0-flash`

---

## 📝 License

This project is open-source under the [MIT License](LICENSE).