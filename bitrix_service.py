import logging

import requests
from datetime import datetime, date, timedelta

from telegram.helpers import escape_markdown

from utils import format_datetime


def create_task_in_bitrix(webhook, title, description=None, deadline=None,
                          responsible: int = None, checklist: list[str] = None,
                          accomplices: list[int] = None,
                          group_id: int = None):
    url = f"{webhook}tasks.task.add.json"

    fields = {"TITLE": title,
              "DEADLINE": deadline if deadline else "",
              "RESPONSIBLE_ID": responsible if responsible else 1,
              "DESCRIPTION": description if description else "",
              "ACCOMPLICES": accomplices if accomplices else [],
              "GROUP_ID": group_id if group_id else "",
              }

    data = {
        "fields": fields
    }

    try:
        resp = requests.post(url, json=data)
        logging.debug(f"Bitrix create task raw response: {resp.text}")
        resp.raise_for_status()
        if resp.status_code != 200:
            logging.error(
                f"Bitrix responded with {resp.status_code}: {resp.text}")
            return None
        resp_data = resp.json()
        task_id = resp_data['result']['task']['id']
        logging.debug("STATUS CODE:", resp.status_code)
        logging.debug("RESPONSE:", resp.text)
    except Exception as e:
        logging.error("Bitrix error:", e)
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
                    logging.debug(f"Пункт чеклиста '{item}' добавлен.")
                else:
                    e = checklist_resp_data.get('error_description')
                    logging.error(f"Ошибка при добавлении пункта "
                                  f"чеклиста '{item}': "
                                  f"{e}")
            except Exception as e:
                logging.error(f"Ошибка при добавлении "
                              f"пункта чеклиста '{item}': {e}")
    return resp_data


def update_task_in_bitrix(webhook,
                          task_id: int,
                          title: str = None,
                          description: str = None,
                          deadline: str = None,
                          responsible: int = None,
                          accomplices: list[int] = None,
                          group_id: int = None,
                          checklist: list[str] = None):
    update_url = f"{webhook}tasks.task.update.json"

    fields = {}
    if title is not None:
        fields["TITLE"] = title
    if description is not None:
        fields["DESCRIPTION"] = description
    if deadline is not None:
        fields["DEADLINE"] = deadline
    if responsible is not None:
        fields["RESPONSIBLE_ID"] = responsible
    if accomplices is not None:
        fields["ACCOMPLICES"] = accomplices
    if group_id is not None:
        fields["GROUP_ID"] = group_id

    if not fields and not checklist:
        logging.debug("Нечего обновлять: поля и чеклист пусты.")
        return None

    data = {
        "taskId": task_id,
        "fields": fields
    }

    try:
        resp = requests.post(update_url, json=data)
        resp_data = resp.json()
        logging.debug("STATUS CODE: %s", resp.status_code)
        logging.debug("RESPONSE: %s", resp.text)
        if not resp_data.get("result"):
            logging.error(f"Ошибка при обновлении задачи {task_id}: "
                          f"{resp_data.get('error_description')}")
            return None
    except Exception as e:
        logging.error("Bitrix update error: %s", e)
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
                    logging.debug(f"Пункт чеклиста '{item}' добавлен.")
                else:
                    logging.error(
                        f"Ошибка при добавлении пункта чеклиста '{item}': "
                        f"{checklist_resp_data.get('error_description')}")
            except Exception as e:
                logging.error(
                    f"Ошибка при добавлении пункта чеклиста '{item}': {e}")

    return resp_data


def get_user_id_from_webhook(webhook: str):
    url = f"{webhook}user.current.json"

    try:
        resp = requests.post(url)
        resp.raise_for_status()
        data = resp.json()
        # {
        #   "result": {
        #       "ID": "123",
        #       "NAME": "...",
        #       ...
        #   },
        #   "time": {...}
        # }
        if "result" in data and isinstance(data["result"], dict):
            user_info = data["result"]
            bitrix_id_str = user_info.get("ID")
            if bitrix_id_str:
                return int(bitrix_id_str)
        logging.error("Bitrix error:", data.get("error"),
                      data.get("error_description"))
        return None

    except Exception as e:
        logging.error("Bitrix error:", e)
        return None


def get_user_name_from_bitrix(webhook: str, user_id: int):
    url = f"{webhook}user.get.json"

    # Запросим пользователя по ID (через фильтр)
    payload = {
        "filter": {
            "ID": user_id
        }
    }

    try:
        resp = requests.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        # {
        #   "result": [
        #     {
        #       "ID": "123",
        #       "NAME": "Иван",
        #       "LAST_NAME": "Иванов",
        #       "SECOND_NAME": "",
        #       ...
        #     }
        #   ]
        # }
        if "result" in data and isinstance(data["result"], list):
            users_list = data["result"]
            if len(users_list) > 0:
                user_info = users_list[0]
                first_name = user_info.get("NAME", "")
                last_name = user_info.get("LAST_NAME", "")
                full_name = f"{first_name} {last_name}".strip()
                return full_name or None

        logging.error("Bitrix error:", data.get("error"),
                      data.get("error_description"))
        return None

    except Exception as e:
        logging.error("Bitrix error:", e)
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

        logging.debug("STATUS CODE:", resp.status_code)
        logging.debug("RESPONSE:", resp.text)

        return resp_data
    except Exception as e:
        logging.debug("Bitrix error:", e)
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
        logging.debug("STATUS CODE:", resp.status_code)
        logging.debug("RESPONSE:", resp.text)
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
            logging.error("Ошибка получения задач:",
                          resp_data.get("error_description"))
            return []
    except Exception as e:
        logging.error("Error fetching overdue tasks:", e)
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
                    f"Сотрудник ({responsible_name}) "
                    f"выполнил {cnt} задач за неделю.")
            return "\n".join(lines)
        else:
            error_desc = resp_data.get("error_description",
                                       "Неизвестная ошибка")
            return f"Ошибка получения задач: {error_desc}"
    except Exception as e:
        return f"Ошибка при запросе: {e}"


def get_my_projects(webhook: str) -> list[dict]:
    url = f"{webhook}sonet_group.get.json"

    data = {}

    try:
        resp = requests.post(url, json=data)
        resp_data = resp.json()
        if "result" in resp_data:
            return resp_data["result"]
        else:
            logging.error("Ошибка получения проектов:",
                          resp_data.get("error_description"))
            return []
    except Exception as e:
        logging.error("Ошибка при запросе проектов:", e)
        return []


def get_project_name_by_id(webhook: str, project_id: int) -> str:
    url = f"{webhook}sonet_group.get.json"

    payload = {
        "FILTER": {
            "ID": project_id
        }
    }

    try:
        resp = requests.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()

        if "result" in data and isinstance(data["result"], list):
            groups_list = data["result"]
            if len(groups_list) > 0:
                group_info = groups_list[0]
                project_title = group_info.get("TITLE")
                if project_title:
                    return project_title
                project_name = group_info.get("NAME")
                if project_name:
                    return project_name

        return '-1'

    except Exception as e:
        logging.error(
            f"Bitrix error while searching project name by ID {project_id}: "
            f"{e}"
        )
        return '-1'


def get_user_id_by_name(webhook: str, user_name: str) -> int:
    url = f"{webhook}user.get.json"

    parts = user_name.strip().split()

    filters_list = [{"NAME": user_name}, {"LAST_NAME": user_name}]

    if len(parts) == 2:
        first_part, second_part = parts[0], parts[1]
        filters_list.append({"NAME": user_name})
        filters_list.append({"LAST_NAME": user_name})

        filters_list.append({
            "NAME": first_part,
            "LAST_NAME": second_part
        })

        filters_list.append({
            "NAME": second_part,
            "LAST_NAME": first_part
        })

    filter_data = {
        "LOGIC": "OR",
        "FILTERS": filters_list
    }

    payload = {
        "filter": filter_data
    }

    try:
        resp = requests.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        logging.debug(f"RAW DATA: {data}")
        if "result" in data and isinstance(data["result"], list):
            users_list = data["result"]
            for user_info in users_list:
                user_id_str = user_info.get("ID")
                if user_id_str is not None:
                    logging.debug("User ID:", user_id_str)
                    return int(user_id_str)

        logging.error(f"Bitrix error while "
                      f"searching user by name '{user_name}'")
        return -1

    except Exception as e:
        logging.error(f"Bitrix error "
                      f"while searching user by name '{user_name}':", e)
        return -1


def get_project_id_by_name(webhook: str, project_name: str) -> int:
    url = f"{webhook}sonet_group.get.json"

    payload = {
        "FILTER": {
            "LOGIC": "OR",
            "TITLE": project_name,
            "NAME": project_name
        }
    }

    try:
        resp = requests.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()

        if "result" in data and isinstance(data["result"], list):
            groups_list = data["result"]
            for group_info in groups_list:
                group_id_str = group_info.get("ID")
                if group_id_str is not None:
                    return int(group_id_str)

        return -1

    except Exception as e:
        logging.error(f"Bitrix error while "
                      f"searching project by name '{project_name}':", e)
        return -1


def get_tasks_filtered(webhook: str, query=None) -> list[dict]:
    today = date.today()
    weekday = today.weekday()
    monday = today - timedelta(days=weekday)
    start_of_week = datetime(monday.year, monday.month, monday.day, 0, 0, 0)
    start_of_week_str = start_of_week.strftime("%Y-%m-%dT%H:%M:%S+03:00")

    user_id = None
    group_id = None

    if query is not None:
        if isinstance(query, int):
            user_id = query
        elif isinstance(query, str):
            found_user_id = get_user_id_by_name(webhook, query)
            if found_user_id != -1:
                user_id = found_user_id
            else:
                found_group_id = get_project_id_by_name(webhook, query)
                if found_group_id != -1:
                    group_id = found_group_id
                else:
                    logging.error(
                        f"Не удалось интерпретировать "
                        f"'{query}' как имя пользователя или проекта.")
                    return []

    not_completed = {"<REAL_STATUS": 5}
    completed_this_week = {
        ">=REAL_STATUS": "1",
        "<=REAL_STATUS": "4",
        ">=CLOSED_DATE": start_of_week_str
    }

    if user_id:
        not_completed["RESPONSIBLE_ID"] = user_id
        completed_this_week["RESPONSIBLE_ID"] = str(user_id)
    if group_id:
        not_completed["GROUP_ID"] = group_id
        completed_this_week["GROUP_ID"] = str(group_id)

    filter_data = {
        "LOGIC": "OR",
        "FILTERS": [
            not_completed,
            completed_this_week
        ]
    }

    request_data = {
        "filter": filter_data,
        "select": [
            "ID", "TITLE", "DEADLINE", "RESPONSIBLE_ID", "REAL_STATUS",
            "CLOSED_DATE", "GROUP_ID"
        ]
    }

    url = f"{webhook}tasks.task.list.json"
    try:
        resp = requests.post(url, json=request_data)
        resp_data = resp.json()
        logging.debug("STATUS CODE:", resp.status_code)
        logging.debug("RESPONSE:", resp.text)

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
            logging.error("Ошибка получения задач:",
                          resp_data.get("error_description"))
            return []
    except Exception as e:
        logging.error("Error fetching tasks:", e)
        return []


def get_tasks_filtered_report(bitrix_url: str, query=None) -> str:
    tasks = get_tasks_filtered(bitrix_url, query)
    if not tasks:
        return escape_markdown("Задач по заданному фильтру нет.", version=2)

    if query is None:
        header = "Задачи (не завершённые или завершённые на этой неделе)"
    else:
        header = f"Задачи по запросу: {query}"

    header_escaped = escape_markdown(header, version=2)

    report_lines = []
    for task in tasks:
        task_id = task.get("id") or task.get("ID")
        title = task.get("title") or task.get("TITLE") or "Без названия"
        real_status = task.get("realStatus") or task.get("REAL_STATUS")
        deadline = task.get("deadline") or task.get("DEADLINE")
        closed_date = task.get("closedDate") or task.get("CLOSED_DATE")
        responsible_id = task.get("responsibleId") or task.get(
            "RESPONSIBLE_ID")
        group_id = task.get("groupId") or task.get("GROUP_ID")

        task_id_esc = escape_markdown(str(task_id),
                                      version=2) if task_id else "—"
        title_esc = escape_markdown(title, version=2)
        real_status_esc = escape_markdown(str(real_status),
                                          version=2) if real_status else "—"
        deadline_str = format_datetime(deadline) if deadline else "—"
        deadline_esc = escape_markdown(deadline_str, version=2)
        closed_date_str = format_datetime(closed_date) if closed_date else "—"
        closed_date_esc = escape_markdown(closed_date_str, version=2)

        responsible_name = get_user_name_from_bitrix(bitrix_url,
                                                     responsible_id)
        if responsible_name:
            responsible_name_esc = escape_markdown(str(responsible_name),
                                                   version=2)
        else:
            responsible_name_esc = "-"

        group_id_esc = escape_markdown(
            get_project_name_by_id(bitrix_url, group_id),
            version=2) if group_id else "—"

        separator = escape_markdown("----------------------", version=2)
        task_text = (
            f"ID: {task_id_esc}\n"
            f"Задача: {title_esc}\n"
            f"Статус: {real_status_esc}\n"
            f"Дедлайн: {deadline_esc}\n"
            f"Дата закрытия: {closed_date_esc}\n"
            f"Ответственный: {responsible_name_esc}\n"
            f"Проект: {group_id_esc}\n"
            f"{separator}"
        )
        report_lines.append(task_text)

    report_text = f"*{header_escaped}*\n\n" + "\n".join(report_lines)
    return report_text


def get_task_fields_from_bitrix(webhook, task_id: int) -> dict:
    """
    Получает данные о задаче (task_id) из Bitrix по-указанному webhook
    и возвращает структуру полей задачи (словарь).
    """
    url = f"{webhook}tasks.task.get.json"
    payload = {
        "taskId": task_id,
        "select": [
            "ID",
            "TITLE",
            "DESCRIPTION",
            "DEADLINE",
            "RESPONSIBLE_ID",
            "ACCOMPLICES",
            "GROUP_ID",
            "SE_CHECKLIST"
        ],
        "params": {
            "ENTITY_SELECT": ["CHECK_LIST_ITEMS"]
        }
    }

    try:
        resp = requests.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        if "result" in data and isinstance(data["result"], dict):
            task_data = data["result"].get("task", {})
            check_list_raw = task_data.get("SE_CHECKLIST", [])
            task_data["checkList"] = check_list_raw
            return task_data
        else:
            logging.error("Bitrix error (get_task_fields_from_bitrix): "
                          f"{data.get('error_description')}")
            return {}
    except Exception as e:
        logging.error(f"Ошибка при запросе задачи {task_id} в Bitrix: {e}")
        return {}


def add_checklist_item(webhook: str, task_id: int, title: str) -> bool:
    """
    Добавляет новый пункт чек-листа к задаче (task_id) через Bitrix API.
    Возвращает True при успехе, иначе False.
    """
    url = f"{webhook}task.checklistitem.add.json"
    data = {
        "TASKID": task_id,
        "FIELDS": {
            "TITLE": title,
            "IS_COMPLETE": "N",
            "SORT_INDEX": 10
        }
    }

    try:
        resp = requests.post(url, json=data)
        resp.raise_for_status()
        resp_data = resp.json()
        if "result" in resp_data and resp_data["result"]:
            logging.debug(f"Пункт чеклиста '{title}' добавлен к задаче "
                          f"{task_id}.")
            return True
        else:
            logging.error(f"Ошибка при добавлении пункта чеклиста: "
                          f"{resp_data}")
            return False

    except Exception as e:
        logging.error(f"Bitrix add_checklist_item error: {e}")
        return False


def delete_checklist_item(webhook: str, task_id: int, item_id: str) -> bool:
    """
    Удаляет пункт чек-листа с ID (item_id) у задачи (task_id) через Bitrix API.
    Возвращает True при успехе, иначе False.
    """
    url = f"{webhook}task.checklistitem.delete.json"
    data = {
        "TASKID": task_id,
        "ITEMID": item_id
    }

    try:
        resp = requests.post(url, json=data)
        resp.raise_for_status()
        resp_data = resp.json()
        if "result" in resp_data and resp_data["result"] is True:
            logging.debug(f"Пункт чеклиста {item_id} удалён из задачи "
                          f"{task_id}.")
            return True
        else:
            logging.error(f"Ошибка при удалении пункта чеклиста: {resp_data}")
            return False

    except Exception as e:
        logging.error(f"Bitrix delete_checklist_item error: {e}")
        return False
