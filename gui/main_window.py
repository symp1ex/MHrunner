import logging
import os
import shutil
import sys
import traceback

from PyQt6.QtWidgets import (
    QMainWindow, QApplication, QWidget, QVBoxLayout,
    QGridLayout, QLabel, QLineEdit, QPushButton, QProgressBar,
    QTextEdit, QMessageBox, QSizePolicy, QInputDialog
)
from PyQt6.QtCore import Qt, QThread, QEvent, QTimer
from PyQt6.QtGui import QColor, QPalette, QFont, QTextOption, QIcon, QGuiApplication

# Импортируем модули с логикой и воркерами
from core.config import get_config_value
from utils.anydesk_utils import launch_anydesk
from utils.litemanager_utils import launch_litemanager
from utils.url_utils import find_anydesk_id, find_litemanager_id, parse_target_string
from utils.process_utils import is_anydesk_running
from workers.tasks import CheckWorker, LaunchWorker, LaunchWorkerFromStep4, LaunchWorkerFromStep5, BaseWorker


class MainWindow(QMainWindow):
    def __init__(self, config, initial_target=None):
        super().__init__()

        self.config = config
        self.initial_target = initial_target

        self.setWindowTitle("Service Launcher App")
        # Устанавливаем фиксированную ширину, но оставляем возможность растягивать по вертикали
        self.setFixedWidth(600)
        self.setMinimumHeight(290) # Минимальная высота
        self.resize(600, 290)  # ширина = 800, высота = 600

        icon_path = os.path.join(os.path.dirname(sys.argv[0]), 'icon.ico')
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
            logging.debug(f"Иконка окна установлена из файла: '{icon_path}'")
        else:
            logging.warning(f"Файл иконки не найден по пути: '{icon_path}'. Иконка окна не установлена.")

        # Применяем светлую палитру
        self._apply_light_palette()


        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(15, 15, 15, 15)

        input_layout = QGridLayout()
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.setHorizontalSpacing(10) # Горизонтальные отступы между элементами в сетке
        input_layout.setVerticalSpacing(8) # Вертикальные отступы

        # Строка 0: Метка и поле ввода
        input_layout.addWidget(QLabel("Enter URL or ID"), 0, 0, alignment=Qt.AlignmentFlag.AlignLeft)
        self.target_entry = QLineEdit()
        input_layout.addWidget(self.target_entry, 0, 1, 1, 2) # Поле ввода занимает 2 колонки
        self.target_entry.returnPressed.connect(self.start_process_flow)
        self.target_entry.installEventFilter(self) # Устанавливаем фильтр событий для вставки по средней кнопке

        self.paste_button = QPushButton("Paste")
        input_layout.addWidget(self.paste_button, 0, 3) # Кнопка Paste в 3 колонке
        self.paste_button.clicked.connect(self.paste_from_clipboard)

        # Строка 1: Статус, Check/Abort, Launch
        self.status_label = QLabel("Ожидание ввода...")
        self.status_label.setWordWrap(False) # Отключаем перенос строк
        self.status_label.setTextFormat(Qt.TextFormat.RichText)
        self.status_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred) # Метка статуса может растягиваться по горизонтали
        input_layout.addWidget(self.status_label, 1, 0, 1, 2, alignment=Qt.AlignmentFlag.AlignLeft) # Метка статуса занимает 2 колонки

        self.check_button = QPushButton("Check")
        input_layout.addWidget(self.check_button, 1, 2) # Кнопка Check во 2 колонке
        self.check_button.clicked.connect(self.start_check)

        self.launch_button = QPushButton("Launch")
        input_layout.addWidget(self.launch_button, 1, 3) # Кнопка Launch в 3 колонке
        self.launch_button.clicked.connect(self.start_process_flow)

        # Строка 2: Прогресс бар
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        # Применяем QSS для увеличения высоты
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                height: 18px; /* Увеличиваем высоту */
                text-align: center; /* Выравниваем текст по центру */
                border: 1px solid grey;
                background-color: #f0f0f0; /* Светлый фон для незаполненной части */
            }
            QProgressBar::chunk {
                background-color: #28a745; /* Зеленый цвет заполненной части */
                width: 10px; /* Ширина "кусочка", влияет на анимацию */
            }
        """)
        input_layout.addWidget(self.progress_bar, 2, 0, 1, 4) # Прогресс бар занимает все 4 колонки

        main_layout.addLayout(input_layout)

        self.json_output_text = QTextEdit()
        self.json_output_text.setReadOnly(True)
        self.json_output_text.setWordWrapMode(QTextOption.WrapMode.WordWrap)
        self.json_output_text.setFont(QFont("Consolas", 10))
        main_layout.addWidget(self.json_output_text)

        self.worker_thread = None
        self.worker = None
        self._launch_data = {}


        if self.initial_target:
            self.target_entry.setText(self.initial_target)
            # Использование QTimer.singleShot для отложенного запуска
            # дает GUI время инициализироваться перед запуском задачи
            QTimer.singleShot(100, self.start_launch)

    def _apply_light_palette(self):
        """Применяет стандартную светлую палитру к приложению."""
        palette = QPalette()
        # Устанавливаем основные цвета для светлой темы
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

        # Устанавливаем палитру для всего приложения
        QApplication.setPalette(palette)


    def _update_status(self, message, level="INFO"):
        """Обновляет текст статус-метки с цветом в зависимости от уровня."""
        color = "black"
        if level == "ERROR":
            color = "red"
        elif level == "WARNING":
            color = "orange"
        elif level == "INFO":
            color = "green"
        elif level == "DEBUG":
             color = "gray"

        self.status_label.setText(f"<span style='color:{color};'>{message}</span>")

    def _update_progress(self, value):
        """Обновляет значение прогресс-бара."""
        self.progress_bar.setValue(value)

    def _update_text_area(self, text):
        """Обновляет текст в текстовой области и прокручивает вверх."""
        self.json_output_text.setPlainText(text)
        # Прокручиваем к началу
        self.json_output_text.verticalScrollBar().setValue(self.json_output_text.verticalScrollBar().minimum())


    def _handle_error(self, message, detailed_traceback):
        """Слот для обработки ошибок из потока."""
        # Логируем полную информацию об ошибке для отладки


        # Проверяем, является ли ошибка пользовательской отменой
        is_aborted_error = "AbortOperation" in detailed_traceback

        if is_aborted_error:
             # Если это ошибка из-за отмены, выводим краткое сообщение в статус
             self._update_status("Операция прервана.", level="WARNING")
             # В текстовое поле выводим сообщение об отмене без полного трейсбека
             self._update_text_area("Операция была прервана пользователем.")
             # Можно опционально добавить message, если он содержит полезную инфу об отмене
             # self._update_text_area(f"Операция была прервана пользователем.\n{message}")
        else:
             # Если это другая ошибка, выводим подробности в статус и краткое сообщение в текстовую область
             self._update_status("Ошибка при работе: подробности ниже.", level="ERROR")
             # В текстовое поле выводим только краткое сообщение об ошибке (message)
             # message уже содержит тип исключения и его текст, как в примере пользователя
             self._update_text_area(f"Произошла ошибка:\n{message}")


        self._update_progress(0)
        # Кнопки будут включены в _worker_finished


    def _request_dialog(self, dialog_type, title, message, options, callback_data):
        """Слот для обработки запросов на диалоги от воркера."""
        logging.debug(f"GUI получил запрос на диалог: {dialog_type}")
        # Отключаем кнопку "Abort" пока открыт диалог, чтобы избежать двойной логики отмены
        # Кнопки Launch/Paste/Entry уже отключены в _start_worker
        self.check_button.setEnabled(False)

        result = None
        if dialog_type == 'app_type':
            # Используем StandardButton.Yes и StandardButton.No как 'RMS' и 'Chain'
            reply = QMessageBox.question(self, title, message,
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                         QMessageBox.StandardButton.Yes) # По умолчанию Yes (RMS)

            if reply == QMessageBox.StandardButton.Yes:
                result = options[0] # 'RMS'
            elif reply == QMessageBox.StandardButton.No:
                result = options[1] # 'Chain'
            else:
                 # Если пользователь закрыл диалог другим способом (например, крестиком)
                 result = None # Сигнализируем об отмене

            self._handle_app_type_dialog_result(result, callback_data)

        elif dialog_type == 'server_state_confirm':
            reply = QMessageBox.question(self, title, message,
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                         QMessageBox.StandardButton.Yes) # По умолчанию Yes (Продолжить)

            # Результат - булево: True если Yes, False если No или закрыто
            self._handle_server_state_confirm_dialog_result(reply == QMessageBox.StandardButton.Yes, callback_data)

        else:
            logging.error(f"Получен запрос на неизвестный тип диалога: {dialog_type}")
            # Обрабатываем как ошибку, которая должна прервать воркер
            error_msg = f"Внутренняя ошибка: неизвестный тип диалога '{dialog_type}'."
            self._handle_error(error_msg, f"Неизвестный тип диалога запрошен воркером: {dialog_type}")
            # Отправляем сигнал отмены текущему воркеру, чтобы он завершился
            if isinstance(self.worker, BaseWorker):
                 self.worker.cancel()


        # Кнопки будут включены в _worker_finished после завершения воркера (или перезапущены в _handle_..._result)


    def _handle_app_type_dialog_result(self, selected_option, launch_data):
        logging.debug(f"Обработка результата диалога выбора типа приложения: '{selected_option}'")
        if selected_option is None:
            logging.info("Выбор типа приложения отменен пользователем.")
            # Отправляем сигнал отмены текущему воркеру
            if isinstance(self.worker, BaseWorker):
                 self.worker.cancel()
            # _handle_error будет вызван воркером, когда он поймает AbortOperation
            return

        vendor = "iiko"
        # Проверяем target_string, которая сохранена в launch_data
        if "syrve" in launch_data.get('target_string', '').lower():
             vendor = "Syrve"

        if selected_option == 'RMS':
            launch_data['app_type'] = f"{vendor}RMS"
        elif selected_option == 'Chain':
            launch_data['app_type'] = f"{vendor}Chain"
        else:
             logging.error(f"Неожиданный результат диалога выбора типа приложения: '{selected_option}'")
             # Обрабатываем как ошибку, которая должна прервать воркер
             error_msg = f"Неожиданный результат диалога выбора типа приложения: '{selected_option}'."
             self._handle_error(error_msg, f"Диалог выбора типа приложения вернул неожиданный результат: {selected_option}")
             # Отправляем сигнал отмены текущему воркеру
             if isinstance(self.worker, BaseWorker):
                  self.worker.cancel()
             return

        launch_data['vendor'] = vendor

        logging.info(f"Пользователь выбрал тип приложения: '{launch_data['app_type']}'. Перезапуск воркера с Шага 4.")
        self._update_status(f"Продолжение запуска (выбран тип: {launch_data['app_type']})...")

        # Перезапускаем воркер с нужного шага с обновленными данными
        self._start_worker(LaunchWorkerFromStep4, launch_data)


    def _handle_server_state_confirm_dialog_result(self, confirmed, launch_data):
        logging.debug(f"Обработка результата диалога подтверждения состояния сервера: {confirmed}")
        if confirmed:
            logging.info("Пользователь подтвердил продолжение запуска. Перезапуск воркера с Шага 5.")
            self._update_status("Продолжение запуска по запросу пользователя.")
            # Перезапускаем воркер с нужного шага с обновленными данными
            self._start_worker(LaunchWorkerFromStep5, launch_data)
        else:
            logging.info("Запуск отменен по запросу пользователя (состояние сервера).")
            # Отправляем сигнал отмены текущему воркеру
            if isinstance(self.worker, BaseWorker):
                 self.worker.cancel()
            # _handle_error будет вызван воркером, когда он поймает AbortOperation
            # _handle_error("Запуск отменен по запросу пользователя.", "Пользователь отменил запуск из-за состояния сервера.")


    def _enable_buttons(self):
        """Включает кнопки и поле ввода."""
        self.launch_button.setEnabled(True)
        self.target_entry.setEnabled(True)
        self.paste_button.setEnabled(True)
        # Кнопка Check/Abort управляется отдельно в _set_check_button_to_check/_set_check_button_to_abort
        # self.check_button.setEnabled(True)

    def _disable_buttons(self):
        """Отключает кнопки и поле ввода."""
        self.launch_button.setEnabled(False)
        self.target_entry.setEnabled(False)
        self.paste_button.setEnabled(False)
        # Кнопка Check/Abort управляется отдельно
        # self.check_button.setEnabled(False)


    def _set_check_button_to_check(self):
        """Настраивает кнопку Check/Abort в режим Check."""
        self.check_button.setText("Check")
        # Отсоединяем старый слот (если был присоединен)
        try: self.check_button.clicked.disconnect(self.abort_process)
        except TypeError: pass # Игнорируем ошибку, если слот не был присоединен
        # Присоединяем новый слот
        try: self.check_button.clicked.connect(self.start_check)
        except TypeError: pass # Игнорируем ошибку, если слот уже присоединен (не должно быть)
        self.check_button.setEnabled(True) # Включаем кнопку

    def _set_check_button_to_abort(self):
        """Настраивает кнопку Check/Abort в режим Abort."""
        self.check_button.setText("Abort")
        # Отсоединяем старый слот (если был присоединен)
        try: self.check_button.clicked.disconnect(self.start_check)
        except TypeError: pass # Игнорируем ошибку, если слот не был присоединен
        # Присоединяем новый слот
        try: self.check_button.clicked.connect(self.abort_process)
        except TypeError: pass # Игнорируем ошибку, если слот уже присоединен (не должно быть)
        self.check_button.setEnabled(True) # Включаем кнопку


    def _start_worker(self, worker_class, data):
        """
        Запускает новый воркер в отдельном потоке.
        Предполагается, что вызывающий код (start_process_flow, start_check)
        уже проверил, что воркер-поток свободен.
        """
        # Сначала пытаемся корректно завершить предыдущий воркер, если он есть.
        # self._cleanup_worker()

        # Создаем новый поток и воркер
        self.worker_thread = QThread()
        # Устанавливаем имя потока для удобства отладки (необязательно)
        self.worker_thread.setObjectName(f"{worker_class.__name__}Thread")

        self.worker = worker_class(self.config, data)
        # Перемещаем воркер в новый поток
        self.worker.moveToThread(self.worker_thread)

        # Соединяем сигналы воркера со слотами в главном потоке (MainWindow)
        self.worker.status_update.connect(self._update_status)
        self.worker.progress_update.connect(self._update_progress)
        self.worker.text_update.connect(self._update_text_area)
        self.worker.error.connect(self._handle_error)
        self.worker.dialog_request.connect(self._request_dialog)

        # Соединяем сигналы завершения для корректной очистки
        # Когда воркер закончит работу (успешно или с ошибкой), он отправит finished
        self.worker.finished.connect(self.worker_thread.quit) # Останавливаем цикл событий потока
        self.worker.finished.connect(self.worker.deleteLater) # Планируем удаление воркера
        # Когда поток завершит работу после quit()
        self.worker_thread.finished.connect(self.worker_thread.deleteLater) # Планируем удаление потока
        self.worker_thread.finished.connect(self._worker_finished) # Вызываем слот для финальной очистки GUI

        # Подключаем запуск метода run воркера к старту потока
        self.worker_thread.started.connect(self.worker.run)

        # Отключаем кнопки ввода и запуска, меняем текст кнопки Check на Abort
        self._disable_buttons()
        self._set_check_button_to_abort()

        # Запускаем поток
        self.worker_thread.start()
        logging.info(f"Запущен новый воркер: {worker_class.__name__} в потоке {self.worker_thread.objectName()}")


    def _worker_finished(self):
        """Слот, вызываемый, когда worker_thread завершает работу."""
        logging.info("GUI получил сигнал worker_thread.finished.")
        self.worker = None
        self.worker_thread = None
        logging.debug("Ссылки self.worker и self.worker_thread обнулены.")

        # Включаем кнопки и возвращаем кнопку Abort в состояние Check
        logging.info("Возврат UI в исходное состояние.")
        self._enable_buttons()
        self._set_check_button_to_check()

        # Очищаем ссылки на воркер и поток после их завершения и планирования удаления
        # Это безопасно делать здесь, т.к. сигнал finished потока гарантирует, что объекты
        # worker и worker_thread уже получили команду deleteLater и скоро будут удалены.
 

    def start_process_flow(self):
        """
        Определяет, запускать ли Anydesk или последовательность BackOffice,
        основываясь на введенной строке.
        Подключена к кнопке Launch и сигналу returnPressed поля ввода.
        Проверяет состояние клавиши Ctrl.
        Проверяет, свободен ли воркер-поток перед запуском BackOffice flow.
        """
        target_string = self.target_entry.text().strip()
        if not target_string:
            self._update_status("Введите URL или LM\AnyDesk ID.", level="WARNING")
            return

        self._update_text_area("") # Очищаем текстовую область
        self._update_progress(0)

        # --- Проверка состояния клавиши Ctrl ---
        # Используем QGuiApplication для доступа к состоянию клавиатуры
        modifiers = QGuiApplication.keyboardModifiers()
        ctrl_is_pressed = modifiers & Qt.KeyboardModifier.ControlModifier
        logging.debug(f"Ctrl нажат?: {bool(ctrl_is_pressed)}")

        litemanager_id = find_litemanager_id(self.config, target_string)

        if litemanager_id:
            logging.info(f"Обнаружен потенциальный LiteManager ID: '{litemanager_id}'. Запуск LiteManager flow.")
            self._handle_litemanager_flow(litemanager_id)
            return # Завершаем функцию

        anydesk_id = find_anydesk_id(target_string)

        if anydesk_id:
            logging.info(f"Обнаружен потенциальный AnyDesk ID: '{anydesk_id}'. Запуск Anydesk flow.")
            self._handle_anydesk_flow(anydesk_id, bool(ctrl_is_pressed))
            return # Завершаем функцию

        logging.info("ID не обнаружен. Запуск BackOffice flow.")
        
        if self.worker_thread is not None and self.worker_thread.isRunning():
             logging.warning("Воркер-поток занят. Невозможно запустить новую BackOffice операцию.")
             self._update_status("Операция уже выполняется. Пожалуйста, подождите.", level="WARNING")
             return # Прерываем функцию, не запускаем новый воркер

        self._update_status("Парсинг введенного адреса...", level="INFO")

        # --- Предварительный парсинг перед запуском воркера ---
        try:
            parsed_target_data = parse_target_string(target_string)
            if parsed_target_data is None or not parsed_target_data.get('UrlOrIp'):
                # Если парсинг не удался, выводим ошибку и останавливаемся
                self._update_status("Invalid input: Не удалось распарсить адрес.", level="ERROR")
                logging.error(f"Ошибка парсинга введенной строки: '{target_string}'. parse_target_string вернул None.")
                self._update_progress(0)
                return # Прерываем функцию, воркер не запускается

            # Сохраняем результат парсинга и определенную схему для конфига
            self._launch_data = {
                'target_string': target_string,
                'parsed_target': parsed_target_data,
                'config_protocol': parsed_target_data['Scheme'] # Сохраняем схему из парсера
            }
            logging.debug(f"Предварительный парсинг успешен. Данные для запуска: {self._launch_data}")

        except Exception as e:
            # Ловим любые другие ошибки при предварительном парсинге
            logging.error(f"Неожиданная ошибка при предварительном парсинге строки '{target_string}': {e}\n{traceback.format_exc()}")
            self._update_status(f"Invalid input: Ошибка парсинга ({e}).", level="ERROR")
            self._update_progress(0)
            return # Прерываем функцию, воркер не запускается
        # --- Конец предварительного парсинга ---


        # Если предварительный парсинг успешен, запускаем воркер BackOffice.
        # LaunchWorker использует переданные parsed_target и config_protocol
        # на Шаге 1 вместо повторного парсинга target_string.
        self._start_worker(LaunchWorker, self._launch_data)


    def _handle_anydesk_flow(self, anydesk_id, ctrl_pressed):
        """
        Обрабатывает последовательность запуска Anydesk:
        Проверка процесса (если Anydesk не запущен И Ctrl нажат), очистка папки, запрос пароля и запуск.
        """
        self._update_status(f"Найден AnyDesk ID: {anydesk_id}. Подготовка...", level="INFO")
        self._update_progress(10) # Начальный прогресс для Anydesk flow

        # --- Проверка процесса Anydesk и очистка папки (ТОЛЬКО если процесс НЕ запущен И Ctrl нажат) ---
        anydesk_is_running = is_anydesk_running()
        logging.info(f"Процесс Anydesk запущен: {anydesk_is_running}. Ctrl нажат: {ctrl_pressed}")

        # Условие для очистки папки: AnyDesk НЕ запущен И Ctrl нажат
        should_clean = not anydesk_is_running and ctrl_pressed

        if should_clean:
            anydesk_appdata_path = os.path.join(os.getenv('APPDATA'), 'AnyDesk')
            logging.info(f"Процесс Anydesk не запущен и Ctrl нажат. Попытка удаления папки кэша: '{anydesk_appdata_path}'")
            self._update_status("Очистка кэша AnyDesk...", level="INFO")
            self._update_progress(20) # Прогресс после проверки, перед очисткой

            if os.path.exists(anydesk_appdata_path):
                try:
                    shutil.rmtree(anydesk_appdata_path, ignore_errors=False) # Не игнорируем ошибки
                    logging.info("Папка кэша Anydesk успешно удалена.")
                    self._update_status("Кэш AnyDesk очищен.", level="INFO")
                    self._update_progress(30) # Прогресс после успешной очистки
                except Exception as e:
                    error_msg = f"Ошибка при удалении папки кэша Anydesk '{anydesk_appdata_path}': {e}"
                    logging.error(error_msg)
                    self._update_status(error_msg, level="ERROR")
                    self._update_text_area(f"Ошибка очистки кэша AnyDesk:\n{error_msg}\n\nЗапуск может быть некорректным.")
                    # Не прерываем flow при ошибке очистки, просто логируем и сообщаем пользователю.
                    self._update_progress(30) # Прогресс после ошибки очистки
            else:
                logging.info("Папка кэша Anydesk не найдена. Очистка не требуется.")
                self._update_status("Кэш AnyDesk не найден, очистка не требуется.", level="INFO")
                self._update_progress(30) # Прогресс, если папка не найдена
        else:
            # Логируем, почему очистка пропущена
            reason = []
            if anydesk_is_running:
                reason.append("AnyDesk запущен")
            if not ctrl_pressed:
                reason.append("Ctrl не нажат")
            logging.warning(f"Очистка папки Anydesk пропущена. Причина: {', '.join(reason)}.")
            self._update_status(f"Очистка кэша Anydesk пропущена.", level="WARNING")
            self._update_progress(30) # Прогресс после пропуска очистки


        # --- Запрос пароля и запуск Anydesk ---
        # Этот блок выполняется независимо от того, была ли очистка
        self._update_status(f"AnyDesk ID: {anydesk_id}. Запрос пароля...", level="INFO")
        self._update_progress(40) # Прогресс перед запросом пароля

        # Отключаем кнопки во время диалога
        self._disable_buttons()

        # Запрашиваем пароль у пользователя
        # QInputDialog.getText блокирует выполнение до закрытия диалога
        password, accepted = QInputDialog.getText(
            self,
            "AnyDesk: Введите пароль",
            f"Введите пароль для подключения к ID {anydesk_id}:",
            QLineEdit.EchoMode.Password # Скрывает вводимый текст
        )

        # Включаем кнопки обратно после закрытия диалога
        self._enable_buttons()
        self._set_check_button_to_check()

        if accepted and password:
            logging.info("Пароль Anydesk введен. Попытка запуска Anydesk.")
            self._update_status(f"Запуск AnyDesk для {anydesk_id}...", level="INFO")
            self._update_progress(50) # Прогресс до 50% на время запуска Anydesk

            anydesk_path = get_config_value(self.config, 'Settings', 'AnyDeskPath', default=None, type_cast=str)

            if not anydesk_path or not os.path.exists(anydesk_path):
                 error_msg = f"Ошибка: Путь к AnyDesk.exe не указан в config.ini или файл не найден: '{anydesk_path}'"
                 logging.error(error_msg)
                 self._update_status(error_msg, level="ERROR")
                 self._update_text_area(f"Ошибка запуска AnyDesk:\n{error_msg}\n\nПроверьте config.ini.")
                 self._update_progress(0)
                 return # Прерываем flow

            try:
                # Запускаем Anydesk
                pid = launch_anydesk(anydesk_path, anydesk_id, password)
                self._update_status(f"AnyDesk запущен для {anydesk_id} (PID: {pid}).", level="INFO")
                self._update_text_area(f"AnyDesk успешно запущен для ID {anydesk_id}.\nPID процесса: {pid}")
                self._update_progress(100)
                logging.info("Anydesk flow завершен успешно.")

            except Exception as e:
                error_msg = f"Ошибка при запуске Anydesk: {e}"
                logging.error(f"{error_msg}\n{traceback.format_exc()}")
                self._update_status(error_msg, level="ERROR")
                self._update_text_area(f"Ошибка запуска AnyDesk:\n{error_msg}\n\nПолные детали в логе.")
                self._update_progress(0)
                logging.error("Anydesk flow завершен с ошибкой.")


        elif accepted and not password:
             logging.warning("Пароль Anydesk не введен.")
             self._update_status("Запуск AnyDesk отменен: пароль не введен.", level="WARNING")
             self._update_text_area("Запуск AnyDesk отменен: пароль не был введен.")
             self._update_progress(0)
             logging.info("Anydesk flow завершен пользователем (пароль не введен).")

        else: # accepted is False (диалог отменен)
            logging.info("Ввод пароля Anydesk отменен пользователем.")
            self._update_status("Запуск AnyDesk отменен пользователем.", level="WARNING")
            self._update_text_area("Запуск AnyDesk отменен пользователем.")
            self._update_progress(0)
            logging.info("Anydesk flow завершен пользователем (диалог отменен).")

    def _handle_litemanager_flow(self, lm_id):
        """Обрабатывает последовательность запуска LiteManager: запрос пароля и запуск."""
        self._update_status(f"Найден LiteManager ID: {lm_id}. Подготовка...", level="INFO")
        self._update_progress(10) # Начальный прогресс для LiteManager flow
        self._update_text_area(f"Обнаружен LiteManager ID: {lm_id}. Пожалуйста, введите пароль для подключения.")

        self._update_status(f"LiteManager ID: {lm_id}. Запрос пароля...", level="INFO")
        self._update_progress(40) # Прогресс перед запросом пароля

        # Отключаем кнопки во время диалога
        self._disable_buttons()

        # Запрашиваем пароль у пользователя
        password, accepted = QInputDialog.getText(
            self,
            "LiteManager: Введите пароль",
            f"Введите пароль для подключения к ID {lm_id}:",
            QLineEdit.EchoMode.Password # Скрывает вводимый текст
        )

        # Включаем кнопки обратно после закрытия диалога
        self._enable_buttons()
        self._set_check_button_to_check()

        if accepted and password:
            logging.info("LiteManager Flow: Пароль LiteManager введен. Попытка запуска LiteManager.")
            self._update_status(f"Запуск LiteManager для {lm_id}...", level="INFO")
            self._update_progress(50) # Прогресс до 50% на время запуска

            lm_path = get_config_value(self.config, 'Settings', 'LiteManagerPath', default=None, type_cast=str)

            if not lm_path or not os.path.exists(lm_path):
                 error_msg = f"Ошибка: Путь к ROMViewer.exe не указан в config.ini или файл не найден: '{lm_path}'"
                 logging.error(f"LiteManager Flow: {error_msg}")
                 self._update_status(error_msg, level="ERROR")
                 self._update_text_area(f"Ошибка запуска LiteManager:\n{error_msg}\n\nПроверьте config.ini.")
                 self._update_progress(0)
                 return # Прерываем flow

            try:
                # Запускаем LiteManager
                pid = launch_litemanager(lm_path, lm_id, password)
                self._update_status(f"LiteManager запущен для {lm_id} (PID: {pid}).", level="INFO")
                self._update_text_area(f"LiteManager успешно запущен для ID {lm_id}.\nPID процесса: {pid}")
                self._update_progress(100)
                logging.info("LiteManager flow завершен успешно.")

            except Exception as e:
                error_msg = f"Ошибка при запуске LiteManager: {e}"
                logging.error(f"LiteManager Flow: {error_msg}\n{traceback.format_exc()}")
                self._update_status(error_msg, level="ERROR")
                self._update_text_area(f"Ошибка запуска LiteManager:\n{error_msg}\n\nПолные детали в логе.")
                self._update_progress(0)
                logging.error("LiteManager flow завершен с ошибкой.")


        elif accepted and not password:
             logging.warning("LiteManager Flow: Пароль LiteManager не введен.")
             self._update_status("Запуск LiteManager отменен: пароль не введен.", level="WARNING")
             self._update_text_area("Запуск LiteManager отменен: пароль не был введен.")
             self._update_progress(0)
             logging.info("LiteManager flow завершен пользователем (пароль не введен).")

        else: # accepted is False (диалог отменен)
            logging.info("LiteManager Flow: Ввод пароля LiteManager отменен пользователем.")
            self._update_status("Запуск LiteManager отменен пользователем.", level="WARNING")
            self._update_text_area("Запуск LiteManager отменен пользователем.")
            self._update_progress(0)
            logging.info("LiteManager flow завершен пользователем (диалог отменен).")


    def start_check(self):
        """
        Запускает последовательность проверки сервера или реагирует на Anydesk ID,
        выводя сообщение "Херню спросил" при обнаружении ID.
        """
        target_string = self.target_entry.text().strip()
        if not target_string:
            self._update_status("Введите URL или IP:порт для проверки.", level="WARNING")
            return

        litemanager_id = find_litemanager_id(self.config, target_string)

        if litemanager_id:
            logging.info(f"LiteManager ID '{litemanager_id}' обнаружен при попытке проверки сервера. Вывод сообщения 'Херню спросил'.")
            self._update_text_area("") # Очищаем текстовую область
            # Используем уровень WARNING для оранжевого цвета, как для предупреждений
            self._update_status("Херню спросил", level="WARNING")
            self._update_progress(0)
            return # Прерываем выполнение, не запуская CheckWorker

        # --- Проверка на AnyDesk ID при нажатии Check ---
        anydesk_id = find_anydesk_id(target_string)

        if anydesk_id:
            logging.info(f"AnyDesk ID '{anydesk_id}' обнаружен при попытке проверки сервера. Вывод сообщения 'Херню спросил'.")
            self._update_text_area("") # Очищаем текстовую область
            # Используем уровень WARNING для оранжевого цвета, как для предупреждений
            self._update_status("Херню спросил", level="WARNING")
            self._update_progress(0)
            return # Прерываем выполнение, не запуская CheckWorker

        # --- Если не Anydesk ID, продолжаем с BackOffice Check flow ---
        logging.info("Запуск BackOffice Check flow.")
        if self.worker_thread is not None and self.worker_thread.isRunning():
             logging.warning("Воркер-поток занят. Невозможно запустить новую Check операцию.")
             self._update_status("Операция уже выполняется. Пожалуйста, подождите.", level="WARNING")
             # Кнопки уже отключены _start_worker'ом предыдущей операции
             return # Прерываем функцию, не запускаем новый воркер
        
        self._update_text_area("") # Очищаем текстовую область
        self._update_status("Выполнение проверки сервера...")
        self._update_progress(0)

        # Запускаем воркер проверки
        self._start_worker(CheckWorker, target_string)


    def abort_process(self):
        """
        Слот для кнопки 'Abort'
        Отменяет активный воркер (BackOffice flow).
        Не влияет на модальные диалоги ввода пароля (Anydesk/LiteManager flow)
        """
        logging.info("Нажата кнопка 'Abort'. Попытка прервать операцию.")
        # Отключаем кнопку Abort сразу, чтобы избежать повторных нажатий
        self.check_button.setEnabled(False)
        self._update_status("Прерывание операции...", level="WARNING")

        if self.worker is not None and isinstance(self.worker, BaseWorker) and self.worker_thread is not None and self.worker_thread.isRunning():
             logging.info(f"Обнаружен активный воркер ({self.worker.__class__.__name__}). Отправка сигнала отмены.")
             self.worker.cancel()
             # Дальнейшая логика (очистка ссылок, включение кнопок) произойдет
             # автоматически, когда воркер завершится (получив сигнал отмены)
             # и вызовет _worker_finished.
        else:
             # Если нет активного воркера, просто возвращаем UI в исходное состояние.
             # Это может произойти, если Abort нажата, когда UI был отключен
             # модальным диалогом (Anydesk/LM password prompt), но воркера не было.
             # В нормальной ситуации кнопка Abort должна быть доступна только
             # когда активен воркер.
             logging.debug("Кнопка Abort нажата, но нет активного воркера.")
             self._enable_buttons()
             self._set_check_button_to_check()


    def paste_from_clipboard(self):
        """Слот для кнопки 'Paste'."""
        clipboard = QApplication.clipboard()
        clipboard_content = clipboard.text()

        if clipboard_content and clipboard_content.strip():
            # Ограничиваем длину, чтобы не загромождать поле ввода
            truncated_content = clipboard_content.strip()[:100]
            self.target_entry.clear()
            self.target_entry.setText(truncated_content)
            logging.debug(f"Вставлено содержимое из буфера (ограничено до 100 символов): '{truncated_content}'")
            self._update_status("Ожидание ввода...")
        else:
            logging.warning("Буфер обмена пуст или содержит нетекстовые данные.")
            self._update_status("Буфер обмена пуст или содержит нетекстовые данные.", level="WARNING")


    def closeEvent(self, event):
        """Обработка события закрытия окна."""
        logging.info("Получен запрос на закрытие окна.")

        # Проверяем, есть ли активный поток воркера.
        # Важно проверять self.worker_thread и self.worker_thread.isRunning()
        # вместе, чтобы избежать RuntimeError при обращении к удаленному объекту
        # и убедиться, что поток действительно еще активен.
        if self.worker_thread is not None and self.worker_thread.isRunning():
            logging.warning("Активный воркер обнаружен при закрытии окна.")
            reply = QMessageBox.question(self, "Выход", "Выполняется операция. Прервать и выйти?",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                         QMessageBox.StandardButton.No)

            if reply == QMessageBox.StandardButton.Yes:
                logging.info("Пользователь подтвердил прерывание операции и выход.")
                self._update_status("Прерывание операции перед выходом...", level="INFO")
                # Отправляем сигнал отмены активному воркеру
                if isinstance(self.worker, BaseWorker):
                     self.worker.cancel()
                     logging.info("Сигнал отмены отправлен воркеру.")

                # Ждем завершения потока (с таймаутом).
                # Это необходимо, чтобы избежать краша при удалении виджетов
                # главным потоком, пока воркер еще пытается к ним обратиться
                # через сигналы/слоты или другие объекты.
                # deleteLater запланирует удаление, но wait блокирует до завершения потока.
                # Таймаут предотвращает зависание, если поток не завершается корректно.
                # После cancel(), воркер должен быстро завершиться, поймав AbortOperation.
                if not self.worker_thread.wait(5000): # Ждем до 5 секунд
                     logging.error("Поток воркера не завершился вовремя при закрытии. Принудительное завершение.")
                     # Принудительное завершение - крайняя мера, может привести к непредсказуемому поведению
                     self.worker_thread.terminate()
                     # Ждем еще немного после terminate
                     if not self.worker_thread.wait(1000):
                          logging.critical("Поток не завершился даже после terminate. Возможен краш.")


                event.accept() # Разрешаем закрытие после ожидания/завершения потока
            else:
                logging.info("Пользователь отменил выход.")
                event.ignore() # Отменяем закрытие
        else:
            logging.info("Нет активной операции. Закрытие окна.")
            event.accept() # Разрешаем закрытие


    def eventFilter(self, obj, event):
        """Фильтр событий для поля ввода."""
        # Обработка вставки из буфера по средней кнопке мыши
        if obj is self.target_entry and event.type() == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.MiddleButton:
                self.paste_from_clipboard()
                return True # Событие обработано
        return super().eventFilter(obj, event)