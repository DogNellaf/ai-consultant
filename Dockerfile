FROM python:3.11-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app app
COPY certs certs
COPY knowledge knowledge
COPY widget widget

# Files stay root's and read-only for the app: it writes nothing to disk (the demo store, sessions
# and uploads live in memory)
RUN useradd --system --uid 1000 app
USER app

EXPOSE 8000
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--workers", "1"]
