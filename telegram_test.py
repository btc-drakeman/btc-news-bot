import requests

BOT_TOKEN = '7887009657:AAGsqVHBhD706TnqCjx9mVfp1YIsAtQVN1w'
USER_ID = '7505401062'

def send_test_message():
    url = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'
    data = {'chat_id': USER_ID, 'text': '테스트 메시지입니다.'}
    resp = requests.post(url, data=data)
    print(resp.status_code, resp.text)

send_test_message()
