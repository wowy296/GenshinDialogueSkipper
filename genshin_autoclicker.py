"""
Genshin Impact Dialogue Skipper
- System tray app with toggle/quit hotkeys
- Auto-detects Genshin Impact and notifies you
- Pixel-based dialogue detection (only presses when dialogue is on screen)
- Multi-resolution support
- Loading screen detection
- Rebindable hotkeys via tray menu
- Configurable in-game interaction key
- Optional Windows startup (as admin via Task Scheduler)
"""

import json
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
import winsound

import psutil
import pyautogui
from PIL import Image, ImageDraw
from pynput.keyboard import Key, KeyCode, Listener, Controller
from win32api import GetSystemMetrics

APP_NAME = "GenshinDialogueSkipper"
INTERVAL = 0.05
GENSHIN_PROCESSES = {"genshinimpact.exe", "yuanshen.exe"}

keyboard = Controller()
active = False
running = True
genshin_running = False
tray_icon = None

# Screen resolution (detected once at startup)
SCREEN_WIDTH = GetSystemMetrics(0)
SCREEN_HEIGHT = GetSystemMetrics(1)

# --- Resolution-adaptive pixel coordinates ---

def scale_x(x_1080p):
    """Scale an x coordinate from 1920-base to current resolution."""
    return int(x_1080p / 1920 * SCREEN_WIDTH)


def scale_y(y_1080p):
    """Scale a y coordinate from 1080-base to current resolution."""
    return int(y_1080p / 1080 * SCREEN_HEIGHT)


# Pixel positions (based on 1920x1080, auto-scaled)
def get_playing_icon_pos():
    return scale_x(84), scale_y(46)


def get_dialogue_icon_lower_pos():
    return scale_x(1301), scale_y(808)


def get_dialogue_icon_higher_pos():
    return scale_x(1301), scale_y(790)


def get_loading_screen_pos():
    return scale_x(1200), scale_y(700)


# --- Dialogue detection ---

PLAYING_ICON_COLOR = (236, 229, 216)
LOADING_SCREEN_WHITE = (255, 255, 255)
DIALOGUE_ICON_WHITE = (255, 255, 255)


def is_genshin_focused():
    """Check if Genshin Impact is the active/foreground window."""
    try:
        title = pyautogui.getActiveWindowTitle()
        return title == "Genshin Impact"
    except Exception:
        return False


def is_dialogue_playing():
    """Check if dialogue is playing (autoplay icon visible)."""
    try:
        x, y = get_playing_icon_pos()
        return pyautogui.pixel(x, y) == PLAYING_ICON_COLOR
    except Exception:
        return False


def is_dialogue_option_available():
    """Check if a dialogue choice is on screen."""
    try:
        # Skip if loading screen (white)
        lx, ly = get_loading_screen_pos()
        if pyautogui.pixel(lx, ly) == LOADING_SCREEN_WHITE:
            return False

        # Check lower dialogue icon
        dx, dy_low = get_dialogue_icon_lower_pos()
        if pyautogui.pixel(dx, dy_low) == DIALOGUE_ICON_WHITE:
            return True

        # Check higher dialogue icon
        _, dy_high = get_dialogue_icon_higher_pos()
        if pyautogui.pixel(dx, dy_high) == DIALOGUE_ICON_WHITE:
            return True

        return False
    except Exception:
        return False


def is_loading_screen():
    """Check if a loading screen is active."""
    try:
        lx, ly = get_loading_screen_pos()
        return pyautogui.pixel(lx, ly) == LOADING_SCREEN_WHITE
    except Exception:
        return False


# --- Config ---

def get_config_path():
    if getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(sys.executable), "config.json")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


DEFAULT_CONFIG = {
    "toggle_key": "Key.f6",
    "quit_key": "Key.f7",
    "interaction_key": "f",
    "smart_detect": True,
    "start_with_windows": False,
}


def load_config():
    path = get_config_path()
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                cfg = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                cfg.setdefault(k, v)
            return cfg
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)


def save_config(cfg):
    path = get_config_path()
    with open(path, "w") as f:
        json.dump(cfg, f, indent=2)


config = load_config()


def parse_key(key_str):
    """Convert a stored key string back to a pynput key object."""
    if key_str.startswith("Key."):
        return getattr(Key, key_str[4:], Key.f6)
    if len(key_str) == 1:
        return KeyCode.from_char(key_str)
    return getattr(Key, key_str, Key.f6)


def key_to_str(key):
    """Convert a pynput key to a storable string."""
    if isinstance(key, Key):
        return str(key)
    if isinstance(key, KeyCode):
        if key.char:
            return key.char
        if key.vk:
            return f"vk_{key.vk}"
    return str(key)


def key_display_name(key_str):
    """Human-readable name for display in menus."""
    if key_str.startswith("Key."):
        return key_str[4:].upper()
    if key_str.startswith("vk_"):
        return f"VK {key_str[3:]}"
    return key_str.upper()


toggle_key = parse_key(config["toggle_key"])
quit_key = parse_key(config["quit_key"])

# --- Icon ---

def make_icon(color):
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((4, 4, 60, 60), fill=color)
    draw.text((22, 16), "F", fill="white")
    return img


def update_tray():
    if tray_icon is None:
        return
    if active:
        tray_icon.icon = make_icon((0, 200, 0))
        status = "ON"
    else:
        tray_icon.icon = make_icon((180, 0, 0))
        status = "OFF"
    genshin_status = "Genshin: Running" if genshin_running else "Genshin: Not detected"
    tray_icon.title = f"Dialogue Skipper: {status} | {genshin_status}"


# --- Toggle / Quit ---

def beep_on():
    winsound.Beep(800, 100)


def beep_off():
    winsound.Beep(400, 100)


def toggle():
    global active
    active = not active
    if active:
        threading.Thread(target=beep_on, daemon=True).start()
    else:
        threading.Thread(target=beep_off, daemon=True).start()
    update_tray()


def quit_app():
    global active, running
    active = False
    running = False
    if tray_icon:
        tray_icon.stop()


# --- Auto-press thread ---

def auto_press():
    interaction_key = config.get("interaction_key", "f")
    smart = config.get("smart_detect", True)

    while running:
        if not active:
            time.sleep(0.1)
            continue

        # Only press when Genshin is focused
        if not is_genshin_focused():
            time.sleep(0.2)
            continue

        if smart:
            # Smart mode: only press when dialogue is detected
            if is_loading_screen():
                time.sleep(0.2)
                continue

            dialogue = is_dialogue_playing()
            options = is_dialogue_option_available()

            if dialogue or options:
                keyboard.press(interaction_key)
                keyboard.release(interaction_key)
                time.sleep(INTERVAL)
            else:
                time.sleep(0.1)
        else:
            # Dumb mode: just spam the key
            keyboard.press(interaction_key)
            keyboard.release(interaction_key)
            time.sleep(INTERVAL)


# --- Genshin detection thread ---

def genshin_watcher():
    global genshin_running, active
    was_running = False
    while running:
        found = False
        try:
            for proc in psutil.process_iter(["name"]):
                if proc.info["name"] and proc.info["name"].lower() in GENSHIN_PROCESSES:
                    found = True
                    break
        except Exception:
            pass

        genshin_running = found

        if found and not was_running:
            update_tray()
            if tray_icon:
                tray_icon.notify("Genshin detected — ready to skip!", "Dialogue Skipper")
        elif not found and was_running:
            if active:
                active = False
                threading.Thread(target=beep_off, daemon=True).start()
            update_tray()

        was_running = found
        time.sleep(5)


# --- Hotkey listener ---

def on_press(key):
    try:
        if key == toggle_key:
            toggle()
        elif key == quit_key:
            quit_app()
            return False
    except Exception:
        pass


# --- Rebind hotkey UI ---

def rebind_key(label, config_key):
    """Open a small tkinter window to capture a new key."""
    global toggle_key, quit_key
    result = [None]

    def on_key(event):
        ks = event.keysym.lower()
        if ks.startswith("f") and ks[1:].isdigit():
            result[0] = getattr(Key, ks, None)
        elif len(ks) == 1:
            result[0] = KeyCode.from_char(ks)
        else:
            mapping = {
                "escape": Key.esc, "space": Key.space,
                "return": Key.enter, "tab": Key.tab,
                "backspace": Key.backspace, "delete": Key.delete,
                "insert": Key.insert, "home": Key.home, "end": Key.end,
                "prior": Key.page_up, "next": Key.page_down,
            }
            result[0] = mapping.get(ks)

        if result[0] is not None:
            root.destroy()

    root = tk.Tk()
    root.title(f"Rebind: {label}")
    root.geometry("300x100")
    root.resizable(False, False)
    root.attributes("-topmost", True)
    tk.Label(root, text=f"Press a new key for:\n{label}", font=("Segoe UI", 12)).pack(expand=True)
    root.bind("<Key>", on_key)
    root.focus_force()
    root.mainloop()

    if result[0] is not None:
        key_str = key_to_str(result[0])
        config[config_key] = key_str
        save_config(config)

        if config_key == "toggle_key":
            toggle_key = result[0]
        else:
            quit_key = result[0]

        restart_listener()
        if tray_icon:
            tray_icon.update_menu()


def change_interaction_key():
    """Open a small tkinter window to set the in-game interaction key."""
    result = [None]

    def on_key(event):
        ks = event.keysym.lower()
        if len(ks) == 1:
            result[0] = ks
            root.destroy()

    root = tk.Tk()
    root.title("Interaction Key")
    root.geometry("300x100")
    root.resizable(False, False)
    root.attributes("-topmost", True)
    tk.Label(
        root,
        text=f"Press your in-game interaction key\n(currently: {config.get('interaction_key', 'f').upper()})",
        font=("Segoe UI", 12),
    ).pack(expand=True)
    root.bind("<Key>", on_key)
    root.focus_force()
    root.mainloop()

    if result[0] is not None:
        config["interaction_key"] = result[0]
        save_config(config)
        if tray_icon:
            tray_icon.update_menu()


listener_ref = [None]


def restart_listener():
    """Stop and restart the keyboard listener with updated keys."""
    if listener_ref[0]:
        listener_ref[0].stop()
    new_listener = Listener(on_press=on_press)
    new_listener.start()
    listener_ref[0] = new_listener


# --- Windows startup (Task Scheduler — runs as admin) ---

TASK_NAME = "GenshinDialogueSkipper"


def is_startup_enabled():
    try:
        result = subprocess.run(
            ["schtasks", "/Query", "/TN", TASK_NAME],
            capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return result.returncode == 0
    except Exception:
        return False


def enable_startup():
    try:
        if getattr(sys, "frozen", False):
            exe_path = sys.executable
        else:
            exe_path = os.path.abspath(__file__)

        subprocess.run(
            ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
            capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW,
        )

        subprocess.run(
            [
                "schtasks", "/Create",
                "/TN", TASK_NAME,
                "/TR", f'"{exe_path}"',
                "/SC", "ONLOGON",
                "/RL", "HIGHEST",
                "/F",
            ],
            capture_output=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        config["start_with_windows"] = True
        save_config(config)
    except Exception:
        pass


def disable_startup():
    try:
        subprocess.run(
            ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
            capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        config["start_with_windows"] = False
        save_config(config)
    except Exception:
        pass


def toggle_startup():
    if is_startup_enabled():
        disable_startup()
    else:
        enable_startup()


def toggle_smart_detect():
    config["smart_detect"] = not config.get("smart_detect", True)
    save_config(config)


# --- Tray menu ---

def setup_tray():
    global tray_icon
    import pystray

    def on_toggle(icon, item):
        toggle()

    def on_rebind_toggle(icon, item):
        threading.Thread(target=lambda: rebind_key("Toggle Autoclicker", "toggle_key"), daemon=True).start()

    def on_rebind_quit(icon, item):
        threading.Thread(target=lambda: rebind_key("Quit App", "quit_key"), daemon=True).start()

    def on_change_interaction(icon, item):
        threading.Thread(target=change_interaction_key, daemon=True).start()

    def on_toggle_startup(icon, item):
        toggle_startup()

    def on_toggle_smart(icon, item):
        toggle_smart_detect()

    def on_quit(icon, item):
        quit_app()

    def startup_checked(item):
        return is_startup_enabled()

    def smart_checked(item):
        return config.get("smart_detect", True)

    menu = pystray.Menu(
        pystray.MenuItem(
            lambda text: f"Toggle ({key_display_name(config['toggle_key'])})",
            on_toggle,
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(
            "Smart Dialogue Detection",
            on_toggle_smart,
            checked=smart_checked,
        ),
        pystray.MenuItem(
            lambda text: f"Interaction Key ({config.get('interaction_key', 'f').upper()})",
            on_change_interaction,
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(
            lambda text: f"Change Toggle Key ({key_display_name(config['toggle_key'])})",
            on_rebind_toggle,
        ),
        pystray.MenuItem(
            lambda text: f"Change Quit Key ({key_display_name(config['quit_key'])})",
            on_rebind_quit,
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(
            "Start with Windows",
            on_toggle_startup,
            checked=startup_checked,
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(
            lambda text: f"Quit ({key_display_name(config['quit_key'])})",
            on_quit,
        ),
    )

    tray_icon = pystray.Icon(
        APP_NAME,
        make_icon((180, 0, 0)),
        "Dialogue Skipper: OFF",
        menu,
    )

    # Start background threads
    threading.Thread(target=auto_press, daemon=True).start()
    threading.Thread(target=genshin_watcher, daemon=True).start()

    listener = Listener(on_press=on_press)
    listener.start()
    listener_ref[0] = listener

    tray_icon.run()
    listener.stop()


if __name__ == "__main__":
    setup_tray()
