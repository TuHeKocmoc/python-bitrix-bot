FROM python:3.14.0b1-slim

WORKDIR /app

# libpq-dev gcc && rm -rf /var/lib/apt/lists/*
RUN apt-get update && apt-get upgrade -y && apt-get install -y g++
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "-m", "bitrix_bot"]
