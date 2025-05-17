FROM python:3.14.0b1-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir --no-deps -r requirements.txt

COPY . .

CMD ["python", "-m", "bitrix_bot"]
