# Python 3.11 슬림 버전 사용 (3.12 대신 안정적인 버전으로 변경)
FROM python:3.10-slim

# 작업 디렉토리 설정
WORKDIR /app

# OS 레벨 빌드 의존성 설치
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    g++ \
    python3-dev \
    libatlas-base-dev \
    && rm -rf /var/lib/apt/lists/*

# requirements.txt 복사
COPY requirements.txt .

# pip 최신화 + 의존성 설치
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# 소스코드 전체 복사
COPY . .

# 실행 명령어 (실제 실행 파일명에 맞게 변경)
CMD ["python", "newsbot.py"]
