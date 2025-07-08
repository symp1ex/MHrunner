import configparser
import os
import sys

# --- Конфигурация ---
CONFIG_FILE = "config.ini"
LOG_FILE_NAME = "debug_log.log" # Это будет использоваться модулем логирования

# Значения конфигурации по умолчанию
DEFAULT_CONFIG = {
    'Settings': {
        'HttpRequestTimeoutSec': '15',
        'InstallerRoot': 'C:\\iiko_Distr', # Корневой каталог для ЛОКАЛЬНЫХ дистрибутивов
        'ConfigFileWaitTimeoutSec': '60',
        'ConfigFileCheckIntervalMs': '100',
        'DebugLogging': 'False', # Включить подробное логирование в консоль и файл
        'DefaultLogin': 'iikoUser',
        'AnyDeskPath': 'C:\\Program Files\\AnyDesk\\AnyDesk.exe',
        'LiteManagerPath': 'C:\Program Files (x86)\\LiteManager Pro - Viewer\\ROMViewer.exe', # Путь к исполняемому файлу LiteManager Viewer
        'LiteManagerIdMask': 'MH_11111' # Маска для определения ID LiteManager (1 = цифра)
    },
    # Определяем ПРИОРИТЕТ источников. Перечислять через запятую.
    # Скрипт будет проверять источники в указанном порядке.
    'SourcePriority': {
        'Order': 'smb, http, ftp'
    },
    # Настройки для SMB источника
    'SmbSource': {
        'Enabled': 'False', # Включить этот источник?
        'Path': '\\\\10.25.100.5\\sharedisk\\iikoBacks', # UNC-путь к корневой папке на SMB
        # Шаблоны имен архивов на SMB. {version} будет заменено на форматированную версию.
        # {vendor_subdir} будет заменено на "Syrve/" для Syrve и "" для iiko.
        # Важно: эти шаблоны относятся к именам ZIP-АРХИВОВ на SMB.
        'iikoRMS_ArchiveName': 'RMSOffice{version}.zip',
        'iikoChain_ArchiveName': 'ChainOffice{version}.zip',
        'SyrveRMS_ArchiveName': 'Syrve/RMSSOffice{version}.zip', # Указываем подпапку Syrve
        'SyrveChain_ArchiveName': 'Syrve/ChainSOffice{version}.zip' # Указываем подпапку Syrve
    },
    # Настройки для HTTP источника
    'HttpSource': {
        'Enabled': 'True', # Включить этот источник?
        'Url': 'https://f.serty.top/iikoBacks', # Базовый URL директории с архивами
        # Шаблоны имен архивов на HTTP. {version} будет заменено на форматированную версию.
        # {vendor_subdir} будет заменено на "Syrve/" для Syrve и "" для iiko.
        'iikoRMS_ArchiveName': 'RMSOffice{version}.zip',
        'iikoChain_ArchiveName': 'ChainOffice{version}.zip',
        'SyrveRMS_ArchiveName': 'Syrve/RMSSOffice{version}.zip', # Указываем подпапку Syrve
        'SyrveChain_ArchiveName': 'Syrve/ChainSOffice{version}.zip' # Указываем подпапку Syrve
    },
    # Настройки для FTP источника
    'FtpSource': {
        'Enabled': 'True', # Включить этот источник?
        'Host': 'ftp.serty.top',
        'Port': '21', # Стандартный порт FTP
        'Username': 'ftpuser',
        'Password': '11', # Внимание: хранение паролей в конфиге небезопасно!
        'Directory': '/iikoBacks', # Путь к директории с архивами на FTP сервере
        # Шаблоны имен архивов на FTP. {version} будет заменено на форматированную версию.
        # {vendor_subdir} будет заменено на "Syrve/" для Syrve и "" для iiko.
        'iikoRMS_ArchiveName': 'RMSOffice{version}.zip',
        'iikoChain_ArchiveName': 'ChainOffice{version}.zip',
        'SyrveRMS_ArchiveName': 'Syrve/RMSSOffice{version}.zip', # Указываем подпапку Syrve
        'SyrveChain_ArchiveName': 'Syrve/ChainSOffice{version}.zip' # Указываем подпапку Syrve
    },
    # Определяем ФОРМАТ имен ПАПОК для ЛОКАЛЬНОГО хранения дистрибутивов.
    # Это ИМЯ КАТАЛОГА, а не архива.
    'LocalInstallerNames': {
        'iikoRMS': 'RMSOffice',
        'iikoChain': 'ChainOffice',
        'SyrveRMS': 'RMSSOffice',
        'SyrveChain': 'ChainSOffice'
    }
}

# Функция загрузки конфига останется здесь, т.к. она работает с файлом конфига
def load_config():
    """Загружает конфигурацию из config.ini или создает его со значениями по умолчанию."""
    config = configparser.ConfigParser()
    # Проверяем наличие файла конфига в текущей директории
    config_path = os.path.join(os.path.dirname(sys.argv[0]), CONFIG_FILE)

    if not os.path.exists(config_path):
        print(f"Создание файла конфигурации по умолчанию: {config_path}")
        try:
            # Создаем и заполняем конфиг в памяти из DEFAULT_CONFIG
            for section, values in DEFAULT_CONFIG.items():
                config.add_section(section)
                for key, value in values.items():
                    config.set(section, key, value)
            # Записываем в файл
            with open(config_path, 'w', encoding='utf-8') as configfile:
                config.write(configfile)
            print(f"Файл конфигурации '{config_path}' успешно создан.")
        except Exception as e:
            print(f"Ошибка при создании файла конфигурации по умолчанию '{config_path}': {e}", file=sys.stderr)
            # Если не удалось создать файл, работаем с конфигом в памяти из DEFAULT_CONFIG
            print("Используются значения конфигурации по умолчанию из памяти.")
            # Убедимся, что config объект содержит дефолты, даже если создание файла упало
            config = configparser.ConfigParser()
            for section, values in DEFAULT_CONFIG.items():
                 config.add_section(section)
                 for key, value in values.items():
                     config.set(section, key, value)

    else:
        try:
            config.read(config_path, encoding='utf-8')
            print(f"Файл конфигурации '{config_path}' успешно загружен.")
            # Проверяем наличие всех секций и ключей из DEFAULT_CONFIG и добавляем их, если отсутствуют
            # Это позволяет добавлять новые настройки в DEFAULT_CONFIG без необходимости удалять старый config.ini
            config_changed = False
            for section, values in DEFAULT_CONFIG.items():
                if not config.has_section(section):
                    config.add_section(section)
                    config_changed = True
                for key, value in values.items():
                    if not config.has_option(section, key):
                        config.set(section, key, value)
                        config_changed = True

            # Если были добавлены новые настройки, сохраняем обновленный файл
            if config_changed:
                 print(f"Обновление файла конфигурации '{config_path}' новыми параметрами.")
                 try:
                     with open(config_path, 'w', encoding='utf-8') as configfile:
                         config.write(configfile)
                     print(f"Файл конфигурации '{config_path}' успешно обновлен.")
                 except Exception as e:
                     print(f"Ошибка при обновлении файла конфигурации '{config_path}': {e}", file=sys.stderr)


        except Exception as e:
            print(f"Ошибка при загрузке файла конфигурации '{config_path}': {e}", file=sys.stderr)
            print("Используются значения конфигурации по умолчанию из памяти.")
            # Если загрузка упала, работаем с дефолтами в памяти
            config = configparser.ConfigParser()
            for section, values in DEFAULT_CONFIG.items():
                 config.add_section(section)
                 for key, value in values.items():
                     config.set(section, key, value)


    return config

# Функция получения значения конфига тоже здесь
def get_config_value(config, section, key, default=None, type_cast=str):
    """Безопасно получает значение конфигурации с приведением типа и значением по умолчанию."""
    # В этой функции не используем log_message, чтобы избежать циклических зависимостей
    # при инициализации логирования, которая зависит от конфига.
    # Вместо этого используем print/sys.stderr.
    try:
        if type_cast == bool:
            return config.getboolean(section, key)
        elif type_cast == int:
            return config.getint(section, key)
        elif type_cast == float:
             return config.getfloat(section, key)
        else:
            return config.get(section, key)
    except (configparser.NoSectionError, configparser.NoOptionError, ValueError) as e:
        # print(f"Внимание: Не удалось получить значение конфигурации [{section}]{key}. Использование значения по умолчанию: {default}. Ошибка: {e}", file=sys.stderr)
        return default

# Глобальная переменная для уровня отладки
# Она будет установлена в main.py после загрузки конфига
DEBUG_LOGGING_ENABLED = False