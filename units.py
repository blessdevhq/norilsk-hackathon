"""Нормализация и конверсия единиц измерения для числовых запросов.

Модуль offline: без сети и внешних зависимостей. Задача — сопоставлять
величины, записанные в разных, но физически совместимых единицах
(мг/л vs г/дм3, °C vs K, м3/ч vs л/с), чтобы числовые фильтры в графе
не пропускали факты только из-за другой записи единицы.

Конверсия линейная: base = value * factor + offset (offset нужен только
для температуры). Дименсии не смешиваются: разные размерности считаются
несовместимыми.
"""

# Каждая каноническая единица: (dimension, factor_to_base, offset).
# factor/offset переводят значение в базовую единицу своей размерности.
_UNIT_REGISTRY = {
    # Концентрация масса/объём, база: мг/л
    "mg/l": ("concentration", 1.0, 0.0),
    "g/l": ("concentration", 1000.0, 0.0),
    "kg/m3": ("concentration", 1000.0, 0.0),
    "mg/m3": ("concentration", 0.001, 0.0),
    "ug/l": ("concentration", 0.001, 0.0),
    # Массовая доля / содержание, база: ppm (г/т)
    "ppm": ("mass_fraction", 1.0, 0.0),
    "g/t": ("mass_fraction", 1.0, 0.0),
    "mg/kg": ("mass_fraction", 1.0, 0.0),
    "%_mass": ("mass_fraction", 10000.0, 0.0),
    # Доля / процент, база: %
    "%": ("percent", 1.0, 0.0),
    # Температура, база: °C
    "c": ("temperature", 1.0, 0.0),
    "k": ("temperature", 1.0, -273.15),
    "f": ("temperature", 5.0 / 9.0, -160.0 / 9.0),
    # Объёмный расход, база: м3/ч
    "m3/h": ("flow", 1.0, 0.0),
    "m3/min": ("flow", 60.0, 0.0),
    "m3/s": ("flow", 3600.0, 0.0),
    "l/h": ("flow", 0.001, 0.0),
    "l/min": ("flow", 0.06, 0.0),
    "l/s": ("flow", 3.6, 0.0),
    # Давление, база: МПа
    "mpa": ("pressure", 1.0, 0.0),
    "kpa": ("pressure", 0.001, 0.0),
    "pa": ("pressure", 1e-6, 0.0),
    "bar": ("pressure", 0.1, 0.0),
    "atm": ("pressure", 0.101325, 0.0),
    # Время, база: ч
    "h": ("time", 1.0, 0.0),
    "min": ("time", 1.0 / 60.0, 0.0),
    "s": ("time", 1.0 / 3600.0, 0.0),
    "day": ("time", 24.0, 0.0),
    # Длина / размер, база: мм
    "mm": ("length", 1.0, 0.0),
    "cm": ("length", 10.0, 0.0),
    "m": ("length", 1000.0, 0.0),
    "um": ("length", 0.001, 0.0),
}

# Сырые записи единиц (ru/en, разные регистры) -> каноническая единица реестра.
_ALIASES = {
    # Концентрация
    "mg/l": "mg/l", "мг/л": "mg/l", "mg/dm3": "mg/l", "мг/дм3": "mg/l",
    "g/l": "g/l", "г/л": "g/l", "g/dm3": "g/l", "г/дм3": "g/l",
    "kg/m3": "kg/m3", "кг/м3": "kg/m3",
    "mg/m3": "mg/m3", "мг/м3": "mg/m3",
    "ug/l": "ug/l", "µg/l": "ug/l", "мкг/л": "ug/l",
    # Массовая доля / содержание
    "ppm": "ppm", "г/т": "g/t", "g/t": "g/t", "mg/kg": "mg/kg", "мг/кг": "mg/kg",
    "% масс": "%_mass", "% мас": "%_mass", "мас.%": "%_mass", "wt%": "%_mass", "wt.%": "%_mass",
    # Процент
    "%": "%", "проц": "%", "percent": "%",
    # Температура
    "c": "c", "°c": "c", "град c": "c", "градус c": "c",
    "celsius": "c", "цельсий": "c",
    "k": "k", "кельвин": "k",
    "f": "f", "°f": "f", "фаренгейт": "f",
    # Расход
    "m3/h": "m3/h", "м3/ч": "m3/h",
    "m3/min": "m3/min", "м3/мин": "m3/min",
    "m3/s": "m3/s", "м3/с": "m3/s",
    "l/h": "l/h", "л/ч": "l/h",
    "l/min": "l/min", "л/мин": "l/min",
    "l/s": "l/s", "л/с": "l/s",
    # Давление
    "mpa": "mpa", "мпа": "mpa",
    "kpa": "kpa", "кпа": "kpa",
    "pa": "pa", "па": "pa",
    "bar": "bar", "бар": "bar",
    "atm": "atm", "атм": "atm",
    # Время
    "h": "h", "ч": "h", "час": "h", "часов": "h", "hour": "h",
    "min": "min", "мин": "min",
    "s": "s", "с": "s", "сек": "s", "sec": "s",
    "day": "day", "сут": "day", "сутки": "day",
    # Длина
    "mm": "mm", "мм": "mm",
    "cm": "cm", "см": "cm",
    "m": "m", "м": "m",
    "um": "um", "µm": "um", "мкм": "um",
}


def _clean_unit(value):
    if value is None:
        return ""
    text = str(value).strip().lower()
    text = text.replace("³", "3").replace("²", "2")
    text = text.replace("℃", "°c").replace("˚c", "°c")
    text = text.replace("°с", "°c")  # кириллическая с -> латинская c
    text = text.replace(" ", " ")
    text = " ".join(text.split())
    return text


def normalize_unit(value):
    """Свести сырую запись единицы к канонической или вернуть None."""
    text = _clean_unit(value)
    if not text:
        return None
    if text in _ALIASES:
        return _ALIASES[text]
    stripped = text.rstrip(".")
    if stripped in _ALIASES:
        return _ALIASES[stripped]
    return None


def is_known_unit(value):
    return normalize_unit(value) is not None


def dimension_of(value):
    canonical = normalize_unit(value)
    if canonical is None:
        return None
    return _UNIT_REGISTRY[canonical][0]


def same_dimension(unit_a, unit_b):
    dim_a = dimension_of(unit_a)
    dim_b = dimension_of(unit_b)
    return dim_a is not None and dim_a == dim_b


def convert_value(value, from_unit, to_unit):
    """Перевести число из from_unit в to_unit. None, если несопоставимо."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None

    from_canonical = normalize_unit(from_unit)
    to_canonical = normalize_unit(to_unit)
    if from_canonical is None or to_canonical is None:
        return None

    from_dim, from_factor, from_offset = _UNIT_REGISTRY[from_canonical]
    to_dim, to_factor, to_offset = _UNIT_REGISTRY[to_canonical]
    if from_dim != to_dim:
        return None

    base = number * from_factor + from_offset
    return (base - to_offset) / to_factor


def convert_range(value_range, from_unit, to_unit):
    """Перевести диапазон (min, max) из from_unit в to_unit. None, если несопоставимо."""
    if value_range is None:
        return None
    low, high = value_range
    converted_low = convert_value(low, from_unit, to_unit)
    converted_high = convert_value(high, from_unit, to_unit)
    if converted_low is None or converted_high is None:
        return None
    return (min(converted_low, converted_high), max(converted_low, converted_high))
