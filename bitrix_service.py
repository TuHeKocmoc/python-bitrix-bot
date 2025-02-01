import requests


def create_task_in_bitrix(webhook, title, deadline=None,
                          responsible: int = None,
                          accomplices: list[int] = None):
    url = f"{webhook}tasks.task.add.json"

    fields = {"TITLE": title,
              "DEADLINE": deadline if deadline else "",
              "RESPONSIBLE_ID": responsible if responsible else 1}

    if accomplices:
        fields["ACCOMPLICES"] = accomplices

    data = {
        "fields": fields
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
