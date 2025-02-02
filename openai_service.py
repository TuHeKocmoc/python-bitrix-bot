from openai import OpenAI
import json
from config import OPENAI_API_KEY
from datetime import datetime

client = OpenAI(api_key=OPENAI_API_KEY)


def parse_message_with_openai(message_text: str):
    """
    {
      "is_task": true,
      "title": "...",
      "deadline": "2025-02-01 13:00:00"
    }
    """
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d %H:%M:%S")
    prompt = f"""
    Сегодняшняя дата/время: {today_str}.
    Если в сообщении есть упоминания дат (например, 
    "завтра 13:00", "в понедельник в 10", "через 2 дня"), 
    постарайся вычислить точный datetime, основываясь на сегодняшней дате.
    Ниже приведён текст от пользователя:
    \"\"\"{message_text}\"\"\"
    
    1) Определи, является ли это постановкой задачи (is_task: true/false).
    2) Если это задача, выдели:
       - title (супер краткое название/описание)
       - description (полное описание задачи, если оно есть)
       - deadline (если указан) в формате YYYY-MM-DD HH:MM:SS 
       (24-часовой формат).
       - checklist (если присутствует) — список элементов чеклиста 
       (каждый пункт — строка).
    
    Ответ верни строго в формате JSON, без добавления пояснений.
    Не используй тройные бэктики, markdown или дополнительный текст.
    
    Пример верного ответа:
    {{ 
        "is_task": true, 
        "title": "…", 
        "description": "…", 
        "deadline": "2025-02-01 13:00:00",
        "checklist": ["Пункт 1", "Пункт 2"]
    }}
    """

    try:
        response = client.chat.completions.create(model="o1-preview",
                                                  messages=[
                                                      {"role": "user",
                                                       "content": prompt}
                                                  ])

        content = response.choices[0].message.content
        print("RAW CONTENT:", repr(content))
        data = json.loads(content)
        return data
    except Exception as e:
        print("OpenAI error:", e)
        return {"is_task": False}
