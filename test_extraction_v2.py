"""
Извлечение сущностей/связей для трека "Научный клубок" — версия 2.

Что изменилось относительно v1 и ПОЧЕМУ:
1. ПЛОСКИЕ записи вместо ссылок по id. Каждый эксперимент несёт весь свой
   контекст внутри себя (материал, режим, состояние, условие испытания,
   свойство, значение). Причина: LLM плохо держит целостность перекрёстных
   id-ссылок в одном JSON — будут висячие ссылки и пропавшие рёбра в графе.
   Нормализацию и дедуп сущностей делаем ПОТОМ, детерминированным кодом при
   загрузке в граф, а не руками модели.
2. Добавлены блоки state и test_condition — скрытые оси, вдоль которых
   реально меняются свойства (размер зерна, старение, температура/напряжение
   испытания, диаметр образца). Без них таблицы по зёрнам/размерам схлопнутся.
3. json.loads обёрнут в try/except: падение теперь ВИДИМОЕ (печатает сырой
   ответ и сохраняет его), а не необработанное исключение в трейсбек.
4. Самопроверка печатает свойства сгруппированно — перепутанные значения
   между зёрнами/режимами видно глазами.

Запуск:
   export API_KEY="your_openrouter_or_openai_compatible_key"
   export BASE_URL="https://openrouter.ai/api/v1"
   export MODEL_NAME="qwen/qwen3-32b"
   python test_extraction_v2.py proxy_doc_2_VZh177.txt
"""

import json
import os
import sys
from openai import OpenAI

BASE_URL = os.getenv("BASE_URL", "https://openrouter.ai/api/v1")
API_KEY = os.getenv("API_KEY", "")
MODEL_NAME = os.getenv("MODEL_NAME", "qwen/qwen3-32b")

if not API_KEY:
    raise SystemExit("Set API_KEY before running test_extraction_v2.py")

client = OpenAI(base_url=BASE_URL, api_key=API_KEY)

# Плоская схема: один эксперимент = одно измерение со всем контекстом.
# state и test_condition — nullable-объекты, заполняются только если есть в тексте.
EXTRACTION_SCHEMA = """
{
  "experiments": [
    {
      "material": {
        "name": "название сплава как в тексте (напр. ВЖ177)",
        "alloy_system": "система легирования, если указана, иначе null",
        "heat": "плавка/слиток/партия, если указана, иначе null"
      },
      "regime": {
        "label": "метка режима из текста ('режим 2', 'гомогенизация'), иначе null",
        "description": "краткое словесное описание обработки",
        "temperature_C": "температура обработки, число или строка-диапазон '1220±5', иначе null",
        "duration_h": "выдержка в часах, число, иначе null",
        "cooling": "способ охлаждения, иначе null"
      },
      "state": {
        "grain_size_ball": "балл зерна по ГОСТ, напр. '5-6', иначе null",
        "grain_size_um": "размер зерна в мкм, напр. '40-60', иначе null",
        "aging": "состояние: 'исходное' / 'выдержка 1050ч при 750°С' / иначе null"
      },
      "test_condition": {
        "test_temperature_C": "температура испытания, число, иначе null",
        "stress_MPa": "напряжение при испытании на длительную прочность, иначе null",
        "sample_diameter_mm": "диаметр образца, число, иначе null",
        "standard": "ГОСТ испытания, если указан, иначе null"
      },
      "property": {
        "name": "название свойства (предел прочности σв, предел текучести σ0,2, жаропрочность/время до разрушения, ударная вязкость KCU, относительное удлинение δ и т.д.)",
        "value": "измеренное значение как в тексте (число или строка)",
        "unit": "единица измерения"
      },
      "confidence": "low | medium | high — насколько явно и однозначно связь выражена в тексте",
      "source_quote": "короткая опорная фраза из текста (не более 15 слов), откуда взято значение"
    }
  ],
  "conclusions": [
    {"text": "краткий вывод, перефразированный, НЕ дословная цитата", "confidence": "low | medium | high"}
  ]
}
"""

EXTRACTION_PROMPT = """Ты — инженер по извлечению структурированных данных из научно-технических текстов по металловедению.

Извлеки из текста все измерения свойств строго по схеме JSON. Правила:
- Одно измерение = одна запись в "experiments". Если одно и то же свойство измерено при РАЗНЫХ размерах зерна, температурах испытания, диаметрах образца или состояниях — это РАЗНЫЕ записи. НЕ объединяй их.
- Заполняй state и test_condition всегда, когда в тексте есть размер зерна, старение, температура/напряжение испытания или диаметр образца. Именно они различают строки таблиц.
- Извлекай только то, что явно указано в тексте, не додумывай. Не заполненные поля — null, ключ не пропускай.
- Числа — числами, где возможно; для диапазонов используй строку ("1220±5", "40-60").
- source_quote — короткая (до 15 слов), чтобы можно было проверить значение по тексту.
- Ответь ТОЛЬКО валидным JSON, без markdown-разметки, без пояснений до или после.

Схема:
{schema}

Текст:
{text}
"""


def extract(text: str) -> dict:
    prompt = EXTRACTION_PROMPT.format(schema=EXTRACTION_SCHEMA, text=text)
    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=16000,
    )
    raw = response.choices[0].message.content.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"\n[!] Модель вернула невалидный JSON: {e}")
        print("--- СЫРОЙ ОТВЕТ (первые 800 символов) ---")
        print(raw[:800])
        with open("failed_raw.txt", "w", encoding="utf-8") as f:
            f.write(raw)
        print("\nПолный сырой ответ сохранён в failed_raw.txt — посмотри, где сломалось.")
        return {"experiments": [], "conclusions": []}


def show_grouped(experiments: list):
    """Печатает свойства сгруппированно по (материал, свойство), чтобы было
    видно, сохранились ли разные состояния как отдельные точки или схлопнулись."""
    groups = {}
    for e in experiments:
        mat = (e.get("material") or {}).get("name", "?")
        prop = (e.get("property") or {}).get("name", "?")
        groups.setdefault((mat, prop), []).append(e)

    for (mat, prop), rows in groups.items():
        print(f"\n  {mat} — {prop}: {len(rows)} значений")
        for e in rows:
            st = e.get("state") or {}
            tc = e.get("test_condition") or {}
            val = (e.get("property") or {}).get("value", "?")
            unit = (e.get("property") or {}).get("unit", "")
            ctx = []
            if st.get("grain_size_ball"): ctx.append(f"зерно {st['grain_size_ball']}")
            if st.get("aging"): ctx.append(str(st["aging"]))
            if tc.get("test_temperature_C"): ctx.append(f"Тисп {tc['test_temperature_C']}°C")
            if tc.get("sample_diameter_mm"): ctx.append(f"Ø{tc['sample_diameter_mm']}мм")
            ctx_str = ", ".join(ctx) if ctx else "без контекста(!)"
            conf = e.get("confidence", "?")
            print(f"    {val} {unit}  [{ctx_str}]  conf={conf}")


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "proxy_doc_2_VZh177.txt"
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()

    print(f"Отправляю {path} ({len(text)} симв.) в {MODEL_NAME} через {BASE_URL}...")
    result = extract(text)
    experiments = result.get("experiments", [])

    print("\n=== РЕЗУЛЬТАТ (JSON) ===")
    print(json.dumps(result, ensure_ascii=False, indent=2))

    print("\n=== СГРУППИРОВАНО ПО СВОЙСТВАМ (главная проверка) ===")
    show_grouped(experiments)

    print("\n=== НА ЧТО СМОТРЕТЬ ГЛАЗАМИ ===")
    print(f"Всего экспериментов: {len(experiments)}")
    print("1. Для ВЖ177 + σв должно быть 3 значения (зерно 2-3, 5-6, 7-8): 1370 / 1550 / 1595 МПа.")
    print("   Если 1 значение или значения перепутаны с зёрнами — схема/модель теряет ось 'размер зерна'.")
    print("2. У каждого значения в [] должен быть контекст. 'без контекста(!)' = потерянная ось.")
    print("3. Жаропрочность (128 / 105 / 46 ч) должна быть привязана к тем же трём зёрнам, не перепутана.")
    print("4. Записи 'исходное' vs 'выдержка 1050ч' по зерну 5-6 — две разные точки, не одна.")
    print("5. confidence: low стоит там, где в тексте реально неоднозначно, а не наугад?")

    with open("extraction_result.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("\nСохранено в extraction_result.json")


if __name__ == "__main__":
    main()
