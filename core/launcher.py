import os
import time
import subprocess
import json
import requests
import logging
import shutil # Импортируем shutil для очистки папок
import traceback # Импортируем traceback для логирования ошибок перед перебрасыванием

# Импортируем нужные функции из других модулей
from core.config import get_config_value
from utils.url_utils import parse_target_string, determine_app_type, sanitize_for_path, get_appdata_path, format_version, get_expected_installer_name
from utils.file_utils import wait_for_file, edit_config_file, get_file_company_name
from utils.process_utils import stop_process_by_pid


# --- Функции для кнопки "Check" ---

def check_server_info(config, target_string, update_status_callback=None, update_progress_callback=None):
    """Выполняет проверку сервера и возвращает информацию о нем."""
    logging.info(f"Начата проверка сервера для: '{target_string}'")
    # Прогресс для проверки: 0% -> 100%
    check_progress_base = 0
    check_progress_range = 100

    try:
        # Шаг проверки: Парсинг (0-10% прогресса проверки)
        parse_progress_range = 10
        if update_status_callback: update_status_callback("Парсинг адреса для проверки...")
        # Используем parse_target_string для извлечения хоста/порта/схемы
        parsed_target = parse_target_string(target_string)
        if parsed_target is None or not parsed_target.get('UrlOrIp'):
            raise ValueError("Не удалось распарсить ввод или извлечь хост/IP.") # Выбрасываем ошибку при неудаче парсинга
        if update_progress_callback: update_progress_callback(check_progress_base + parse_progress_range)

        target_url_or_ip = parsed_target['UrlOrIp']
        target_port = parsed_target['Port']
        # ИСПРАВЛЕНО: Используем схему, определенную парсером на основе порта
        probe_scheme = parsed_target['Scheme']
        logging.debug(f"Определена схема '{probe_scheme}' для probe_url на основе порта '{target_port}'.")


        # Шаг проверки: Формирование URL и запрос (10-90% прогресса проверки)
        http_request_progress_base = check_progress_base + parse_progress_range
        http_request_progress_range = 80 # Оставляем 10% на обработку результата

        if update_status_callback: update_status_callback(f"Запрос информации о сервере: {target_url_or_ip}:{target_port}...")

        # Логика формирования probe_url: используем схему, определенную выше, и порт из парсинга.
        # Порт включается в URL только если он НЕ стандартный для этой схемы.
        standard_http_port = 80
        standard_https_port = 443
        include_port_in_probe_url = True

        if probe_scheme == "http" and target_port == standard_http_port:
             include_port_in_probe_url = False
        elif probe_scheme == "https" and target_port == standard_https_port:
             include_port_in_probe_url = False
        # Если порт указан явно, даже если он стандартный, включаем его в URL для надежности
        # (хотя requests может быть умным и без этого).
        # Эта логика осталась, но теперь она применяется к схеме, определенной портом.


        probe_url = f"{probe_scheme}://{target_url_or_ip}"
        if include_port_in_probe_url:
            probe_url += f":{target_port}"
        probe_url += "/resto/getServerMonitoringInfo.jsp"

        logging.info(f"URL для запроса информации о сервере (проверка): {probe_url}")

        http_timeout = get_config_value(config, 'Settings', 'HttpRequestTimeoutSec', default=15, type_cast=int)
        server_info = None
        try:
            if update_progress_callback: update_progress_callback(http_request_progress_base + http_request_progress_range * 0.1) # Прогресс в начале запроса

            response = requests.get(probe_url, timeout=http_timeout)
            response.raise_for_status()
            server_info = response.json()

            if update_progress_callback: update_progress_callback(http_request_progress_base + http_request_progress_range) # Прогресс после запроса

        except requests.exceptions.Timeout:
            raise ConnectionError(f"Таймаут ({http_timeout} сек) при выполнении GET-запроса к '{probe_url}'")
        except requests.exceptions.ConnectionError as e:
             raise ConnectionError(f"Ошибка подключения при выполнении GET-запроса к '{probe_url}': {e}")
        except requests.exceptions.RequestException as e:
            raise ConnectionError(f"Ошибка HTTP запроса к '{probe_url}': {e}")
        except Exception as e:
             raise ConnectionError(f"Неожиданная ошибка при запросе к '{probe_url}': {e}")

        # Шаг проверки: Обработка результата (90-100% прогресса проверки)
        process_response_progress_base = http_request_progress_base + http_request_progress_range
        process_response_progress_range = 10

        if update_status_callback: update_status_callback("Получен ответ от сервера. Обработка...")
        logging.debug(f"Получен ответ от сервера: {server_info}")

        # Проверяем наличие нужных ключей
        if None in [server_info.get("edition"), server_info.get("version"), server_info.get("serverState")]:
             logging.debug(f"Полный ответ сервера: {server_info}")
             raise ValueError("Ответ сервера не содержит ожидаемых ключей (edition, version, serverState).")

        if update_progress_callback: update_progress_callback(process_response_progress_base + process_response_progress_range) # Прогресс 100% проверки

        logging.info("Проверка сервера завершена успешно.")
        if update_status_callback: update_status_callback("Проверка завершена. Ответ сервера получен.", level="INFO")

        return server_info # Возвращаем полученную информацию

    except Exception as e:
        logging.error(f"Ошибка во время проверки сервера: {e}\n{traceback.format_exc()}")
        # В CheckWorker эта ошибка будет поймана и отправлена в GUI через сигнал error
        # GUI сам отобразит статус "Ошибка проверки" и подробности.
        # if update_status_callback: update_status_callback(f"Ошибка проверки: {e}", level="ERROR")
        if update_progress_callback: update_progress_callback(check_progress_base) # Сбрасываем прогресс при ошибке
        raise e # Перебрасываем ошибку для обработки в воркере/GUI


# --- Функции-шаги для последовательности запуска (используются LaunchWorker) ---
# Они не управляют последовательностью или прогрессом напрямую (кроме передачи колбэков)
# Они принимают config, launch_data (или его части), и колбэки для GUI/отмены.
# Они возвращают обновленные launch_data или выбрасывают исключение при ошибке.

def step_parse_input(target_string):
    """Шаг 1: Парсинг ввода."""
    logging.info(f"Шаг 1: Парсинг введенного адреса: '{target_string}'")
    parsed_target = parse_target_string(target_string)
    if parsed_target is None or not parsed_target.get('UrlOrIp'):
        # Эта ошибка будет поймана в GUI.main_window перед запуском воркера.
        # Если же мы дошли сюда (например, при возобновлении), и parsed_target почему-то None,
        # то это серьезная внутренняя ошибка.
        raise ValueError("Не удалось распарсить ввод или извлечь хост/IP.")

    # Сохраняем результат парсинга и определенную схему для конфига
    return {'parsed_target': parsed_target, 'config_protocol': parsed_target['Scheme']}

def step_http_request(config, parsed_target):
    """Шаг 2: Выполнение HTTP-запроса."""
    target_url_or_ip = parsed_target['UrlOrIp']
    target_port = parsed_target['Port']
    logging.info(f"Шаг 2: Выполнение GET-запроса к {target_url_or_ip}:{target_port}...")

    # ИСПРАВЛЕНО: Используем схему, определенную парсером на основе порта
    probe_scheme = parsed_target['Scheme']
    logging.debug(f"Определена схема '{probe_scheme}' для probe_url на основе порта '{target_port}'.")


    standard_http_port = 80
    standard_https_port = 443
    include_port_in_probe_url = True

    if probe_scheme == "http" and target_port == standard_http_port:
         include_port_in_probe_url = False
    elif probe_scheme == "https" and target_port == standard_https_port:
         include_port_in_probe_url = False
    # Если порт указан явно, даже если он стандартный, включаем его в URL для надежности
    # (хотя requests может быть умным и без этого).
    # Эта логика осталась, но теперь она применяется к схеме, определенной портом.


    probe_url = f"{probe_scheme}://{target_url_or_ip}"
    if include_port_in_probe_url:
        probe_url += f":{target_port}"
    probe_url += "/resto/getServerMonitoringInfo.jsp"

    logging.info(f"URL для запроса информации о сервере: {probe_url}")

    http_timeout = get_config_value(config, 'Settings', 'HttpRequestTimeoutSec', default=15, type_cast=int)
    server_info = None
    try:
        response = requests.get(probe_url, stream=False, timeout=http_timeout) # stream=False для этого запроса
        response.raise_for_status()
        server_info = response.json()

    except requests.exceptions.Timeout:
        raise ConnectionError(f"Таймаут ({http_timeout} сек) при выполнении GET-запроса к '{probe_url}'")
    except requests.exceptions.ConnectionError as e:
         raise ConnectionError(f"Ошибка подключения при выполнении GET-запроса к '{probe_url}': {e}")
    except requests.exceptions.RequestException as e:
        raise ConnectionError(f"Ошибка HTTP запроса к '{probe_url}': {e}")
    except Exception as e:
         raise ConnectionError(f"Неожиданная ошибка при запросе к '{probe_url}': {e}")

    logging.debug(f"Получен ответ от сервера: {server_info}")

    # Возвращаем server_info. config_protocol уже определен на шаге 1.
    return {'server_info': server_info, 'probe_url': probe_url} # Удален 'config_protocol' из возвращаемого значения, т.к. он определен на шаге 1

def step_process_response(target_string, server_info):
    """Шаг 3: Обработка ответа и определение типа приложения."""
    logging.info("Шаг 3: Обработка ответа сервера и определение типа приложения.")
    edition = server_info.get("edition")
    version_raw = server_info.get("version")
    server_state = server_info.get("serverState")

    if None in [edition, version_raw, server_state]:
         logging.debug(f"Полный ответ сервера: {server_info}")
         raise ValueError("Ответ сервера не содержит ожидаемых ключей (edition, version, serverState).")

    logging.info(f"Получены данные сервера: Edition='{edition}', Version='{version_raw}', ServerState='{server_state}'")

    app_info = determine_app_type(target_string, edition)

    if app_info is None:
         return {'edition': edition, 'version_raw': version_raw, 'server_state': server_state, 'app_info': None}
    else:
        logging.info(f"Определен тип приложения: '{app_info['AppType']}' (Производитель: '{app_info['Vendor']}')")
        return {'edition': edition, 'version_raw': version_raw, 'server_state': server_state, 'app_info': app_info}


def step_check_server_state(parsed_target, server_state):
    """Шаг 4: Проверка состояния сервера."""
    logging.info("Шаг 4: Проверка состояния сервера.")
    target_url_or_ip = parsed_target['UrlOrIp']

    if server_state != "STARTED_SUCCESSFULLY":
        logging.warning(f"Состояние сервера '{target_url_or_ip}' не 'STARTED_SUCCESSFULLY', текущее состояние: '{server_state}'.")
        return False

    logging.info("Состояние сервера OK.")
    return True


def step_format_version(version_raw):
    """Шаг 5: Форматирование версии."""
    logging.info("Шаг 5: Форматирование версии.")
    version_formatted = format_version(version_raw)
    logging.info(f"Форматированная версия: '{version_formatted}'")
    return {'version_formatted': version_formatted}


def step_get_installer_name(config, app_type, version_formatted):
    """Шаг 6: Определение ожидаемого имени каталога дистрибутива."""
    logging.info("Шаг 6: Определение имени дистрибутива.")
    expected_installer_name = get_expected_installer_name(config, app_type, version_formatted)
    if expected_installer_name is None:
        raise ValueError("Ошибка формирования имени дистрибутива.")
    logging.info(f"Ожидаемое имя каталога дистрибутива: '{expected_installer_name}'")
    return {'expected_installer_name': expected_installer_name}


# find_or_download_installer находится в core/installer.py


def step_appdata_cleanup(parsed_target, vendor, app_type, version_raw):
    """Шаг 8: Определение пути AppData и очистка."""
    logging.info("Шаг 8: Определение пути AppData и очистка.")
    sanitized_target = sanitize_for_path(parsed_target['UrlOrIp'])
    logging.info(f"Санитизированный адрес для пути AppData: '{sanitized_target}'")

    backoffice_temp_dir = get_appdata_path(vendor, app_type, sanitized_target, version_raw)
    if backoffice_temp_dir is None:
         raise EnvironmentError("Не удалось определить путь временной папки кэша.")

    logging.info(f"Ожидаемый путь временной папки кэша: '{backoffice_temp_dir}'")

    if os.path.exists(backoffice_temp_dir):
        logging.info(f"Очистка существующей временной папки кэша: '{backoffice_temp_dir}'")
        try:
            shutil.rmtree(backoffice_temp_dir, ignore_errors=True)
            logging.info("Временная папка успешно удалена.")
        except Exception as e:
            logging.error(f"Ошибка при удалении временной папки '{backoffice_temp_dir}': {e}")

    else:
        logging.info("Временная папка кэша не найдена. Удаление не требуется.")

    return {'backoffice_temp_dir': backoffice_temp_dir, 'sanitized_target': sanitized_target}


def step_first_run(installer_path, sanitized_target):
    """Шаг 9: Первый запуск BackOffice.exe."""
    logging.info("Шаг 9: Первый запуск BackOffice.exe.")
    backoffice_exe_path = os.path.join(installer_path, "BackOffice.exe")
    if not os.path.exists(backoffice_exe_path):
         raise FileNotFoundError(f"Файл BackOffice.exe не найден в каталоге дистрибутива: '{backoffice_exe_path}'.")

    backoffice_args = f"/AdditionalTmpFolder=\"{sanitized_target}\""
    logging.info(f"Первый запуск BackOffice.exe: '{backoffice_exe_path}' с аргументами: '{backoffice_args}'")

    try:
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE

        process = subprocess.Popen(
            [backoffice_exe_path, backoffice_args],
            cwd=installer_path,
            shell=True,
            startupinfo=startupinfo,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )
        logging.info(f"BackOffice.exe успешно запущен (первый раз, PID: {process.pid}).")

        return {'backoffice_process': process, 'backoffice_exe_path': backoffice_exe_path, 'backoffice_args': backoffice_args}

    except FileNotFoundError:
         raise FileNotFoundError(f"Не удалось найти исполняемый файл BackOffice.exe: '{backoffice_exe_path}'. Убедитесь в правильности пути.")
    except Exception as e:
         raise RuntimeError(f"Ошибка при первом запуске BackOffice.exe: {e}")


def step_wait_edit_config(config, launch_data, update_status_callback, update_progress_callback, progress_base, progress_range, is_canceled_callback):
    """Шаг 10: Ожидание и редактирование файла backclient.config."""
    logging.info("Шаг 10: Ожидание и редактирование файла backclient.config.")
    backoffice_temp_dir = launch_data['backoffice_temp_dir']
    target_url_or_ip = launch_data['parsed_target']['UrlOrIp']
    target_port = launch_data['parsed_target']['Port']
    config_protocol = launch_data['config_protocol']

    # Получаем логин из конфига
    target_login = get_config_value(config, 'Settings', 'DefaultLogin', default='iikoUser', type_cast=str)
    logging.info(f"Получен логин из конфига для записи: '{target_login}'")

    config_file_path = os.path.join(backoffice_temp_dir, "config", "backclient.config.xml")
    config_wait_timeout = get_config_value(config, 'Settings', 'ConfigFileWaitTimeoutSec', default=60, type_cast=int)
    config_check_interval = get_config_value(config, 'Settings', 'ConfigFileCheckIntervalMs', default=100, type_cast=int)

    # Ожидаем появления файла конфигурации
    # wait_for_file вернет False, если отмена. Выбросит TimeoutError при таймауте.
    wait_success = wait_for_file(config_file_path, config_wait_timeout, config_check_interval,
                                 update_status_callback, update_progress_callback,
                                 progress_base, progress_range,
                                 is_canceled_callback=is_canceled_callback)

    if not wait_success:
         # Если wait_for_file вернул False, это была отмена.
         logging.warning("Ожидание файла конфига отменено.")
         # Останавливаем процесс BackOffice, если он еще запущен.
         current_process = launch_data.get('backoffice_process')
         if current_process and current_process.poll() is None:
             logging.warning("Остановка процесса BackOffice после отмены ожидания конфига...")
             stop_process_by_pid(current_process.pid)
             launch_data['backoffice_process'] = None
         return False # Сигнализируем воркеру, что wait_for_file не нашел файл (из-за отмены)
    # Если wait_for_file выбросил TimeoutError, он будет пойман в воркере.

    # Файл найден. Останавливаем процесс BackOffice перед редактированием.
    current_process = launch_data.get('backoffice_process')
    if current_process and current_process.poll() is None:
        logging.info(f"Файл конфигурации найден. Остановка процесса BackOffice (PID: {current_process.pid}) для редактирования файла.")
        stop_process_by_pid(current_process.pid)
        time.sleep(1.0)
        launch_data['backoffice_process'] = None


    # Редактируем файл конфигурации
    if not edit_config_file(config_file_path, target_url_or_ip, target_port, config_protocol, target_login, update_status_callback):
         raise RuntimeError(f"Не удалось отредактировать файл конфигурации '{config_file_path}'.")

    return True # Сигнализируем об успехе


def step_restart(installer_path, backoffice_exe_path, backoffice_args):
    """Шаг 11: Перезапуск BackOffice.exe."""
    logging.info("Шаг 11: Перезапуск BackOffice.exe.")
    logging.info(f"Перезапуск BackOffice.exe: '{backoffice_exe_path}' с аргументами: '{backoffice_args}'")

    try:
         startupinfo = None
         if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE

         process = subprocess.Popen(
            [backoffice_exe_path, backoffice_args],
            cwd=installer_path,
            shell=True,
            startupinfo=startupinfo,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
         )
         logging.info(f"BackOffice.exe успешно перезапущен (PID: {process.pid}).")

         return {'backoffice_process': process}

    except FileNotFoundError:
         raise FileNotFoundError(f"Не удалось найти исполняемый файл BackOffice.exe для перезапуска: '{backoffice_exe_path}'.")
    except Exception as e:
         raise RuntimeError(f"Ошибка при перезапуске BackOffice.exe: {e}")


# Вспомогательная функция для очистки временных файлов/папок при ошибке или отмене
def _cleanup_temp_files(temp_archive_path, temp_extract_path, local_installer_path):
     """Вспомогательная функция для очистки временных файлов/папок при ошибке или отмене."""
     logging.debug("Начата очистка временных файлов/папок.")
     if os.path.exists(temp_extract_path):
          try:
              shutil.rmtree(temp_extract_path, ignore_errors=True)
              logging.debug(f"Временная папка распаковки '{temp_extract_path}' очищена.")
          except Exception as temp_e:
              logging.warning(f"Ошибка при очистке временной папки распаковки '{temp_extract_path}': {temp_e}")

     if os.path.exists(temp_archive_path):
          try:
              os.remove(temp_archive_path)
              logging.debug(f"Временный архив '{temp_archive_path}' удален.")
          except Exception as temp_e:
              logging.warning(f"Ошибка при очистке временного архива '{temp_archive_path}' после основной ошибки: {temp_e}")

     installer_root = get_config_value(None, 'Settings', 'InstallerRoot', default='D:\\Backs')
     if os.path.exists(local_installer_path) and os.path.normpath(local_installer_path) != os.path.normpath(installer_root):
          try:
              shutil.rmtree(local_installer_path, ignore_errors=True)
              logging.debug(f"Локальная папка дистрибутива '{local_installer_path}' очищена после ошибки/отмены.")
          except Exception as cleanup_e:
               logging.warning(f"Ошибка при очистке локальной папки дистрибутива '{local_installer_path}' после ошибки: {cleanup_e}")
     logging.debug("Очистка временных файлов/папок завершена.")
