# utils/file_utils.py - Обновленный

import ctypes
import ctypes.wintypes
import os
import time
import xml.etree.ElementTree as ET
import logging

from utils.exceptions import AbortOperation


def get_file_company_name(filepath):
    """Получает CompanyName из свойств файла через WinAPI (только для Windows)."""
    if os.name != 'nt':
        logging.debug(f"get_file_company_name через WinAPI доступна только на Windows. Текущая ОС: {os.name}")
        return None

    logging.debug(f"Попытка чтения CompanyName из файла через WinAPI: '{filepath}'")

    if not os.path.isfile(filepath):
        logging.error(f"Ошибка: Файл не найден для чтения метаданных: '{filepath}'")
        return None

    try:
        size = ctypes.windll.version.GetFileVersionInfoSizeW(filepath, None)
        if size == 0:
            logging.debug(f"Информация о версии отсутствует в файле '{filepath}'.")
            return None

        res = ctypes.create_string_buffer(size)
        if ctypes.windll.version.GetFileVersionInfoW(filepath, 0, size, res) == 0:
             last_error = ctypes.GetLastError()
             logging.error(f"Ошибка WinAPI GetFileVersionInfoW для файла '{filepath}': Код ошибки {last_error}")
             return None

        lplpBuffer = ctypes.c_void_p()
        puLen = ctypes.wintypes.UINT()
        if ctypes.windll.version.VerQueryValueW(res, r'\\VarFileInfo\\Translation', ctypes.byref(lplpBuffer), ctypes.byref(puLen)) == 0:
             last_error = ctypes.GetLastError()
             logging.debug(f"Ошибка WinAPI VerQueryValueW (Translation) для файла '{filepath}': Код ошибки {last_error}")
             logging.debug("Не удалось получить список переводов. Попытка использовать стандартный перевод 040904b0.")
             lang_codepage = '040904b0'
        else:
             translation = ctypes.cast(lplpBuffer, ctypes.POINTER(ctypes.c_ushort * 2)).contents
             lang_codepage = f'{translation[0]:04x}{translation[1]:04x}'
             logging.debug(f"Найден перевод: {lang_codepage}")

        sub_block = f'\\StringFileInfo\\{lang_codepage}\\CompanyName'

        lplpBuffer = ctypes.c_wchar_p()
        puLen = ctypes.wintypes.UINT()
        if ctypes.windll.version.VerQueryValueW(res, sub_block, ctypes.byref(lplpBuffer), ctypes.byref(puLen)) == 0:
             last_error = ctypes.GetLastError()
             logging.debug(f"Ошибка WinAPI VerQueryValueW (CompanyName) для файла '{filepath}': Код ошибки {last_error}")
             logging.warning(f"CompanyName не найдено в метаданных файла '{filepath}' (или ошибка чтения).")
             return None

        company_name = lplpBuffer.value
        logging.debug(f"Извлечено CompanyName: '{company_name}'")
        return company_name.strip() if company_name else None

    except Exception as e:
        logging.error(f"Ошибка при извлечении CompanyName через WinAPI для файла '{filepath}': {e}")
        return None


# Добавляем is_canceled_callback в параметры
def wait_for_file(filepath, timeout_sec, check_interval_ms, update_status_callback=None, update_progress_callback=None, progress_base=0.0, progress_range=1.0, is_canceled_callback=None):
    """
    Ожидает появления файла с таймаутом и обновлением прогресса.
    update_status_callback(message) - callback для обновления статуса.
    update_progress_callback(progress_factor) - callback для обновления прогресса (0.0 до 1.0 для этого шага).
    progress_base, progress_range - определяют диапазон общего прогресса для этого шага.
    is_canceled_callback() - callback, возвращающий True, если операция отменена.
    """
    logging.info(f"Ожидание появления файла: '{filepath}'")
    if update_status_callback:
        update_status_callback(f"Ожидание файла: '{os.path.basename(filepath)}'...")
    if is_canceled_callback and is_canceled_callback(): return False # Проверка отмены

    max_attempts = int(timeout_sec * 1000 / check_interval_ms)
    file_found = False

    # Прогресс для этого этапа (внутри wait_for_file): 0% -> 50% на ожидание файла
    step_progress_base_internal = 0.0
    step_progress_range_internal = 0.5

    for attempt in range(max_attempts):
        if is_canceled_callback and is_canceled_callback():
             logging.warning("Ожидание файла отменено.")
             if update_status_callback: update_status_callback("Ожидание файла отменено.")
             return False # Сигнал отмены

        if os.path.exists(filepath):
            file_found = True
            logging.info("Файл найден!")
            if update_status_callback:
                update_status_callback("Файл конфигурации найден.")
            if update_progress_callback:
                 # Обновляем прогресс до конца первой части ожидания
                 update_progress_callback(progress_base + (step_progress_base_internal + step_progress_range_internal) * progress_range)
            break
        time.sleep(check_interval_ms / 1000)
        if update_progress_callback and max_attempts > 0:
            progress_in_step_internal = step_progress_base_internal + (attempt + 1) / max_attempts * step_progress_range_internal
            update_progress_callback(progress_base + progress_in_step_internal * progress_range)


    if not file_found:
        logging.error(f"Таймаут ожидания файла конфигурации '{filepath}' ({timeout_sec} сек).")
        if update_status_callback:
            update_status_callback("Таймаут ожидания файла.", level="ERROR")
        # НЕ возвращаем False, а выбрасываем исключение, т.к. это не отмена, а таймаут
        raise TimeoutError(f"Таймаут ожидания файла конфигурации '{filepath}'.")


    # Ожидание содержимого файла (не пустой/не заблокирован)
    logging.info(f"Ожидание содержимого в файле: '{filepath}'")
    if update_status_callback:
        update_status_callback("Ожидание содержимого файла...")
    if is_canceled_callback and is_canceled_callback(): return False # Проверка отмены

    content_wait_timeout_sec = 10 # Таймаут ожидания содержимого
    content_check_interval_ms = 50
    max_content_attempts = int(content_wait_timeout_sec * 1000 / content_check_interval_ms)
    content_found = False

    # Прогресс для этого этапа (внутри wait_for_file): 50% -> 100% на ожидание содержимого
    step_progress_base_content_internal = 0.5
    step_progress_range_content_internal = 0.5

    for attempt in range(max_content_attempts):
        if is_canceled_callback and is_canceled_callback():
             logging.warning("Ожидание содержимого файла отменено.")
             if update_status_callback: update_status_callback("Ожидание содержимого файла отменено.")
             return False # Сигнал отмены

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content_preview = f.read(100)
                if content_preview and '<' in content_preview:
                    content_found = True
                    logging.info("Содержимое файла обнаружено.")
                    if update_status_callback:
                        update_status_callback("Содержимое файла обнаружено.")
                    if update_progress_callback:
                        # Обновляем прогресс до конца второй части ожидания
                        update_progress_callback(progress_base + (step_progress_base_internal + step_progress_range_content_internal) * progress_range)
                    break
        except Exception as e:
            logging.debug(f"Ошибка при чтении превью файла '{filepath}': {e}")

        time.sleep(content_check_interval_ms / 1000)
        if update_progress_callback and max_content_attempts > 0:
            progress_in_step_content_internal = step_progress_base_content_internal + (attempt + 1) / max_content_attempts * step_progress_range_content_internal
            update_progress_callback(progress_base + progress_in_step_content_internal * progress_range)


    if not content_found:
        logging.error(f"Таймаут ожидания содержимого в файле конфигурации '{filepath}' ({content_wait_timeout_sec} сек). Файл пуст или некорректен?")
        if update_status_callback:
            update_status_callback("Таймаут ожидания содержимого файла.", level="ERROR")
        # НЕ возвращаем False, а выбрасываем исключение
        raise TimeoutError(f"Таймаут ожидания содержимого в файле конфигурации '{filepath}'.")


    return True


def edit_config_file(filepath, target_url_or_ip, target_port, config_protocol, target_login, update_status_callback=None):
    """Редактирует файл backclient.config.xml."""
    logging.info(f"Редактирование файла конфигурации: '{filepath}'")
    if update_status_callback:
        update_status_callback("Редактирование файла конфигурации...")

    try:
        time.sleep(0.5) # Даем немного времени после остановки процесса

        tree = ET.parse(filepath)
        root = tree.getroot()

        servers_list_node = root.find('.//ServersList')
        login_node = root.find('.//Login')

        if servers_list_node is not None:
            logging.debug("Узел ServersList найден.")

            server_addr_node = servers_list_node.find('ServerAddr')
            if server_addr_node is not None:
                server_addr_node.text = target_url_or_ip
                logging.info(f"  Обновлен ServerAddr на '{target_url_or_ip}'")
            else:
                logging.warning("  Узел ServerAddr не найден под ServersList. Не удалось обновить.")

            protocol_node = servers_list_node.find('Protocol')
            if protocol_node is not None:
                protocol_node.text = config_protocol
                logging.info(f"  Обновлен Protocol на '{config_protocol}'")
            else:
                logging.warning("  Узел Protocol не найден под ServersList. Не удалось обновить.")

            port_node = servers_list_node.find('Port')
            if port_node is not None:
                port_node.text = str(target_port)
                logging.info(f"  Обновлен Port на '{target_port}'")
            else:
                logging.warning("  Узел Port не найден под ServersList. Не удалось обновить.")

            if login_node is not None:
                login_node.text = target_login
                logging.info(f"  Обновлен Login на '{target_login}'")
            else:
                logging.info(f"  Узел Login не найден, используется admin по-умолчанию'")
                
            tree.write(filepath, encoding='utf-8', xml_declaration=True)
            logging.info("Файл конфигурации успешно обновлен.")
            if update_status_callback:
                update_status_callback("Файл конфигурации успешно обновлен.")
            return True

        else:
            logging.error(f"Узел ServersList не найден в файле конфигурации '{filepath}'. Не удалось отредактировать.")
            if update_status_callback:
                update_status_callback("Ошибка: Узел ServersList не найден в конфиге.", level="ERROR")
            return False

    except FileNotFoundError:
        logging.error(f"Ошибка: Файл конфигурации не найден для редактирования: '{filepath}'")
        if update_status_callback:
            update_status_callback("Ошибка: Файл конфига не найден.", level="ERROR")
        return False
    except ET.ParseError as e:
        logging.error(f"Ошибка парсинга XML файла '{filepath}': {e}")
        if update_status_callback:
            update_status_callback(f"Ошибка парсинга XML: {e}", level="ERROR")
        return False
    except Exception as e:
        logging.error(f"Произошла ошибка при работе с файлом конфигурации '{filepath}': {e}")
        if update_status_callback:
            update_status_callback(f"Ошибка редактирования конфига: {e}", level="ERROR")
        return False