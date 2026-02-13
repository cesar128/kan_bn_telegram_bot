import requests
import pickle
from datetime import datetime, timezone, timedelta
import telebot
import re
import time
import os
from html.parser import HTMLParser

# Configuration
BASE_URL = os.getenv("BASE_URL")
KANBN_API_KEY = os.getenv("KANBN_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TELEGRAM_THREAD_ID = os.getenv("TELEGRAM_THREAD_ID")

WORKSPACE_ID = os.getenv("WORKSPACE_ID")
BOARD_ID = os.getenv("BOARD_ID")

KANBN_BASE_URL = f"{BASE_URL}api/v1"
STATE_FILE = os.path.join("db", "bot_state.pkl")
# BOARD_ID = "ro8lbgsa5fqc"  # Board de prueba
HEADERS = {"x-api-key": KANBN_API_KEY}


def get_json(endpoint):
    r = requests.get(f"{KANBN_BASE_URL}{endpoint}", headers=HEADERS)
    return r.json() if r.status_code == 200 else []


def load_state():
    try:
        with open(STATE_FILE, "rb") as f:
            return pickle.load(f)
    except:
        # Default: Start from 1 hour ago if no state exists
        return {
            "last_check": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        }


class TelegramHTMLFilter(HTMLParser):
    def __init__(self):
        super().__init__()
        self.result = []
        self.allowed_tags = {
            "b",
            "strong",
            "i",
            "em",
            "u",
            "ins",
            "s",
            "strike",
            "del",
            "span",
            "tg-spoiler",
            "a",
            "tg-emoji",
            "code",
            "pre",
            "blockquote",
        }

    def handle_starttag(self, tag, attrs):
        if tag in self.allowed_tags:
            # Reconstruct the tag with its attributes
            attrs_str = "".join(f' {k}="{v}"' for k, v in attrs)
            self.result.append(f"<{tag}{attrs_str}>")
        elif tag in ("ul", "ol"):
            # Skip list containers
            pass
        elif tag == "li":
            self.result.append("- ")
        elif tag == "br":
            self.result.append("\n")
        elif tag == "p":
            # Opening p tag doesn't add anything
            pass

    def handle_endtag(self, tag):
        if tag in self.allowed_tags:
            self.result.append(f"</{tag}>")
        elif tag in ("ul", "ol"):
            pass
        elif tag == "li":
            self.result.append("\n")
        elif tag == "p":
            self.result.append("\n")

    def handle_data(self, data):
        self.result.append(data)

    def get_result(self):
        return "".join(self.result)


def filter_html_for_telegram(html_string):
    parser = TelegramHTMLFilter()
    parser.feed(html_string)
    return parser.get_result()


def main():
    state = load_state()
    last_check = state["last_check"]

    # 1. Get all lists in the board
    lists = get_json(f"/boards/{BOARD_ID}")

    current_run_time = datetime.now(timezone.utc).isoformat()

    all_cards = []

    for l in lists["lists"]:
        for card in l["cards"]:
            all_cards.append(card)

    statuses = []

    for card in all_cards:
        activities = get_json(f"/cards/{card['publicId']}/activities")
        if not "activities" in activities:
            continue
        for act in activities["activities"]:
            # Only process activities newer than our last global check
            statuses.append(act["type"])
            if act["createdAt"] > last_check:
                try:
                    if act["type"] == "card.created":
                        msg = f'🆕 Nueva tarea: <a href="{BASE_URL}cards/{card["publicId"]}">{card["title"]}</a>\nDescripción:\n{card["description"]}'
                    elif act["type"] == "card.updated.label.added":
                        msg = f'🔄 Tarea actualizada: <a href="{BASE_URL}cards/{card["publicId"]}">{card["title"]}</a>\n\nEtiqueta agregada: <strong>{act["label"]["name"]}</strong>'
                    elif act["type"] == "card.updated.comment.added":
                        msg = f'💬 Comentario agregado: <a href="{BASE_URL}cards/{card["publicId"]}">{card["title"]}</a>\n\n:{act["comment"]["comment"]}'
                    elif act["type"] == "card.updated.list":
                        msg = f'🔀Tarea movida a otra lista: <a href="{BASE_URL}cards/{card["publicId"]}">{card["title"]}</a>\n\n<strong>{act["fromList"]["name"]} ==> {act["toList"]["name"]}</strong>'
                    elif act["type"] == "card.updated.member.added":
                        msg = f'🐸 Asignacion de tarea: <a href="{BASE_URL}cards/{card["publicId"]}">{card["title"]}</a>\n\nAsignada a <strong>{act["member"]["user"]["name"]}</strong>'
                    elif act["type"] == "card.updated.attachment.added":
                        msg = f'📎 Agregó documento adjunto: <a href="{BASE_URL}cards/{card["publicId"]}">{card["title"]}</a>'
                    else:
                        msg = f'🤔 {act["type"]}: <a href="{BASE_URL}cards/{card["publicId"]}">{card["title"]}</a>'

                    msg = f"Actualizacion de {act['user']['name']}\n" + msg

                    msg = filter_html_for_telegram(msg)

                    bot = telebot.TeleBot(TELEGRAM_TOKEN, parse_mode="html")
                    bot.send_message(
                        TELEGRAM_CHAT_ID,
                        msg,
                        disable_web_page_preview=True,
                        message_thread_id=TELEGRAM_THREAD_ID,
                    )
                except Exception as e:
                    print(f"Error processing activity {card['publicId']}: {e}")

    print(f"Checked at {current_run_time}, last check was at {last_check}")

    # 4. Save the current timestamp as the new baseline
    with open(STATE_FILE, "wb") as f:
        pickle.dump({"last_check": current_run_time}, f)


# {
# 'card.updated.label.added',
# 'card.updated.description',
# 'card.updated.comment.added',
# 'card.updated.list',
# 'card.created',
# 'card.updated.attachment.added',
# 'card.updated.member.added',
# 'card.updated.member.removed'
# }


if __name__ == "__main__":
    while True:
        try:
            main()
        except Exception as e:
            print(f"Error: {e}")
        time.sleep(60)  # Wait 1 minute before next run
