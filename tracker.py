# tracker.py - 진입가 및 최고가 관리

entry_price_dict = {}
peak_price_dict = {}

def set_entry_price(symbol: str, price: float):
    symbol = symbol.upper()
    entry_price_dict[symbol] = price
    peak_price_dict[symbol] = price  # 최초 진입가는 곧 최초 최고가


def get_entry_price(symbol: str):
    return entry_price_dict.get(symbol.upper())


def get_peak_price(symbol: str):
    return peak_price_dict.get(symbol.upper())


def update_peak_price(symbol: str, current_price: float):
    symbol = symbol.upper()
    if symbol in peak_price_dict:
        peak_price_dict[symbol] = max(peak_price_dict[symbol], current_price)
