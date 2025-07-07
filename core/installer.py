# core/installer.py - Обновленный

import os
import zipfile
import shutil
import tempfile
import logging

# Импортируем нужные функции из других модулей
from core.config import get_config_value
# Импортируем функции скачивания с обновленными параметрами
from core.downloader import download_from_http, download_from_ftp, download_from_smb
from utils.file_utils import get_file_company_name
from utils.url_utils import get_expected_installer_name
from utils.exceptions import AbortOperation

# Добавляем is_canceled_callback в параметры
def find_or_download_installer(config, app_type, version_formatted, vendor, update_status_callback, update_progress_callback, progress_base, progress_range, is_canceled_callback=None):
    """
    Находит дистрибутив локально или скачивает/распаковывает его с настроенных источников
    в порядке приоритета.
    update_status_callback(message, level) - callback для обновления статуса.
    update_progress_callback(progress_value) - callback для обновления общего прогресса (0-100).
    progress_base, progress_range - определяют диапазон общего прогресса для этого шага.
    is_canceled_callback() - callback, возвращающий True, если операция отменена.
    """
    logging.info(f"Начат поиск или скачивание дистрибутива для типа '{app_type}' версии '{version_formatted}' (производитель '{vendor}')")
    if is_canceled_callback and is_canceled_callback():
        logging.info("Операция поиска/скачивания отменена.")
        if update_status_callback: update_status_callback("Операция отменена.")
        return None # Сигнал отмены

    installer_root = get_config_value(config, 'Settings', 'InstallerRoot', default='D:\\Backs')
    expected_local_dir_name = get_expected_installer_name(config, app_type, version_formatted)
    if expected_local_dir_name is None:
         logging.error("Ошибка определения имени локальной папки дистрибутива.")
         if update_status_callback: update_status_callback("Ошибка определения имени локальной папки.", level="ERROR")
         return None

    local_installer_path = os.path.join(installer_root, expected_local_dir_name)
    backoffice_exe_direct_path = os.path.join(local_installer_path, "BackOffice.exe")

    if update_status_callback: update_status_callback(f"Проверка локального дистрибутива: {expected_local_dir_name}...")
    logging.info(f"Проверка локального дистрибутива: '{local_installer_path}'")

    # Прогресс этого шага: 0% -> 100% (в рамках переданного progress_base и progress_range)
    # Распределяем прогресс внутри этого шага
    local_check_progress_factor = 0.1 # 10% на проверку локально
    download_extract_progress_factor = 0.8 # 80% на скачивание/распаковку
    final_check_move_progress_factor = 0.1 # 10% на проверку/перемещение

    # 1. Проверяем локально (0-10% этого шага)
    if os.path.exists(backoffice_exe_direct_path):
        logging.info(f"Найден локальный дистрибутив: {local_installer_path}")
        company_name = get_file_company_name(backoffice_exe_direct_path)
        if company_name is None or vendor.lower() in company_name.lower():
            if update_status_callback: update_status_callback("Локальный дистрибутив найден и производитель совпадает (или не определен).")
            logging.info("Производитель совпадает (или не определен). Используем локальный дистрибутив.")
            if update_progress_callback: update_progress_callback(progress_base + progress_range * local_check_progress_factor) # Прогресс 10% этого шага
            return local_installer_path
        else:
            if update_status_callback: update_status_callback("Локальный дистрибутив найден, но производитель не совпадает.", level="WARNING")
            logging.warning(f"Производитель локального дистрибутива ('{company_name}') не совпадает с ожидаемым ('{vendor}'). Будет предпринята попытка скачать.")
            if os.path.exists(local_installer_path):
                 logging.info(f"Удаление локальной папки с несовпадающим производителем: '{local_installer_path}'")
                 shutil.rmtree(local_installer_path, ignore_errors=True)

    # Если локальная проверка не удалась, обновляем прогресс до конца этапа локальной проверки
    if update_progress_callback: update_progress_callback(progress_base + progress_range * local_check_progress_factor)


    # 2. Если локальная проверка не удалась, начинаем процесс скачивания/распаковки/проверки
    if update_status_callback: update_status_callback(f"Локальный дистрибутив не найден или не подходит. Попытка скачать с удаленных источников...")
    logging.info(f"Локальный дистрибутив '{backoffice_exe_direct_path}' не найден или не прошел проверку.")

    temp_archive_path = os.path.join(tempfile.gettempdir(), f"{expected_local_dir_name}.zip")
    temp_archive_path_exists = False
    temp_extract_path = os.path.join(local_installer_path, "temp_extract_folder")


    # --- ГЛАВНЫЙ TRY БЛОК для скачивания, распаковки и подготовки ---
    try:
        if is_canceled_callback and is_canceled_callback(): raise AbortOperation("Operation aborted before download.")

        # Очищаем локальную папку на всякий случай
        if os.path.exists(local_installer_path):
            logging.debug(f"Очистка существующей локальной папки '{local_installer_path}' перед скачиванием/распаковкой.")
            shutil.rmtree(local_installer_path, ignore_errors=True)

        # Создаем корневую папку дистрибутивов и папку для этого дистрибутива
        os.makedirs(installer_root, exist_ok=True)
        os.makedirs(local_installer_path, exist_ok=True)
        logging.debug(f"Создана локальная папка дистрибутива: '{local_installer_path}'.")

        temp_archive_dir = os.path.dirname(temp_archive_path)
        if not os.path.exists(temp_archive_dir):
            os.makedirs(temp_archive_dir, exist_ok=True)
            logging.debug(f"Создана родительская директория для временного архива: '{temp_archive_dir}'.")

        # Очищаем временный файл, если он вдруг остался
        if os.path.exists(temp_archive_path):
             try:
                 os.remove(temp_archive_path)
                 logging.debug(f"Удален старый временный архив '{temp_archive_path}'.")
             except Exception as e:
                 logging.warning(f"Не удалось удалить старый временный архив '{temp_archive_path}': {e}")


        # 2.1. Скачиваем с удаленных источников по приоритету (Занимает часть download_extract_progress_factor)
        # Прогресс для скачивания: progress_base + local_check_progress_factor * progress_range  до  progress_base + local_check_progress_factor * progress_range + download_part_range
        download_part_base = progress_base + local_check_progress_factor * progress_range
        download_part_range = download_extract_progress_factor * progress_range * 0.5 # 50% от download_extract_progress_factor на скачивание (40% от общего)

        source_order_str = get_config_value(config, 'SourcePriority', 'Order', default='smb, http, ftp', type_cast=str)
        source_order = [s.strip().lower() for s in source_order_str.split(',') if s.strip()]

        download_success = False
        for source_type in source_order:
            if is_canceled_callback and is_canceled_callback(): raise AbortOperation(f"Operation aborted during {source_type} download attempt.")

            logging.debug(f"Попытка скачивания с источника '{source_type}'...")
            # Передаем колбэк отмены и диапазон прогресса для скачивания
            if source_type == 'smb':
                if download_from_smb(config, app_type, version_formatted, temp_archive_path, update_status_callback, update_progress_callback, download_part_base, download_part_range, is_canceled_callback):
                     download_success = True
                     temp_archive_path_exists = True
                     break
            elif source_type == 'http':
                if download_from_http(config, app_type, version_formatted, temp_archive_path, update_status_callback, update_progress_callback, download_part_base, download_part_range, is_canceled_callback):
                     download_success = True
                     temp_archive_path_exists = True
                     break
            elif source_type == 'ftp':
                if download_from_ftp(config, app_type, version_formatted, temp_archive_path, update_status_callback, update_progress_callback, download_part_base, download_part_range, is_canceled_callback):
                     download_success = True
                     temp_archive_path_exists = True
                     break
            else:
                logging.warning(f"Неизвестный источник в приоритете: '{source_type}'. Пропускаем.")
                if update_status_callback: update_status_callback(f"Неизвестный источник: '{source_type}'.", level="WARNING")

            logging.debug(f"Скачивание с источника '{source_type}' не удалось.")


        if not download_success:
            raise RuntimeError("Не удалось скачать дистрибутив ни с одного доступного источника.")


        # 2.2. Распаковываем скачанный архив (Занимает оставшуюся часть download_extract_progress_factor)
        # Прогресс для распаковки: progress_base + local_check_progress_factor * progress_range + download_part_range  до  progress_base + local_check_progress_factor * progress_range + download_extract_progress_factor * progress_range
        extract_part_base = download_part_base + download_part_range
        extract_part_range = download_extract_progress_factor * progress_range * 0.5 # 50% от download_extract_progress_factor на распаковку (40% от общего)


        if update_status_callback: update_status_callback(f"Распаковка архива '{os.path.basename(temp_archive_path)}'...")
        logging.info(f"Распаковка архива '{temp_archive_path}' во временную папку '{temp_extract_path}'.")

        os.makedirs(temp_extract_path, exist_ok=True)

        try:
            with zipfile.ZipFile(temp_archive_path, 'r') as zip_ref:
                file_list = zip_ref.namelist()
                total_files = len(file_list)
                extracted_count = 0

                if total_files == 0:
                     logging.warning("Архив пуст. Распаковка не требуется.")

                for file_info in file_list:
                    if is_canceled_callback and is_canceled_callback(): raise AbortOperation("Extraction aborted")

                    zip_ref.extract(file_info, temp_extract_path)
                    extracted_count += 1
                    if update_progress_callback and total_files > 0:
                        current_extract_progress = (extracted_count / total_files)
                        update_progress_callback(extract_part_base + current_extract_progress * extract_part_range)

            logging.info("Распаковка завершена.")
            if update_status_callback: update_status_callback("Архив успешно распакован во временную папку.")
            if update_progress_callback: update_progress_callback(extract_part_base + extract_part_range)


        except zipfile.BadZipFile:
            raise zipfile.BadZipFile(f"Архив '{os.path.basename(temp_archive_path)}' поврежден или не является ZIP-файлом.")
        except Exception as e: # Ловим и другие ошибки распаковки
            raise RuntimeError(f"Ошибка при распаковке архива '{os.path.basename(temp_archive_path)}': {e}")


        # 2.3. Проверка и перемещение распакованного дистрибутива (Занимает final_check_move_progress_factor)
        # Прогресс для проверки/перемещения: progress_base + local_check_progress_factor * progress_range + download_extract_progress_factor * progress_range  до  progress_base + progress_range
        final_part_base = progress_base + local_check_progress_factor * progress_range + download_extract_progress_factor * progress_range
        final_part_range = final_check_move_progress_factor * progress_range # 10% от общего

        if update_status_callback: update_status_callback("Проверка и перемещение распакованного дистрибутива...")
        logging.info(f"Поиск BackOffice.exe во временной папке распаковки: '{temp_extract_path}'")

        found_backoffice_exe = None
        actual_content_root = None

        # Прогресс внутри финальной части: 0.0 - 1.0
        search_progress_factor_in_final = 0.2 # 20% финальной части на поиск
        move_progress_factor_in_final = 0.8 # 80% финальной части на перемещение

        if update_progress_callback: update_progress_callback(final_part_base + search_progress_factor_in_final * final_part_range)

        for dirpath, dirnames, filenames in os.walk(temp_extract_path):
             if is_canceled_callback and is_canceled_callback(): raise AbortOperation("Search for BackOffice.exe aborted")
             if "BackOffice.exe" in filenames:
                 found_backoffice_exe = os.path.join(dirpath, "BackOffice.exe")
                 actual_content_root = dirpath
                 logging.info(f"BackOffice.exe найден по пути: '{found_backoffice_exe}'. Корень содержимого: '{actual_content_root}'")
                 break

        if not found_backoffice_exe or not actual_content_root:
             raise FileNotFoundError(f"Файл BackOffice.exe не найден в распакованном содержимом архива '{os.path.basename(temp_archive_path)}'.")


        logging.info(f"Перемещение содержимого из '{actual_content_root}' в '{local_installer_path}'")
        if update_status_callback: update_status_callback("Перемещение содержимого дистрибутива...")
        try:
            # Используем shutil.copytree и shutil.rmtree для имитации перемещения с контролем
            # shutil.move может быть быстрее, но не поддерживает прогресс и может упасть на разных ФС
            # Копируем содержимое actual_content_root в local_installer_path
            # TODO: Реализовать копирование с прогрессом, если нужно более детальное обновление
            shutil.copytree(actual_content_root, local_installer_path, dirs_exist_ok=True)

            # Обновляем прогресс после копирования
            if update_progress_callback: update_progress_callback(final_part_base + (search_progress_factor_in_final + move_progress_factor_in_final * 0.5) * final_part_range) # 50% перемещения

            # После успешного копирования, удаляем временную папку распаковки
            logging.debug(f"Удаление временной папки распаковки: '{temp_extract_path}'")
            shutil.rmtree(temp_extract_path, ignore_errors=True)
            logging.debug("Временная папка распаковки удалена.")

            # Обновляем прогресс после удаления временной папки
            if update_progress_callback: update_progress_callback(final_part_base + (search_progress_factor_in_final + move_progress_factor_in_final) * final_part_range) # 100% перемещения


        except Exception as e:
            raise RuntimeError(f"Ошибка при перемещении содержимого дистрибутива: {e}")


        # 2.4. Финальная проверка и верификация производителя BackOffice.exe после перемещения
        if is_canceled_callback and is_canceled_callback(): raise AbortOperation("Final check aborted")

        if update_status_callback: update_status_callback("Финальная проверка дистрибутива...")
        backoffice_exe_final_path = os.path.join(local_installer_path, "BackOffice.exe")
        if not os.path.exists(backoffice_exe_final_path):
             raise FileNotFoundError(f"Файл BackOffice.exe не найден по ожидаемому конечному пути '{backoffice_exe_final_path}' после перемещения.")

        company_name = get_file_company_name(backoffice_exe_final_path)
        if company_name is not None and vendor.lower() not in company_name.lower():
            raise ValueError(f"Производитель распакованного дистрибутива ('{company_name}') не совпадает с ожидаемым ('{vendor}'). Дистрибутив, возможно, некорректен.")

        # Прогресс для всего шага find_or_download_installer достигнут (progress_base + progress_range)
        if update_progress_callback: update_progress_callback(progress_base + progress_range)


        # --- УСПЕХ: Удаляем временные папки и возвращаем путь ---
        logging.info("Производитель распакованного дистрибутива совпадает (или не определен). Дистрибутив готов к использованию.")
        if update_status_callback: update_status_callback("Дистрибутив успешно подготовлен.")

        # Временная папка распаковки уже удалена после shutil.copytree
        # Удаляем временный архив, если он был создан
        if temp_archive_path_exists and os.path.exists(temp_archive_path):
             try:
                 os.remove(temp_archive_path)
                 logging.debug("Временный архив успешно удален после успешной проверки.")
             except Exception as e:
                 logging.warning(f"Ошибка при удалении временного архива '{temp_archive_path}' после успеха: {e}")

        return local_installer_path # Возвращаем путь к готовому дистрибутиву


    # --- ГЛАВНЫЙ EXCEPT БЛОК ---
    except AbortOperation as e:
         # Ловим наше пользовательское исключение отмены
         logging.info(f"Операция отменена: {e}")
         if update_status_callback: update_status_callback("Операция отменена.", level="INFO")
         # Очистка временных файлов и папок при отмене
         _cleanup_temp_files(temp_archive_path, temp_extract_path, local_installer_path)
         return None # Возвращаем None при отмене

    except Exception as e:
        logging.error(f"Ошибка в процессе подготовки дистрибутива: {e}")
        if update_status_callback: update_status_callback(f"Ошибка подготовки дистрибутива: {e}", level="ERROR")
        # Очистка временных файлов и папок при ошибке
        _cleanup_temp_files(temp_archive_path, temp_extract_path, local_installer_path)
        # Перебрасываем ошибку, чтобы ее поймал воркер
        raise e


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
              logging.warning(f"Ошибка при очистке временного архива '{temp_archive_path}': {temp_e}")

     # Очищаем локальную папку дистрибутива, если она была создана, но подготовка не завершилась успешно
     # Это важно, чтобы при следующей попытке не использовать неполный или некорректный дистрибутив.
     # Проверяем, что папка существует и не является корневой (избежать случайного удаления D:\Backs)
     installer_root = get_config_value(None, 'Settings', 'InstallerRoot', default='D:\\Backs') # Загружаем дефолт, конфиг может быть None
     if os.path.exists(local_installer_path) and os.path.normpath(local_installer_path) != os.path.normpath(installer_root):
          try:
              shutil.rmtree(local_installer_path, ignore_errors=True)
              logging.debug(f"Локальная папка дистрибутива '{local_installer_path}' очищена после ошибки/отмены.")
          except Exception as cleanup_e:
               logging.warning(f"Ошибка при очистке локальной папки дистрибутива '{local_installer_path}' после ошибки/отмены: {cleanup_e}")
     logging.debug("Очистка временных файлов/папок завершена.")
