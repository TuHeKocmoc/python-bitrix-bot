FROM python:3.14.0b1-slim

WORKDIR /app

#RUN apt-get update && apt-get install -y libpq-dev gcc && rm -rf /var/lib/apt/lists/*
RUN apt-get update && apt-get install -y g++
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "-m", "bitrix_bot"]
