# Разовая миграция старых данных на новую схему из 7 колонок.
# Объединяет ВСЕ источники (таблица + локальный CSV + оригинал салонов) по ссылке,
# убирает дубли, у старых строк Рейтинг/Отзывы/Сайт оставляет пустыми.
# Сначала пишет CSV, потом переписывает таблицу — чтобы данные не потерять.
import os
import sys

HERE = r"C:\Python_rabota\Google_maps_review"
os.chdir(HERE)
sys.path.insert(0, HERE)

import pandas as pd
import main

OLD = ["Название", "Телефон", "Адрес", "Ссылка"]   # что было в старой схеме


def rows_from_csv(path):
    out = []
    if os.path.exists(path) and os.path.getsize(path) > 0:
        df = pd.read_csv(path, dtype=str).fillna("")   # dtype=str — сохраняем ведущие нули
        for _, r in df.iterrows():
            out.append({c: r.get(c, "") for c in OLD})
    return out


writer = main.SheetsWriter(main.GOOGLE_CREDS_PATH, main.GOOGLE_SHEET_ID)
if not writer.sheet:
    print("Нет связи с таблицей — миграция прервана.")
    sys.exit(1)

# 1) Собираем из всех источников
all_rows = []
vals = writer.sheet.get_all_values()
if vals and "Ссылка" in vals[0]:
    hdr = vals[0]
    for row in vals[1:]:
        d = {hdr[i]: (row[i] if i < len(row) else "") for i in range(len(hdr))}
        all_rows.append({c: d.get(c, "") for c in OLD})
all_rows += rows_from_csv(os.path.join(HERE, "google_maps_test.csv"))
all_rows += rows_from_csv(r"C:\Python_rabota\Google_maps\google_maps_test.csv")

# 2) Дедуп по ссылке (берём первое вхождение)
seen, unique = set(), []
for r in all_rows:
    link = r.get("Ссылка", "")
    if link and link not in seen:
        seen.add(link)
        unique.append(r)
print(f"Собрано из всех источников: {len(all_rows)} | уникальных по ссылке: {len(unique)}")

# 3) В новую схему (7 колонок); Рейтинг/Отзывы/Сайт пустые — их тогда не собирали
new_rows = [[r["Название"], "", "", "", r["Телефон"], r["Адрес"], r["Ссылка"]] for r in unique]

# 4) Сначала CSV (это наша подстраховка)
pd.DataFrame(new_rows, columns=main.COLUMNS).to_csv(main.filename, index=False, encoding="utf-8-sig")
print(f"CSV переписан: {len(new_rows)} строк -> {os.path.abspath(main.filename)}")

# 5) Затем таблица: чистим, шапка, данные
ws = writer.sheet
ws.clear()
ws.append_row(main.COLUMNS)
if new_rows:
    ws.append_rows(new_rows, value_input_option="RAW")
print(f"Таблица переписана: {len(new_rows)} строк (без дублей, 7 колонок).")
print("Готово.")
