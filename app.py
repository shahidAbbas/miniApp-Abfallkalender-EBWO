from flask import Flask, request, jsonify
import threading
import logging
import sys
import requests
from bs4 import BeautifulSoup
from datetime import datetime

app = Flask(__name__)
app.secret_key = '4c3d2e1f0a9b8c7d6e5f4g3h2i1j0k9l'  # Replace with your generated secret key

# Shared list to store messages
messages = []
lock = threading.Lock()

# Configure logging
logging.basicConfig(level=logging.DEBUG, stream=sys.stdout)

# Constants
TENANT_NAME = "t0001"  # Updated to match the tenant name
TOKEN_URL = f"https://idp.mycity.kobil.com/auth/realms/{TENANT_NAME}/protocol/openid-connect/token/"
CLIENT_ID = "85217890-2ee0-40a2-9ef5-28ba0239c57b"
CLIENT_SECRET = "421b8363-e6b1-4ded-96b5-38583f3d2087"
USERNAME = "signing-integration"
PASSWORD = "MhNBBhA7hvZNGuJZ"

def get_access_token():
    payload = {
        'username': USERNAME,
        'password': PASSWORD,
        'client_id': CLIENT_ID,
        'grant_type': 'password',
        'client_secret': CLIENT_SECRET
    }
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Accept': 'application/json'
    }

    response = requests.post(TOKEN_URL, data=payload, headers=headers)
    response_data = response.json()
    return response_data.get("access_token")

def send_message(to_user_id, message_text):
    access_token = get_access_token()
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Authorization': f"Bearer {access_token}"
    }
    payload = {
        "serviceUuid": CLIENT_ID,
        "messageType": "processChatMessage",
        "version": 3,
        "messageContent": {
            "messageText": message_text
        }
    }
    url = f"https://idp.mycityapp.cloud.test.kobil.com/auth/realms/{TENANT_NAME}/mpower/v1/users/{to_user_id}/message/"
    response = requests.post(url, json=payload, headers=headers)
    app.logger.debug('Message sent to user %s: %s', to_user_id, response.json())

def get_street_web_address(street_name, user_id):
    url = f"https://www.ebwo.de/de/abfallkalender/2024/?sTerm={street_name}"
    send_message(user_id, f"Searching for street: {street_name}")
    response = requests.get(url)
    send_message(user_id, f"Request URL: {url}\nStatus Code: {response.status_code}")
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')

    list_entries = soup.find_all('li', class_='listEntryObject-news')
    send_message(user_id, f"Found {len(list_entries)} list entries")
    for entry in list_entries:
        if street_name.lower() in entry.get_text(strip=True).lower():
            street_url = entry.get('data-url')
            if street_url:
                full_street_url = f"https://www.ebwo.de{street_url}"
                send_message(user_id, f"Street URL found: {full_street_url}")
                return full_street_url
    send_message(user_id, "No matching street URL found")
    return None

def get_abholtermine(street_url, user_id):
    response = requests.get(street_url)
    send_message(user_id, f"Requesting street URL: {street_url}\nStatus Code: {response.status_code}")
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')
    abholtermine = {
        "Gelbe Tonne": [],
        "Altpapier": [],
        "Restabfall (bis 240 Liter)": [],
        "Bio-Abfälle": []
    }

    divs = soup.find_all('div', style=lambda value: value and 'margin-top:25px;' in value)
    send_message(user_id, f"Found {len(divs)} divs with dates")
    category_order = ["Gelbe Tonne", "Altpapier", "Restabfall (bis 240 Liter)", "Bio-Abfälle"]

    for idx, div in enumerate(divs):
        current_category = category_order[idx % len(category_order)]
        div_content = div.get_text(separator="\n").split("\n")
        dates = [d.strip() for d in div_content if d.strip() and d.strip().isdigit() == False and d.strip().count('.') == 2]
        
        abholtermine[current_category].extend(dates)
        send_message(user_id, f"Category: {current_category}\nDates: {', '.join(dates)}")

    for category in abholtermine:
        abholtermine[category] = sorted(abholtermine[category], key=lambda date: datetime.strptime(date, "%d.%m.%Y"))

    send_message(user_id, f"Final sorted dates: {abholtermine}")
    return abholtermine

@app.route('/')
def index():
    return jsonify({"message": "Welcome to the Chat Service"}), 200

@app.route('/chat_callback', methods=['POST'])
def chat_callback():
    json_data = request.get_json()
    app.logger.debug('Received JSON data: %s', json_data)

    message_content = json_data.get("message", {}).get("content", {}).get("messageContent", {}).get("messageText", "")
    message_type = json_data.get("message", {}).get("content", {}).get("messageType", "")
    user_id = json_data.get("message", {}).get("from", {}).get("userId", "")

    if message_type == "init":
        # Ask for the user's street name
        send_message(user_id, "Bitte geben Sie Ihren Straßennamen ein. 2")
    elif message_type == "processChatMessage" and message_content:
        # Process the user's response (assume it's the street name)
        street_name = message_content.strip()
        app.logger.debug(f'Street name received: {street_name}')
        send_message(user_id, f"Street name received: {street_name}")
        street_url = get_street_web_address(street_name, user_id)
        if street_url:
            abholtermine = get_abholtermine(street_url, user_id)
            response_message = f"Abholtermine für {street_name}:\n"
            for category, dates in abholtermine.items():
                response_message += f"{category}:\n"
                response_message += "\n".join(dates) + "\n"
            send_message(user_id, response_message)
        else:
            send_message(user_id, "Straße nicht gefunden. Bitte versuchen Sie es erneut.")
    else:
        app.logger.debug('Unknown message type or empty message content.')

    return jsonify({"status": "received"}), 200

if __name__ == '__main__':
    app.run(debug=True)