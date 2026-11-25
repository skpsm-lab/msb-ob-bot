import os
import time
import threading
import requests
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
from flask import Flask

# ==========================================
# ૧. TELEGRAM સેટિંગ્સ
# ==========================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "9060401982:AAHSGw_Vu_0M_nMQh8ribyUZPGiYHFeCY6s")
CHAT_ID = os.environ.get("CHAT_ID", "5893873608")

# ==========================================
# ૨. કુલ ૫૬ સ્ક્રિપ્ટ્સનું લિસ્ટ
# ==========================================
CRYPTO_LIST = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

YAHOO_LIST = [
    "^NSEI", "^BSESN", "GC=F",
    "ADANIENT.NS", "ADANIPORTS.NS", "APOLLOHOSP.NS", "ASIANPAINT.NS", "AXISBANK.NS",
    "BAJAJ-AUTO.NS", "BAJFINANCE.NS", "BAJAJFINSV.NS", "BEL.NS", "BHARTIARTL.NS",
    "BPCL.NS", "CIPLA.NS", "COALINDIA.NS", "DRREDDY.NS", "EICHERMOT.NS",
    "GRASIM.NS", "HCLTECH.NS", "HDFCBANK.NS", "HDFCLIFE.NS", "HEROMOTOCO.NS",
    "HINDALCO.NS", "HINDUNILVR.NS", "ICICIBANK.NS", "INDUSINDBK.NS", "INFY.NS",
    "ITC.NS", "JIOFIN.NS", "JSWSTEEL.NS", "KOTAKBANK.NS", "LT.NS",
    "M&M.NS", "MARUTI.NS", "NESTLEIND.NS", "NTPC.NS", "ONGC.NS",
    "POWERGRID.NS", "RELIANCE.NS", "SBILIFE.NS", "SBIN.NS", "SHRIRAMFIN.NS",
    "SUNPHARMA.NS", "TATACONSUM.NS", "TATAMOTORS.NS", "TATASTEEL.NS", "TCS.NS",
    "TECHM.NS", "TITAN.NS", "TRENT.NS", "ULTRACEMCO.NS", "WIPRO.NS"
]

# ==========================================
# ૩. સ્ટ્રેટેજી સેટિંગ્સ (5m)
# ==========================================
TIMEFRAME = "5m"
ZIGZAG_LEN = 9
FIB_FACTOR = 0.273
EMA_LEN = 200
RR_RATIO = 2.0
USE_EMA_FILTER = True

last_alerted = {}
app = Flask(__name__)

@app.route("/")
def home():
    return f"MSB-OB 56 Scanner is Running! Last checked: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC"

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram Error: {e}")

def get_binance_data(symbol, interval="5m", limit=300):
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    try:
        r = requests.get(url, params=params, timeout=10).json()
        df = pd.DataFrame(r, columns=[
            "time", "open", "high", "low", "close", "volume",
            "close_time", "qav", "trades", "tbbav", "tbqav", "ignore"
        ])
        for col in ["open", "high", "low", "close"]:
            df[col] = df[col].astype(float)
        df["time"] = pd.to_datetime(df["time"], unit="ms")
        return df[["time", "open", "high", "low", "close"]]
    except Exception as e:
        print(f"Binance Error ({symbol}): {e}")
        return None

def get_yahoo_batch_data(symbols, interval="5m"):
    try:
        data = yf.download(
            symbols,
            period="5d",
            interval=interval,
            group_by="ticker",
            threads=True,
            progress=False
        )
        return data
    except Exception as e:
        print(f"Yahoo Batch Error: {e}")
        return None

def check_msb_ob_signal(df, symbol):
    if df is None or len(df) < EMA_LEN + 20:
        return

    df = df.copy()
    df["ema200"] = df["close"].ewm(span=EMA_LEN, adjust=False).mean()
    highs = df["high"].values
    lows = df["low"].values
    opens = df["open"].values
    closes = df["close"].values
    ema200 = df["ema200"].values

    swing_highs = []
    swing_lows = []
    trend = 1

    for i in range(ZIGZAG_LEN, len(df) - 1):
        to_up = highs[i] >= np.max(highs[i - ZIGZAG_LEN + 1 : i + 1])
        to_down = lows[i] <= np.min(lows[i - ZIGZAG_LEN + 1 : i + 1])

        prev_trend = trend
        if trend == 1 and to_down:
            trend = -1
        elif trend == -1 and to_up:
            trend = 1

        if trend != prev_trend:
            if trend == 1:
                idx = i - ZIGZAG_LEN + int(np.argmin(lows[i - ZIGZAG_LEN : i + 1]))
                swing_lows.append((idx, lows[idx]))
            else:
                idx = i - ZIGZAG_LEN + int(np.argmax(highs[i - ZIGZAG_LEN : i + 1]))
                swing_highs.append((idx, highs[idx]))

    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return

    h0i, h0 = swing_highs[-1]
    h1i, h1 = swing_highs[-2]
    l0i, l0 = swing_lows[-1]
    l1i, l1 = swing_lows[-2]

    curr = len(df) - 2
    candle_time = str(df["time"].iloc[curr])
    if last_alerted.get(symbol) == candle_time:
        return

    c_open, c_high, c_low, c_close = opens[curr], highs[curr], lows[curr], closes[curr]
    c_ema = ema200[curr]

    # --- BULLISH MSB & Bu-OB ---
    bull_msb = (h0 > h1) and (h0 > h1 + abs(h1 - l0) * FIB_FACTOR)
    if bull_msb and (not USE_EMA_FILTER or c_close > c_ema):
        ob_idx = None
        for idx in range(l0i, max(h1i, 0), -1):
            if opens[idx] > closes[idx]:
                ob_idx = idx
                break
        if ob_idx is not None:
            ob_top, ob_bottom = highs[ob_idx], lows[ob_idx]
            if c_low <= ob_top and c_close > ob_bottom and c_close > c_open:
                sl = ob_bottom
                risk = c_close - sl
                if risk > 0:
                    tp = c_close + (risk * RR_RATIO)
                    msg = (
                        f"🟢 <b>BUY SIGNAL (MSB-OB | 5m)</b>\n"
                        f"📌 <b>Symbol:</b> {symbol}\n"
                        f"💰 <b>Entry:</b> {c_close:.2f}\n"
                        f"🛑 <b>SL:</b> {sl:.2f}\n"
                        f"🎯 <b>TP (1:2):</b> {tp:.2f}\n"
                        f"🕒 <b>Candle:</b> {candle_time}"
                    )
                    send_telegram(msg)
                    last_alerted[symbol] = candle_time

    # --- BEARISH MSB & Be-OB ---
    bear_msb = (l0 < l1) and (l0 < l1 - abs(h0 - l1) * FIB_FACTOR)
    if bear_msb and (not USE_EMA_FILTER or c_close < c_ema):
        ob_idx = None
        for idx in range(h0i, max(l1i, 0), -1):
            if opens[idx] < closes[idx]:
                ob_idx = idx
                break
        if ob_idx is not None:
            ob_top, ob_bottom = highs[ob_idx], lows[ob_idx]
            if c_high >= ob_bottom and c_close < ob_top and c_close < c_open:
                sl = ob_top
                risk = sl - c_close
                if risk > 0:
                    tp = c_close - (risk * RR_RATIO)
                    msg = (
                        f"🔴 <b>SELL SIGNAL (MSB-OB | 5m)</b>\n"
                        f"📌 <b>Symbol:</b> {symbol}\n"
                        f"💰 <b>Entry:</b> {c_close:.2f}\n"
                        f"🛑 <b>SL:</b> {sl:.2f}\n"
                        f"🎯 <b>TP (1:2):</b> {tp:.2f}\n"
                        f"🕒 <b>Candle:</b> {candle_time}"
                    )
                    send_telegram(msg)
                    last_alerted[symbol] = candle_time

def wait_for_next_5m():
    now = datetime.now()
    seconds_past = (now.minute % 5) * 60 + now.second
    sleep_time = (300 - seconds_past) + 5
    time.sleep(sleep_time)

def scanner_loop():
    send_telegram("🚀 <b>Render Cloud પર 56 Scripts MSB-OB (5m) Scanner ચાલુ થઈ ગયું છે!</b>")
    while True:
        try:
            for coin in CRYPTO_LIST:
                df_c = get_binance_data(coin, TIMEFRAME)
                check_msb_ob_signal(df_c, coin)

            batch_data = get_yahoo_batch_data(YAHOO_LIST, TIMEFRAME)
            if batch_data is not None and not batch_data.empty:
                for sym in YAHOO_LIST:
                    try:
                        if sym in batch_data.columns.get_level_values(0):
                            df_s = batch_data[sym].dropna().reset_index()
                            time_col = "Datetime" if "Datetime" in df_s.columns else "Date"
                            df_s = df_s.rename(columns={
                                time_col: "time", "Open": "open", "High": "high",
                                "Low": "low", "Close": "close"
                            })
                            df_s = df_s[["time", "open", "high", "low", "close"]].tail(300).reset_index(drop=True)
                            check_msb_ob_signal(df_s, sym)
                    except Exception as e:
                        print(f"Error processing {sym}: {e}")
        except Exception as e:
            print(f"Loop Error: {e}")

        wait_for_next_5m()

if __name__ == "__main__":
    t = threading.Thread(target=scanner_loop, daemon=True)
    t.start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
