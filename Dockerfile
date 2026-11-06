FROM python:3.11-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# The embedding model is baked into the image: no download at start, no outside calls at run time
COPY scripts/download_model.py scripts/
RUN python scripts/download_model.py

COPY app app
COPY knowledge knowledge
COPY widget widget
COPY scripts scripts

RUN useradd --system --uid 1000 app && chown -R app /app
USER app

EXPOSE 8000
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
