"""Тесты конверсии единиц и её влияния на числовые фильтры графа."""

from units import (
    convert_range,
    convert_value,
    is_known_unit,
    normalize_unit,
    same_dimension,
)


def approx(actual, expected, tol=1e-6):
    return actual is not None and abs(actual - expected) <= tol * max(1.0, abs(expected))


def test_normalize_aliases():
    assert normalize_unit("мг/дм3") == "mg/l"
    assert normalize_unit("г/дм3") == "g/l"
    assert normalize_unit("°C") == "c"
    assert normalize_unit("м3/ч") == "m3/h"
    assert normalize_unit("л/с") == "l/s"
    assert normalize_unit("МПа") == "mpa"
    assert normalize_unit("совершенно неизвестная единица") is None
    print("OK: normalize aliases")


def test_concentration():
    # 0.5 г/л = 500 мг/л
    assert approx(convert_value(0.5, "г/л", "мг/л"), 500.0)
    # 300 мг/дм3 = 300 мг/л (dm3 == l)
    assert approx(convert_value(300, "мг/дм3", "mg/l"), 300.0)
    # 1 кг/м3 = 1000 мг/л
    assert approx(convert_value(1, "кг/м3", "мг/л"), 1000.0)
    print("OK: concentration")


def test_temperature():
    assert approx(convert_value(0, "°C", "K"), 273.15)
    assert approx(convert_value(100, "°C", "K"), 373.15)
    assert approx(convert_value(32, "°F", "°C"), 0.0)
    assert approx(convert_value(212, "°F", "°C"), 100.0)
    print("OK: temperature")


def test_flow_and_pressure():
    # 1 л/с = 3.6 м3/ч
    assert approx(convert_value(1, "л/с", "м3/ч"), 3.6)
    # 1 бар = 0.1 МПа
    assert approx(convert_value(1, "бар", "МПа"), 0.1)
    # 1 атм ≈ 0.101325 МПа
    assert approx(convert_value(1, "атм", "МПа"), 0.101325)
    print("OK: flow and pressure")


def test_incompatible_dimensions():
    assert convert_value(1, "мг/л", "°C") is None
    assert not same_dimension("мг/л", "°C")
    assert same_dimension("г/л", "мг/дм3")
    assert convert_range((40, 60), "°C", "K") == (313.15, 333.15)
    print("OK: incompatible dimensions")


def test_known_unit():
    assert is_known_unit("мг/л")
    assert is_known_unit("m3/h")
    assert not is_known_unit(None)
    assert not is_known_unit("штук")
    print("OK: is_known_unit")


def test_filter_integration():
    """Фильтр по 500 мг/л должен ловить факт, записанный как 0.5 г/л."""
    from query_graph import condition_matches

    cond_g_per_l = {"parameter": "концентрация", "value": "0.5", "unit": "г/л"}
    assert condition_matches(cond_g_per_l, parameter="концентрация", value_min=400, value_max=600, unit="мг/л")

    # Несовместимая размерность не должна давать ложное совпадение
    cond_temp = {"parameter": "температура", "value": "500", "unit": "°C"}
    assert not condition_matches(cond_temp, value_min=400, value_max=600, unit="мг/л")
    print("OK: filter integration")


def main():
    test_normalize_aliases()
    test_concentration()
    test_temperature()
    test_flow_and_pressure()
    test_incompatible_dimensions()
    test_known_unit()
    test_filter_integration()
    print("OK: all unit tests passed")


if __name__ == "__main__":
    main()
