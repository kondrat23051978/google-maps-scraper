import os
import sys
import time
import random
import pandas as pd
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# --- Кириллица в консоли без кракозябр (Windows) ---
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
        import ctypes
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)  # консоль в режим UTF-8
    except Exception:
        pass

# --- ПУЛЬТ УПРАВЛЕНИЯ ---
keyword = "кафе, рестораны"
location = "Киев, Позняки"
target_count = 20          # Сколько НОВЫХ карточек собрать за один запуск
filename = "google_maps_test.csv"
search_query = f"{keyword} {location}"

# Папка скрипта — чтобы ключ находился, откуда бы ты ни запускал
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Google Sheets (необязательно). Пусто — парсер просто пишет CSV, как раньше.
# GOOGLE_CREDS_PATH — путь к JSON-ключу service account (положи рядом с main.py)
# GOOGLE_SHEET_ID   — ID таблицы из ссылки: docs.google.com/spreadsheets/d/<ВОТ_ЭТО>/edit
#                     берётся из переменной окружения или из файла .env (см. .env.example)
def _load_dotenv(path):
    """Мини-загрузчик .env без доп. зависимостей: строки вида KEY=value."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(os.path.join(BASE_DIR, ".env"))
GOOGLE_CREDS_PATH = os.path.join(BASE_DIR, "service_account.json")
GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "")

# Имена колонок храним в одном месте — чтобы нигде не было рассинхрона
COLUMNS = ["Название", "Рейтинг", "Отзывы", "Сайт", "Телефон", "Адрес", "Ссылка"]
# ------------------------


class SheetsWriter:
    """Заливка собранного в Google Sheets.
    Если ключ не настроен или что-то пошло не так — тихо пропускаем:
    парсер продолжает работать и пишет CSV как обычно."""

    def __init__(self, creds_path, sheet_id):
        self.sheet = None
        if not creds_path or not sheet_id:
            print("--- Google Sheets не настроен (пустой ключ/ID) — пишу только в CSV ---")
            return
        if not os.path.exists(creds_path):
            print(f"--- Ключ '{creds_path}' не найден — пишу только в CSV ---")
            return
        try:
            import gspread
            from google.oauth2.service_account import Credentials

            scopes = ["https://www.googleapis.com/auth/spreadsheets"]
            creds = Credentials.from_service_account_file(creds_path, scopes=scopes)
            client = gspread.authorize(creds)
            self.sheet = client.open_by_key(sheet_id).sheet1
            if not self.sheet.row_values(1):       # пустая таблица — пишем шапку
                self.sheet.append_row(COLUMNS)
            print("--- Google Sheets подключён ---")
        except Exception as e:
            print(f"--- Не удалось подключить Google Sheets: {e} — пишу только в CSV ---")
            self.sheet = None

    def _links_in_sheet(self):
        """Ссылки, которые уже есть в таблице — для защиты от дублей."""
        values = self.sheet.get_all_values()
        if not values or "Ссылка" not in values[0]:
            return set()
        idx = values[0].index("Ссылка")
        return {row[idx] for row in values[1:] if len(row) > idx and row[idx]}

    def append_rows(self, rows):
        """Дозаписываем пачку строк одним запросом.
        Защита от дублей: сверяемся по ссылке с тем, что уже в таблице —
        повторы не лезут, даже если локальный CSV неполный."""
        if not self.sheet or not rows:
            return
        try:
            already = self._links_in_sheet()
            link_idx = COLUMNS.index("Ссылка")
            fresh = [r for r in rows if r[link_idx] not in already]
            skipped = len(rows) - len(fresh)
            if not fresh:
                print(f"--- В таблице уже всё есть (пропущено дублей: {skipped}) ---")
                return
            # RAW — хранить как текст, иначе телефон '0980...' Google превратит в число
            self.sheet.append_rows(fresh, value_input_option="RAW")
            msg = f"--- В Google Sheets добавлено {len(fresh)} строк"
            if skipped:
                msg += f", пропущено дублей: {skipped}"
            print(msg + " ---")
        except Exception as e:
            print(f"--- Ошибка записи в Google Sheets: {e} (данные сохранены в CSV) ---")


def human_pause(a, b):
    """Случайная пауза, как у живого человека (а не ровный метроном бота)."""
    time.sleep(random.uniform(a, b))


def launch_browser(p):
    """Запускаем настоящий Chrome (меньше палимся). Нет Chrome — откат на Chromium."""
    # --disable-blink-features=AutomationControlled прячет флаг navigator.webdriver
    args = ["--disable-blink-features=AutomationControlled"]
    try:
        return p.chromium.launch(headless=False, channel="chrome", args=args)
    except Exception:
        print("--- Chrome не найден, запускаю встроенный Chromium ---")
        return p.chromium.launch(headless=False, args=args)


def load_existing_links(path):
    """Множество уже собранных ссылок — чтобы не дублировать между запусками."""
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        print("--- База ещё пустая, начинаю с нуля ---")
        return set()
    try:
        old_df = pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return set()
    except Exception as e:
        # Не молчим: битый CSV — повод остановиться, а не тихо потерять данные
        print(f"--- ВНИМАНИЕ: не смог прочитать базу: {e}")
        raise
    if "Ссылка" not in old_df.columns:
        print("--- В базе нет колонки 'Ссылка' — считаю, что дублей нет ---")
        return set()
    links = set(old_df["Ссылка"].dropna())
    print(f"--- ПАМЯТЬ: в базе уже {len(links)} записей. Ищу только новых! ---")
    return links


def save_row(path, row):
    """Сохраняем КАЖДУЮ запись сразу — чтобы при сбое не потерять всю пачку."""
    need_header = (not os.path.exists(path)) or os.path.getsize(path) == 0
    df = pd.DataFrame([row], columns=COLUMNS)
    if need_header:
        # Новый файл: utf-8-sig (с BOM) — чтобы Excel правильно показал кириллицу
        df.to_csv(path, mode="w", index=False, header=True, encoding="utf-8-sig")
    else:
        # Дозапись: обычный utf-8 — иначе pandas вставит лишний BOM в середину файла
        df.to_csv(path, mode="a", index=False, header=False, encoding="utf-8")


def looks_like_captcha(page):
    """Грубая проверка: не подсунул ли Google капчу / страницу 'вы робот'."""
    if "sorry" in page.url.lower():
        return True
    try:
        content = page.content().lower()
    except Exception:
        return False
    markers = ["unusual traffic", "необычный трафик", "captcha", "recaptcha", "i'm not a robot"]
    return any(m in content for m in markers)


def collect_links(page, query, existing_links, target):
    """Фаза 1: скроллим ленту ('бульдозер') и собираем ссылки на карточки."""
    url = f"https://www.google.com/maps/search/{query.replace(' ', '+')}"
    page.goto(url, timeout=60000)

    # Ждём именно ленту результатов, а не слепую паузу на N секунд
    try:
        page.wait_for_selector('div[role="feed"]', timeout=30000)
    except PlaywrightTimeout:
        if looks_like_captcha(page):
            raise RuntimeError("Google показал капчу. Останавливаюсь — зайди позже и помедленнее.")
        raise RuntimeError("Лента результатов не появилась (сменилась вёрстка или район пустой).")

    human_pause(2, 4)

    newly_found = []
    seen = set(existing_links)
    attempts = 0
    last_len = 0
    print("--- Начинаю глубокий поиск... ---")

    while len(newly_found) < target:
        feed = page.query_selector('div[role="feed"]')
        if not feed:
            break

        # Резкий скролл вниз
        page.evaluate("el => el.scrollBy(0, 7000)", feed)
        human_pause(3, 6)   # случайно вместо ровных 6 сек — и человечнее, и надёжнее

        items = page.query_selector_all('div[role="article"]')
        current_len = len(items)

        if current_len <= last_len:
            attempts += 1
            print(f"--- Google притормозил, попытка {attempts}/3... ---")
            human_pause(3, 5)
            if attempts >= 3:   # после 3 пустых попыток выходим
                break
        else:
            attempts = 0        # нашли новое — сбрасываем счётчик
        last_len = current_len

        for item in items:
            link_el = item.query_selector("a")
            if not link_el:
                continue
            link = link_el.get_attribute("href")
            name = item.get_attribute("aria-label") or "Без названия"
            if link and link not in seen:
                newly_found.append({"Название": name, "Ссылка": link})
                seen.add(link)
                print(f"  Нашёл: {name}")

    return newly_found


def scrape_card(page, item):
    """Фаза 2: заходим в карточку и достаём рейтинг, отзывы, сайт, телефон, адрес."""
    page.goto(item["Ссылка"], timeout=30000)
    page.wait_for_selector("h1", timeout=15000)   # заголовок карточки есть всегда
    human_pause(1.5, 3.0)

    # Рейтинг и число отзывов — блок под названием заведения
    rating, reviews = "Не найден", "Не найден"
    rblock = page.query_selector("div.F7nice")
    if rblock:
        r = rblock.query_selector('span[aria-hidden="true"]')
        if r and r.inner_text().strip():
            rating = r.inner_text().strip()
        labels = [el.get_attribute("aria-label") or "" for el in rblock.query_selector_all("span[aria-label]")]
        revs = ""
        for lbl in labels:   # сначала ищем подпись со словом 'отзыв/review/відгук'
            if any(k in lbl.lower() for k in ("review", "отзыв", "відгук", "огляд")):
                revs = "".join(ch for ch in lbl if ch.isdigit())
                break
        if not revs:         # запас: подпись с наибольшим числом цифр
            for lbl in labels:
                d = "".join(ch for ch in lbl if ch.isdigit())
                if len(d) > len(revs):
                    revs = d
        reviews = revs or "Не найден"

    # Сайт заведения (НЕ ссылка на карты, а настоящий сайт бизнеса)
    website = "Не найден"
    w_el = page.query_selector('a[data-item-id="authority"]')
    if w_el:
        website = w_el.get_attribute("href") or "Не найден"

    # Телефон
    phone = "Не найден"
    p_el = page.query_selector('button[data-item-id^="phone:tel:"]')
    if p_el:
        phone = p_el.get_attribute("data-item-id").replace("phone:tel:", "")

    # Адрес
    address = "Не найден"
    a_el = page.query_selector('button[data-item-id^="address"]')
    if a_el:
        raw = a_el.get_attribute("aria-label") or ""
        # 'Адрес: ...' / укр. 'Адреса: ...' — режем по первому ':' (язык не важен)
        address = raw.split(":", 1)[-1].strip() if ":" in raw else raw.strip()
        address = address or "Не найден"

    return {
        "Название": item["Название"],
        "Рейтинг": rating,
        "Отзывы": reviews,
        "Сайт": website,
        "Телефон": phone,
        "Адрес": address,
        "Ссылка": item["Ссылка"],
    }


def scrape_maps(query, target):
    start = time.time()

    # Защита от порчи данных: если у старого CSV другая схема колонок — стоп, нужна миграция
    if os.path.exists(filename) and os.path.getsize(filename) > 0:
        old_cols = list(pd.read_csv(filename, nrows=0).columns)
        if old_cols != COLUMNS:
            print("\n--- СТОП: схема файла не совпадает с текущей (нужна миграция) ---")
            print(f"    в файле: {old_cols}")
            print(f"    сейчас:  {COLUMNS}")
            print("    Остановился, чтобы не испортить CSV. Нужно мигрировать файл/таблицу под новые колонки.")
            return

    existing_links = load_existing_links(filename)
    sheets = SheetsWriter(GOOGLE_CREDS_PATH, GOOGLE_SHEET_ID)

    new_rows = []   # то, что зальём в Google Sheets пачкой
    saved = 0

    with sync_playwright() as p:
        browser = launch_browser(p)
        # Без кастомного user_agent — настоящий Chrome сам шлёт правильный
        context = browser.new_context()
        # Доп. подстраховка: гасим navigator.webdriver на уровне JS
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = context.new_page()

        try:
            newly_found = collect_links(page, query, existing_links, target)
            print(f"\n--- Нашёл {len(newly_found)} новых карточек. Собираю данные... ---")

            for i, item in enumerate(newly_found, 1):
                try:
                    print(f"[{i}/{len(newly_found)}] Захожу: {item['Название']}")
                    data = scrape_card(page, item)
                    save_row(filename, data)                 # в CSV сразу
                    new_rows.append([data[c] for c in COLUMNS])
                    saved += 1
                    print(f"    OK: рейтинг {data['Рейтинг']} ({data['Отзывы']}) | сайт: {data['Сайт'][:40]}")
                except PlaywrightTimeout:
                    if looks_like_captcha(page):
                        print("    ! Похоже на капчу — останавливаюсь, чтобы не усугублять")
                        break
                    print("    ! Карточка грузилась слишком долго — пропускаю")
                    continue
                except Exception as e:
                    print(f"    ! Ошибка на карточке: {e}")
                    continue

        except KeyboardInterrupt:
            print("\n--- Остановлено вручную. Всё собранное до этого уже в CSV. ---")
        except RuntimeError as e:
            print(f"\n--- Стоп: {e} ---")
        finally:
            browser.close()     # браузер закроется в ЛЮБОМ случае

    # Заливаем в Google Sheets пачкой — что собрали, то зальём (даже если прервали)
    sheets.append_rows(new_rows)

    elapsed = time.time() - start
    with_site = sum(1 for r in new_rows if r[COLUMNS.index("Сайт")] != "Не найден")
    total_now = len(existing_links) + saved

    print("\n" + "=" * 52)
    print(f" ИТОГ по запросу: {query}")
    print(f"   Добавлено новых : {saved}  (с сайтом: {with_site})")
    print(f"   Всего в базе    : {total_now}")
    print(f"   Время           : {elapsed:.0f} сек")
    print(f"   CSV-файл        : {os.path.abspath(filename)}")
    if GOOGLE_SHEET_ID:
        print(f"   Google-таблица  : https://docs.google.com/spreadsheets/d/{GOOGLE_SHEET_ID}/edit")
    print("=" * 52)


# ЗАПУСК
if __name__ == "__main__":
    scrape_maps(search_query, target_count)
