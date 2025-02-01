import requests


def create_task_in_bitrix(webhook, title, description=None, deadline=None,
                          responsible: int = None, checklist: list[str] = None,
                          accomplices: list[int] = None):
    url = f"{webhook}tasks.task.add.json"

    fields = {"TITLE": title,
              "DEADLINE": deadline if deadline else "",
              "RESPONSIBLE_ID": responsible if responsible else 1,
              "DESCRIPTION": description if description else "",
              "ACCOMPLICES": accomplices if accomplices else [],
              }


    data = {
        "fields": fields
    }

    try:
        resp = requests.post(url, json={"fields": fields})
        resp_data = resp.json()

        if resp.status_code == 200 and 'result' in resp_data:
            task_id = resp_data['result']
            print(f"Задача создана, ID: {task_id}")

            if checklist:
                for item in checklist:
                    add_checklist_item(webhook, task_id, item)

            return resp_data
        else:
            print("Ошибка при создании задачи:", resp_data)
            return None
    except Exception as e:
        print("Bitrix error:", e)
        return None


def add_checklist_item(webhook, task_id, checklist_item):
    url = f"{webhook}tasks.checklistitem.add.json"

    data = {
        "task_id": task_id,
        "fields": {
            "TITLE": checklist_item,
            "IS_COMPLETE": "N"  # Задаём чеклист как не завершённый
        }
    }

    try:
        resp = requests.post(url, json=data)
        resp_data = resp.json()

        if resp.status_code == 200:
            print(
                f"Чеклист элемент '{checklist_item}' "
                f"добавлен к задаче {task_id}")
        else:
            print("Ошибка при добавлении чеклист элемента:", resp_data)
    except Exception as e:
        print("Bitrix error:", e)


def get_user_id_from_webhook(webhook: str):
    url = f"{webhook}user.current.json"

    try:
        resp = requests.post(url)
        resp.raise_for_status()
        data = resp.json()
        # Обычно data выглядит так:
        # {
        #   "result": {
        #       "ID": "123",
        #       "NAME": "...",
        #       ...
        #   },
        #   "time": {...}
        # }
        if "result" in data and isinstance(data["result"], dict):
            # Берём поле "ID"
            user_info = data["result"]
            bitrix_id_str = user_info.get("ID")
            if bitrix_id_str:
                return int(bitrix_id_str)
        # Иначе
        print("Bitrix error:", data.get("error"),
              data.get("error_description"))
        return None

    except Exception as e:
        print("Bitrix error:", e)
        return None
