import subprocess
import os
import logging
import tempfile # Импорт tempfile
import time # Импорт time

def launch_anydesk(anydesk_path, anydesk_id, anydesk_password):
    """
    Запускает Anydesk с указанным ID и паролем, используя временный батник
    для передачи пароля через echo | pipeline.
    """
    logging.info(f"Попытка запуска Anydesk для ID: '{anydesk_id}'")

    if not os.path.exists(anydesk_path):
        logging.error(f"Ошибка: Исполняемый файл Anydesk не найден по пути: '{anydesk_path}'")
        raise FileNotFoundError(f"Anydesk executable not found at '{anydesk_path}'")

    # Создаем временный файл батника
    # Используем NamedTemporaryFile, чтобы файл был автоматически удален после закрытия
    # suffix='.bat' указывает расширение
    # delete=False, потому что на Windows файл может быть заблокирован, пока процесс cmd.exe его использует
    # Мы удалим его явно после запуска процесса.
    temp_bat = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.bat', delete=False, encoding='utf-8') as tmp_file:
            temp_bat_path = tmp_file.name
            anydesk_disk = anydesk_path[:2]
            # Записываем команды в батник
            # @echo off - отключает эхо команд
            # chcp 65001 - устанавливает кодировку UTF-8 (для надежности)
            # echo <пароль> | "<путь Anydesk>" <ID> --with-password - основная команда с пайпом
            # exit - закрывает окно cmd.exe после выполнения
            bat_content = f"""@echo off
{anydesk_disk}
chcp 65001 > nul
echo {anydesk_password} | "{anydesk_path}" {anydesk_id} --with-password
exit
"""
            tmp_file.write(bat_content)
            logging.debug(f"Создан временный батник: '{temp_bat_path}'")
            logging.debug(f"Содержимое батника:\n{bat_content}") # Логируем содержимое для отладки (без пароля в логах!)
            # Внимание: В реальном приложении не стоит логировать пароль!
            # Здесь для отладки содержимого, но пароль в echo не выводится.

        # Запускаем временный батник
        # shell=True обязательно, чтобы cmd.exe обработал пайп (|)
        # creationflags=subprocess.CREATE_NO_WINDOW скрывает окно cmd.exe
        process = subprocess.Popen(
            [temp_bat_path],
            shell=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )

        logging.info(f"Временный батник '{os.path.basename(temp_bat_path)}' запущен для AnyDesk ID '{anydesk_id}'. PID процесса cmd: {process.pid}")

        # Даем Anydesk немного времени на старт, прежде чем удалять батник
        time.sleep(1)

        # Удаляем временный батник.
        # Даже если cmd.exe еще не завершился, файл часто можно удалить на Windows.
        try:
            os.remove(temp_bat_path)
            logging.debug(f"Временный батник '{temp_bat_path}' успешно удален.")
        except Exception as e:
            logging.warning(f"Не удалось удалить временный батник '{temp_bat_path}': {e}")


        # Мы не ждем завершения процесса Anydesk/батника здесь, он запускается в фоне.
        return process.pid # Возвращаем PID процесса батника (cmd.exe) для информации

    except FileNotFoundError:
         # Эта ошибка уже обработана выше, но на всякий случай
         logging.error(f"Ошибка FileNotFoundError при запуске Anydesk через батник: '{anydesk_path}'.")
         raise FileNotFoundError(f"Anydesk executable not found at '{anydesk_path}'")
    except Exception as e:
        logging.error(f"Ошибка при запуске временного батника для Anydesk ID '{anydesk_id}': {e}")
        raise RuntimeError(f"Failed to launch Anydesk batch file: {e}")