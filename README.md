# Genshin Dialogue Skipper

Auto-presses F to skip through dialogue quickly in Genshin Impact. Runs as a system tray app — no console window.

## Features

- **F6** to toggle auto-skip on/off (beep sound confirms toggle)
- **F7** to quit
- **Auto-detects Genshin** — notifies you when the game is running, auto-disables when you close it
- **Rebindable hotkeys** — right-click the tray icon to change toggle/quit keys
- **Start with Windows** — optional, launches as admin automatically via Task Scheduler
- Tray icon shows status: red = off, green = on

## Download

Grab the latest `.exe` from [Releases](../../releases) — no Python needed.

1. Download `GenshinDialogueSkipper.exe`
2. Right-click → **Run as administrator**
3. Look for the icon in your system tray (bottom-right) — right-click for options
4. A `config.json` is created automatically to save your settings

**Important:** Must run as admin or hotkeys won't work while Genshin is focused.

## Build from Source

```bash
pip install -r requirements.txt
pyinstaller --onefile --noconsole --name GenshinDialogueSkipper --hidden-import=pynput.keyboard._win32 --hidden-import=pynput.mouse._win32 genshin_autoclicker.py
```

The exe will be in the `dist/` folder.
