# 사고사례 판단 훈련: 화면(React 빌드) + FastAPI + 레이아웃 파서를 컨테이너 하나로.
# 데이터는 Supabase (DATABASE_URL, SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY), LLM은 OPENAI_API_KEY 등 환경변수로 준다.
# 빌드: docker build -t accident-trainer .
# 실행: docker run -p 8000:8000 --env-file .env accident-trainer   -> http://localhost:8000

# 1) 화면 빌드
FROM node:22-slim AS web
WORKDIR /web/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# 2) 서버
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/tmp/accident-trainer \
    FRONTEND_DIST=/app/frontend/dist
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
COPY parser/requirements.txt parser/requirements.txt
# 파서의 고정 버전(pdfplumber 등)이 우선하도록 함께 설치한다
RUN pip install -r backend/requirements.txt -r parser/requirements.txt
COPY parser/ parser/
COPY backend/ backend/
COPY --from=web /web/frontend/dist frontend/dist
WORKDIR /app/backend
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD python -c "import urllib.request,os;urllib.request.urlopen(f'http://127.0.0.1:{os.getenv(\"PORT\",\"8000\")}/api/health')"
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
