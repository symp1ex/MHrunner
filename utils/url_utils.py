import os
import re
import logging

def parse_target_string(input_string):
    """
    Парсит входную строку (URL или IP:Port), извлекая хост/IP, порт и определяя схему.

    Логика определения:
    1. Определяется порт: если явно указан после последнего двоеточия, используется он, иначе 443.
    2. Определяется схема: если порт == 443, схема https, иначе http.
    3. Определяется хост/IP: часть строки до первого двоеточия (если порт был указан) или до первого слэша.
    """
    logging.debug(f"Начат парсинг строки: '{input_string}'")
    if not input_string or not input_string.strip():
        logging.error("Входная строка для парсинга пуста.")
        return None

    # Удаляем потенциальную схему (http, https, ftp, ftps) и символы авторизации (@)
    # Это упрощает поиск хоста и порта в оставшейся части строки.
    temp_input = re.sub(r"^(https?|ftp|ftps)://", "", input_string, flags=re.IGNORECASE)
    temp_input = re.sub(r"^[^@]+@", "", temp_input)

    logging.debug(f"Строка после удаления схемы/авторизации: '{temp_input}'")

    url_or_ip = None
    port = 443 # Порт по умолчанию

    # 1. Определяем порт
    # Ищем последнее двоеточие, за которым следуют цифры до конца строки или слэша.
    port_match = re.search(r":(\d+)(?:/.*)?$", temp_input)
    if port_match:
        try:
            explicit_port = int(port_match.group(1))
            # Валидируем порт: должен быть в разумном диапазоне
            if 1 <= explicit_port <= 65535:
                 port = explicit_port
                 logging.debug(f"Явный порт '{port}' извлечен из исходной строки.")
                 # Удаляем часть с портом из строки для парсинга хоста
                 temp_input_for_host = temp_input[:port_match.start()]
            else:
                 logging.warning(f"Извлечен некорректный номер порта '{explicit_port}'. Используется порт по умолчанию 443.")
                 temp_input_for_host = temp_input # Используем исходную строку без удаления порта
                 port = 443 # Сбрасываем на дефолтный, если порт некорректен
        except ValueError:
            logging.warning(f"Не удалось распарсить порт из '{port_match.group(1)}', используется порт по умолчанию 443.")
            temp_input_for_host = temp_input # Используем исходную строку без удаления порта
            port = 443
    else:
         logging.debug("Явный порт не найден, используется порт по умолчанию 443.")
         temp_input_for_host = temp_input # Нет порта для удаления

    # 2. Определяем схему на основе конечного порта
    config_scheme = "https" if port == 443 else "http"
    logging.debug(f"Определена схема '{config_scheme}' на основе порта '{port}'.")


    # 3. Определяем хост/IP
    # Удаляем путь, если он есть (часть после первого слэша) из строки для хоста
    # Если после удаления порта осталась пустая строка, это ошибка парсинга.
    if not temp_input_for_host:
         logging.error(f"Не удалось извлечь хост/IP из строки '{input_string}' после обработки порта.")
         return None

    host_part = temp_input_for_host.split('/', 1)[0]
    url_or_ip = host_part.strip() # Удаляем пробелы по краям

    if not url_or_ip:
         logging.error(f"Хост/IP оказался пустым после парсинга строки: '{input_string}'")
         return None


    # Простая проверка, является ли это IPv4 адресом
    is_ip_address = False
    if re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", url_or_ip):
         # Дополнительная валидация октетов
         octets = url_or_ip.split('.')
         if len(octets) == 4 and all(0 <= int(octet) <= 255 for octet in octets):
             is_ip_address = True
             logging.debug("Хост определен как IP-адрес IPv4.")
         else:
             logging.warning(f"Хост '{url_or_ip}' выглядит как IP, но октеты неверны или их количество не 4.")
    # Можно добавить проверку на IPv6, но для простоты пока ограничимся IPv4

    logging.debug(f"Парсинг завершен: Хост/IP: '{url_or_ip}', Порт: {port}, Схема: {config_scheme}, IsIpAddress: {is_ip_address}")

    return {
        'UrlOrIp': url_or_ip,
        'Port': port,
        'Scheme': config_scheme, # Добавляем определенную схему
        'IsIpAddress': is_ip_address
    }


def format_version(version_string):
    """Форматирует строку версии, возвращая только первые цифры из трёх первых частей."""
    # ... (остается без изменений)
    logging.debug(f"Форматирование версии: '{version_string}'")
    if not version_string:
        logging.warning("Входная строка версии пуста.")
        return ""

    parts = version_string.split('.')
    digits = []

    for part in parts:
        # Берем только начальные цифры из каждой части
        match = re.match(r"^\d+", part)
        if match:
            # Добавляем только ПЕРВУЮ цифру из найденного числового сегмента
            digits.append(match.group(0)[0])
        # Если мы уже получили цифры из 3 частей, останавливаемся
        if len(digits) == 3:
            break

    # Объединяем собранные цифры (максимум 3)
    result = "".join(digits)

    # Если после попытки извлечения цифр результат пустой, но исходная строка была не пуста
    if not result and version_string:
        logging.warning(f"Не удалось извлечь первые цифры из первых трех частей версии '{version_string}'. Возвращаем исходную строку.")
        return version_string # Возвращаем исходную строку

    logging.debug(f"Форматированная версия: '{result}'")
    return result


def determine_app_type(input_string, edition):
    """Определяет тип приложения и производителя на основе входной строки и edition."""
    # ... (остается без изменений)
    logging.debug(f"Определение типа приложения для строки '{input_string}' и edition '{edition}'")
    vendor = "iiko" # По умолчанию
    # Проверяем входную строку на наличие "syrve" (без учета регистра)
    if "syrve" in input_string.lower():
        vendor = "Syrve"

    app_type = None
    # Определяем тип на основе edition
    if edition: # Проверяем, что edition не None или пустая строка
        if edition.lower() == "default":
            app_type = f"{vendor}RMS"
        elif edition.lower() == "chain":
            app_type = f"{vendor}Chain"
        else:
            # Не удалось определить автоматически, требуется взаимодействие с пользователем.
            # В GUI это будет обработано вызовом диалога.
            logging.warning(f"Не удалось автоматически определить тип RMS/Chain по edition ('{edition}') для производителя '{vendor}'. Требуется выбор пользователя.")
            return None # Возвращаем None, чтобы сигнализировать о необходимости выбора
    else:
        logging.warning(f"Значение 'edition' из ответа сервера пустое или отсутствует. Не удалось автоматически определить тип приложения.")
        return None # Требуется выбор пользователя, так как edition не определен

    logging.debug(f"Определен тип приложения: '{app_type}' (Производитель: '{vendor}')")
    return {
        'AppType': app_type,
        'Vendor': vendor
    }

def get_expected_installer_name(config, app_type, version_formatted):
    """Формирует ожидаемое имя ЛОКАЛЬНОГО каталога дистрибутива на основе конфига."""
    # ... (остается без изменений)
    logging.debug(f"Формирование имени ЛОКАЛЬНОГО каталога дистрибутива для типа '{app_type}' и версии '{version_formatted}'")

    # Читаем базовое имя из конфига LocalInstallerNames
    # Используем get_config_value из core.config
    from core.config import get_config_value
    base_name = get_config_value(config, 'LocalInstallerNames', app_type, default=None, type_cast=str)

    if base_name is None:
        logging.error(f"Ошибка: Не найдено базовое имя ЛОКАЛЬНОГО каталога для типа приложения '{app_type}' в разделе LocalInstallerNames конфига.")
        return None

    result_name = f"{base_name}{version_formatted}"
    logging.debug(f"Ожидаемое имя ЛОКАЛЬНОГО каталога дистрибутива: '{result_name}'")
    return result_name

def sanitize_for_path(input_string):
    """Очищает строку для использования в пути к файлу, удаляя или заменяя недопустимые символы."""
    # ... (остается без изменений)
    logging.debug(f"Санитизация строки для пути: '{input_string}'")
    # Заменяем двоеточие на тире (часто используется в URL:порт)
    sanitized = input_string.replace(':', '-')
    # Удаляем недопустимые символы Windows
    sanitized = re.sub(r'[<>"/\\|?*]', '_', sanitized)
    # Удаляем начальные/конечные пробелы (ограничение Windows)
    sanitized = re.sub(r'^[.\s]+|[.\s]+$', '', sanitized)
    # Схлопываем последовательности точек, подчеркиваний и пробелов в одно подчеркивание
    sanitized = re.sub(r'[._\s]+', '_', sanitized)
     # Удаляем конечные точки (строгое правило Windows)
    sanitized = re.sub(r'\.+$', '', sanitized)

    # Убеждаемся, что строка не пустая после санитизации
    if not sanitized:
        sanitized = "default_name"
        logging.warning(f"Внимание: Строка стала пустой после санитизации. Используется имя по умолчанию: '{sanitized}'")
    logging.debug(f"Санитизированная строка: '{sanitized}'")
    return sanitized

def get_appdata_path(vendor, app_type, sanitized_target, version_raw=None):
    """Определяет правильный путь к временной папке кэша BackOffice в AppData."""
    # ... (остается без изменений)
    logging.debug(f"Определение пути AppData для производителя '{vendor}', типа '{app_type}', адреса '{sanitized_target}' и версии '{version_raw}'")
    app_data_root = os.getenv('APPDATA')
    if not app_data_root:
        logging.error("Переменная окружения APPDATA не найдена.")
        return None

    vendor_folder = "iiko" # Папка по умолчанию
    if vendor.lower() == "syrve":
        # Для Syrve версий 9+ используется папка 'Syrve', для более старых - 'iiko'
        try:
            if version_raw:
                version_parts = version_raw.split('.')
                if version_parts and len(version_parts) > 0:
                    major_version_str = re.match(r"^\d+", version_parts[0]) # Берем только цифры из первой части
                    if major_version_str:
                        major_version = int(major_version_str.group(0))
                        if major_version >= 9:
                            vendor_folder = "Syrve"
                            logging.debug(f"Версия Syrve >= 9 ('{version_raw}'). Используется папка Syrve в AppData.")
                        else:
                             logging.debug(f"Версия Syrve < 9 ('{version_raw}'). Используется папка iiko в AppData.")
                    else:
                         logging.warning(f"Не удалось извлечь основную версию из '{version_raw}'. Используется папка iiko.", level="WARNING")
                else:
                     logging.warning(f"Строка версии '{version_raw}' пуста или некорректна. Используется папка iiko.")
            else:
                 logging.warning("Версия не предоставлена для логики папки Syrve. Используется папка iiko в AppData.")

        except (ValueError, IndexError) as e:
             logging.warning(f"Ошибка парсинга основной версии из '{version_raw}' для логики папки Syrve: {e}. Используется папка iiko.")


    # Определяем промежуточную папку: Rms или Chain
    intermediate_folder = "Rms" if "rms" in app_type.lower() else "Chain"

    # Объединяем части пути
    backoffice_temp_dir = os.path.join(app_data_root, vendor_folder, intermediate_folder, sanitized_target)
    logging.info(f"Определен полный путь временной папки кэша: '{backoffice_temp_dir}' (Папка производителя в AppData: '{vendor_folder}')")
    return backoffice_temp_dir