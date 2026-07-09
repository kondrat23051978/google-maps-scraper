# Контролируемый прогон укреплённого парсера. main.py НЕ трогаем.
# Пишем в отдельный test_run.csv и берём маленькую цель — быстро и вежливо к Google.
import os
import sys

HERE = r"C:\Python_rabota\Google_maps_review"
os.chdir(HERE)            # чтобы CSV писался сюда
sys.path.insert(0, HERE)  # чтобы найти main.py

import main

main.filename = "test_run.csv"          # свежий файл — соберём реальные новые данные
main.GOOGLE_SHEET_ID = ""               # тест НЕ пишет в реальную таблицу (только CSV)
main.scrape_maps(main.search_query, 6)   # маленькая цель для теста
