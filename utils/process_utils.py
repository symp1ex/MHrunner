import subprocess
import os
import logging

def stop_process_by_pid(pid):
    """Останавливает процесс по его PID (для Windows)."""
    if pid is None:
        logging.warning("PID процесса BackOffice не известен, пропуск остановки.")
        return False # Не удалось остановить

    logging.info(f"Попытка остановить процесс BackOffice (PID: {pid})...")
    try:
        # На Windows taskkill - надежный способ принудительно завершить процесс
        # /F - принудительно
        # /T - завершить дочерние процессы (не обязательно, но безопасно)
        # creationflags=subprocess.CREATE_NO_WINDOW - предотвращает появление консольного окна taskkill
        # check=True выбросит CalledProcessError, если taskkill вернет ненулевой код
        result = subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], check=True, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
        logging.info(f"Процесс BackOffice (PID: {pid}) успешно остановлен. stdout: {result.stdout.strip()}")
        return True # Успешно остановлен
    except subprocess.CalledProcessError as e:
        # taskkill вернет ненулевой код, если процесс не найден (уже завершен) или нет прав
        logging.warning(f"Ошибка при остановке процесса BackOffice (PID: {pid}). Код выхода: {e.returncode}, stdout: {e.stdout.strip()}, stderr: {e.stderr.strip()}")
        # Если код 128, это означает "процесс не найден". Считаем это успехом (процесс не запущен)
        if e.returncode == 128:
             logging.info(f"Процесс (PID: {pid}) не найден, вероятно, уже завершен.")
             return True # Считаем, что процесс остановлен (или уже был)
        return False # Не удалось остановить по другой причине
    except FileNotFoundError:
        logging.error("Команда 'taskkill' не найдена. Убедитесь, что вы на Windows.")
        return False # Не удалось остановить
    except Exception as e:
        logging.error(f"Неизвестная ошибка при остановке процесса BackOffice (PID: {pid}): {e}")
        return False # Не удалось остановить

def is_anydesk_running():
    """Проверяет, запущен ли процесс Anydesk.exe (для Windows)."""
    if os.name != 'nt':
        logging.debug("Проверка процесса Anydesk доступна только на Windows.")
        return False # На других ОС считаем, что не запущен или неактуально

    logging.debug("Проверка запущенности процесса Anydesk.exe...")
    try:
        # Используем tasklist для поиска процесса по имени образа
        # /FI "IMAGENAME eq Anydesk.exe" - Фильтр: Имя образа равно "Anydesk.exe"
        # /NH - No Header (не выводить заголовки столбцов)
        # /FO CSV - Format Output как CSV (легче парсить, хотя нам не нужно парсить, только проверить наличие)
        # check=False, чтобы не выбрасывать исключение, если процесс не найден (tasklist вернет код 1)
        # capture_output=True, text=True - для захвата вывода
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq Anydesk.exe", "/NH", "/FO", "CSV"],
            check=False,
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW # Не показывать консольное окно tasklist
        )

        # Логируем вывод для отладки
        logging.debug(f"tasklist stdout:\n{result.stdout.strip()}")
        if result.stderr.strip():
             logging.debug(f"tasklist stderr:\n{result.stderr.strip()}")
        logging.debug(f"tasklist returncode: {result.returncode}")

        if "anydesk.exe" in result.stdout.lower():
            logging.debug("Строка 'Anydesk.exe' найдена в выводе tasklist. Процесс запущен.")
            return True
        else:
            logging.debug("Строка 'Anydesk.exe' не найдена в выводе tasklist. Процесс не запущен.")
            return False

    except FileNotFoundError:
        logging.error("Команда 'tasklist' не найдена. Убедитесь, что вы на Windows.")
        return False # Не удалось проверить
    except Exception as e:
        logging.error(f"Неизвестная ошибка при проверке процесса Anydesk: {e}")
        return False # Не удалось проверить