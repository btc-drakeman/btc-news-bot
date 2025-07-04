import time
import requests
import pandas as pd
from datetime import datetime
from config import USER_IDS

SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'XRPUSDT', 'ETHFIUSDT']

def analysis_loop():
    while True:
        for symbol in SYMBOLS:
            print(f"📊 analyze_symbol() 호출됨: {symbol}")
            try:
                result = analyze_symbol(symbol)
                if result:
                    for uid in USER_IDS:
                        send_telegram(result, uid)
            except Exception as e:
                print(f"❌ 분석 중 오류 발생 ({symbol}): {e}")
            time.sleep(3)
        time.sleep(600)