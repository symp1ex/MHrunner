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
