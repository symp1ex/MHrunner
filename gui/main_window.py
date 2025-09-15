# gui/main_window.py
import logging
import os
import shutil
import sys
import traceback
from gui.notebook import NotebookWindow

from PyQt6.QtWidgets import (
    QMainWindow, QApplication, QWidget, QVBoxLayout,
    QGridLayout, QLabel, QLineEdit, QPushButton, QProgressBar,
    QTextEdit, QMessageBox, QSizePolicy, QInputDialog, QHBoxLayout
)
from PyQt6.QtCore import Qt, QThread, QEvent, QTimer, QProcess, QSize
from PyQt6.QtGui import QColor, QPalette, QFont, QTextOption, QIcon, QGuiApplication

from core.config import get_config_value
from utils.anydesk_utils import launch_anydesk
from utils.litemanager_utils import launch_litemanager
from utils.url_utils import find_anydesk_id, find_litemanager_id, parse_target_string
from utils.process_utils import is_anydesk_running
from workers.tasks import CheckWorker, LaunchWorker, LaunchWorkerFromStep4, LaunchWorkerFromStep5, BaseWorker


class MainWindow(QMainWindow):
    def __init__(self, config, translator, initial_target=None):
        super().__init__()

        self.config = config
        self.translator = translator
        self.initial_target = initial_target

        try:
            width = int(get_config_value(self.config, 'Settings', 'width_win', default='600'))
            height = int(get_config_value(self.config, 'Settings', 'height_win', default='290'))
        except Exception:
            width = 600
            height = 290
        
        self.setMinimumWidth(450)
        self.setMinimumHeight(220)
        self.setMaximumWidth(600)
        self.setMaximumHeight(400)
        self.resize(width, height)

        icon_path = os.path.join(os.path.dirname(sys.argv[0]), 'icon.ico')
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        else:
            logging.warning(f"Файл иконки не найден по пути: '{icon_path}'.")

        self._apply_light_palette()

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        self.main_layout = QVBoxLayout(central_widget)
        self.main_layout.setContentsMargins(15, 15, 15, 15)

        # Инициализируем все UI элементы
        self.setup_ui()
        # Применяем переводы ко всем элементам
        self.retranslateUi()

        self.worker_thread = None
        self.worker = None
        self._launch_data = {}

        if self.initial_target:
            self.target_entry.setText(self.initial_target)
            QTimer.singleShot(100, self.start_process_flow)

    def setup_ui(self):
        """Создает и размещает все виджеты в окне."""
        input_row_layout = QHBoxLayout()
        input_row_layout.setSpacing(10)

        self.lang_button = QPushButton()
        self.lang_button.setFixedSize(32, 24)
        self.lang_button.setIconSize(QSize(28, 22))
        self.lang_button.setFlat(True)
        self.lang_button.clicked.connect(self._switch_language)
        input_row_layout.addWidget(self.lang_button)

        self.notebook_button = QPushButton("📚")
        self.notebook_button.setMaximumSize(30, 30)
        input_row_layout.addWidget(self.notebook_button, 0, Qt.AlignmentFlag.AlignRight)
        self.notebook_button.clicked.connect(self.show_notebook)

        self.target_entry = QLineEdit()
        self.target_entry.returnPressed.connect(self.start_process_flow)
        self.target_entry.installEventFilter(self)
        input_row_layout.addWidget(self.target_entry, 1)

        self.paste_button = QPushButton()
        self.paste_button.clicked.connect(self.paste_from_clipboard)
        self.paste_button.setFixedWidth(105)
        input_row_layout.addWidget(self.paste_button)
        
        self.main_layout.addLayout(input_row_layout)

        grid_layout = QGridLayout()
        grid_layout.setHorizontalSpacing(10)
        grid_layout.setVerticalSpacing(8)
        grid_layout.setContentsMargins(0, 8, 0, 0)

        self.status_label = QLabel()
        self.status_label.setWordWrap(False)
        self.status_label.setTextFormat(Qt.TextFormat.RichText)
        self.status_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        grid_layout.addWidget(self.status_label, 0, 0, 1, 1)

        self.check_button = QPushButton()
        self.check_button.clicked.connect(self.start_check)
        self.check_button.setFixedWidth(105)
        grid_layout.addWidget(self.check_button, 0, 1)

        self.launch_button = QPushButton()
        self.launch_button.clicked.connect(self.start_process_flow)
        self.launch_button.setFixedWidth(105)
        grid_layout.addWidget(self.launch_button, 0, 2)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setStyleSheet("""
            QProgressBar { height: 18px; text-align: center; border: 1px solid grey; background-color: #f0f0f0; }
            QProgressBar::chunk { background-color: #28a745; width: 10px; }
        """)
        grid_layout.addWidget(self.progress_bar, 1, 0, 1, 3)

        self.main_layout.addLayout(grid_layout)

        self.json_output_text = QTextEdit()
        self.json_output_text.setReadOnly(True)
        self.json_output_text.setWordWrapMode(QTextOption.WrapMode.WordWrap)
        self.json_output_text.setFont(QFont("Consolas", 10))
        self.main_layout.addWidget(self.json_output_text)

    def retranslateUi(self):
        """Обновляет текст на всех виджетах в соответствии с текущим языком."""
        self.setWindowTitle(self.tr("Service Launcher App"))
        self.paste_button.setText(self.tr("Paste"))
        self.check_button.setText(self.tr("Check"))
        self.launch_button.setText(self.tr("Launch"))
        self.status_label.setText(self.tr("Waiting for input..."))
        # Обновляем иконку флага, так как язык мог измениться
        self._update_language_button_icon()

    def changeEvent(self, event):
        """
        Этот метод перехватывает события, происходящие с окном.
        Мы ловим событие смены языка и вызываем retranslateUi, чтобы обновить весь текст.
        """
        if event.type() == QEvent.Type.LanguageChange:
            logging.debug("Перехвачено событие смены языка. Обновление UI...")
            self.retranslateUi()
        super().changeEvent(event)

    def _update_language_button_icon(self):
        current_locale = get_config_value(self.config, 'Settings', 'Language', default='ru')
        target_locale = 'en' if current_locale == 'ru' else 'ru'
        
        script_dir = os.path.dirname(sys.argv[0])
        icon_path = os.path.join(script_dir, 'icons', f'{target_locale}.png')

        if os.path.exists(icon_path):
            self.lang_button.setIcon(QIcon(icon_path))
            self.lang_button.setText("")
        else:
            self.lang_button.setIcon(QIcon())
            self.lang_button.setText(target_locale.upper())
            logging.warning(f"Иконка для локали '{target_locale}' не найдена: {icon_path}")

    def _switch_language(self):
        """Переключает язык, сохраняет настройку и обновляет UI."""
        current_locale = get_config_value(self.config, 'Settings', 'Language', default='ru')
        target_locale = 'en' if current_locale == 'ru' else 'ru'

        # Переключаем язык с помощью нашего класса Translator
        self.translator.switch_language(target_locale)
        
        # Сохраняем новую настройку в config.ini
        self.config.set('Settings', 'Language', target_locale)
        try:
            config_path = os.path.join(os.path.dirname(sys.argv[0]), "config.ini")
            with open(config_path, 'w', encoding='utf-8') as configfile:
                self.config.write(configfile)
            logging.info(f"Язык переключен на '{target_locale}' и сохранен в конфиг.")
        except Exception as e:
            logging.error(f"Не удалось сохранить настройку языка в config.ini: {e}")
            QMessageBox.critical(self, self.tr("Error"), self.tr("Failed to save language settings."))

    def _apply_light_palette(self):
        # ... (код этой функции без изменений)
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, QColor(240, 240, 240))
        palette.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.black)
        palette.setColor(QPalette.ColorRole.Base, Qt.GlobalColor.white)
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor(230, 230, 230))
        palette.setColor(QPalette.ColorRole.ToolTipBase, Qt.GlobalColor.white)
        palette.setColor(QPalette.ColorRole.ToolTipText, Qt.GlobalColor.black)
        palette.setColor(QPalette.ColorRole.Text, Qt.GlobalColor.black)
        palette.setColor(QPalette.ColorRole.Button, QColor(220, 220, 220))
        palette.setColor(QPalette.ColorRole.ButtonText, Qt.GlobalColor.black)
        palette.setColor(QPalette.ColorRole.BrightText, Qt.GlobalColor.red)
        palette.setColor(QPalette.ColorRole.Highlight, QColor(48, 140, 198))
        palette.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.white)
        palette.setColor(QPalette.ColorGroup.Active, QPalette.ColorRole.WindowText, Qt.GlobalColor.black)
        palette.setColor(QPalette.ColorGroup.Inactive, QPalette.ColorRole.WindowText, QColor(128, 128, 128))
        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(128, 128, 128))
        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(128, 128, 128))
        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(128, 128, 128))
        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Highlight, QColor(192, 192, 192))
        QApplication.setPalette(palette)
        
    # ... (весь остальной код файла main_window.py, начиная с _update_status, остается без изменений)
    def _update_status(self, message, level="INFO"):
        color = "black"
        if level == "ERROR": color = "red"
        elif level == "WARNING": color = "orange"
        elif level == "INFO": color = "green"
        elif level == "DEBUG": color = "gray"
        self.status_label.setText(f"<span style='color:{color};'>{message}</span>")

    def _update_progress(self, value):
        self.progress_bar.setValue(value)

    def _update_text_area(self, text):
        self.json_output_text.setPlainText(text)
        self.json_output_text.verticalScrollBar().setValue(self.json_output_text.verticalScrollBar().minimum())

    def _handle_error(self, message, detailed_traceback):
        is_aborted_error = "AbortOperation" in detailed_traceback
        
        if is_aborted_error:
            self._update_status(self.tr("Operation aborted."), level="WARNING")
            self._update_text_area(self.tr("The operation was aborted by the user."))
        elif message.startswith("DISTRIBUTION_NOT_FOUND|"):
            try:
                _, app_type, version = message.split('|')
                error_text = self.tr("Distribution for server edition '{app_type}' and version '{version}' could not be found for installation.").format(app_type=app_type, version=version)
                self._update_text_area(self.tr("An error has occurred:") + f"\n{error_text}")
                self._update_status(self.tr("Error: Distribution not found."), level="ERROR")
            except Exception as e:
                logging.error(f"Ошибка парсинга сообщения DISTRIBUTION_NOT_FOUND: {e}")
                self._update_text_area(self.tr("An error has occurred:") + f"\n{message}")
        else:
            self._update_status(self.tr("Error during operation: details below."), level="ERROR")
            self._update_text_area(self.tr("An error has occurred:") + f"\n{message}")

        self._update_progress(0)

    def _request_dialog(self, dialog_type, title, message, options, callback_data):
        logging.debug(f"GUI получил запрос на диалог: {dialog_type}")
        self.check_button.setEnabled(False)

        result = None
        if dialog_type == 'app_type':
            reply = QMessageBox.question(self, self.tr(title), self.tr(message),
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                         QMessageBox.StandardButton.Yes)
            if reply == QMessageBox.StandardButton.Yes: result = options[0]
            elif reply == QMessageBox.StandardButton.No: result = options[1]
            else: result = None
            self._handle_app_type_dialog_result(result, callback_data)
        elif dialog_type == 'server_state_confirm':
            reply = QMessageBox.question(self, self.tr(title), self.tr(message),
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                         QMessageBox.StandardButton.Yes)
            self._handle_server_state_confirm_dialog_result(reply == QMessageBox.StandardButton.Yes, callback_data)
        else:
            logging.error(f"Получен запрос на неизвестный тип диалога: {dialog_type}")
            error_msg = self.tr("Internal error: unknown dialog type '{dialog_type}'.").format(dialog_type=dialog_type)
            self._handle_error(error_msg, f"Неизвестный тип диалога запрошен воркером: {dialog_type}")
            if isinstance(self.worker, BaseWorker):
                 self.worker.cancel()

    def _handle_app_type_dialog_result(self, selected_option, launch_data):
        logging.debug(f"Обработка результата диалога выбора типа приложения: '{selected_option}'")
        if selected_option is None:
            logging.info("Выбор типа приложения отменен пользователем.")
            if isinstance(self.worker, BaseWorker): self.worker.cancel()
            return
        vendor = "iiko"
        if "syrve" in launch_data.get('target_string', '').lower(): vendor = "Syrve"
        if selected_option == 'RMS': launch_data['app_type'] = f"{vendor}RMS"
        elif selected_option == 'Chain': launch_data['app_type'] = f"{vendor}Chain"
        else:
            error_msg = self.tr("Unexpected result from app type dialog: '{selected_option}'.").format(selected_option=selected_option)
            self._handle_error(error_msg, f"Диалог выбора типа приложения вернул неожиданный результат: {selected_option}")
            if isinstance(self.worker, BaseWorker): self.worker.cancel()
            return
        launch_data['vendor'] = vendor
        logging.info(f"Пользователь выбрал тип приложения: '{launch_data['app_type']}'. Перезапуск воркера с Шага 4.")
        self._update_status(self.tr("Continuing launch (type selected: {app_type})").format(app_type=launch_data['app_type']))
        self._start_worker(LaunchWorkerFromStep4, launch_data)

    def _handle_server_state_confirm_dialog_result(self, confirmed, launch_data):
        logging.debug(f"Обработка результата диалога подтверждения состояния сервера: {confirmed}")
        if confirmed:
            logging.info("Пользователь подтвердил продолжение запуска. Перезапуск воркера с Шага 5.")
            self._update_status(self.tr("Continuing launch at user's request."))
            self._start_worker(LaunchWorkerFromStep5, launch_data)
        else:
            logging.info("Запуск отменен по запросу пользователя (состояние сервера).")
            if isinstance(self.worker, BaseWorker): self.worker.cancel()

    def _enable_buttons(self):
        self.launch_button.setEnabled(True)
        self.target_entry.setEnabled(True)
        self.paste_button.setEnabled(True)

    def _disable_buttons(self):
        self.launch_button.setEnabled(False)
        self.target_entry.setEnabled(False)
        self.paste_button.setEnabled(False)

    def _set_check_button_to_check(self):
        self.check_button.setText(self.tr("Check"))
        try: self.check_button.clicked.disconnect(self.abort_process)
        except TypeError: pass
        try: self.check_button.clicked.connect(self.start_check)
        except TypeError: pass
        self.check_button.setEnabled(True)

    def _set_check_button_to_abort(self):
        self.check_button.setText(self.tr("Abort"))
        try: self.check_button.clicked.disconnect(self.start_check)
        except TypeError: pass
        try: self.check_button.clicked.connect(self.abort_process)
        except TypeError: pass
        self.check_button.setEnabled(True)

    def _start_worker(self, worker_class, data):
        self.worker_thread = QThread()
        self.worker_thread.setObjectName(f"{worker_class.__name__}Thread")
        self.worker = worker_class(self.config, data)
        self.worker.moveToThread(self.worker_thread)
        self.worker.status_update.connect(self._update_status)
        self.worker.progress_update.connect(self._update_progress)
        self.worker.text_update.connect(self._update_text_area)
        self.worker.error.connect(self._handle_error)
        self.worker.dialog_request.connect(self._request_dialog)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)
        self.worker_thread.finished.connect(self._worker_finished)
        self.worker_thread.started.connect(self.worker.run)
        self._disable_buttons()
        self._set_check_button_to_abort()
        self.worker_thread.start()
        logging.info(f"Запущен новый воркер: {worker_class.__name__} в потоке {self.worker_thread.objectName()}")

    def _worker_finished(self):
        logging.info("GUI получил сигнал worker_thread.finished.")
        self.worker = None
        self.worker_thread = None
        logging.debug("Ссылки self.worker и self.worker_thread обнулены.")
        logging.info("Возврат UI в исходное состояние.")
        self._enable_buttons()
        self._set_check_button_to_check()

    def start_process_flow(self):
        target_string = self.target_entry.text().strip()
        if not target_string:
            self._update_status(self.tr("Enter a URL or an LM/AnyDesk ID."), level="WARNING")
            return

        self._update_text_area("")
        self._update_progress(0)

        modifiers = QGuiApplication.keyboardModifiers()
        ctrl_is_pressed = modifiers & Qt.KeyboardModifier.ControlModifier
        logging.debug(f"Ctrl нажат?: {bool(ctrl_is_pressed)}")

        litemanager_id = find_litemanager_id(self.config, target_string)
        if litemanager_id:
            self._handle_litemanager_flow(litemanager_id)
            return

        anydesk_id = find_anydesk_id(target_string)
        if anydesk_id:
            self._handle_anydesk_flow(anydesk_id, bool(ctrl_is_pressed))
            return

        if self.worker_thread is not None and self.worker_thread.isRunning():
             self._update_status(self.tr("An operation is already in progress. Please wait."), level="WARNING")
             return

        self._update_status(self.tr("Parsing the entered address..."), level="INFO")

        try:
            parsed_target_data = parse_target_string(target_string)
            if parsed_target_data is None or not parsed_target_data.get('UrlOrIp'):
                self._update_status(self.tr("Invalid input: Failed to parse the address."), level="ERROR")
                logging.error(f"Ошибка парсинга введенной строки: '{target_string}'.")
                self._update_progress(0)
                return
            self._launch_data = {
                'target_string': target_string,
                'parsed_target': parsed_target_data,
                'config_protocol': parsed_target_data['Scheme']
            }
        except Exception as e:
            logging.error(f"Неожиданная ошибка при предварительном парсинге строки '{target_string}': {e}\n{traceback.format_exc()}")
            self._update_status(self.tr("Invalid input: Parsing error ({error}).").format(error=e), level="ERROR")
            self._update_progress(0)
            return

        self._start_worker(LaunchWorker, self._launch_data)

    def _handle_anydesk_flow(self, anydesk_id, ctrl_pressed):
        self._update_status(self.tr("AnyDesk ID found: {anydesk_id}. Preparing...").format(anydesk_id=anydesk_id), level="INFO")
        self._update_progress(10)

        anydesk_is_running = is_anydesk_running()
        should_clean = not anydesk_is_running and ctrl_pressed
        if should_clean:
            anydesk_appdata_path = os.path.join(os.getenv('APPDATA'), 'AnyDesk')
            self._update_status(self.tr("Clearing AnyDesk cache..."), level="INFO")
            self._update_progress(20)
            if os.path.exists(anydesk_appdata_path):
                try:
                    shutil.rmtree(anydesk_appdata_path)
                    self._update_status(self.tr("AnyDesk cache cleared."), level="INFO")
                    self._update_progress(30)
                except Exception as e:
                    error_msg = self.tr("Error removing AnyDesk cache folder '{path}': {error}").format(path=anydesk_appdata_path, error=e)
                    self._update_status(error_msg, level="ERROR")
                    self._update_text_area(self.tr("Error clearing AnyDesk cache:") + f"\n{error_msg}")
            else:
                self._update_status(self.tr("AnyDesk cache not found, no cleanup required."), level="INFO")
                self._update_progress(30)
        else:
            self._update_status(self.tr("AnyDesk cache cleanup skipped."), level="WARNING")
            self._update_progress(30)

        self._update_status(self.tr("AnyDesk ID: {anydesk_id}. Requesting password...").format(anydesk_id=anydesk_id), level="INFO")
        self._update_progress(40)
        self._disable_buttons()

        password, accepted = QInputDialog.getText(
            self,
            self.tr("AnyDesk: Enter Password"),
            self.tr("Enter the password to connect to ID {anydesk_id}:").format(anydesk_id=anydesk_id),
            QLineEdit.EchoMode.Password
        )
        self._enable_buttons()
        self._set_check_button_to_check()

        if accepted and password:
            self._update_status(self.tr("Launching AnyDesk for {anydesk_id}...").format(anydesk_id=anydesk_id), level="INFO")
            self._update_progress(50)
            anydesk_path = get_config_value(self.config, 'Settings', 'AnyDeskPath')
            if not anydesk_path or not os.path.exists(anydesk_path):
                 error_msg = self.tr("Error: Path to AnyDesk.exe is not specified in config.ini or the file was not found: '{path}'").format(path=anydesk_path)
                 self._update_status(error_msg, level="ERROR")
                 self._update_text_area(self.tr("Error launching AnyDesk:") + f"\n{error_msg}")
                 self._update_progress(0)
                 return
            try:
                pid = launch_anydesk(anydesk_path, anydesk_id, password)
                self._update_status(self.tr("AnyDesk launched for {anydesk_id} (PID: {pid}).").format(anydesk_id=anydesk_id, pid=pid), level="INFO")
                self._update_text_area(self.tr("AnyDesk successfully launched for ID {anydesk_id}.\nProcess PID: {pid}").format(anydesk_id=anydesk_id, pid=pid))
                self._update_progress(100)
            except Exception as e:
                error_msg = self.tr("Error launching AnyDesk: {error}").format(error=e)
                self._update_status(error_msg, level="ERROR")
                self._update_text_area(self.tr("Error launching AnyDesk:") + f"\n{error_msg}")
                self._update_progress(0)
        elif accepted and not password:
             self._update_status(self.tr("AnyDesk launch canceled: no password entered."), level="WARNING")
             self._update_text_area(self.tr("AnyDesk launch canceled: a password was not provided."))
             self._update_progress(0)
        else:
            self._update_status(self.tr("AnyDesk launch canceled by user."), level="WARNING")
            self._update_text_area(self.tr("AnyDesk launch canceled by user."))
            self._update_progress(0)

    def _handle_litemanager_flow(self, lm_id):
        self._update_status(self.tr("LiteManager ID found: {lm_id}. Preparing...").format(lm_id=lm_id), level="INFO")
        self._update_progress(10)
        self._update_text_area(self.tr("LiteManager ID detected: {lm_id}. Please enter the password to connect.").format(lm_id=lm_id))
        self._update_status(self.tr("LiteManager ID: {lm_id}. Requesting password...").format(lm_id=lm_id), level="INFO")
        self._update_progress(40)
        self._disable_buttons()

        password, accepted = QInputDialog.getText(
            self,
            self.tr("LiteManager: Enter Password"),
            self.tr("Enter the password to connect to ID {lm_id}:").format(lm_id=lm_id),
            QLineEdit.EchoMode.Password
        )
        self._enable_buttons()
        self._set_check_button_to_check()

        if accepted and password:
            self._update_status(self.tr("Launching LiteManager for {lm_id}...").format(lm_id=lm_id), level="INFO")
            self._update_progress(50)
            lm_path = get_config_value(self.config, 'Settings', 'LiteManagerPath')
            if not lm_path or not os.path.exists(lm_path):
                 error_msg = self.tr("Error: Path to ROMViewer.exe is not specified in config.ini or the file was not found: '{path}'").format(path=lm_path)
                 self._update_status(error_msg, level="ERROR")
                 self._update_text_area(self.tr("Error launching LiteManager:") + f"\n{error_msg}")
                 self._update_progress(0)
                 return
            try:
                pid = launch_litemanager(lm_path, lm_id, password)
                self._update_status(self.tr("LiteManager launched for {lm_id} (PID: {pid}).").format(lm_id=lm_id, pid=pid), level="INFO")
                self._update_text_area(self.tr("LiteManager successfully launched for ID {lm_id}.\nProcess PID: {pid}").format(lm_id=lm_id, pid=pid))
                self._update_progress(100)
            except Exception as e:
                error_msg = self.tr("Error launching LiteManager: {error}").format(error=e)
                self._update_status(error_msg, level="ERROR")
                self._update_text_area(self.tr("Error launching LiteManager:") + f"\n{error_msg}")
                self._update_progress(0)
        elif accepted and not password:
             self._update_status(self.tr("LiteManager launch canceled: no password entered."), level="WARNING")
             self._update_text_area(self.tr("LiteManager launch canceled: a password was not provided."))
             self._update_progress(0)
        else:
            self._update_status(self.tr("LiteManager launch canceled by user."), level="WARNING")
            self._update_text_area(self.tr("LiteManager launch canceled by user."))
            self._update_progress(0)

    def start_check(self):
        target_string = self.target_entry.text().strip()
        if not target_string:
            self._update_status(self.tr("Enter a URL or IP:port to check."), level="WARNING")
            return

        if find_litemanager_id(self.config, target_string) or find_anydesk_id(target_string):
            self._update_text_area("")
            self._update_status(self.tr("Invalid request"), level="WARNING")
            self._update_progress(0)
            return

        if self.worker_thread is not None and self.worker_thread.isRunning():
             self._update_status(self.tr("An operation is already in progress. Please wait."), level="WARNING")
             return
        
        self._update_text_area("")
        self._update_status(self.tr("Performing server check..."))
        self._update_progress(0)
        self._start_worker(CheckWorker, target_string)

    def abort_process(self):
        logging.info("Нажата кнопка 'Abort'. Попытка прервать операцию.")
        self.check_button.setEnabled(False)
        self._update_status(self.tr("Aborting operation..."), level="WARNING")

        if self.worker is not None and isinstance(self.worker, BaseWorker) and self.worker_thread is not None and self.worker_thread.isRunning():
             self.worker.cancel()
        else:
             logging.debug("Кнопка Abort нажата, но нет активного воркера.")
             self._enable_buttons()
             self._set_check_button_to_check()

    def paste_from_clipboard(self):
        clipboard = QApplication.clipboard()
        clipboard_content = clipboard.text()

        if clipboard_content and clipboard_content.strip():
            truncated_content = clipboard_content.strip()[:100]
            self.target_entry.clear()
            self.target_entry.setText(truncated_content)
            self._update_status(self.tr("Waiting for input..."))
        else:
            self._update_status(self.tr("Clipboard is empty or contains non-text data."), level="WARNING")

    def closeEvent(self, event):
        if self.worker_thread is not None and self.worker_thread.isRunning():
            reply = QMessageBox.question(self, self.tr("Exit"),
                                         self.tr("An operation is in progress. Abort and exit?"),
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                         QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                if isinstance(self.worker, BaseWorker):
                     self.worker.cancel()
                if not self.worker_thread.wait(5000):
                     self.worker_thread.terminate()
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()

    def eventFilter(self, obj, event):
        if obj is self.target_entry and event.type() == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.MiddleButton:
                self.paste_from_clipboard()
                return True
        return super().eventFilter(obj, event)

    def show_notebook(self):
        """Открывает окно книжки подключений"""
        notebook_window = NotebookWindow(self)
        notebook_window.connection_selected.connect(self.handle_notebook_selection)
        notebook_window.exec()

    def handle_notebook_selection(self, connection_id):
        """Обрабатывает выбор подключения из книжки"""
        self.target_entry.setText(connection_id)
        self.start_process_flow()