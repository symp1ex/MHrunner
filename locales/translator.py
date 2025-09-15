# locale/translator.py
import os
import sys
import logging
from PyQt6.QtCore import QTranslator, QLocale, QLibraryInfo

class Translator:
    def __init__(self, app, config):
        self.app = app
        self.config = config
        self.translator = QTranslator()
        self.system_translator = QTranslator()

    def get_locale_path(self, locale_name):
        """Возвращает путь к файлу перевода для указанной локали."""
        # Определяем базовый путь (либо из _MEIPASS для PyInstaller, либо директория скрипта)
        if hasattr(sys, '_MEIPASS'):
            base_path = sys._MEIPASS
        else:
            base_path = os.path.dirname(os.path.abspath(sys.argv[0]))
        
        return os.path.join(base_path, 'locales', f'{locale_name}.qm')

    def switch_language(self, locale_name):
        """Переключает язык приложения."""
        logging.debug(f"Попытка переключения на локаль: {locale_name}")

        # Сначала удаляем старые переводчики, если они были установлены
        self.app.removeTranslator(self.translator)
        self.app.removeTranslator(self.system_translator)

        # Устанавливаем перевод стандартных диалогов Qt (например, кнопки в QMessageBox)
        qt_locale_name = QLocale(locale_name).name() # e.g., "ru_RU"
        translations_path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
        if self.system_translator.load(qt_locale_name, translations_path):
            self.app.installTranslator(self.system_translator)
            logging.debug(f"Загружен системный перевод Qt для локали: {qt_locale_name}")
        else:
            logging.warning(f"Не удалось загрузить системный перевод Qt для локали: {qt_locale_name} по пути {translations_path}")


        # Устанавливаем перевод нашего приложения
        locale_path = self.get_locale_path(locale_name)
        if os.path.exists(locale_path):
            if self.translator.load(locale_path):
                self.app.installTranslator(self.translator)
                logging.info(f"Успешно загружен файл перевода: {locale_path}")
                return True
            else:
                logging.error(f"Ошибка загрузки файла перевода: {locale_path}")
                return False
        else:
            if locale_name != 'en': # Английский - базовый, для него файл не нужен
                logging.warning(f"Файл перевода не найден: {locale_path}")
            return False