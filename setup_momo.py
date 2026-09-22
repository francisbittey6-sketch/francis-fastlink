import uuid
import requests

# Your subscription key from the MTN Developer portal
SUBSCRIPTION_KEY = "64f508962f7245408beeebf8eeb82bc0"

# 1. Generate a unique API User ID (UUID v4)
api_user_id = str(uuid.uuid4())
print(f"Generated API User ID (UUID): {api_user_id}")

# 2. Endpoint to create the API user
url_api_user = "https://sandbox.momodeveloper.mtn.com/v1_0/apiuser"

headers_api_user = {
    "X-Reference-Id": api_user_id,
    "Ocp-Apim-Subscription-Key": SUBSCRIPTION_KEY,
    "Content-Type": "application/json",
}

# Sandbox requires a callback host (you can use a placeholder like webhook.site for testing)
payload = {"providerCallbackHost": "https://webhook.site"}

try:
  print("Sending request to create API user...")
  response = requests.post(
      url_api_user, json=payload, headers=headers_api_user
  )
  print(f"Create API User Status Code: {response.status_code}")
  print(f"Create API User Response: {response.text}")

  if response.status_code == 201:
    print("\n--- API User Created Successfully! ---")

    # 3. Endpoint to generate the API Key for this user
    url_api_key = (
        f"https://sandbox.momodeveloper.mtn.com/v1_0/apiuser/{api_user_id}/apikey"
    )
    headers_api_key = {
        "Ocp-Apim-Subscription-Key": SUBSCRIPTION_KEY,
    }

    print("Generating API Key...")
    key_response = requests.post(url_api_key, headers=headers_api_key)
    print(f"API Key Status Code: {key_response.status_code}")
    print(f"API Key Response: {key_response.text}")

    if key_response.status_code == 201:
      api_key = key_response.json().get("apiKey")
      print("\n==============================")
      print("SUCCESS! SAVE THESE CREDENTIALS:")
      print(f"API User (X-Reference-Id): {api_user_id}")
      print(f"API Key: {api_key}")
      print("==============================\n")
    else:
      print("Failed to generate API Key.")
  else:
    print("Failed to create API User. Check your subscription key or network.")

except Exception as e:
  print(f"An error occurred: {e}")