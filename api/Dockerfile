# api/Dockerfile
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# КОПИРУЕМ ВСЮ ПАПКУ api внутрь контейнера
COPY . .

EXPOSE 8000

# Команду можно не задавать: у тебя в docker-compose своя команда запуска с ожиданием postgres/kafka
# CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
