import requests
import json

API_URL = "http://127.0.0.1:8000/api/v1/vision/process"

def main():
    print("--- TEST 1: No API Key (Should fail) ---")
    response_fail = requests.post(API_URL)
    print(f"Status Code: {response_fail.status_code}")
    print(f"Response: {response_fail.text}\n")

    print("--- TEST 2: Correct API Key (Should succeed) ---")
    headers = {
        "X-API-Key": "AQUAGUARD-VISION-SECURE",
        "Content-Type": "application/json"
    }
    payload = {
        "roi_lat": 19.5,
        "roi_lon": 71.4,
        "timestamp": "2026-10-07T14:18:00Z"
    }

    response_success = requests.post(API_URL, headers=headers, json=payload)
    print(f"Status Code: {response_success.status_code}")

    if response_success.status_code == 200:
        print("Integration Dictionary Output:")
        print(json.dumps(response_success.json(), indent=2))
    else:
        print(f"Error: {response_success.text}")

if __name__ == "__main__":
    main()