import re
import json
import time
import os
import threading
import requests
from flask import Flask

BOT_TOKEN = os.environ["8217436710:AAHsEtLlCrjgAGnDgJjSOKqaWER78qOUt_A"]
CHANNEL_ID = os.environ["-1004315979125"]

FILES_ENDPOINT = "https://delta.filenetwork.vip/get_files.php"
STATE_FILE = "last_apk_state.json"
CHECK_INTERVAL = 10  # секунд

VERSION_RE = re.compile(r"v?(\d+(?:\.\d+){1,3})", re.IGNORECASE)

app = Flask(__name__)


@app.route("/")
def health():
    return "ok", 200


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def format_bytes(size):
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} TB"


def extract_version(filename):
    m = VERSION_RE.search(filename)
    return m.group(1) if m else filename


def fetch_latest_apk():
    resp = requests.get(FILES_ENDPOINT, timeout=10, headers={
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://delta.filenetwork.vip/android.html",
    })
    resp.raise_for_status()
    data = resp.json()
    files = data.get("latest_apk") or []
    return files[0] if files else None


def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHANNEL_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    r = requests.post(url, json=payload, timeout=15)
    r.raise_for_status()


def poll_loop():
    state = load_state()
    last_name = state.get("name")
    last_size = state.get("size")
    last_modified = state.get("last_modified")

    print(f"[poll] старт. последнее: {last_name} ({last_modified})", flush=True)

    while True:
        try:
            latest = fetch_latest_apk()
            if latest:
                name = latest.get("name")
                size = latest.get("size")
                mtime = latest.get("last_modified")

                if name != last_name or size != last_size or mtime != last_modified:
                    version = extract_version(name)
                    text = (
                        f"🚀 <b>Delta Executor — обновление</b>\n\n"
                        f"Версия: <b>{version}</b>\n"
                        f"Файл: <code>{name}</code>\n"
                        f"Размер: {format_bytes(size)}\n"
                        f"Обновлено: {mtime}\n\n"
                        f"⬇️ <a href='https://delta.filenetwork.vip/file/{name}'>Скачать</a>"
                    )
                    send_telegram_message(text)
                    print(f"[poll] отправлено: {name}", flush=True)

                    last_name, last_size, last_modified = name, size, mtime
                    save_state({"name": last_name, "size": last_size, "last_modified": last_modified})
                else:
                    print("[poll] изменений нет", flush=True)
        except Exception as e:
            print(f"[poll] ошибка: {e}", flush=True)

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    threading.Thread(target=poll_loop, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
