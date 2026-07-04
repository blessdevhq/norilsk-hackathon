import argparse
import json
import re
from pathlib import Path

from openai import OpenAI

try:
    from config import API_KEY, BASE_URL, MODEL_NAME
except Exception as exc:
    print(f"ERROR: cannot import BASE_URL, API_KEY, MODEL_NAME from config.py -> {exc}")
    raise SystemExit(1)


INPUT_DIR = Path("extracted")
OUTPUT_PATH = Path("facts.jsonl")
CHUNK_SIZE = 3000
CHUNK_OVERLAP = 300
DOCUMENT_CONTEXT_CHARS = 500
MAX_TOKENS = 16000


EXTRACTION_SCHEMA = """
{
  "facts": [
    {
      "material": {
        "name": "название материала как в тексте, например сплав, руда, раствор, реагент, отход; если не указано — null",
        "type": "один из вариантов: сплав | руда | раствор | реагент | отход | другое; если тип неясен — другое",
        "composition_note": "состав, марка, содержание компонентов или краткая заметка о составе; если не указано — null"
      },
      "process": {
        "name": "название процесса: выщелачивание, электроэкстракция, флотация, обжиг, отжиг, очистка или другой процесс как в тексте; если не указано — null",
        "label": "метка режима, опыта, стадии, схемы или варианта из текста; если не указано — null",
        "description": "краткое описание процесса или операции своими словами на основе текста; если не указано — null"
      },
      "conditions": [
        {
          "parameter": "название параметра условия, например температура, концентрация, скорость потока, время, давление, pH, размер образца, состояние",
          "value": "значение параметра как в тексте, число или строка-диапазон; если не указано — null",
          "unit": "единица измерения, например °C, г/л, м3/ч, ч, МПа, мм; если не указано — null"
        }
      ],
      "result": {
        "property": "измеренное свойство, показатель или наблюдаемый результат: извлечение, содержание, прочность, выход, степень очистки и т.д.; если не указано — null",
        "value": "значение результата как в тексте, число или строка; если не указано — null",
        "unit": "единица измерения результата; если не указано — null",
        "direction": "рост | снижение | без изменений | null — направление изменения показателя, если явно указано"
      },
      "context": {
        "equipment": "оборудование, установка, печь, аппарат, ячейка, колонна и т.д.; если не указано — null",
        "location_geo": "страна, регион, месторождение, предприятие или географическая привязка, если указаны; если не указано — null",
        "year": "год, если указан; если не указано — null",
        "lab_or_author": "лаборатория, организация, автор или коллектив, если указаны; если не указано — null"
      },
      "confidence": "low | medium | high — насколько явно и однозначно связь выражена в тексте",
      "source_quote": "короткая опорная фраза из текста, не более 15 слов, откуда взят факт"
    }
  ],
  "conclusions": [
    {
      "text": "краткий вывод, перефразированный, НЕ дословная цитата",
      "confidence": "low | medium | high"
    }
  ]
}
"""


EXTRACTION_PROMPT = """Ты — инженер по извлечению структурированных данных из русских научно-технических текстов горно-металлургического домена.

Извлеки из текста факты строго по схеме JSON. Правила:
- Один факт = одна запись в "facts". Факт должен нести весь свой контекст внутри себя: материал, процесс, условия, результат, контекст документа.
- Если одно и то же свойство измерено при РАЗНЫХ условиях (разная температура, концентрация, размер образца, состояние) — это РАЗНЫЕ записи, НЕ объединяй их
- Извлекай только то, что явно указано в тексте; не заполненные поля — null, ключи не пропускай
- conditions — всегда список объектов. Если условий несколько, добавь несколько объектов. Если условий нет, верни пустой список [].
- Числа возвращай числами, где это безопасно; диапазоны и значения с символами оставляй строками, например "750±10", "40-60", ">95".
- material.type выбирай только из списка: сплав, руда, раствор, реагент, отход, другое.
- result.direction выбирай только из списка: рост, снижение, без изменений, null.
- source_quote — короткая фраза до 15 слов, чтобы можно было проверить факт по тексту.
- conclusions оставь как отдельный список кратких выводов, перефразированных, не дословных цитат.
- Ответь ТОЛЬКО валидным JSON, без markdown-разметки, без пояснений до или после.

Схема:
{schema}

Контекст документа (начало):
{document_context}

Текст чанка:
{text}
"""


def clean_text(text):
    text = text.replace("\x00", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_paragraphs(text):
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if paragraphs:
        return paragraphs
    return [text.strip()] if text.strip() else []


def chunk_text(text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    paragraphs = split_paragraphs(clean_text(text))
    chunks = []
    current = ""

    for paragraph in paragraphs:
        if len(paragraph) > chunk_size:
            if current:
                chunks.append(current.strip())
                current = ""
            start = 0
            while start < len(paragraph):
                part = paragraph[start : start + chunk_size].strip()
                if part:
                    chunks.append(part)
                if start + chunk_size >= len(paragraph):
                    break
                start += max(1, chunk_size - overlap)
            continue

        candidate = paragraph if not current else current + "\n\n" + paragraph
        if len(candidate) <= chunk_size:
            current = candidate
        else:
            if current:
                chunks.append(current.strip())
            prefix = current[-overlap:].strip() if overlap and current else ""
            current = (prefix + "\n\n" + paragraph).strip() if prefix else paragraph

    if current:
        chunks.append(current.strip())

    return chunks


def strip_markdown_fences(raw):
    raw = raw.strip()
    if not raw.startswith("```"):
        return raw

    parts = raw.split("```")
    if len(parts) < 2:
        return raw

    raw = parts[1].strip()
    if raw.lower().startswith("json"):
        raw = raw[4:].strip()
    return raw


def safe_name(name):
    return re.sub(r"[^A-Za-zА-Яа-я0-9_.-]+", "_", name)[:120]


def build_prompt(document_context, chunk):
    return EXTRACTION_PROMPT.format(
        schema=EXTRACTION_SCHEMA,
        document_context=document_context,
        text=chunk,
    )


def call_llm(client, prompt, source_file, chunk_id):
    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=MAX_TOKENS,
        )
        content = response.choices[0].message.content
        if content is None:
            print(f"ERROR: empty LLM response: file={source_file}, chunk={chunk_id}")
            return None
        return content.strip()
    except Exception as exc:
        print(f"ERROR: LLM request failed: file={source_file}, chunk={chunk_id} -> {exc}")
        return None


def save_failed_raw(raw, source_file, chunk_id):
    failed_path = Path(f"failed_raw_{safe_name(source_file)}_chunk_{chunk_id}.txt")
    try:
        failed_path.write_text(raw or "", encoding="utf-8")
        print(f"Saved raw failed response to {failed_path}")
    except Exception as exc:
        print(f"ERROR: cannot save raw failed response: file={source_file}, chunk={chunk_id} -> {exc}")


def parse_json_response(raw, source_file, chunk_id):
    cleaned = strip_markdown_fences(raw)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        print(f"ERROR: invalid JSON: file={source_file}, chunk={chunk_id} -> {exc}")
        print("--- RAW RESPONSE FIRST 800 CHARS ---")
        print(cleaned[:800])
        return None


def extract_chunk(client, document_context, chunk, source_file, chunk_id):
    prompt = build_prompt(document_context, chunk)

    for attempt in range(1, 3):
        raw = call_llm(client, prompt, source_file, chunk_id)
        if raw is None:
            return {"facts": [], "conclusions": []}

        parsed = parse_json_response(raw, source_file, chunk_id)
        if parsed is not None:
            facts = parsed.get("facts")
            conclusions = parsed.get("conclusions")
            if not isinstance(facts, list):
                print(f"ERROR: JSON field 'facts' is not a list: file={source_file}, chunk={chunk_id}")
                facts = []
            if not isinstance(conclusions, list):
                print(f"ERROR: JSON field 'conclusions' is not a list: file={source_file}, chunk={chunk_id}")
                conclusions = []
            return {"facts": facts, "conclusions": conclusions}

        if attempt == 1:
            print(f"Retrying JSON extraction once: file={source_file}, chunk={chunk_id}")
        else:
            save_failed_raw(raw, source_file, chunk_id)

    return {"facts": [], "conclusions": []}


def fact_to_record(fact, source_file, chunk_id):
    if not isinstance(fact, dict):
        return None
    record = {
        "record_type": "fact",
        "source_file": source_file,
        "chunk_id": chunk_id,
    }
    record.update(fact)
    return record


def conclusion_to_record(conclusion, source_file, chunk_id):
    if not isinstance(conclusion, dict):
        return None
    return {
        "record_type": "conclusion",
        "source_file": source_file,
        "chunk_id": chunk_id,
        "text": conclusion.get("text"),
        "confidence": conclusion.get("confidence"),
    }


def write_jsonl_records(handle, records, source_file, chunk_id):
    written = 0
    for record in records:
        if record is None:
            continue
        try:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            written += 1
        except Exception as exc:
            print(f"ERROR: cannot write JSONL record: file={source_file}, chunk={chunk_id} -> {exc}")
    try:
        handle.flush()
    except Exception as exc:
        print(f"ERROR: cannot flush JSONL output: file={source_file}, chunk={chunk_id} -> {exc}")
    return written


def get_input_files(input_dir, limit):
    try:
        files = sorted(input_dir.glob("*.txt"), key=lambda path: path.name.lower())
    except Exception as exc:
        print(f"ERROR: cannot list input directory {input_dir} -> {exc}")
        return []
    if limit is not None:
        files = files[:limit]
    return files


def process_file(client, path, output_handle):
    source_file = path.name
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:
        print(f"ERROR: cannot read file {path} -> {exc}")
        return {"chunks": 0, "facts": 0, "conclusions": 0, "errors": 1}

    text = clean_text(text)
    if not text:
        print(f"WARNING: empty text file, skipped: {source_file}")
        return {"chunks": 0, "facts": 0, "conclusions": 0, "errors": 0}

    chunks = chunk_text(text)
    document_context = text[:DOCUMENT_CONTEXT_CHARS]
    print(f"\nFile: {source_file} ({len(text)} chars), chunks: {len(chunks)}")

    file_facts = 0
    file_conclusions = 0
    file_errors = 0

    for index, chunk in enumerate(chunks, start=1):
        result = extract_chunk(client, document_context, chunk, source_file, index)
        facts = result.get("facts", [])
        conclusions = result.get("conclusions", [])

        fact_records = [fact_to_record(fact, source_file, index) for fact in facts]
        conclusion_records = [
            conclusion_to_record(conclusion, source_file, index)
            for conclusion in conclusions
        ]
        written = write_jsonl_records(
            output_handle,
            fact_records + conclusion_records,
            source_file,
            index,
        )

        fact_count = len([record for record in fact_records if record is not None])
        conclusion_count = len([record for record in conclusion_records if record is not None])
        file_facts += fact_count
        file_conclusions += conclusion_count
        if written != fact_count + conclusion_count:
            file_errors += 1

        print(
            f"  chunk {index}/{len(chunks)}: facts={fact_count}, "
            f"conclusions={conclusion_count}"
        )

    return {
        "chunks": len(chunks),
        "facts": file_facts,
        "conclusions": file_conclusions,
        "errors": file_errors,
    }


def parse_args():
    parser = argparse.ArgumentParser(description="Extract mining/metallurgy facts from extracted/*.txt")
    parser.add_argument(
        "--input",
        default="extracted",
        help='Path to folder with .txt files (default: "extracted")',
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Process first N txt files from input folder (default: 5)",
    )
    return parser.parse_args()


def validate_config():
    if not BASE_URL or not API_KEY or not MODEL_NAME:
        print("ERROR: BASE_URL, API_KEY and MODEL_NAME must be set in config.py")
        return False
    if API_KEY == "ВСТАВЬ_СВОЙ_КЛЮЧ":
        print("WARNING: config.py still contains placeholder API_KEY.")
        print("Replace API_KEY before real LLM extraction.")
    return True


def main():
    args = parse_args()
    input_dir = Path(args.input)
    if args.limit is not None and args.limit < 0:
        print("ERROR: --limit must be >= 0")
        return

    if not validate_config():
        return

    if not input_dir.exists():
        print(f"ERROR: input directory does not exist: {input_dir}")
        return

    files = get_input_files(input_dir, args.limit)
    if not files:
        print(f"WARNING: no .txt files found in {input_dir}")
        return

    client = OpenAI(base_url=BASE_URL, api_key=API_KEY)
    totals = {"files": 0, "chunks": 0, "facts": 0, "conclusions": 0, "errors": 0}

    print(f"Model: {MODEL_NAME}")
    print(f"Base URL: {BASE_URL}")
    print(f"Input: {input_dir}")
    print(f"Output: {OUTPUT_PATH}")
    print(f"Limit: {args.limit}")

    try:
        with OUTPUT_PATH.open("w", encoding="utf-8") as output_handle:
            for path in files:
                stats = process_file(client, path, output_handle)
                totals["files"] += 1
                totals["chunks"] += stats["chunks"]
                totals["facts"] += stats["facts"]
                totals["conclusions"] += stats["conclusions"]
                totals["errors"] += stats["errors"]
    except Exception as exc:
        print(f"ERROR: cannot open or write output file {OUTPUT_PATH} -> {exc}")
        return

    print("\nDone.")
    print(f"Files processed: {totals['files']}")
    print(f"Chunks processed: {totals['chunks']}")
    print(f"Facts extracted: {totals['facts']}")
    print(f"Conclusions extracted: {totals['conclusions']}")
    print(f"Errors: {totals['errors']}")


if __name__ == "__main__":
    main()
