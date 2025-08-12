# api/Dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

# create a data dir for sqlite
RUN mkdir -p /data
VOLUME /data

EXPOSE 8000
CMD ["sh", "-c", "sleep 10 && uvicorn main:app --host 0.0.0.0 --port 8000"]

