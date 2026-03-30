import os, time, threading, requests
from datetime import datetime
from flask import Flask
from binance.client import Client
from binance.enums import *
from binance.exceptions import BinanceAPIException

# ========= CONFIG =========
API_KEY = os.getenv("X4FItsMDMqLhkmRvxgBAvdQsgCTp51Iv7laH1p00iIeeOaewIJL2CWpjjvW8WTGt")
API_SECRET = os.getenv("nTNXhs0g4xS1Un1A3iOHvpNOFzV36a8iExZMMRXvwxSdyGpu8uZIBgah0EUiUzeB")
TELEGRAM_TOKEN = os.getenv("8025404826:AAHwAIFw4zZa-QQxjBfbaI73AhVQ6n8bRxw")
CHAT_ID = os.getenv("8783795172")

BOT_NAME = "BOT_GODMODE"

INITIAL_CAPITAL = 100
TP_PERCENT = 1
SL_PERCENT = 0.5

SYMBOLS = [
    "BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT",
    "ADAUSDT","DOGEUSDT","AVAXUSDT","LINKUSDT",
    "MATICUSDT","DOTUSDT","LTCUSDT"
]

# ========= INIT =========
client = Client(API_KEY, API_SECRET)
client.FUTURES_URL = "https://testnet.binancefuture.com/fapi"

current_capital = INITIAL_CAPITAL
current_symbol = "BTCUSDT"
cycle_active = False
cycle_start_balance = 0

stats = {"cycles":0,"wins":0,"losses":0,"pnl":0}
history = []

# ========= TELEGRAM =========
def send(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": msg[:4000]}
        )
    except:
        pass

# ========= SAFE CALL =========
def safe_call(func, *args, **kwargs):
    for _ in range(3):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if "502" in str(e):
                time.sleep(2)
                continue
            return None
    return None

# ========= VOLATILITÉ =========
def get_volatility(symbol):
    k = safe_call(client.futures_klines, symbol=symbol, interval="1m", limit=20)
    if not k:
        return 0
    highs = [float(x[2]) for x in k]
    lows = [float(x[3]) for x in k]
    return (max(highs) - min(lows)) / min(lows)

def choose_best_symbol():
    best_symbol, best_vol = None, 0
    for s in SYMBOLS:
        vol = get_volatility(s)
        if vol > best_vol:
            best_vol = vol
            best_symbol = s
    return best_symbol, best_vol

# ========= LEVIER =========
def get_leverage(vol):
    if vol > 0.02:
        return 100
    elif vol > 0.01:
        return 75
    return 50

# ========= POSITIONS =========
def get_positions_value():
    positions = safe_call(client.futures_account)
    long_val, short_val = 0, 0
    if not positions:
        return 0, 0
    for p in positions['positions']:
        amt = float(p['positionAmt'])
        price = float(p['markPrice'])
        if amt > 0:
            long_val = amt * price
        elif amt < 0:
            short_val = abs(amt * price)
    return long_val, short_val

# ========= WEB =========
app = Flask(__name__)

@app.route("/")
def web():
    long_val, short_val = get_positions_value()

    html = f"""
    <html><head>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta http-equiv="refresh" content="5">
    <style>
    body {{ background:#0f172a; color:white; font-family:Arial; padding:20px; }}
    .card {{ background:#1e293b; padding:20px; margin:10px 0; border-radius:12px; font-size:22px; }}
    </style></head><body>

    <h1>🔥 {BOT_NAME}</h1>

    <div class="card">🪙 Paire: {current_symbol}</div>
    <div class="card">💰 Capital: {round(current_capital,2)}$</div>
    <div class="card">📈 PNL: {round(stats['pnl'],2)}$</div>
    <div class="card">🔁 Cycles: {stats['cycles']}</div>

    <div class="card">🟢 LONG: {round(long_val,2)}$</div>
    <div class="card">🔴 SHORT: {round(short_val,2)}$</div>
    """

    for h in history[-5:][::-1]:
        html += f"<div class='card'>🕒 {h['time']} | {round(h['pnl'],2)}$ → {round(h['capital'],2)}$</div>"

    html += "</body></html>"
    return html

def run_web():
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)

# ========= TRADE =========
def open_position(symbol, side, usd, lev):
    try:
        if usd < 5:
            return False

        price_data = safe_call(client.futures_mark_price, symbol=symbol)
        if not price_data:
            return False

        price = float(price_data['markPrice'])
        qty = round((usd * lev) / price, 3)

        if qty <= 0:
            return False

        position_side = "LONG" if side=="LONG" else "SHORT"
        order_side = SIDE_BUY if side=="LONG" else SIDE_SELL

        safe_call(client.futures_change_leverage, symbol=symbol, leverage=lev)

        safe_call(client.futures_create_order,
            symbol=symbol,
            side=order_side,
            positionSide=position_side,
            type="MARKET",
            quantity=qty
        )

        tp = price*(1+TP_PERCENT/100) if side=="LONG" else price*(1-TP_PERCENT/100)
        sl = price*(1-SL_PERCENT/100) if side=="LONG" else price*(1+SL_PERCENT/100)

        safe_call(client.futures_create_order,
            symbol=symbol,
            side=SIDE_SELL if side=="LONG" else SIDE_BUY,
            positionSide=position_side,
            type="TAKE_PROFIT_MARKET",
            stopPrice=round(tp,4),
            closePosition=True
        )

        safe_call(client.futures_create_order,
            symbol=symbol,
            side=SIDE_SELL if side=="LONG" else SIDE_BUY,
            positionSide=position_side,
            type="STOP_MARKET",
            stopPrice=round(sl,4),
            closePosition=True
        )

        send(f"🚀 {symbol} {side} | {usd}$ | lev {lev}")
        return True

    except BinanceAPIException as e:
        send(f"❌ API: {e}")
        return False
    except Exception as e:
        send(f"❌ Crash: {e}")
        return False

# ========= CYCLE =========
def start_cycle():
    global cycle_active, cycle_start_balance, current_symbol

    best_symbol, vol = choose_best_symbol()
    if not best_symbol:
        return

    current_symbol = best_symbol
    lev = get_leverage(vol)

    balance = safe_call(client.futures_account_balance)
    if not balance:
        return

    usdt = float(next(b for b in balance if b['asset']=="USDT")['balance'])
    cycle_start_balance = usdt

    half = current_capital / 2

    ok1 = open_position(current_symbol,"LONG",half,lev)
    ok2 = open_position(current_symbol,"SHORT",half,lev)

    if ok1 and ok2:
        send(f"🔥 Nouveau cycle {current_symbol} lev {lev}")
        cycle_active = True

# ========= CHECK =========
def check_cycle():
    global cycle_active, current_capital

    positions = safe_call(client.futures_account)
    if not positions:
        return

    open_amt = sum(abs(float(p['positionAmt'])) for p in positions['positions'])

    if open_amt == 0 and cycle_active:

        balance = safe_call(client.futures_account_balance)
        if not balance:
            return

        usdt = float(next(b for b in balance if b['asset']=="USDT")['balance'])
        pnl = usdt - cycle_start_balance

        current_capital += pnl
        stats["pnl"] += pnl
        stats["cycles"] += 1

        history.append({
            "time": datetime.now().strftime("%H:%M"),
            "pnl": pnl,
            "capital": current_capital
        })

        send(f"📊 Cycle fini: {round(pnl,2)}$ | Capital {round(current_capital,2)}$")
        cycle_active = False

# ========= LOOP =========
def bot_loop():
    global cycle_active

    while True:
        try:
            client.futures_ping()

            if not cycle_active:
                start_cycle()

            check_cycle()

            time.sleep(5)

        except BinanceAPIException as e:
            print("API Error:", e)
            time.sleep(5)

        except Exception as e:
            print("Crash:", e)
            time.sleep(5)

# ========= START =========
print("🔥 BOT GODMODE FINAL ONLINE")

threading.Thread(target=run_web).start()
bot_loop()
