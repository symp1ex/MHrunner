import logging
import os
import sys

from PyQt6.QtWidgets import (
    QMainWindow, QApplication, QWidget, QVBoxLayout,
    QGridLayout, QLabel, QLineEdit, QPushButton, QProgressBar,
    QTextEdit, QMessageBox, QSizePolicy
)
from PyQt6.QtCore import Qt, QThread, QEvent, QTimer
from PyQt6.QtGui import QColor, QPalette, QFont, QTextOption, QIcon

# Импортируем модули с логикой и воркерами
from workers.tasks import CheckWorker, LaunchWorker, LaunchWorkerFromStep4, LaunchWorkerFromStep5, BaseWorker


class MainWindow(QMainWindow):
    def __init__(self, config, initial_target=None):
        super().__init__()

        self.config = config
        self.initial_target = initial_target

        self.setWindowTitle("BackOffice Launcher App")
        # Устанавливаем фиксированную ширину, но оставляем возможность растягивать по вертикали
        self.setFixedWidth(550)
        self.setFixedHeight(260) # Минимальная высота

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
        input_layout.addWidget(QLabel("Введите URL или IP:порт:"), 0, 0, alignment=Qt.AlignmentFlag.AlignLeft)
        self.target_entry = QLineEdit()
        input_layout.addWidget(self.target_entry, 0, 1, 1, 2) # Поле ввода занимает 2 колонки
        self.target_entry.returnPressed.connect(self.start_launch)
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
        self.launch_button.clicked.connect(self.start_launch)

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
            color = "green" # Зеленый для информационных сообщений

        # ИСПРАВЛЕНО: Используем setText для QLabel, RichText включен для цвета
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
        logging.error(f"GUI получил сигнал об ошибке: {message}")
        logging.error(f"Полный трейсбек ошибки:\n{detailed_traceback}")

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
        """Запускает новый воркер в отдельном потоке."""
        # Сначала пытаемся корректно завершить предыдущий воркер, если он есть.
        self._cleanup_worker()

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


    def _cleanup_worker(self):
        """
        Отправляет сигнал отмены предыдущему воркеру, если он активен.
        Не ждет завершения потока и не обнуляет ссылки здесь.
        """
        # Проверяем, существует ли ссылка на предыдущий воркер и является ли он экземпляром BaseWorker
        # Также проверяем, что поток еще работает, чтобы избежать RuntimeError при обращении к завершенному потоку
        if self.worker is not None and isinstance(self.worker, BaseWorker) and self.worker_thread is not None and self.worker_thread.isRunning():
            logging.warning("Обнаружен активный воркер. Отправка сигнала отмены.")
            # Отправляем сигнал отмены. Воркер должен сам проверить этот флаг.
            self.worker.cancel()
            # Мы не ждем здесь завершения потока.
            # Поток завершится сам после получения сигнала отмены и обработки AbortOperation
            # или после естественного завершения run().
            # deleteLater, вызванные ранее, позаботятся об удалении объектов Qt.
            # Ссылки self.worker и self.worker_thread будут обнулены в _worker_finished.
        # else:
             # logging.debug("Нет активного воркера для очистки.")


    def _worker_finished(self):
        """Слот, вызываемый, когда worker_thread завершает работу."""
        logging.info("GUI получил сигнал worker_thread.finished.")
        # Включаем кнопки и возвращаем кнопку Abort в состояние Check
        self._enable_buttons()
        self._set_check_button_to_check()

        # Очищаем ссылки на воркер и поток после их завершения и планирования удаления
        # Это безопасно делать здесь, т.к. сигнал finished потока гарантирует, что объекты
        # worker и worker_thread уже получили команду deleteLater и скоро будут удалены.
        self.worker = None
        self.worker_thread = None
        logging.debug("Ссылки self.worker и self.worker_thread обнулены.")


    def start_launch(self):
        """Запускает последовательность запуска BackOffice."""
        target_string = self.target_entry.text().strip()
        if not target_string:
            self._update_status("Введите URL или IP:порт.", level="WARNING")
            return

        self._update_text_area("") # Очищаем текстовую область
        self._update_status("Запуск процесса...")
        self._update_progress(0)

        # Сохраняем начальные данные для передачи воркеру
        self._launch_data = {'target_string': target_string}

        # Запускаем основной воркер запуска
        self._start_worker(LaunchWorker, self._launch_data)


    def start_check(self):
        """Запускает последовательность проверки сервера."""
        target_string = self.target_entry.text().strip()
        if not target_string:
            self._update_status("Введите URL или IP:порт для проверки.", level="WARNING")
            return

        self._update_text_area("") # Очищаем текстовую область
        self._update_status("Выполнение проверки сервера...")
        self._update_progress(0)

        # Запускаем воркер проверки
        self._start_worker(CheckWorker, target_string)


    def abort_process(self):
        """Слот для кнопки 'Abort'."""
        logging.info("Нажата кнопка 'Abort'. Попытка прервать операцию.")
        # Отключаем кнопку Abort сразу, чтобы избежать повторных нажатий
        self.check_button.setEnabled(False)
        self._update_status("Прерывание операции...", level="WARNING")

        # Вызываем _cleanup_worker, который отправит сигнал отмены активному воркеру
        # _cleanup_worker сам проверяет, есть ли активный воркер
        self._cleanup_worker()

        # Дальнейшая логика (включение кнопок, смена текста кнопки) произойдет
        # автоматически, когда воркер завершится (получив сигнал отмены)
        # и вызовет _worker_finished.


    def paste_from_clipboard(self):
        """Слот для кнопки 'Paste'."""
        clipboard = QApplication.clipboard()
        clipboard_content = clipboard.text()

        if clipboard_content and clipboard_content.strip():
            # Ограничиваем длину, чтобы не загромождать поле ввода
            truncated_content = clipboard_content.strip()[:250] # Увеличил лимит
            self.target_entry.clear()
            self.target_entry.setText(truncated_content)
            logging.debug(f"Вставлено содержимое из буфера (ограничено до 250 символов): '{truncated_content}'")
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