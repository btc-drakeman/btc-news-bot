import requests

BASE_URL = 'https://api.mexc.com'

# 단일 심볼 현재가 조회
def get_current_price(symbol: str):
    try:
        endpoint = f"/api/v3/ticker/price"
        res = requests.get(BASE_URL + endpoint, params={"symbol": symbol}, timeout=5)
        res.raise_for_status()
        return float(res.json()["price"])
    except Exception as e:
        print(f"⚠️ 가격 조회 실패: {symbol} → {e}")
        return None

# 다수 심볼 가격 조회 (SIMULATION용)
def get_all_prices(symbols: list[str]) -> dict:
    prices = {}
    for symbol in symbols:
        price = get_current_price(symbol)
        if price:
            prices[symbol] = price
    return prices
