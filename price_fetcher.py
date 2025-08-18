import requests

SPOT_BASE = 'https://api.mexc.com'
FUTURES_BASE = 'https://contract.mexc.com'

def _futures_symbol(symbol: str) -> str:
    return symbol.replace("USDT", "_USDT")

def get_current_price(symbol: str):
    """선물 가격 우선, 실패 시 현물로 폴백."""
    try:
        fsym = _futures_symbol(symbol)
        r = requests.get(f"{FUTURES_BASE}/api/v1/contract/ticker",
                         params={"symbol": fsym}, timeout=5)
        r.raise_for_status()
        data = r.json().get("data")
        if isinstance(data, list) and data:
            return float(data[0]["lastPrice"])
        else:
            return float(data["lastPrice"])
    except Exception:
        try:
            r = requests.get(f"{SPOT_BASE}/api/v3/ticker/price",
                             params={"symbol": symbol}, timeout=5)
            r.raise_for_status()
            return float(r.json()["price"])
        except Exception:
            return None

def get_all_prices(symbols):
    prices = {}
    for s in symbols:
        p = get_current_price(s)
        if p is not None:
            prices[s] = p
    return prices
