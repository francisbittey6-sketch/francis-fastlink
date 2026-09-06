import os
import json
import requests
from fastapi import FastAPI, BackgroundTasks, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from typing import Dict

app = FastAPI()

# Enable CORS for frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration & Environment Variables
PAYSTACK_SECRET_KEY = "sk_test_8a2d40db43c570b6d9e55b019b081888d543f6a7"
PAYSTACK_INIT_URL = "https://api.paystack.co/transaction/initialize"
PAYSTACK_VERIFY_URL = "https://api.paystack.co/transaction/verify/"

SMS_API_KEY = "your_arkesel_api_key"
SMS_SENDER_ID = "Fastllink"
SMS_URL = "https://sms.arkesel.com/api/v2/sms/send"

# Persistent JSON storage file so accounts survive server reloads
USERS_FILE = "users.json"

def load_users():
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_users(users):
    with open(USERS_FILE, "w") as f:
        json.dump(users, f, indent=4)

# Load users into memory on startup
users_db = load_users()

# Data Models
class UserRegister(BaseModel):
    full_name: str
    phone_number: str
    pin: str

class UserLogin(BaseModel):
    phone_number: str
    pin: str

class PurchaseRequest(BaseModel):
    phone_number: str
    network: str
    bundle_size: str
    amount: float

# Helper function to send SMS via Arkesel
def send_sms(phone_number: str, message: str):
    sms_payload = {
        "sender": SMS_SENDER_ID,
        "message": message,
        "recipients": [phone_number]
    }
    sms_headers = {
        "api-key": SMS_API_KEY,
        "Content-Type": "application/json"
    }
    try:
        requests.post(SMS_URL, json=sms_payload, headers=sms_headers)
    except Exception as e:
        print(f"SMS notification error: {e}")

# --- USER ACCOUNT ENDPOINTS ---
@app.post("/api/register")
def register_user(data: UserRegister):
    global users_db
    users_db = load_users()  # Refresh from file
    
    if data.phone_number in users_db:
        raise HTTPException(status_code=400, detail="An account with this phone number already exists.")
    
    users_db[data.phone_number] = {
        "full_name": data.full_name,
        "phone_number": data.phone_number,
        "pin": data.pin
    }
    save_users(users_db)
    return {"status": "success", "message": "Account created successfully!"}

@app.post("/api/login")
def login_user(data: UserLogin):
    global users_db
    users_db = load_users()  # Refresh from file
    
    user = users_db.get(data.phone_number)
    if not user or user["pin"] != data.pin:
        raise HTTPException(status_code=400, detail="Invalid phone number or PIN.")
    
    return {"status": "success", "message": f"Welcome back, {user['full_name']}!", "full_name": user["full_name"]}

# --- PAYMENT & FULFILLMENT ENDPOINTS ---
@app.post("/api/initialize-payment")
def initialize_payment(data: PurchaseRequest):
    headers = {
        "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json"
    }
    
    # Auto-generate a valid email format accepted by Paystack
    generated_email = f"user_{data.phone_number}@fastlink.com"
    
    payload = {
        "email": generated_email,
        "amount": int(data.amount * 100),
        "callback_url": "http://localhost:8000/success.html",
        "metadata": {
            "phone_number": data.phone_number,
            "network": data.network,
            "bundle_size": data.bundle_size
        }
    }

    response = requests.post(PAYSTACK_INIT_URL, json=payload, headers=headers)
    res_data = response.json()

    if not res_data.get("status"):
        raise HTTPException(status_code=400, detail=res_data.get("message", "Payment initialization failed"))

    return res_data

def fulfill_bundle_and_notify(phone_number: str, network: str, bundle_size: str, amount_ghs: float):
    payment_msg = f"FRANCIS'S FASTLINK: Payment of GHS {amount_ghs:.2f} received for your {bundle_size} {network} bundle. Processing delivery..."
    send_sms(phone_number, payment_msg)

    VENDOR_API_URL = "https://api.yourdatavendor.com/v1/topup"
    VENDOR_API_KEY = "your_vendor_api_key"

    vendor_payload = {
        "network": network,
        "phone": phone_number,
        "bundle": bundle_size
    }
    vendor_headers = {
        "Authorization": f"Bearer {VENDOR_API_KEY}",
        "Content-Type": "application/json"
    }

    fulfillment_success = False
    try:
        vendor_res = requests.post(VENDOR_API_URL, json=vendor_payload, headers=vendor_headers)
        if vendor_res.status_code == 200:
            fulfillment_success = True
    except Exception as e:
        print(f"Vendor API connection error: {e}")

    if fulfillment_success:
        delivery_msg = f"FRANCIS'S FASTLINK: Your {bundle_size} {network} data bundle has been successfully delivered to {phone_number}. Enjoy!"
    else:
        delivery_msg = f"FRANCIS'S FASTLINK: Payment confirmed! Your {bundle_size} {network} bundle for {phone_number} is being queued."
    
    send_sms(phone_number, delivery_msg)

@app.get("/api/verify-payment/{reference}")
def verify_payment(reference: str, background_tasks: BackgroundTasks):
    headers = {"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"}

    response = requests.get(PAYSTACK_VERIFY_URL + reference, headers=headers)
    res_data = response.json()

    if not res_data.get("status") or res_data["data"]["status"] != "success":
        raise HTTPException(
            status_code=400,
            detail="Payment verification failed or transaction is still pending.",
        )

    transaction_data = res_data.get("data", {})
    amount_paid = transaction_data.get("amount", 0) / 100

    metadata = transaction_data.get("metadata", {})
    phone_number = metadata.get("phone_number", "0240000000")
    network = metadata.get("network", "MTN")
    bundle_size = metadata.get("bundle_size", "1GB")

    background_tasks.add_task(fulfill_bundle_and_notify, phone_number, network, bundle_size, amount_paid)

    return {
        "status": "success",
        "message": "Payment verified successfully. Notifications and delivery are in progress!",
        "data": transaction_data
    }

# --- ADVANCED USSD GATEWAY ENDPOINT (Supports Guests, Self & Other Numbers) ---
@app.post("/api/ussd")
async def ussd_gateway(request: Request, background_tasks: BackgroundTasks):
    form_data = await request.form()
    caller_phone = form_data.get("phoneNumber", "")
    text = form_data.get("text", "")
    
    if caller_phone.startswith("+233"):
        caller_phone = "0" + caller_phone[4:]

    inputs = text.split("*") if text else []
    response_message = ""

    # --- MAIN MENU ---
    if text == "":
        response_message = (
            "CON Welcome to Francis' Fastlink\n"
            "1. Buy Data Bundle\n"
            "2. Check Account Status"
        )

    # --- OPTION 1: BUY DATA BUNDLE FLOW ---
    elif len(inputs) == 1 and inputs[0] == "1":
        response_message = (
            "CON Select Network:\n"
            "1. MTN\n"
            "2. Telecel\n"
            "3. AT"
        )

    elif len(inputs) == 2 and inputs[0] == "1":
        response_message = (
            "CON Select Bundle Size:\n"
            "1. 1GB - GHS 5\n"
            "2. 2GB - GHS 10\n"
            "3. 5GB - GHS 25\n"
            "4. 10GB - GHS 50"
        )

    elif len(inputs) == 3 and inputs[0] == "1":
        response_message = (
            "CON Recipient Number:\n"
            f"1. Buy for Self ({caller_phone})\n"
            "2. Buy for Another Number"
        )

    elif len(inputs) == 4 and inputs[0] == "1":
        recipient_choice = inputs[3]
        if recipient_choice == "1":
            # Buy for self - execute immediately
            network_choice = inputs[1]
            bundle_choice = inputs[2]
            
            net_map = {"1": "MTN", "2": "Telecel", "3": "AT"}
            bundle_map = {
                "1": ("1GB", 5.0), 
                "2": ("2GB", 10.0), 
                "3": ("5GB", 25.0), 
                "4": ("10GB", 50.0)
            }
            
            network = net_map.get(network_choice, "MTN")
            bundle_size, amount = bundle_map.get(bundle_choice, ("1GB", 5.0))

            background_tasks.add_task(fulfill_bundle_and_notify, caller_phone, network, bundle_size, amount)

            response_message = (
                f"END Request Received!\n"
                f"Processing {bundle_size} {network} bundle for {caller_phone} (GHS {amount}). "
                f"SMS confirmation incoming."
            )
        elif recipient_choice == "2":
            response_message = "CON Enter recipient phone number (e.g. 0551234987):"
        else:
            response_message = "END Invalid choice. Session ended."

    elif len(inputs) == 5 and inputs[0] == "1" and inputs[3] == "2":
        target_phone = inputs[4]
        network_choice = inputs[1]
        bundle_choice = inputs[2]
        
        net_map = {"1": "MTN", "2": "Telecel", "3": "AT"}
        bundle_map = {
            "1": ("1GB", 5.0), 
            "2": ("2GB", 10.0), 
            "3": ("5GB", 25.0), 
            "4": ("10GB", 50.0)
        }
        
        network = net_map.get(network_choice, "MTN")
        bundle_size, amount = bundle_map.get(bundle_choice, ("1GB", 5.0))

        background_tasks.add_task(fulfill_bundle_and_notify, target_phone, network, bundle_size, amount)

        response_message = (
            f"END Request Received!\n"
            f"Processing {bundle_size} {network} bundle for {target_phone} (GHS {amount}). "
            f"SMS confirmation incoming."
        )

    # --- OPTION 2: CHECK ACCOUNT STATUS FLOW ---
    elif len(inputs) == 1 and inputs[0] == "2":
        global users_db
        users_db = load_users()
        
        user = users_db.get(caller_phone)
        if user:
            response_message = (
                f"END Account Found:\n"
                f"Name: {user['full_name']}\n"
                f"Phone: {caller_phone}\n"
                f"Status: Active Fastlink Member"
            )
        else:
            response_message = (
                f"END No account found for {caller_phone}.\n"
                f"You can still buy data anytime! Visit localhost:8000 to register if desired."
            )

    # --- FALLBACK ---
    else:
        response_message = "END Invalid input. Session ended."

    return PlainTextResponse(response_message)

# Serve static HTML files from the project folder
app.mount("/", StaticFiles(directory=".", html=True), name="static")