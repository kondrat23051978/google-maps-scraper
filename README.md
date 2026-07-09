# Google Maps Business Scraper → Google Sheets

Collects business listings from Google Maps for a given search query and
location (name, rating, review count, website, phone, address, map link) and
exports them to a clean CSV / Google Sheets — built for lead generation,
competitor analysis, and local market research.

**Engineering highlights:**
- Browser automation with Playwright (handles Google Maps' dynamic, infinite-scroll result list)
- Deduplication across repeated runs, so re-running doesn't re-collect the same listings
- Direct Google Sheets export via a service account — falls back to CSV-only if no credentials are configured, nothing breaks
- Small standalone test runner for a quick sample-size dry run before a full scrape

**Stack:** Python, Playwright, Google Sheets API (gspread), Pandas.

**Example use cases:** lead lists for local-SEO/marketing agencies, competitor
mapping in a given city or district, cold-outreach list building.

## Setup

1. `pip install -r requirements.txt` (Playwright also needs a one-time `playwright install chromium`)
2. Edit the config block at the top of `main.py` — search keyword, location, how many new listings to collect per run
3. *(Optional)* Google Sheets export: create a Google Cloud service account, download its JSON key as `service_account.json` in the project folder, share your target spreadsheet with the service account's email, and set `GOOGLE_SHEET_ID` in `main.py`
4. Run: `python main.py`

Without `service_account.json` configured, the script simply writes to CSV —
no errors, no missing functionality.

## Output columns

`Назва` (Name) · `Рейтинг` (Rating) · `Відгуки` (Review count) · `Сайт` (Website) · `Телефон` (Phone) · `Адреса` (Address) · `Посилання` (Map link)
