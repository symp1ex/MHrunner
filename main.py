import sys
import os
import logging

from PyQt6.QtWidgets import QApplication

# Импортируем модули
from core.config import load_config # Загрузка конфига
from utils.logging_setup import setup_logging # Настройка логирования
from gui.main_window import MainWindow # Главное окно


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

    # 5. Создаем главное окно, передавая конфиг и начальный аргумент
    main_window = MainWindow(config, initial_target)

    # 6. Показываем окно
    main_window.show()

    # 7. Запускаем цикл событий приложения
    sys.exit(app.exec())