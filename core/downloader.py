# core/downloader.py - Обновленный

import requests
import os
import urllib.parse
import time
import logging
from ftplib import FTP
import shutil

# Импортируем get_config_value из core.config
from core.config import get_config_value

# Добавляем is_canceled_callback в параметры функций скачивания
def download_from_http(config, app_type, version_formatted, temp_archive_path, update_status_callback, update_progress_callback, progress_base, progress_range, is_canceled_callback=None):
    """Скачивает архив дистрибутива по HTTP."""
    logging.debug(f"Попытка скачивания с HTTP.")
    if is_canceled_callback and is_canceled_callback(): return False # Проверка отмены

    http_enabled = get_config_value(config, 'HttpSource', 'Enabled', default=False, type_cast=bool)
    if not http_enabled:
        logging.debug("HTTP источник отключен в конфиге.")
        return False # Источник отключен

    http_url_base = get_config_value(config, 'HttpSource', 'Url', default=None, type_cast=str)
    if not http_url_base:
        logging.error("Ошибка: Не указан URL для HTTP источника в конфиге.")
        if update_status_callback: update_status_callback("Ошибка: Не указан URL для HTTP источника.", level="ERROR")
        return False # Не настроен

    archive_name_template = get_config_value(config, 'HttpSource', f'{app_type}_ArchiveName', default=None, type_cast=str)
    if not archive_name_template:
         logging.error(f"Ошибка: Не указан шаблон имени архива для типа '{app_type}' в разделе HttpSource конфига.")
         if update_status_callback: update_status_callback(f"Ошибка: Не указан шаблон имени архива для '{app_type}'.", level="ERROR")
         return False # Не настроен

    archive_name = archive_name_template.replace('{version}', version_formatted)
    http_full_url = urllib.parse.urljoin(http_url_base.rstrip('/') + '/', archive_name)

    if update_status_callback: update_status_callback(f"Скачивание с HTTP: {os.path.basename(http_full_url)}...")
    logging.info(f"Попытка скачивания с HTTP: '{http_full_url}' в '{temp_archive_path}'.")

    try:
        response = requests.get(http_full_url, stream=True, timeout=get_config_value(config, 'Settings', 'HttpRequestTimeoutSec', default=15, type_cast=int))
        response.raise_for_status()

        total_size = int(response.headers.get('content-length', 0))
        downloaded_size = 0
        buffer_size = 8192

        with open(temp_archive_path, 'wb') as f_dst:
            for chunk in response.iter_content(chunk_size=buffer_size):
                if is_canceled_callback and is_canceled_callback():
                     logging.warning("Скачивание HTTP отменено.")
                     if update_status_callback: update_status_callback("Скачивание HTTP отменено.")
                     # Очищаем частичный файл при отмене
                     if os.path.exists(temp_archive_path):
                         try: os.remove(temp_archive_path)
                         except Exception as e: logging.warning(f"Ошибка при удалении частичного файла '{temp_archive_path}' после отмены: {e}")
                     return False # Сигнал отмены

                if chunk:
                    f_dst.write(chunk)
                    downloaded_size += len(chunk)
                    if update_progress_callback and total_size > 0:
                         current_source_progress = (downloaded_size / total_size)
                         update_progress_callback(progress_base + current_source_progress * progress_range)

        logging.info("Скачивание HTTP завершено.")
        if update_status_callback: update_status_callback("Скачивание HTTP завершено.")
        if update_progress_callback: update_progress_callback(progress_base + progress_range)
        return True

    except requests.exceptions.RequestException as e:
        logging.error(f"Ошибка HTTP скачивания с '{http_full_url}': {e}")
        if update_status_callback: update_status_callback(f"Ошибка HTTP скачивания: {e}", level="ERROR")
        return False
    except Exception as e:
        logging.error(f"Неизвестная ошибка при скачивании с HTTP '{http_full_url}': {e}")
        if update_status_callback: update_status_callback(f"Неизвестная ошибка HTTP скачивания: {e}", level="ERROR")
        return False


# Добавляем is_canceled_callback в параметры функций скачивания
def download_from_ftp(config, app_type, version_formatted, temp_archive_path, update_status_callback, update_progress_callback, progress_base, progress_range, is_canceled_callback=None):
    """Скачивает архив дистрибутива по FTP."""
    logging.debug(f"Попытка скачивания с FTP.")
    if is_canceled_callback and is_canceled_callback(): return False # Проверка отмены

    ftp_enabled = get_config_value(config, 'FtpSource', 'Enabled', default=False, type_cast=bool)
    if not ftp_enabled:
        logging.debug("FTP источник отключен в конфиге.")
        return False

    ftp_host = get_config_value(config, 'FtpSource', 'Host', default=None, type_cast=str)
    ftp_port = get_config_value(config, 'FtpSource', 'Port', default=21, type_cast=int)
    ftp_username = get_config_value(config, 'FtpSource', 'Username', default='anonymous', type_cast=str)
    ftp_password = get_config_value(config, 'FtpSource', 'Password', default='', type_cast=str)
    ftp_directory = get_config_value(config, 'FtpSource', 'Directory', default=None, type_cast=str)

    if not ftp_host or not ftp_directory:
        logging.error("Ошибка: Не указаны Host или Directory для FTP источника в конфиге.")
        if update_status_callback: update_status_callback("Ошибка: Не указаны Host или Directory для FTP.", level="ERROR")
        return False

    archive_name_template = get_config_value(config, 'FtpSource', f'{app_type}_ArchiveName', default=None, type_cast=str)
    if not archive_name_template:
         logging.error(f"Ошибка: Не указан шаблон имени архива для типа '{app_type}' в разделе FtpSource конфига.")
         if update_status_callback: update_status_callback(f"Ошибка: Не указан шаблон имени архива для '{app_type}'.", level="ERROR")
         return False

    archive_name = archive_name_template.replace('{version}', version_formatted)

    if update_status_callback: update_status_callback(f"Скачивание с FTP: {archive_name}...")
    logging.info(f"Попытка скачивания с FTP: '{ftp_host}:{ftp_port}{ftp_directory}/{archive_name}' в '{temp_archive_path}'.")

    from ftplib import FTP, all_errors
    try:
        with FTP() as ftp:
            ftp.connect(ftp_host, ftp_port)
            ftp.login(ftp_username, ftp_password)
            logging.debug(f"FTP логин успешен. Текущая директория: {ftp.pwd()}")

            try:
                ftp.cwd(ftp_directory)
                logging.debug(f"FTP смена директории на '{ftp_directory}' успешна. Текущая директория: {ftp.pwd()}")
            except all_errors as e:
                 logging.error(f"Ошибка FTP: Не удалось сменить директорию на '{ftp_directory}': {e}")
                 if update_status_callback: update_status_callback(f"Ошибка FTP: Не найдена директория '{ftp_directory}'.", level="ERROR")
                 return False

            archive_dir = os.path.dirname(archive_name)
            archive_file = os.path.basename(archive_name)

            if archive_dir and archive_dir != '.':
                 try:
                      ftp.cwd(archive_dir)
                      logging.debug(f"FTP смена директории на подпапку '{archive_dir}' успешна. Текущая директория: {ftp.pwd()}")
                 except all_errors as e:
                      logging.error(f"Ошибка FTP: Не удалось сменить директорию на '{archive_dir}': {e}")
                      if update_status_callback: update_status_callback(f"Ошибка FTP: Не найдена подпапка '{archive_dir}'.", level="ERROR")
                      return False

            try:
                total_size = ftp.size(archive_file)
                logging.debug(f"Размер архива на FTP: {total_size} байт.")
            except all_errors as e:
                 logging.warning(f"Ошибка FTP: Не удалось получить размер файла '{archive_file}': {e}")
                 total_size = 0

            downloaded_size = 0
            buffer_size = 8192

            def handle_ftp_progress(chunk):
                 if is_canceled_callback and is_canceled_callback():
                     # Если отмена во время скачивания, вызываем исключение,
                     # чтобы прервать retrbinary
                     raise AbortOperation("FTP download aborted")

                 nonlocal downloaded_size
                 downloaded_size += len(chunk)
                 if update_progress_callback and total_size > 0:
                      current_source_progress = (downloaded_size / total_size)
                      update_progress_callback(progress_base + current_source_progress * progress_range)
                 f_dst.write(chunk)

            # Определяем пользовательское исключение для отмены
            class AbortOperation(Exception):
                pass

            with open(temp_archive_path, 'wb') as f_dst:
                 try:
                      ftp.retrbinary(f'RETR {archive_file}', handle_ftp_progress, buffer_size)
                 except AbortOperation:
                      logging.warning("FTP скачивание прервано по запросу отмены.")
                      if update_status_callback: update_status_callback("Скачивание FTP отменено.")
                      # Очищаем частичный файл при отмене
                      if os.path.exists(temp_archive_path):
                          try: os.remove(temp_archive_path)
                          except Exception as e: logging.warning(f"Ошибка при удалении частичного файла '{temp_archive_path}' после отмены: {e}")
                      return False # Сигнал отмены


            logging.info("Скачивание FTP завершено.")
            if update_status_callback: update_status_callback("Скачивание FTP завершено.")
            if update_progress_callback: update_progress_callback(progress_base + progress_range)
            return True

    except all_errors as e:
        logging.error(f"Ошибка FTP скачивания с '{ftp_host}:{ftp_port}{ftp_directory}/{archive_name}': {e}")
        if update_status_callback: update_status_callback(f"Ошибка FTP скачивания: {e}", level="ERROR")
        return False
    except Exception as e:
        logging.error(f"Неизвестная ошибка при скачивании с FTP '{ftp_host}:{ftp_port}{ftp_directory}/{archive_name}': {e}")
        if update_status_callback: update_status_callback(f"Неизвестная ошибка FTP скачивания: {e}", level="ERROR")
        return False


# Добавляем is_canceled_callback в параметры функций скачивания
def download_from_smb(config, app_type, version_formatted, temp_archive_path, update_status_callback, update_progress_callback, progress_base, progress_range, is_canceled_callback=None):
    """Скачивает архив дистрибутива с SMB ресурса (копированием)."""
    logging.debug(f"Попытка скачивания с SMB.")
    if is_canceled_callback and is_canceled_callback(): return False # Проверка отмены

    smb_enabled = get_config_value(config, 'SmbSource', 'Enabled', default=False, type_cast=bool)
    if not smb_enabled:
        logging.debug("SMB источник отключен в конфиге.")
        return False

    smb_path_base = get_config_value(config, 'SmbSource', 'Path', default=None, type_cast=str)
    if not smb_path_base:
        logging.error("Ошибка: Не указан Path для SMB источника в конфиге.")
        if update_status_callback: update_status_callback("Ошибка: Не указан Path для SMB.", level="ERROR")
        return False

    archive_name_template = get_config_value(config, 'SmbSource', f'{app_type}_ArchiveName', default=None, type_cast=str)
    if not archive_name_template:
         logging.error(f"Ошибка: Не указан шаблон имени архива для типа '{app_type}' в разделе SmbSource конфига.")
         if update_status_callback: update_status_callback(f"Ошибка: Не указан шаблон имени архива для '{app_type}'.", level="ERROR")
         return False

    archive_name = archive_name_template.replace('{version}', version_formatted)
    smb_full_path = f"{smb_path_base.rstrip('/\\')}{os.sep}{archive_name.replace('/', os.sep).replace('\\', os.sep)}"

    if update_status_callback: update_status_callback(f"Скачивание с SMB: {os.path.basename(smb_full_path)}...")
    logging.info(f"Попытка скачивания с SMB: '{smb_full_path}' в '{temp_archive_path}'.")

    try:
        if not os.path.exists(smb_full_path):
             logging.error(f"Ошибка: Исходный архив не найден на SMB: '{smb_full_path}'.")
             if update_status_callback: update_status_callback("Ошибка: Исходный архив не найден на SMB.", level="ERROR")
             return False

        try:
            total_size = os.path.getsize(smb_full_path)
            logging.debug(f"Размер архива на SMB: {total_size} байт.")
        except Exception as e:
             logging.warning(f"Ошибка при получении размера файла '{smb_full_path}': {e}")
             total_size = 0

        copied_size = 0
        buffer_size = 1024 * 1024 # 1 MB buffer

        with open(smb_full_path, 'rb') as f_src, open(temp_archive_path, 'wb') as f_dst:
            while True:
                if is_canceled_callback and is_canceled_callback():
                     logging.warning("Копирование SMB отменено.")
                     if update_status_callback: update_status_callback("Копирование SMB отменено.")
                     # Очищаем частичный файл при отмене
                     if os.path.exists(temp_archive_path):
                         try: os.remove(temp_archive_path)
                         except Exception as e: logging.warning(f"Ошибка при удалении частичного файла '{temp_archive_path}' после отмены: {e}")
                     return False # Сигнал отмены

                buffer = f_src.read(buffer_size)
                if not buffer:
                    break
                f_dst.write(buffer)
                copied_size += len(buffer)
                if update_progress_callback and total_size > 0:
                    current_source_progress = (copied_size / total_size)
                    update_progress_callback(progress_base + current_source_progress * progress_range)

        logging.info("Копирование SMB завершено.")
        if update_status_callback: update_status_callback("Копирование SMB завершено.")
        if update_progress_callback: update_progress_callback(progress_base + progress_range)
        return True

    except FileNotFoundError:
        logging.error(f"Ошибка FileNotFoundError при скачивании с SMB: '{smb_full_path}'.")
        if update_status_callback: update_status_callback("Ошибка SMB скачивания: Файл не найден.", level="ERROR")
        return False
    except PermissionError:
        logging.error(f"Ошибка доступа PermissionError при скачивании с SMB: '{smb_full_path}'. Проверьте права.")
        if update_status_callback: update_status_callback("Ошибка SMB скачивания: Нет прав доступа.", level="ERROR")
        return False
    except Exception as e:
        logging.error(f"Неизвестная ошибка при скачивании с SMB '{smb_full_path}': {e}")
        if update_status_callback: update_status_callback(f"Неизвестная ошибка SMB скачивания: {e}", level="ERROR")
        return False