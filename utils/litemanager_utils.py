import subprocess
import os
import logging

def launch_litemanager(lm_path, lm_id, lm_password):
    """
    Запускает LiteManager Viewer с указанным ID и паролем.
    Использует аргументы командной строки /NOIPID: и /password:.
    """
    logging.info(f"Попытка запуска LiteManager для ID: '{lm_id}'")

    if not os.path.exists(lm_path):
        logging.error(f"Ошибка: Исполняемый файл LiteManager Viewer не найден по пути: '{lm_path}'")
        raise FileNotFoundError(f"LiteManager Viewer executable not found at '{lm_path}'")

    # Формируем аргументы командной строки
    args = [
        lm_path,
        f"/NOIPID:{lm_id}",
        f"/password:{lm_password}"
    ]
    # Внимание: Логируем команду БЕЗ пароля!
    logging.debug(f"Команда LiteManager: '{args[0]}' '{args[1]}' '/password:***'")

    try:
        # Запускаем процесс LiteManager
        # Используем список аргументов, чтобы не полагаться на shell для парсинга
        # creationflags=subprocess.CREATE_NO_WINDOW скрывает консольное окно процесса
        process = subprocess.Popen(
            args,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )

        logging.info(f"LiteManager запущен для ID '{lm_id}'. PID: {process.pid}")

        # Мы не ждем завершения процесса LiteManager здесь, он запускается в фоне.
        return process.pid # Возвращаем PID запущенного процесса для информации

    except FileNotFoundError:
         # Эта ошибка уже обработана выше, но на всякий случай
         logging.error(f"Ошибка FileNotFoundError при запуске LiteManager: '{lm_path}'.")
         raise FileNotFoundError(f"LiteManager Viewer executable not found at '{lm_path}'")
    except Exception as e:
        logging.error(f"Ошибка при запуске LiteManager с ID '{lm_id}': {e}")
        raise RuntimeError(f"Failed to launch LiteManager: {e}")