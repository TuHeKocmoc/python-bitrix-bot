FROM python:3.13.3-slim

WORKDIR /app

RUN apt-get update && apt-get upgrade -y && \
    apt-get install -y g++ libpq-dev gcc ffmpeg tzdata && \
    rm -rf /var/lib/apt/lists/*

ENV TZ=Europe/Moscow
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo "$TZ" > /etc/timezone
COPY requirements.txt ./
RUN pip install --no-cache-dir --use-deprecated=legacy-resolver -r requirements.txt

COPY . .

CMD ["python", "-m", "bitrix_bot"]
