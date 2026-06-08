import os
import time
import requests

ACCESS_TOKEN = os.getenv("INSTAGRAM_TOKEN")
ACCOUNT_ID = os.getenv("INSTAGRAM_ACCOUNT_ID")

ACCESS_TOKEN="IGAAbztNwLCbNBZAGFQY1A0THBZAYUF1OFZAZAN1ByQjlsc2V1Tl9VeDhjbnNqSG1VOUtHb25JekFJQ1VIbHNzYS1aUk5qeHd2ZAGNCSmtaTkRNa29zM1VsdHY2SGVSeG9JVm5oMlNudFQwSFpreWtTTk1GdmJBTzloem5JVWR3RGtWQQZDZD"
ACCOUNT_ID="17841427063072741"

VIDEO_URL = "https://samplelib.com/mp4/sample-5s.mp4"
CAPTION = "My automated Reel upload 🚀"

GRAPH_URL = "https://graph.facebook.com/v23.0"


def create_container():
    url = f"{GRAPH_URL}/{ACCOUNT_ID}/media"

    payload = {
        "media_type": "REELS",
        "video_url": VIDEO_URL,
        "caption": CAPTION,
        "access_token": ACCESS_TOKEN,
    }

    response = requests.post(url, data=payload)
    response.raise_for_status()

    data = response.json()
    print("Container created:", data)

    return data["id"]


def wait_until_finished(container_id):
    status_url = f"{GRAPH_URL}/{container_id}"

    while True:
        params = {
            "fields": "status_code",
            "access_token": ACCESS_TOKEN,
        }

        response = requests.get(status_url, params=params)
        response.raise_for_status()

        status = response.json().get("status_code")
        print("Status:", status)

        if status == "FINISHED":
            return

        if status == "ERROR":
            raise Exception("Instagram processing failed")

        time.sleep(10)


def publish_container(container_id):
    url = f"{GRAPH_URL}/{ACCOUNT_ID}/media_publish"

    payload = {
        "creation_id": container_id,
        "access_token": ACCESS_TOKEN,
    }

    response = requests.post(url, data=payload)
    response.raise_for_status()

    data = response.json()
    print("Published:", data)

    return data


if __name__ == "__main__":
    container_id = create_container()
    wait_until_finished(container_id)
    publish_container(container_id)