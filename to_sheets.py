# Синхронизация CSV -> Google Sheets: дописывает ТОЛЬКО те строки, которых в таблице ещё нет.
# Сверка по ссылке, поэтому запускать можно сколько угодно раз — дубликатов не будет.
import os
import sys

HERE = r"C:\Python_rabota\Google_maps_review"
os.chdir(HERE)
sys.path.insert(0, HERE)

import pandas as pd
import main

writer = main.SheetsWriter(main.GOOGLE_CREDS_PATH, main.GOOGLE_SHEET_ID)
if not writer.sheet:
    print("Связь с таблицей не установлена — смотри сообщение выше.")
    print("Причины обычно: таблица не расшарена на client_email или не включён Sheets API.")
    sys.exit(1)

# Какие ссылки уже есть в таблице (колонка 'Ссылка')
existing = set()
values = writer.sheet.get_all_values()
if values and "Ссылка" in values[0]:
    idx = values[0].index("Ссылка")
    existing = {row[idx] for row in values[1:] if len(row) > idx and row[idx]}

# Читаем CSV как текст (dtype=str) — сохраняем ведущие нули телефонов
df = pd.read_csv(main.filename, dtype=str).fillna("")
all_rows = df[main.COLUMNS].values.tolist()

# Оставляем только те, чьей ссылки ещё нет в таблице
link_idx = main.COLUMNS.index("Ссылка")
new_rows = [r for r in all_rows if r[link_idx] not in existing]

if not new_rows:
    print(f"В таблице уже всё есть ({len(existing)} строк) — добавлять нечего.")
else:
    print(f"В таблице {len(existing)} строк, в CSV {len(all_rows)}. Дописываю {len(new_rows)} недостающих...")
    writer.append_rows(new_rows)
print("Готово.")
