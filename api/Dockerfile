FROM python:3.13-alpine

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN addgroup -S app && adduser -S app -G app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
RUN mkdir -p /data && chown app:app /data
USER app

EXPOSE 5175
CMD ["uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "5175"]
