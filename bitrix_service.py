import requests
from datetime import datetime
from utils import format_datetime


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


def get_overdue_tasks(webhook: str) -> list[dict]:
    now = datetime.now()
    current_time = now.strftime("%Y-%m-%dT%H:%M:%S+03:00")

    url = f"{webhook}tasks.task.list.json"
    data = {
        "filter": {
            "<DEADLINE": current_time,
            ">=REAL_STATUS": "1",
            "<=REAL_STATUS": "4"
        },
        "select": ["ID", "TITLE", "DEADLINE", "RESPONSIBLE_ID", "status",
                   "notViewed"]
    }

    try:
        resp = requests.post(url, json=data)
        resp_data = resp.json()
        print("STATUS CODE:", resp.status_code)
        print("RESPONSE:", resp.text)
        if "result" in resp_data:
            result = resp_data["result"]
            if isinstance(result, list):
                tasks = result
            elif isinstance(result, dict) and "tasks" in result:
                tasks = result["tasks"]
            else:
                tasks = []
            return tasks
        else:
            print("Ошибка получения задач:",
                  resp_data.get("error_description"))
            return []
    except Exception as e:
        print("Error fetching overdue tasks:", e)
        return []


def get_overdue_tasks_report(bitrix_url: str) -> str:
    tasks = get_overdue_tasks(bitrix_url)
    if not tasks:
        return "На данный момент нет просроченных задач."

    report_lines = []
    for task in tasks:
        title = task.get("title", "Без названия")
        deadline = task.get("deadline", "Не указан")
        responsible_info = task.get("responsible", {})
        responsible_name = responsible_info.get("name", "Не указан")

        task_text = (
            f"Задача: {title}\n"
            f"Дедлайн: {format_datetime(deadline)}\n"
            f"Ответственный: {responsible_name}\n"
            "----------------------"
        )
        report_lines.append(task_text)

    report_text = "🔥 **Просроченные задачи** 🔥\n\n" + "\n".join(report_lines)
    return report_text


def get_completed_tasks_report(webhook: str, start_date: str,
                               end_date: str) -> str:
    url = f"{webhook}tasks.task.list.json"
    data = {
        "filter": {
            "STATUS": "5",
            ">=CLOSED_DATE": start_date,
            "<=CLOSED_DATE": end_date
        },
        "select": ["ID", "TITLE", "CLOSED_DATE", "RESPONSIBLE_ID"]
    }
    try:
        resp = requests.post(url, json=data)
        resp_data = resp.json()
        if "result" in resp_data:
            result = resp_data["result"]
            if isinstance(result, dict) and "tasks" in result:
                tasks = result["tasks"]
            elif isinstance(result, list):
                tasks = result
            else:
                tasks = []
            if not tasks:
                return "За прошедшую неделю завершённых задач не найдено."

            counts = {}
            for task in tasks:
                responsible_info = task.get("responsible", {})
                responsible_name = responsible_info.get("name", "Не указан")
                if responsible_name:
                    counts[responsible_name] = (
                            counts.get(responsible_name, 0) + 1)

            if not counts:
                return "За прошедшую неделю завершённых задач не найдено."

            lines = []
            for responsible_name, cnt in counts.items():
                lines.append(
                    f"Сотрудник (Bitrix ID: {responsible_name}) "
                    f"выполнил {cnt} задач за неделю.")
            return "\n".join(lines)
        else:
            error_desc = resp_data.get("error_description",
                                       "Неизвестная ошибка")
            return f"Ошибка получения задач: {error_desc}"
    except Exception as e:
        return f"Ошибка при запросе: {e}"
