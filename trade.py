"""
XRP RSI Auto Trading Bot (DRY RUN)
"""

import os
import json
import hmac
import hashlib
import time
import requests
from datetime import datetime, timezone, timedelta

PAIR = "xrp_jpy"
RSI_PERIOD = 14
RSI_BUY = 35
RSI_SELL = 65

STOP_LOSS = -0.06
TAKE_PROFIT = 0.10

ORDER_RATIO = 0.01
MIN_ORDER_JPY = 500

CANDLE_TYPE = "1hour"
DRY_RUN = True

for key in [
    "BITBANK_API_KEY",
    "BITBANK_API_SECRET",
    "GIST_TOKEN",
    "GIST_ID",
]:
    if not os.getenv(key):
        raise RuntimeError(f"環境変数未設定: {key}")

API_KEY = os.environ["BITBANK_API_KEY"]
API_SECRET = os.environ["BITBANK_API_SECRET"]
GIST_TOKEN = os.environ["GIST_TOKEN"]
GIST_ID = os.environ["GIST_ID"]

GIST_FILE = "xrp_state.json"


DEFAULT_STATE = {
    "holding": False,
    "buy_price": 0.0,
    "buy_amount": 0.0,
    "prev_rsi": 50.0,
    "last_run": "",
}


def log(msg):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"[{now}] {msg}")


def load_state():
    try:
        r = requests.get(
            f"https://api.github.com/gists/{GIST_ID}",
            headers={"Authorization": f"token {GIST_TOKEN}"},
            timeout=10,
        )
        r.raise_for_status()

        content = r.json()["files"][GIST_FILE]["content"]
        return {**DEFAULT_STATE, **json.loads(content)}
    except Exception:
        return DEFAULT_STATE.copy()


def save_state(state):
    state["last_run"] = datetime.now(timezone.utc).isoformat()

    payload = {
        "files": {
            GIST_FILE: {
                "content": json.dumps(
                    state,
                    indent=2,
                    ensure_ascii=False,
                )
            }
        }
    }

    r = requests.patch(
        f"https://api.github.com/gists/{GIST_ID}",
        headers={"Authorization": f"token {GIST_TOKEN}"},
        json=payload,
        timeout=10,
    )
    r.raise_for_status()


def fetch_candlesticks(pair, candle_type="1hour"):
    date = datetime.now(timezone.utc).strftime("%Y%m%d")

    url = (
        f"https://public.bitbank.cc/"
        f"{pair}/candlestick/{candle_type}/{date}"
    )

    r = requests.get(url, timeout=10)
    r.raise_for_status()

    data = r.json()

    candles = data["data"]["candlestick"][0]["ohlcv"]

    closes = [float(c[3]) for c in candles]
    closes = closes[-100:]
    return closes

def fetch_current_price(pair):
    r = requests.get(
        f"https://public.bitbank.cc/{pair}/ticker",
        timeout=10,
    )

    r.raise_for_status()

    return float(
        r.json()["data"]["last"]
    )

def calc_rsi(closes, period=14):
    recent = closes[-(period + 1):]

    gains = []
    losses = []

    for i in range(1, len(recent)):
        diff = recent[i] - recent[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def get_balance(asset):
    path = "/v1/user/assets"

    nonce = str(int(time.time() * 1000))

    signature = hmac.new(
        API_SECRET.encode(),
        (nonce + path).encode(),
        hashlib.sha256,
    ).hexdigest()

    r = requests.get(
        "https://api.bitbank.cc" + path,
        headers={
            "ACCESS-KEY": API_KEY,
            "ACCESS-NONCE": nonce,
            "ACCESS-SIGNATURE": signature,
        },
        timeout=10,
    )

    r.raise_for_status()

    result = r.json()

    if result["success"] != 1:
        raise RuntimeError(result)

    for item in result["data"]["assets"]:
        if item["asset"] == asset:
            return float(item["free_amount"])

    return 0.0


def place_order(pair, side, amount):
    log(f"[DRY RUN] {side} {amount:.4f} XRP")
    return {}


def run():
    log("WORKFLOW VERSION 2026-06-07")
    log("=" * 50)
    log("XRP RSI Bot 起動")

    state = load_state()

    # 実残高と状態の整合性確認
    if state["holding"] and get_balance("xrp") <= 0:
        log("保有フラグをリセット")
        state["holding"] = False
        state["buy_price"] = 0.0
        state["buy_amount"] = 0.0

    closes = fetch_candlesticks(PAIR)
    current_price = fetch_current_price(PAIR)

    rsi = calc_rsi(closes)
    prev_rsi = state["prev_rsi"]

    log(f"RSI prev={prev_rsi:.2f} current={rsi:.2f}")
    log(f"price={current_price:.4f}")
    log(f"holding={state['holding']}")

    action = "HOLD"

    # ------------------
    # BUY
    # ------------------
    if not state["holding"]:

        log(
            f"BUY CHECK: prev={prev_rsi:.2f} "
            f"current={rsi:.2f} "
            f"threshold={RSI_BUY}"
        )

        buy_signal = (
            prev_rsi >= RSI_BUY
            and rsi < RSI_BUY
        )

        if buy_signal:

            jpy_balance = get_balance("jpy")
            order_jpy = jpy_balance * ORDER_RATIO

            log(
                f"買いシグナル検出 "
                f"(JPY={jpy_balance:.0f})"
            )

            if order_jpy >= MIN_ORDER_JPY:

                amount_xrp = round(
                    order_jpy / current_price,
                    4
                )

                place_order(
                    PAIR,
                    "buy",
                    amount_xrp
                )

                state["holding"] = True
                state["buy_price"] = current_price
                state["buy_amount"] = amount_xrp

                action = "BUY"

            else:
                log(
                    f"残高不足 "
                    f"{order_jpy:.0f}円"
                )

    # ------------------
    # SELL
    # ------------------
    else:

        change = (
            current_price
            - state["buy_price"]
        ) / state["buy_price"]

        log(
            f"損益={change*100:.2f}% "
            f"buy={state['buy_price']:.4f}"
        )

        log(
            f"SELL CHECK: prev={prev_rsi:.2f} "
            f"current={rsi:.2f} "
            f"threshold={RSI_SELL}"
        )

        sell_signal = (
            (prev_rsi <= RSI_SELL and rsi > RSI_SELL)
            or change <= STOP_LOSS
            or change >= TAKE_PROFIT
        )

        if sell_signal:

            amount = min(
                state["buy_amount"],
                get_balance("xrp")
            )

            if amount > 0:

                place_order(
                    PAIR,
                    "sell",
                    round(amount, 4)
                )

                state["holding"] = False
                state["buy_price"] = 0.0
                state["buy_amount"] = 0.0

                action = "SELL"

    state["prev_rsi"] = rsi

    save_state(state)

    log(f"action={action}")
    log("=" * 50)


if __name__ == "__main__":
    run()
