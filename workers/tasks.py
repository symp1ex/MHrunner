# workers/tasks.py - ОБНОВЛЕННЫЙ (исправлена остановка процесса после успешного запуска)

import os
import time
from PyQt6.QtCore import QObject, pyqtSignal, QThread
import logging
import traceback
import json
import shutil

# Импортируем функции-шаги из core.launcher
from core.launcher import (
    check_server_info,
    step_parse_input,
    step_http_request,
    step_process_response,
    step_check_server_state,
    step_format_version,
    step_get_installer_name,
    step_appdata_cleanup,
    step_first_run,
    step_wait_edit_config,
    step_restart
)
from core.installer import find_or_download_installer
from utils.exceptions import AbortOperation
from utils.process_utils import stop_process_by_pid
from utils.file_utils import edit_config_file, wait_for_file
from core.config import get_config_value



class BaseWorker(QObject):
    """Базовый класс для воркеров, предоставляющий сигналы для GUI."""
    status_update = pyqtSignal(str, str)
    progress_update = pyqtSignal(int)
    text_update = pyqtSignal(str)
    # Обновленный сигнал ошибки: message (краткое), detailed_traceback (полное)
    error = pyqtSignal(str, str)
    finished = pyqtSignal()

    dialog_request = pyqtSignal(str, str, str, list, object)

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._is_canceled = False

    def _update_status(self, message, level="INFO"):
        self.status_update.emit(message, level)

    def _update_progress(self, value):
        safe_value = max(0, min(100, value))
        self.progress_update.emit(int(safe_value))

    def _update_text(self, text):
        self.text_update.emit(text)

    def _request_dialog(self, dialog_type, title, message, options, callback_data):
        self.dialog_request.emit(dialog_type, title, message, options, callback_data)

    def cancel(self):
        """Устанавливает флаг отмены для воркера."""
        self._is_canceled = True
        logging.info(f"{self.__class__.__name__} received cancellation request.")
        # Воркер должен проверять self._is_canceled в своих длительных операциях


class CheckWorker(BaseWorker):
    """Воркер для выполнения проверки сервера."""
    def __init__(self, config, target_string, parent=None):
        super().__init__(config, parent)
        self.target_string = target_string

    def run(self):
        logging.info(f"CheckWorker запущен для '{self.target_string}'.")
        try:
            # Проверка на отмену перед началом
            if self._is_canceled: raise AbortOperation("Check operation aborted before start.")

            server_info = check_server_info(
                self.config,
                self.target_string,
                self._update_status,
                self._update_progress
            )

            # Проверка на отмену после завершения check_server_info
            if self._is_canceled: raise AbortOperation("Check operation aborted after check_server_info.")


            formatted_json = json.dumps(server_info, indent=4, ensure_ascii=False)
            self._update_text(formatted_json)

            self._update_status("Проверка завершена.", level="INFO")
            self._update_progress(100)

        except AbortOperation as e:
             logging.info(f"CheckWorker отменен: {e}")
             self._update_status("Проверка отменена.", level="INFO")
             self._update_progress(0)
             self._update_text(f"Проверка отменена:\n{e}")

        except Exception as e:
            logging.error(f"Ошибка в CheckWorker: {e}\n{traceback.format_exc()}")
            # В GUI _handle_error отобразит подробности
            self._update_status("Ошибка проверки: подробности ниже.", level="ERROR")
            self._update_progress(0)
            self.error.emit(str(e), traceback.format_exc())

        finally:
            self.finished.emit()
            logging.info("CheckWorker завершен.")


class LaunchWorker(BaseWorker):
    """Воркер для выполнения последовательности запуска BackOffice."""
    PROGRESS_BOUNDARIES = {
        'parse': (0, 5),
        'http_request': (5, 20),
        'process_response': (20, 35),
        'check_state': (35, 40),
        'format_version': (40, 45),
        'get_name': (45, 50),
        'find_download': (50, 90),
        'appdata_cleanup': (90, 95),
        'first_run': (95, 96),
        'wait_edit_config': (96, 98),
        'restart': (98, 100)
    }

    def __init__(self, config, launch_data, parent=None):
        super().__init__(config, parent)
        self.launch_data = launch_data
        self._current_process = None # Ссылка на запущенный процесс BackOffice для остановки при ошибке/отмене

    def _get_step_progress_range(self, step_name):
        """Возвращает базовое значение и диапазон прогресса для шага."""
        base, end = self.PROGRESS_BOUNDARIES.get(step_name, (0, 0))
        return base, end - base

    def _update_step_progress(self, step_name, factor=1.0):
        """Обновляет общий прогресс на основе прогресса внутри шага."""
        base, range_ = self._get_step_progress_range(step_name)
        total_progress = base + factor * range_
        self._update_progress(total_progress)

    def _stop_backoffice_process(self):
        """Останавливает запущенный процесс BackOffice, если он есть и отслеживается."""
        if self._current_process and self._current_process.poll() is None:
            logging.info(f"Остановка процесса BackOffice (PID: {self._current_process.pid}) по запросу воркера.")
            stop_process_by_pid(self._current_process.pid)
            self._current_process = None # Сбрасываем ссылку после попытки остановки
        elif self._current_process is None:
             logging.debug("Нет отслеживаемого процесса BackOffice для остановки.")
        else: # self._current_process.poll() is not None, т.е. процесс уже завершился
             logging.debug(f"Отслеживаемый процесс BackOffice (PID: {self._current_process.pid}) уже завершен.")
             self._current_process = None # Сбрасываем ссылку, если процесс уже завершен


    def run(self):
        logging.info("LaunchWorker запущен.")
        try:
            # Шаг 1: Парсинг ввода (0-5%)
            if self._is_canceled: raise AbortOperation("Operation aborted before step 1.")
            self._update_status("Парсинг введенного адреса...")
            step_data = step_parse_input(self.launch_data['target_string'])
            self.launch_data.update(step_data)
            self._update_step_progress('parse')
            logging.debug("Шаг 1 завершен.")

            # Шаг 2: Выполнение HTTP-запроса (5-20%)
            if self._is_canceled: raise AbortOperation("Operation aborted before step 2.")
            base, range_ = self._get_step_progress_range('http_request')
            self._update_progress(base + range_ * 0.1) # Начальный прогресс шага
            self._update_status(f"Выполнение GET-запроса к {self.launch_data['parsed_target']['UrlOrIp']}:{self.launch_data['parsed_target']['Port']}...")
            step_data = step_http_request(self.config, self.launch_data['parsed_target'])
            self.launch_data.update(step_data)
            self._update_step_progress('http_request')
            logging.debug("Шаг 2 завершен.")

            # Шаг 3: Обработка ответа и определение типа приложения (20-35%)
            if self._is_canceled: raise AbortOperation("Operation aborted before step 3.")
            self._update_status("Обработка ответа сервера...")
            step_data = step_process_response(self.launch_data['target_string'], self.launch_data['server_info'])
            self.launch_data.update(step_data)

            if self.launch_data.get('app_info') is None:
                 logging.info("Требуется выбор типа приложения пользователем.")
                 self._update_step_progress('process_response', 0.5) # Прогресс до середины шага
                 self._request_dialog('app_type', "Выбор типа приложения",
                                      f"Не удалось автоматически определить тип RMS/Chain для производителя по edition ('{self.launch_data.get('edition', 'N/A')}').\nВыберите тип приложения:",
                                      ['RMS', 'Chain'],
                                      self.launch_data)
                 return # Ожидаем ответа от GUI, воркер завершится здесь временно

            self.launch_data['app_type'] = self.launch_data['app_info']['AppType']
            self.launch_data['vendor'] = self.launch_data['app_info']['Vendor']
            self._update_status(f"Определен тип приложения: '{self.launch_data['app_type']}' (Производитель: '{self.launch_data['vendor']}')")
            self._update_step_progress('process_response')
            logging.debug("Шаг 3 завершен.")

            # Переходим к Шагу 4
            self._run_from_step4()


        except AbortOperation as e:
            # Ловим пользовательскую отмену
            logging.info(f"Операция отменена в LaunchWorker (шаги 1-3): {e}")
            self._update_status("Операция отменена.", level="INFO")
            self._update_progress(0)
            self._update_text(f"Операция отменена:\n{e}")
            # Очистка временных файлов/папок происходит в find_or_download_installer при AbortOperation
            # Дополнительная очистка, если отмена произошла до скачивания
            if 'local_installer_path' in self.launch_data and os.path.exists(self.launch_data['local_installer_path']):
                 try:
                      installer_root = get_config_value(self.config, 'Settings', 'InstallerRoot', default='D:\\Backs')
                      # Убеждаемся, что не удаляем корневую папку
                      if os.path.normpath(self.launch_data['local_installer_path']) != os.path.normpath(installer_root):
                           shutil.rmtree(self.launch_data['local_installer_path'], ignore_errors=True)
                           logging.debug(f"Локальная папка дистрибутива '{self.launch_data['local_installer_path']}' очищена после отмены.")
                 except Exception as cleanup_e:
                      logging.warning(f"Ошибка при очистке локальной папки дистрибутива '{self.launch_data['local_installer_path']}' после отмены: {cleanup_e}")

            # Останавливаем процесс BackOffice, если он был запущен до отмены (например, на шаге 9)
            self._stop_backoffice_process()


        except Exception as e:
            # Ловим любые другие ошибки
            logging.error(f"Ошибка в LaunchWorker (шаги 1-3): {e}\n{traceback.format_exc()}")
            # В GUI _handle_error отобразит подробности
            self._update_status("Ошибка запуска: подробности ниже.", level="ERROR")
            self._update_progress(0)
            self._update_text(f"Ошибка во время запуска:\n{traceback.format_exc()}")
            self.error.emit(str(e), traceback.format_exc())

            # Останавливаем процесс BackOffice, если он был запущен и еще работает
            self._stop_backoffice_process()


        finally:
            # В этом finally блоке НЕ останавливаем процесс,
            # т.к. он может быть финальным запущенным процессом.
            # Остановка происходит только в блоках except или AbortOperation.
            self.finished.emit()
            logging.info("LaunchWorker завершен.")

    def _run_from_step4(self):
        """Продолжение последовательности запуска с Шага 4."""
        logging.info("Продолжение последовательности с Шага 4.")
        try:
            # Шаг 4: Проверка состояния сервера (35-40%)
            if self._is_canceled: raise AbortOperation("Operation aborted before step 4.")
            self._update_status("Проверка состояния сервера...")
            server_state_ok = step_check_server_state(self.launch_data['parsed_target'], self.launch_data['server_state'])

            if not server_state_ok:
                 logging.info("Требуется подтверждение состояния сервера пользователем.")
                 self._update_step_progress('check_state', 0.5) # Прогресс до середины шага
                 self._request_dialog('server_state_confirm', "Состояние сервера",
                                      f"Состояние сервера '{self.launch_data['parsed_target']['UrlOrIp']}' не 'STARTED_SUCCESSFULLY', текущее состояние: '{self.launch_data['server_state']}'.\nПродолжить запуск BackOffice?",
                                      ['Yes', 'No'],
                                      self.launch_data)
                 return # Ожидаем ответа от GUI, воркер завершится здесь временно

            self._update_status("Состояние сервера OK.")
            self._update_step_progress('check_state')
            logging.debug("Шаг 4 завершен.")

            # Переходим к Шагу 5
            self._run_from_step5()

        except AbortOperation as e:
            logging.info(f"Операция отменена в _run_from_step4: {e}")
            self._update_status("Операция отменена.", level="INFO")
            self._update_progress(self.PROGRESS_BOUNDARIES['check_state'][0]) # Сбрасываем прогресс шага
            self._update_text(f"Операция отменена:\n{e}")
            self._stop_backoffice_process() # Останавливаем процесс при отмене

        except Exception as e:
            logging.error(f"Ошибка в _run_from_step4: {e}\n{traceback.format_exc()}")
            self._update_status("Ошибка запуска: подробности ниже.", level="ERROR")
            self._update_progress(self.PROGRESS_BOUNDARIES['check_state'][0]) # Сбрасываем прогресс шага
            self._update_text(f"Ошибка во время запуска:\n{traceback.format_exc()}")
            self.error.emit(str(e), traceback.format_exc())
            self._stop_backoffice_process() # Останавливаем процесс при ошибке


    def _run_from_step5(self):
        """Продолжение последовательности запуска с Шага 5."""
        logging.info("Продолжение последовательности с Шага 5.")
        try:
            # Шаг 5: Форматирование версии (40-45%)
            if self._is_canceled: raise AbortOperation("Operation aborted before step 5.")
            self._update_status("Форматирование версии...")
            step_data = step_format_version(self.launch_data['version_raw'])
            self.launch_data.update(step_data)
            self._update_status(f"Форматированная версия: {self.launch_data['version_formatted']}")
            self._update_step_progress('format_version')
            logging.debug("Шаг 5 завершен.")

            # Шаг 6: Определение ожидаемого имени каталога дистрибутива (45-50%)
            if self._is_canceled: raise AbortOperation("Operation aborted before step 6.")
            self._update_status("Определение имени дистрибутива...")
            step_data = step_get_installer_name(self.config, self.launch_data['app_type'], self.launch_data['version_formatted'])
            self.launch_data.update(step_data)
            self._update_status(f"Ожидаемое имя дистрибутива: {self.launch_data['expected_installer_name']}")
            self._update_step_progress('get_name')
            logging.debug("Шаг 6 завершен.")

            # Шаг 7: Поиск или скачивание дистрибутива (50-90%)
            if self._is_canceled: raise AbortOperation("Operation aborted before step 7.")
            base, range_ = self._get_step_progress_range('find_download')
            self._update_progress(base) # Начальный прогресс шага
            installer_path = find_or_download_installer(
                self.config,
                self.launch_data['app_type'],
                self.launch_data['version_formatted'],
                self.launch_data['vendor'],
                self._update_status,
                self._update_progress,
                base,
                range_,
                lambda: self._is_canceled # Передаем колбэк отмены
            )

            if installer_path is None:
                 # find_or_download_installer возвращает None только при отмене
                 raise AbortOperation("Installer download/preparation aborted.")

            self.launch_data['installer_path'] = installer_path
            self._update_status(f"Каталог дистрибутива готов: {os.path.basename(installer_path)}")
            self._update_step_progress('find_download', 1.0)
            logging.debug("Шаг 7 завершен.")


            # Шаг 8: Определение пути AppData и очистка (90-95%)
            if self._is_canceled: raise AbortOperation("Operation aborted before step 8.")
            base, range_ = self._get_step_progress_range('appdata_cleanup')
            self._update_progress(base + range_ * 0.1) # Начальный прогресс шага
            self._update_status("Определение пути AppData и очистка...")
            step_data = step_appdata_cleanup(
                self.launch_data['parsed_target'],
                self.launch_data['vendor'],
                self.launch_data['app_type'],
                self.launch_data['version_raw']
            )
            self.launch_data.update(step_data)
            self._update_status("Временная папка кэша очищена (если существовала).")
            self._update_step_progress('appdata_cleanup')
            logging.debug("Шаг 8 завершен.")


            # Шаг 9: Первый запуск BackOffice.exe (95-96%)
            if self._is_canceled: raise AbortOperation("Operation aborted before step 9.")
            base, range_ = self._get_step_progress_range('first_run')
            self._update_progress(base + range_ * 0.1) # Начальный прогресс шага
            self._update_status("Первый запуск BackOffice.exe...")
            step_data = step_first_run(self.launch_data['installer_path'], self.launch_data['sanitized_target'])
            self.launch_data.update(step_data)
            self._current_process = self.launch_data.get('backoffice_process') # Сохраняем ссылку на процесс для возможной остановки
            self._update_status(f"BackOffice.exe запущен (PID: {self._current_process.pid}).")
            self._update_step_progress('first_run')
            logging.debug("Шаг 9 завершен.")


            # Шаг 10: Ожидание и редактирование файла backclient.config (96-98%)
            if self._is_canceled: raise AbortOperation("Operation aborted before step 10.")
            base, range_ = self._get_step_progress_range('wait_edit_config')
            self._update_progress(base) # Начальный прогресс шага

            # Ожидаем появления файла конфигурации
            wait_success = wait_for_file(
                os.path.join(self.launch_data['backoffice_temp_dir'], "config", "backclient.config.xml"),
                get_config_value(self.config, 'Settings', 'ConfigFileWaitTimeoutSec', default=60, type_cast=int),
                get_config_value(self.config, 'Settings', 'ConfigFileCheckIntervalMs', default=100, type_cast=int),
                self._update_status,
                self._update_progress,
                base, # База прогресса для wait_for_file
                range_, # Диапазон прогресса для wait_for_file
                lambda: self._is_canceled # Передаем колбэк отмены
            )

            if not wait_success:
                 # wait_for_file вернет False, если отмена произошла во время ожидания
                 raise AbortOperation("Waiting for config file aborted.")
            # Если wait_for_file выбросил TimeoutError, он будет пойман в блоке except.


            # Файл найден. Останавливаем процесс BackOffice перед редактированием.
            self._stop_backoffice_process() # Останавливаем процесс, запущенный на шаге 9
            time.sleep(1.0) # Даем немного времени

            self._update_status("Редактирование файла конфигурации...")
            # Прогресс редактирования внутри wait_edit_config уже учтен в wait_for_file
            if not edit_config_file(
                os.path.join(self.launch_data['backoffice_temp_dir'], "config", "backclient.config.xml"),
                self.launch_data['parsed_target']['UrlOrIp'],
                self.launch_data['parsed_target']['Port'],
                self.launch_data['config_protocol'],
                self._update_status
            ):
                 raise RuntimeError(f"Не удалось отредактировать файл конфигурации '{os.path.join(self.launch_data['backoffice_temp_dir'], 'config', 'backclient.config.xml')}'.")

            self._update_status("Файл конфигурации успешно отредактирован.")
            self._update_step_progress('wait_edit_config', 1.0) # Обновляем прогресс шага до 100%
            logging.debug("Шаг 10 завершен.")


            # Шаг 11: Перезапуск BackOffice.exe (98-100%)
            if self._is_canceled: raise AbortOperation("Operation aborted before step 11.")
            base, range_ = self._get_step_progress_range('restart')
            self._update_progress(base + range_ * 0.1) # Начальный прогресс шага
            self._update_status("Перезапуск BackOffice.exe...")

            # Предыдущий процесс уже остановлен на шаге 10
            step_data = step_restart(
                self.launch_data['installer_path'],
                self.launch_data['backoffice_exe_path'],
                self.launch_data['backoffice_args']
            )
            self.launch_data.update(step_data)
            # !!! ВАЖНОЕ ИЗМЕНЕНИЕ !!!
            # Мы НЕ сохраняем ссылку на финальный процесс в self._current_process.
            # Это означает, что LaunchWorker перестает отслеживать этот процесс.
            # Это позволяет приложению GUI закрыться без предупреждения.
            # self._current_process = self.launch_data.get('backoffice_process') # УДАЛЯЕМ ЭТУ СТРОКУ

            logging.info(f"BackOffice.exe успешно перезапущен (PID: {self.launch_data.get('backoffice_process').pid}).")
            self._update_status("BackOffice.exe успешно перезапущен.")
            self._update_step_progress('restart')
            logging.debug("Шаг 11 завершен.")


            # --- Завершение ---
            self._update_status("Готово! BackOffice запущен.", level="INFO") # Более краткий статус
            self._update_progress(100)
            logging.info("Последовательность запуска BackOffice успешно завершена.")


        except AbortOperation as e:
            logging.info(f"Операция отменена в LaunchWorker (шаги 4-11): {e}")
            self._update_status("Операция отменена.", level="INFO")
            self._update_progress(0)
            self._update_text(f"Операция отменена:\n{e}")
            # Очистка временных файлов/папок происходит в find_or_download_installer при AbortOperation
            # Дополнительная очистка, если отмена произошла до скачивания
            if 'local_installer_path' in self.launch_data and os.path.exists(self.launch_data['local_installer_path']):
                 try:
                      installer_root = get_config_value(self.config, 'Settings', 'InstallerRoot', default='D:\\Backs')
                       # Убеждаемся, что не удаляем корневую папку
                      if os.path.normpath(self.launch_data['local_installer_path']) != os.path.normpath(installer_root):
                           shutil.rmtree(self.launch_data['local_installer_path'], ignore_errors=True)
                           logging.debug(f"Локальная папка дистрибутива '{self.launch_data['local_installer_path']}' очищена после отмены.")
                 except Exception as cleanup_e:
                      logging.warning(f"Ошибка при очистке локальной папки дистрибутива '{self.launch_data['local_installer_path']}' после отмены: {cleanup_e}")

            # Останавливаем процесс BackOffice, если он был запущен и отслеживается
            self._stop_backoffice_process()


        except Exception as e:
            logging.error(f"Ошибка в LaunchWorker (шаги 4-11): {e}\n{traceback.format_exc()}")
            self._update_status("Ошибка запуска: подробности ниже.", level="ERROR")
            self._update_progress(0)
            self._update_text(f"Ошибка во время запуска:\n{traceback.format_exc()}")
            self.error.emit(str(e), traceback.format_exc())

            # Останавливаем процесс BackOffice, если он был запущен и отслеживается
            self._stop_backoffice_process()

        finally:
            # В этом finally блоке НЕ останавливаем процесс,
            # т.к. он может быть финальным запущенным процессом.
            # Остановка происходит только в блоках except или AbortOperation.
            self.finished.emit()
            logging.info("LaunchWorker завершен.")


# LaunchWorkerFromStep4 и LaunchWorkerFromStep5 теперь просто вызывают _run_from_step4 и _run_from_step5
# и наследуют логику обработки ошибок и отмены от LaunchWorker
class LaunchWorkerFromStep4(LaunchWorker):
     """Воркер для возобновления последовательности запуска с Шага 4 (после выбора типа приложения)."""
     def run(self):
         logging.info("LaunchWorkerFromStep4 запущен (продолжение с Шага 4).")
         try:
             if self._is_canceled: raise AbortOperation("Operation aborted before step 4 (resumed).")
             # Пропускаем шаги 1, 2, 3 - обновляем прогресс до конца Шага 3
             self._update_step_progress('process_response')

             # Продолжаем с Шага 4
             self._run_from_step4()

         except AbortOperation as e:
             logging.info(f"Операция отменена в LaunchWorkerFromStep4: {e}")
             self._update_status("Операция отменена.", level="INFO")
             self._update_progress(0)
             self._update_text(f"Операция отменена:\n{e}")
             self._stop_backoffice_process() # Останавливаем процесс при отмене

         except Exception as e:
             logging.error(f"Ошибка в LaunchWorkerFromStep4: {e}\n{traceback.format_exc()}")
             self._update_status("Ошибка запуска: подробности ниже.", level="ERROR")
             self._update_progress(0)
             self._update_text(f"Ошибка во время запуска:\n{traceback.format_exc()}")
             self.error.emit(str(e), traceback.format_exc())
             self._stop_backoffice_process() # Останавливаем процесс при ошибке

         finally:
             self.finished.emit()
             logging.info("LaunchWorkerFromStep4 завершен.")


class LaunchWorkerFromStep5(LaunchWorker):
     """Воркер для возобновления последовательности запуска с Шага 5 (после подтверждения состояния сервера)."""
     def run(self):
         logging.info("LaunchWorkerFromStep5 запущен (продолжение с Шага 5).")
         try:
             if self._is_canceled: raise AbortOperation("Operation aborted before step 5 (resumed).")
             # Пропускаем шаги 1, 2, 3, 4 - обновляем прогресс до конца Шага 4
             self._update_step_progress('check_state')

             # Продолжаем с Шага 5
             self._run_from_step5()

         except AbortOperation as e:
             logging.info(f"Операция отменена в LaunchWorkerFromStep5: {e}")
             self._update_status("Операция отменена.", level="INFO")
             self._update_progress(0)
             self._update_text(f"Операция отменена:\n{e}")
             self._stop_backoffice_process() # Останавливаем процесс при отмене

         except Exception as e:
             logging.error(f"Ошибка в LaunchWorkerFromStep5: {e}\n{traceback.format_exc()}")
             self._update_status("Ошибка запуска: подробности ниже.", level="ERROR")
             self._update_progress(0)
             self._update_text(f"Ошибка во время запуска:\n{traceback.format_exc()}")
             self.error.emit(str(e), traceback.format_exc())
             self._stop_backoffice_process() # Останавливаем процесс при ошибке

         finally:
             self.finished.emit()
             logging.info("LaunchWorkerFromStep5 завершен.")