import base64
import os
import uuid
from dotenv import load_dotenv
import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

load_dotenv()

router = APIRouter(prefix="/api/v1/momo", tags=["MTN MoMo Payment"])

# Load environment variables
API_USER = os.getenv("MOMO_API_USER")
API_KEY = os.getenv("MOMO_API_KEY")
SUBSCRIPTION_KEY = os.getenv("MOMO_SUBSCRIPTION_KEY")
ENVIRONMENT = os.getenv("MOMO_ENVIRONMENT", "sandbox")

BASE_URL = (
    "https://proxy.momoapi.mtn.com"
    if ENVIRONMENT == "production"
    else "https://sandbox.momodeveloper.mtn.com"
)


class PaymentRequest(BaseModel):
  phone_number: str  # e.g., "233241234567"
  amount: str  # e.g., "10.00"
  description: str


async def get_momo_token() -> str:
  """Generates the OAuth access token from MTN MoMo API."""
  token_url = f"{BASE_URL}/collection/token/"

  credentials = f"{API_USER}:{API_KEY}"
  encoded_credentials = base64.b64encode(credentials.encode("utf-8")).decode(
      "utf-8"
  )

  headers = {
      "Authorization": f"Basic {encoded_credentials}",
      "Ocp-Apim-Subscription-Key": SUBSCRIPTION_KEY,
  }

  async with httpx.AsyncClient() as client:
    response = await client.post(token_url, headers=headers)
    if response.status_code != 200:
      raise HTTPException(
          status_code=400,
          detail="Failed to authenticate with MTN MoMo service.",
      )
    return response.json().get("access_token")


@router.post("/request-pay")
async def request_to_pay(data: PaymentRequest):
  """Triggers the Mobile Money payment prompt on the user's phone."""
  token = await get_momo_token()
  transaction_id = str(uuid.uuid4())  # Unique ID for this specific transaction

  r2p_url = f"{BASE_URL}/collection/v1_0/requesttopay"

  headers = {
      "Authorization": f"Bearer {token}",
      "X-Reference-Id": transaction_id,
      "X-Target-Environment": ENVIRONMENT,
      "Ocp-Apim-Subscription-Key": SUBSCRIPTION_KEY,
      "Content-Type": "application/json",
  }

  # Note: Sandbox environments typically require currency to be 'EUR' or local test currency depending on account configuration
  payload = {
      "amount": data.amount,
      "currency": "EUR" if ENVIRONMENT == "sandbox" else "GHS",
      "externalId": transaction_id[:8],
      "payer": {"partyIdType": "MSISDN", "partyId": data.phone_number},
      "payerMessage": data.description,
      "payeeNote": "Francis Fastlink Data Bundle",
  }

  async with httpx.AsyncClient() as client:
    response = await client.post(r2p_url, json=payload, headers=headers)

    if response.status_code not in [200, 202]:
      raise HTTPException(
          status_code=400,
          detail=(
              "Failed to initiate payment prompt. Check phone number format."
          ),
      )

    return {
        "status": "success",
        "message": "Payment prompt sent to customer phone.",
        "transaction_id": transaction_id,
    }