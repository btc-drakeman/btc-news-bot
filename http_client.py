# http_client.py
import requests
from requests.adapters import HTTPAdapter, Retry

def make_session():
    s = requests.Session()
    retries = Retry(
        total=3,                # 최대 3번 재시도
        backoff_factor=0.6,     # 0.6, 1.2, 2.4초 ...
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,
    )
    s.mount("https://", HTTPAdapter(max_retries=retries))
    s.mount("http://", HTTPAdapter(max_retries=retries))
    s.headers.update({"User-Agent": "mexcbot/1.0"})
    return s

SESSION = make_session()

