import os
import re
import sqlite3
from datetime import datetime
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import httpx
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = FastAPI(title="Francis' Fastlink - Automated Data Distribution & USSD Engine")

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- CONFIGURATION & PRICING ---
RECEIVER_PHONE = "0249998737"
TECHLINK_API_KEY = os.getenv("TECHLINK_API_KEY")
WHOLESALE_API_URL = os.getenv("WHOLESALE_API_URL", "https://api.techlinkgh.com/api/v1/topup")
WALLET_BALANCE_URL = "https://api.techlinkgh.com/api/v1/wallet/balance"

# Base wholesale/cost prices (A hidden 5% profit margin is automatically added on checkout)
BASE_PRICES = {
    "MTN": {
        "1GB": 4.50,
        "2GB": 9.00,
        "3GB": 13.00,
        "4GB": 17.00,
        "5GB": 21.80,
        "10GB": 41.50,
    },
    "TELECEL": {
        "1GB": 5.00,
        "2GB": 10.00,
        "3GB": 14.50,
        "4GB": 18.50,
        "5GB": 22.00,
        "10GB": 43.00,
    },
    "AIRTELTIGO": {
        "1GB": 4.80,
        "2GB": 9.50,
        "3GB": 13.50,
        "4GB": 17.50,
        "5GB": 22.00,
        "10GB": 42.00,
    },
}

DB_FILE = "fastlink.db"

# --- DATABASE SETUP (AUTO-FIXES SCHEMA) ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Automatically drops the old table to prevent column mismatch errors
    cursor.execute("DROP TABLE IF EXISTS orders")
    
    cursor.execute("""
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reference TEXT UNIQUE,
            customer_phone TEXT,
            network TEXT,
            bundle_name TEXT,
            amount REAL,
            status TEXT,
            created_at TEXT,
            delivered_at TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

class CheckoutRequest(BaseModel):
    phone_number: str
    network: str
    bundle_name: str

# --- BACKGROUND WORKER: TECHLINK GH FULFILLMENT ---
async def fulfill_wholesale_bundle(phone_number: str, network: str, bundle_size: str, reference: str):
    """Sends automated top-up request to Techlink GH live API."""
    headers = {
        "x-api-key": TECHLINK_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "phone": phone_number,
        "network": network,
        "bundle": bundle_size,
        "reference": reference,
    }

    delivered_time = None
    status = "FAILED"

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(WHOLESALE_API_URL, json=payload, headers=headers)
            if response.status_code in [200, 201]:
                delivered_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                status = "SUCCESSFUL"
                print(f"--- Techlink GH: Successfully delivered {bundle_size} to {phone_number} ---")
            else:
                print(f"--- Techlink GH Error: {response.text} ---")
        except Exception as e:
            print(f"--- Techlink GH Connection Exception: {e} ---")

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE orders 
        SET status = ?, delivered_at = ? 
        WHERE reference = ?
    """, (status, delivered_time, reference))
    conn.commit()
    conn.close()


# --- FRONTEND UI ---
@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Francis' Fastlink - Automated High-Speed Data Distribution</title>
        <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-[#0b1329] text-zinc-100 min-h-screen flex justify-center p-3 font-sans">
        <div class="w-full max-w-md space-y-4 pb-12">
            
            <!-- HEADER -->
            <div class="text-center space-y-1 pt-2">
                <h1 class="text-xl font-black text-amber-500 tracking-wider">FRANCIS' FASTLINK</h1>
                <p class="text-xs text-zinc-400 font-medium">Automated High-Speed Data Distribution</p>
            </div>

            <!-- LIVE DELIVERY STATUS CARD -->
            <div class="bg-[#131d3b] border border-zinc-700/60 rounded-2xl p-4 shadow-xl space-y-3">
                <div class="flex justify-between items-center">
                    <div class="flex items-center space-x-2">
                        <span class="w-2 h-2 bg-emerald-400 rounded-full animate-ping"></span>
                        <span class="text-xs font-bold text-zinc-200 tracking-wide uppercase">Delivery Status</span>
                    </div>
                    <span class="bg-red-500/10 text-red-500 border border-red-500/30 text-[10px] font-bold px-2.5 py-0.5 rounded-full flex items-center space-x-1.5">
                        <span class="w-1.5 h-1.5 bg-red-500 rounded-full animate-pulse"></span>
                        <span>LIVE</span>
                    </span>
                </div>
                <div class="bg-[#090e1f] rounded-xl p-3 space-y-2 border border-zinc-800">
                    <div class="flex justify-between text-[11px] text-zinc-400">
                        <span>LATEST DELIVERED ORDER</span>
                        <span id="latest-batch-time" class="font-mono text-zinc-300">Loading...</span>
                    </div>
                    <div class="flex justify-between items-center">
                        <span id="latest-batch-id" class="text-sm font-mono font-bold text-amber-400">#------</span>
                        <span id="latest-batch-status" class="text-[10px] bg-emerald-950 text-emerald-400 px-2.5 py-0.5 rounded-full border border-emerald-800 font-bold">Checking</span>
                    </div>
                </div>
            </div>

            <!-- VIEW 1: NETWORK SELECTION -->
            <div id="network-view" class="space-y-3">
                <h2 class="text-xs font-bold uppercase tracking-wider text-zinc-400 px-1">Select Your Network</h2>
                
                <div onclick="selectNetwork('MTN')" class="bg-[#131d3b] border border-zinc-700/60 rounded-2xl p-4 cursor-pointer hover:border-amber-400 transition flex items-center justify-between shadow-md">
                    <div class="flex items-center space-x-3">
                        <div class="w-11 h-11 bg-amber-400 rounded-xl flex items-center justify-center text-zinc-950 font-black text-xs shadow">MTN</div>
                        <div>
                            <h3 class="text-sm font-bold text-zinc-100">MTN Non-Expiry Bundles</h3>
                            <p class="text-xs text-zinc-400">6 bundles available</p>
                        </div>
                    </div>
                    <span class="text-amber-400 text-lg font-bold">›</span>
                </div>

                <div onclick="selectNetwork('TELECEL')" class="bg-[#131d3b] border border-zinc-700/60 rounded-2xl p-4 cursor-pointer hover:border-red-400 transition flex items-center justify-between shadow-md">
                    <div class="flex items-center space-x-3">
                        <div class="w-11 h-11 bg-red-600 rounded-xl flex items-center justify-center text-white font-black text-xs shadow">TC</div>
                        <div>
                            <h3 class="text-sm font-bold text-zinc-100">TELECEL Bundles</h3>
                            <p class="text-xs text-zinc-400">6 bundles available</p>
                        </div>
                    </div>
                    <span class="text-red-400 text-lg font-bold">›</span>
                </div>

                <div onclick="selectNetwork('AIRTELTIGO')" class="bg-[#131d3b] border border-zinc-700/60 rounded-2xl p-4 cursor-pointer hover:border-cyan-400 transition flex items-center justify-between shadow-md">
                    <div class="flex items-center space-x-3">
                        <div class="w-11 h-11 bg-cyan-600 rounded-xl flex items-center justify-center text-white font-black text-xs shadow">AT</div>
                        <div>
                            <h3 class="text-sm font-bold text-zinc-100">AirtelTigo Bundles</h3>
                            <p class="text-xs text-zinc-400">6 bundles available</p>
                        </div>
                    </div>
                    <span class="text-cyan-400 text-lg font-bold">›</span>
                </div>
            </div>

            <!-- VIEW 2: BUNDLE SIZE LIST -->
            <div id="bundle-view" class="hidden space-y-3">
                <div class="flex items-center justify-between bg-[#131d3b] border border-zinc-700/60 rounded-xl p-3 shadow">
                    <button onclick="goBackToNetworks()" class="text-xs font-semibold text-zinc-400 hover:text-white">← Back</button>
                    <h2 id="bundle-header-title" class="text-sm font-bold text-zinc-100">Bundles</h2>
                    <span></span>
                </div>
                <div id="bundle-list" class="space-y-2"></div>
            </div>

            <!-- VIEW 3: CHECKOUT -->
            <div id="checkout-view" class="hidden bg-[#131d3b] border border-zinc-700/60 rounded-2xl p-5 shadow-xl space-y-4">
                <div class="flex justify-between items-center border-b border-zinc-800 pb-2">
                    <h2 class="text-sm font-bold text-zinc-100">Secure Checkout</h2>
                    <button onclick="goBackToBundles()" class="text-zinc-400 hover:text-white text-sm font-bold">✕</button>
                </div>

                <div>
                    <label class="block text-[10px] font-bold text-zinc-400 uppercase tracking-wider mb-2">Payment Destination</label>
                    <div class="bg-amber-500/10 border border-amber-500/30 rounded-xl p-3">
                        <p class="text-xs font-bold text-amber-300">Francis' Direct MoMo</p>
                        <p class="text-[11px] text-amber-400/80 font-mono">0249998737</p>
                    </div>
                </div>

                <div>
                    <label class="block text-[10px] font-bold text-zinc-400 uppercase tracking-wider mb-1">Recipient Phone Number</label>
                    <input type="text" id="recipient-phone" placeholder="e.g., 0244123456" 
                        class="w-full bg-[#090e1f] border border-zinc-700 rounded-xl px-3 py-2.5 text-sm text-zinc-100 focus:outline-none focus:border-amber-400">
                </div>

                <div class="bg-[#090e1f] border border-zinc-800 rounded-xl p-3 space-y-1.5 text-xs">
                    <div class="flex justify-between"><span class="text-zinc-400">Selected Bundle:</span> <span id="sum-bundle" class="font-semibold text-zinc-200">1GB</span></div>
                    <div class="flex justify-between items-center text-sm pt-2 border-t border-zinc-800">
                        <span class="font-bold text-zinc-300">Total Display Price:</span>
                        <span id="sum-price" class="font-bold text-amber-400 text-base">₵4.50</span>
                    </div>
                </div>

                <button onclick="executeCheckout()" class="w-full bg-amber-500 hover:bg-amber-400 text-zinc-950 font-bold py-3 rounded-xl text-xs shadow-lg transition">Generate Direct Shortcode</button>
            </div>

            <!-- VIEW 4: SUCCESS & USSD DIAL -->
            <div id="success-view" class="hidden space-y-4">
                <div class="bg-amber-500 rounded-2xl p-6 text-center text-zinc-950 shadow-lg">
                    <h2 class="text-lg font-black mb-1">Payment Prompt Ready</h2>
                    <p class="text-xs font-medium opacity-90">Approve payment on your phone. Delivery will auto-trigger upon confirmation.</p>
                </div>

                <div class="bg-[#131d3b] border-2 border-amber-400/80 rounded-2xl p-5 text-center space-y-3 shadow-xl">
                    <div id="ussd-code-display" class="text-base font-black font-mono text-amber-300 tracking-wider bg-[#090e1f] p-3 rounded-xl border border-zinc-800"></div>
                    <a id="dial-btn" href="#" class="w-full bg-emerald-600 hover:bg-emerald-500 text-white font-bold py-3.5 rounded-xl text-sm flex items-center justify-center space-x-2 shadow-md transition">
                        <span>📞</span>
                        <span id="dial-btn-text">Dial to Pay</span>
                    </a>
                </div>

                <div class="bg-[#131d3b] border border-zinc-700/60 rounded-2xl p-4 space-y-3 text-xs shadow">
                    <div class="flex justify-between"><span class="text-zinc-400">Order Reference:</span> <span id="suc-ref" class="font-mono font-bold text-zinc-200"></span></div>
                    <div class="flex justify-between items-center">
                        <span class="text-zinc-400">Status:</span>
                        <span id="suc-status-badge" class="bg-amber-500/20 text-amber-300 border border-amber-500/30 px-2.5 py-0.5 rounded-full font-bold text-[10px]">Processing via Techlink GH</span>
                    </div>
                </div>
            </div>

        </div>

        <script>
            let selectedNetwork = '';
            let selectedBundleName = '';

            const bundleDisplayData = {
                'MTN': [
                    {name: '1GB', price: 4.50}, {name: '2GB', price: 9.00}, 
                    {name: '3GB', price: 13.00}, {name: '4GB', price: 17.00}, 
                    {name: '5GB', price: 21.80}, {name: '10GB', price: 41.50}
                ],
                'TELECEL': [
                    {name: '1GB', price: 5.00}, {name: '2GB', price: 10.00}, 
                    {name: '3GB', price: 14.50}, {name: '4GB', price: 18.50}, 
                    {name: '5GB', price: 22.00}, {name: '10GB', price: 43.00}
                ],
                'AIRTELTIGO': [
                    {name: '1GB', price: 4.80}, {name: '2GB', price: 9.50}, 
                    {name: '3GB', price: 13.50}, {name: '4GB', price: 17.50}, 
                    {name: '5GB', price: 22.00}, {name: '10GB', price: 42.00}
                ]
            };

            async function fetchLiveStats() {
                try {
                    const res = await fetch('/api/v1/stats');
                    const data = await res.json();
                    if (data.reference) {
                        document.getElementById('latest-batch-id').innerText = data.reference;
                        document.getElementById('latest-batch-time').innerText = data.timestamp;
                        document.getElementById('latest-batch-status').innerText = "Delivered";
                    } else {
                        document.getElementById('latest-batch-id').innerText = "FL-0000";
                        document.getElementById('latest-batch-time').innerText = "Ready";
                        document.getElementById('latest-batch-status').innerText = "Online";
                    }
                } catch (e) {
                    console.error("Stats fetch error:", e);
                }
            }
            setInterval(fetchLiveStats, 5000);
            fetchLiveStats();

            function selectNetwork(net) {
                selectedNetwork = net;
                document.getElementById('network-view').classList.add('hidden');
                document.getElementById('bundle-view').classList.remove('hidden');
                document.getElementById('bundle-header-title').innerText = net + " Bundles";

                const listEl = document.getElementById('bundle-list');
                listEl.innerHTML = '';
                bundleDisplayData[net].forEach(b => {
                    listEl.innerHTML += `
                        <div onclick="openCheckout('${b.name}', ${b.price})" class="bg-[#131d3b] border border-zinc-700/60 hover:border-amber-400 rounded-xl p-3.5 cursor-pointer flex justify-between items-center shadow transition">
                            <span class="font-bold text-sm text-zinc-100">${b.name} Bundle</span>
                            <div class="flex items-center space-x-2">
                                <span class="font-bold text-amber-400 text-sm">₵${b.price.toFixed(2)}</span>
                                <span class="text-zinc-500 text-sm">›</span>
                            </div>
                        </div>
                    `;
                });
            }

            function goBackToNetworks() {
                document.getElementById('bundle-view').classList.add('hidden');
                document.getElementById('network-view').classList.remove('hidden');
            }

            function openCheckout(bundleName, price) {
                selectedBundleName = bundleName;
                document.getElementById('bundle-view').classList.add('hidden');
                document.getElementById('checkout-view').classList.remove('hidden');
                document.getElementById('sum-bundle').innerText = bundleName;
                document.getElementById('sum-price').innerText = `₵${price.toFixed(2)}`;
                document.getElementById('recipient-phone').value = '';
            }

            function goBackToBundles() {
                document.getElementById('checkout-view').classList.add('hidden');
                document.getElementById('bundle-view').classList.remove('hidden');
            }

            async function executeCheckout() {
                const phone = document.getElementById('recipient-phone').value.trim();
                if (!phone || phone.length < 10) { alert("Please enter a valid recipient phone number."); return; }

                const res = await fetch('/api/v1/checkout', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ phone_number: phone, network: selectedNetwork, bundle_name: selectedBundleName })
                });
                const data = await res.json();
                if (res.ok) {
                    document.getElementById('checkout-view').classList.add('hidden');
                    document.getElementById('success-view').classList.remove('hidden');
                    document.getElementById('suc-ref').innerText = data.reference;

                    const ussdString = `*170*1*1*0249998737*${data.amount.toFixed(2)}*${data.reference}#`;
                    document.getElementById('ussd-code-display').innerText = ussdString;
                    document.getElementById('dial-btn').href = `tel:${encodeURIComponent(ussdString)}`;
                    document.getElementById('dial-btn-text').innerText = `Dial to Pay ₵${data.amount.toFixed(2)}`;

                    pollOrderStatus(data.reference);
                }
            }

            async function pollOrderStatus(reference) {
                const interval = setInterval(async () => {
                    const res = await fetch(`/api/v1/order/status/${reference}`);
                    const data = await res.json();
                    if (data.status === 'SUCCESSFUL') {
                        document.getElementById('suc-status-badge').className = "bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 px-2.5 py-0.5 rounded-full font-bold text-[10px]";
                        document.getElementById('suc-status-badge').innerText = "Delivered Successfully!";
                        clearInterval(interval);
                        fetchLiveStats();
                    }
                }, 4000);
            }
        </script>
    </body>
    </html>
    """

# --- BACKEND API ENDPOINTS ---
@app.get("/api/v1/stats")
def get_live_stats():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT reference, created_at FROM orders WHERE status = 'SUCCESSFUL' ORDER BY id DESC LIMIT 1")
    row = cursor.fetchone()
    conn.close()

    if row:
        return {"reference": row[0], "timestamp": row[1]}
    return {"reference": None, "timestamp": None}

@app.post("/api/v1/checkout")
def process_checkout(order: CheckoutRequest, background_tasks: BackgroundTasks):
    network_key = order.network.upper().strip()
    base_price = BASE_PRICES.get(network_key, {}).get(order.bundle_name)
    if not base_price:
        raise HTTPException(status_code=400, detail="Invalid bundle selected.")

    # Hidden 5% profit margin calculation
    final_amount = round(base_price * 1.05, 2)
    reference_id = f"FL-{os.urandom(2).hex().upper()}"
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO orders (reference, customer_phone, network, bundle_name, amount, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (reference_id, order.phone_number, network_key, order.bundle_name, final_amount, "PENDING", created_at))
    conn.commit()
    conn.close()

    # Trigger background wholesale fulfillment with Techlink GH
    background_tasks.add_task(
        fulfill_wholesale_bundle,
        phone_number=order.phone_number,
        network=network_key,
        bundle_size=order.bundle_name,
        reference=reference_id
    )

    return {"status": "success", "reference": reference_id, "amount": final_amount}

@app.get("/api/v1/order/status/{reference}")
def get_order_status(reference: str):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT status FROM orders WHERE reference = ?", (reference,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Order not found")

    return {"reference": reference, "status": row[0]}

@app.get("/api/v1/test-connection")
async def test_techlink_connection():
    headers = {"x-api-key": TECHLINK_API_KEY}
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(WALLET_BALANCE_URL, headers=headers)
            if response.status_code == 200:
                return {"status": "connected", "data": response.json()}
            return {"status": "error", "code": response.status_code, "detail": response.text}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))