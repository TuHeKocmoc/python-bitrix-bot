import logging

from openai import OpenAI
from openai.types.chat import ChatCompletionUserMessageParam
import json
from ..config import OPENAI_API_KEY
from datetime import datetime

client = OpenAI(api_key=OPENAI_API_KEY)


def parse_message_with_openai(message_text: str,
                              available_projects: list[str] = None):
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

    Доступные проекты: {available_projects}

    Выдели следующие поля:
       - title: супер краткое название или описание задачи;
       - description: полное описание задачи, если оно присутствует;
       - deadline: если указан, вычисленный дедлайн в формате 
       YYYY-MM-DD HH:MM:SS (24-часовой формат);
       - checklist: если присутствует, список элементов чеклиста 
       (каждый пункт — строка);
       - project: выбери проект для задачи согласно следующим правилам:
             a) Если в тексте присутствует слово, которое точно совпадает с
              названием одного из доступных проектов, выбери этот проект.
             b) Если доступен только один проект, выбери его.
             c) Если в тексте нет упоминания проекта и имеется 
             проект "по-умолчанию", выбери его.
             d) Если в тексте нет упоминания проекта и проекта "по-умолчанию" 
             нет, оставь поле project пустым.

    Ответ верни строго в формате JSON, без добавления пояснений.
    Не используй тройные бэктики, markdown или дополнительный текст.

    Пример верного ответа:
    {{
        "title": "Название задачи", 
        "description": "Полное описание задачи", 
        "deadline": "2025-02-01 13:00:00",
        "checklist": ["Пункт 1", "Пункт 2"],
        "project": "Название выбранного проекта"
    }}
    """

    try:
        response = client.chat.completions.create(
            model="o3-mini",
            messages=[
                ChatCompletionUserMessageParam(
                    role="user",
                    content=prompt
                )
            ]
        )

        content = response.choices[0].message.content
        logging.debug("RAW CONTENT:", repr(content))
        data = json.loads(content)
        return data
    except Exception as e:
        logging.error("OpenAI error:", e)
        return {"is_task": False}
