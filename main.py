# main.py
import sys
import os
import logging

from PyQt6.QtWidgets import QApplication

# Импортируем модули
from core.config import load_config, get_config_value
from utils.logging_setup import setup_logging
from gui.main_window import MainWindow
from locale.translator import Translator # Импортируем наш класс Translator


if __name__ == "__main__":
    # 1. Загружаем конфигурацию
    config = load_config()

    # 2. Настраиваем логирование на основе конфига
    setup_logging(config)
    logging.info("Приложение запущено.")

    # 3. Проверяем аргументы командной строки
    initial_target = None
    if len(sys.argv) > 1:
        initial_target = sys.argv[1]
        logging.info(f"Получен аргумент командной строки: '{initial_target}'")

    # 4. Создаем экземпляр QApplication
    app = QApplication(sys.argv)

    # 5. Создаем, настраиваем и применяем локализацию
    # Создаем экземпляр нашего переводчика
    translator = Translator(app, config)
    # Загружаем язык из конфига (по умолчанию 'ru')
    current_locale = get_config_value(config, 'Settings', 'Language', default='ru')
    translator.switch_language(current_locale)

    # 6. Создаем главное окно, передавая ему конфиг, переводчик и начальный аргумент
    main_window = MainWindow(config, translator, initial_target)

    # 7. Показываем окно
    main_window.show()

    # 8. Запускаем цикл событий приложения
    sys.exit(app.exec())