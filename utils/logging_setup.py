import logging
import sys
import os
from core.config import LOG_FILE_NAME, get_config_value # Импорт конфига для имени файла и уровня отладки

# Глобальная переменная для объекта конфига, будет установлена из main.py
_config = None

def setup_logging(config):
    """Настраивает стандартный модуль логирования."""
    global _config
    _config = config

    debug_enabled = get_config_value(_config, 'Settings', 'DebugLogging', default=False, type_cast=bool)

    # Устанавливаем корневой логгер
    # Уровень логирования зависит от настройки DebugLogging
    log_level = logging.DEBUG if debug_enabled else logging.INFO
    logging.basicConfig(level=log_level,
                        format='[%(asctime)s] [%(levelname)s] %(message)s',
                        datefmt='%Y-%m-%d %H:%M:%S',
                        handlers=[
                            logging.StreamHandler(sys.stdout) # Вывод в консоль
                        ])

    # Добавляем файловый хэндлер, если включено отладочное логирование
    if debug_enabled:
        try:
            # Получаем путь к лог-файлу относительно директории скрипта
            script_dir = os.path.dirname(sys.argv[0])
            log_file_path = os.path.join(script_dir, LOG_FILE_NAME)

            # Создаем директорию для логов, если она указана в пути и не существует
            log_dir = os.path.dirname(log_file_path)
            if log_dir and not os.path.exists(log_dir):
                os.makedirs(log_dir)

            file_handler = logging.FileHandler(log_file_path, encoding='utf-8', mode='a')
            file_handler.setLevel(logging.DEBUG) # Файловый лог пишет все отладочные сообщения
            file_handler.setFormatter(logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
            logging.getLogger().addHandler(file_handler)
            logging.info(f"Отладочное логирование в файл включено: {log_file_path}")
        except Exception as e:
            logging.error(f"Ошибка при настройке файлового логирования в '{log_file_path}': {e}")

    logging.info(f"Логирование настроено. Уровень: {'DEBUG' if debug_enabled else 'INFO'}")
