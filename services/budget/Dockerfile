FROM python:3.11-alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=5001

WORKDIR /app

RUN apk add --no-cache ca-certificates libstdc++

COPY requirements.txt .

RUN pip install --no-cache-dir --only-binary=pymssql -r requirements.txt

RUN addgroup -S appgroup && adduser -S appuser -G appgroup

COPY . .

USER appuser

EXPOSE 5001

CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT} --workers 2 --threads 2 --timeout 30 --access-logfile - --error-logfile - app:app"]