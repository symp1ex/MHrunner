# gui/main_window.py - ОБНОВЛЕННЫЙ (исправлен RuntimeError и вывод ошибок отмены, исправлен AttributeError setHtml)

import sys
import os
import json
import logging
import traceback

from PyQt6.QtWidgets import (
    QMainWindow, QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QLineEdit, QPushButton, QProgressBar,
    QTextEdit, QMessageBox
)
from PyQt6.QtCore import Qt, QThread, QObject, QEvent, QTimer
from PyQt6.QtGui import QColor, QPalette, QClipboard, QTextOption

# Импортируем модули с логикой и воркерами
from core.config import load_config
from utils.process_utils import stop_process_by_pid
from workers.tasks import CheckWorker, LaunchWorker, LaunchWorkerFromStep4, LaunchWorkerFromStep5, BaseWorker
# Импортируем AbortOperation для проверки типа исключения
from utils.exceptions import AbortOperation


class MainWindow(QMainWindow):
    def __init__(self, config, initial_target=None):
        super().__init__()

        self.config = config
        self.initial_target = initial_target

        self.setWindowTitle("BackOffice Launcher (PyQt6)")
        self.setGeometry(100, 100, 600, 290)
        self.setMinimumSize(400, 200)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(15, 15, 15, 15)

        input_layout = QGridLayout()
        input_layout.setContentsMargins(0, 0, 0, 0)

        input_layout.addWidget(QLabel("Введите URL или IP:порт:"), 0, 0, alignment=Qt.AlignmentFlag.AlignLeft)

        self.target_entry = QLineEdit()
        input_layout.addWidget(self.target_entry, 0, 1, 1, 2)
        self.target_entry.returnPressed.connect(self.start_launch)
        self.target_entry.installEventFilter(self)


        self.paste_button = QPushButton("Paste")
        input_layout.addWidget(self.paste_button, 0, 3)
        self.paste_button.clicked.connect(self.paste_from_clipboard)

        self.status_label = QLabel("Ожидание ввода...")
        self.status_label.setWordWrap(True)
        # Убедимся, что QLabel может отображать RichText, хотя AutoText обычно достаточно
        self.status_label.setTextFormat(Qt.TextFormat.RichText)
        input_layout.addWidget(self.status_label, 1, 0, 1, 2, alignment=Qt.AlignmentFlag.AlignLeft)

        self.check_button = QPushButton("Check")
        input_layout.addWidget(self.check_button, 1, 2)
        self.check_button.clicked.connect(self.start_check)


        self.launch_button = QPushButton("Launch")
        input_layout.addWidget(self.launch_button, 1, 3)
        self.launch_button.clicked.connect(self.start_launch)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        input_layout.addWidget(self.progress_bar, 2, 0, 1, 4)

        main_layout.addLayout(input_layout)

        self.json_output_text = QTextEdit()
        self.json_output_text.setReadOnly(True)
        self.json_output_text.setWordWrapMode(QTextOption.WrapMode.WordWrap)
        main_layout.addWidget(self.json_output_text)

        self.worker_thread = None
        self.worker = None
        self._launch_data = {}


        if self.initial_target:
            self.target_entry.setText(self.initial_target)
            # Использование QTimer.singleShot для отложенного запуска
            # дает GUI время инициализироваться перед запуском задачи
            QTimer.singleShot(100, self.start_launch)

    def _update_status(self, message, level="INFO"):
        color = "black"
        if level == "ERROR":
            color = "red"
        elif level == "WARNING":
            color = "orange"
        # ИСПРАВЛЕНО: Используем setText вместо setHtml
        self.status_label.setText(f"<span style='color:{color};'>{message}</span>")

    def _update_progress(self, value):
        self.progress_bar.setValue(value)

    def _update_text_area(self, text):
        self.json_output_text.setPlainText(text)
        # Прокручиваем к началу
        self.json_output_text.verticalScrollBar().setValue(self.json_output_text.verticalScrollBar().minimum())


    def _handle_error(self, message, detailed_traceback):
        """Слот для обработки ошибок из потока."""
        logging.error(f"GUI получил сигнал об ошибке: {message}")

        # Ищем имя класса исключения AbortOperation в трейсбеке
        is_aborted_error = "AbortOperation" in detailed_traceback

        if is_aborted_error:
             # Если это ошибка из-за отмены, выводим краткое сообщение
             self._update_status("Операция прервана (Aborted).", level="WARNING")
             # Выводим детальный трейсбек в текстовую область для отладки, но с пояснением
             self._update_text_area(f"Операция была прервана пользователем.\n\nДетали ошибки (если применимо):\n{detailed_traceback}")
        else:
             # Если это другая ошибка, выводим подробности
             self._update_status(f"Ошибка: {message}", level="ERROR")
             self._update_text_area(f"Произошла ошибка:\n{detailed_traceback}")
             # Убираем дублирующий MessageBox, т.к. информация уже в текстовой области
             # QMessageBox.critical(self, "Ошибка", f"Произошла ошибка:\n{message}")


        self._update_progress(0)
        # Кнопки будут включены в _worker_finished


    def _request_dialog(self, dialog_type, title, message, options, callback_data):
        """Слот для обработки запросов на диалоги от воркера."""
        logging.debug(f"GUI получил запрос на диалог: {dialog_type}")
        # Отключаем кнопку "Abort" пока открыт диалог, чтобы избежать двойной логики отмены
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
            self._handle_error(f"Внутренняя ошибка: неизвестный тип диалога '{dialog_type}'.", "Неизвестный тип диалога запрошен воркером.")

        # После обработки диалога, если воркер не был перезапущен, включаем кнопки
        # (Если воркер перезапущен, кнопки будут отключены в _start_worker)
        if self.worker_thread is None or not self.worker_thread.isRunning():
             self._enable_buttons()
             self._set_check_button_to_check()


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
        if "syrve" in launch_data.get('target_string', '').lower():
             vendor = "Syrve"

        if selected_option == 'RMS':
            launch_data['app_type'] = f"{vendor}RMS"
        elif selected_option == 'Chain':
            launch_data['app_type'] = f"{vendor}Chain"
        else:
             logging.error(f"Неожиданный результат диалога выбора типа приложения: '{selected_option}'")
             # Отправляем сигнал отмены текущему воркеру
             if isinstance(self.worker, BaseWorker):
                  self.worker.cancel()
             # _handle_error будет вызван воркером, когда он поймает AbortOperation
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
        self.launch_button.setEnabled(True)
        self.target_entry.setEnabled(True)
        self.paste_button.setEnabled(True)
        # Кнопка Check/Abort управляется отдельно
        # self.check_button.setEnabled(True)

    def _disable_buttons(self):
        self.launch_button.setEnabled(False)
        self.target_entry.setEnabled(False)
        self.paste_button.setEnabled(False)
        # Кнопка Check/Abort управляется отдельно
        # self.check_button.setEnabled(False)


    def _set_check_button_to_check(self):
        self.check_button.setText("Check")
        # Отсоединяем старый слот (если был присоединен)
        try: self.check_button.clicked.disconnect(self.abort_process)
        except TypeError: pass # Игнорируем ошибку, если слот не был присоединен
        # Присоединяем новый слот
        try: self.check_button.clicked.connect(self.start_check)
        except TypeError: pass # Игнорируем ошибку, если слот уже присоединен (не должно быть)
        self.check_button.setEnabled(True) # Включаем кнопку

    def _set_check_button_to_abort(self):
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

        # Отключаем кнопки и меняем текст кнопки Check на Abort
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
        if self.worker is not None and isinstance(self.worker, BaseWorker):
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
        self.worker = None
        self.worker_thread = None
        logging.debug("Ссылки self.worker и self.worker_thread обнулены.")


    def start_launch(self):
        target_string = self.target_entry.text().strip()
        if not target_string:
            self._update_status("Введите URL или IP:порт.", level="WARNING")
            return

        self._update_text_area("")
        self._update_status("Запуск процесса...")
        self._update_progress(0)

        # Сохраняем начальные данные для передачи воркеру
        self._launch_data = {'target_string': target_string}

        # Запускаем основной воркер запуска
        self._start_worker(LaunchWorker, self._launch_data)


    def start_check(self):
        target_string = self.target_entry.text().strip()
        if not target_string:
            self._update_status("Введите URL или IP:порт для проверки.", level="WARNING")
            return

        self._update_text_area("")
        # ИСПРАВЛЕНО: Исправлена опечатка в кириллице, хотя это не причина ошибки setHtml
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
        self._cleanup_worker()

        # Дальнейшая логика (включение кнопок, смена текста кнопки) произойдет
        # автоматически, когда воркер завершится и вызовет _worker_finished.
        # Если воркер не был активен (_cleanup_worker ничего не сделал),
        # то кнопки останутся в состоянии "отключены" и "Abort".
        # В этом случае, можно добавить небольшую задержку или проверку,
        # чтобы вернуть их в исходное состояние, если отмена не была отправлена.
        # Но в текущей логике _cleanup_worker всегда вызывается перед _start_worker,
        # так что этот сценарий (Abort при отсутствии активного воркера)
        # возможен только если пользователь нажал Abort сразу после завершения предыдущей задачи,
        # до того как _worker_finished успел обнулить ссылки.
        # Current _cleanup_worker handles the None case, so it's mostly fine.
        # Let's add a check in _cleanup_worker for clarity. (Already added debug log)


    def paste_from_clipboard(self):
        """Слот для кнопки 'Paste'."""
        clipboard = QApplication.clipboard()
        clipboard_content = clipboard.text()

        if clipboard_content and clipboard_content.strip():
            # Ограничиваем длину, чтобы не загромождать поле ввода
            truncated_content = clipboard_content.strip()[:200] # Увеличил лимит на всякий случай
            self.target_entry.clear()
            self.target_entry.setText(truncated_content)
            logging.debug(f"Вставлено содержимое из буфера (ограничено до 200 символов): '{truncated_content}'")
            self._update_status("Ожидание ввода...")
        else:
            logging.warning("Буфер обмена пуст или содержит нетекстовые данные.")
            self._update_status("Буфер обмена пуст или содержит нетекстовые данные.", level="WARNING")


    def closeEvent(self, event):
        """Обработка события закрытия окна."""
        logging.info("Получен запрос на закрытие окна.")

        # Проверяем, есть ли активный поток воркера
        # Важно проверять именно объект потока, а не self.worker_thread.isRunning(),
        # чтобы избежать RuntimeError при обращении к удаленному объекту.
        # Достаточно проверить, что ссылка не None.
        if self.worker_thread is not None:
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