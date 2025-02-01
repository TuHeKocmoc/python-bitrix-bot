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
        resp = requests.post(url, json=data)
        resp_data = resp.json()
        task_id = resp_data['result']['task']['id']
        print("STATUS CODE:", resp.status_code)
        print("RESPONSE:", resp.text)
    except Exception as e:
        print("Bitrix error:", e)
        return None

    if checklist:
        checklist_url = f"{webhook}task.checklistitem.add.json"
        for item in checklist:
            checklist_data = {
                "TASKID": task_id,
                "FIELDS": {
                    "TITLE": item,
                    "IS_COMPLETE": "N",
                    "SORT_INDEX": 10
                }
            }
            try:
                checklist_resp = requests.post(checklist_url,
                                               json=checklist_data)
                checklist_resp_data = checklist_resp.json()
                if checklist_resp_data.get('result'):
                    print(f"Пункт чеклиста '{item}' добавлен.")
                else:
                    print(f"Ошибка при добавлении пункта чеклиста '{item}':"
                          f" {checklist_resp_data.get('error_description')}")
            except Exception as e:
                print(f"Ошибка при добавлении пункта чеклиста '{item}': {e}")
    return resp_data


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


def add_checklist_to_task(webhook, task_id, checklist):
    url = f"{webhook}tasks.task.update.json"

    checklist_data = [{"TITLE": item, "IS_COMPLETED": "N"} for item in
                      checklist]

    data = {
        "taskId": task_id,
        "fields": {
            "CHECKLIST": checklist_data
        }
    }

    try:
        resp = requests.post(url, json=data)
        resp_data = resp.json()

        print("STATUS CODE:", resp.status_code)
        print("RESPONSE:", resp.text)

        return resp_data
    except Exception as e:
        print("Bitrix error:", e)
        return None
