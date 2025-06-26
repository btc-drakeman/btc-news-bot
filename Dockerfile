# Python 3.12.10 슬림 버전 사용
FROM python:3.12.10-slim

# 작업 디렉토리 설정
WORKDIR /app

# 의존성 먼저 복사 (캐시 활용 위해)
COPY requirements.txt .

# pip 최신화 + 의존성 설치
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# 소스코드 전체 복사
COPY . .

# 실행 명령어 (실제 실행 파일명에 맞게 변경)
CMD ["python", "newsbot.py"]
