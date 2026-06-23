# Price Tracker

REST API сервиса отслеживания динамики цен на товары в разных интернет-магазинах
с пересчётом в выбранную пользователем валюту по **историческим** курсам (Украина → НБУ).
Фронтенда нет — только API.

## Стек

- **Python 3.12**, **Django 5** + **Django REST Framework**
- **PostgreSQL 16** (деньги — `NUMERIC`, не float)
- **Celery 5** + **Redis** (брокер и result backend) + **Celery Beat** (расписание)
- **Docker / Docker Compose**, **GitLab CI**

## Архитектура

Слои: `views (тонкие) → services / selectors → models`. Бизнес-логика — в
`services.py` / `selectors.py`, Celery-таски только оркестрируют.

Ключевые решения:

- **Цены хранятся в USD.** Любая валюта — только на отображении, через сервис
  конвертации. Добавление новой валюты не требует миграции данных — нужны лишь её курсы.
- **Историю конвертируем курсом ТОГО дня**, а не сегодняшним. Курсы НБУ храним по
  дням; для каждой точки истории берём курс её даты (с carry-forward на выходные:
  ближайший более ранний рабочий день). Это смысловое ядро задания.
- **Плагинные магазины и провайдеры валют** — через реестр интерфейсов
  (Registry + Adapter + Strategy). Новый магазин = новый адаптер + одна строка
  регистрации; ядро и другие адаптеры не трогаем (Open-Closed).
- **Денормализованные агрегаты.** Тяжёлые выборки (миллионы товаров) идут из
  `ProductDailyStat` (min/max/avg/trend на товар-день), а не из сырой `PriceRecord`.
  Сортировка по цене делается в USD (умножение на положительный курс порядок не
  меняет), конвертируются уже выбранные строки.
- **Тренд считается в USD** (собственное движение цены товара, без искажения
  девальвацией валюты отображения).
- **Масштаб.** Список — keyset-пагинация (курсор по `(цена/тренд, product_id)`),
  не `OFFSET`, чтобы глубокие страницы не деградировали на миллионах строк. История
  без диапазона ограничена окном. `PriceRecord` ключуется по дате — готова к
  range-партиционированию по годам/месяцам, когда история разрастётся.

### Celery-пайплайн

Периодические таски (Beat) оркестрируются через **chord**:

```
group( fetch_prices[shop] за каждый активный магазин )  ──┐  (параллельно)
                                                          ▼
                                            recompute_daily_stats   (callback)
                                                          ▼
                                            check_price_alerts
```

Плюс ежедневный `fetch_currency_rates` (курсы НБУ на сегодня). Все записи —
идемпотентны (`update_or_create` по натуральному ключу), внешние вызовы — с
таймаутами и ретраями; падение одного магазина не валит остальных.

## API

Базовый префикс — `/api`. Параметр `currency` (например `UAH`, `EUR`) задаёт
валюту отображения; по умолчанию — USD.

| Метод | Эндпоинт | Описание |
|-------|----------|----------|
| `GET`  | `/api/products/?currency=&ordering=price\|-price\|trend\|-trend&only_tracked=&page_size=` | список товаров с диапазоном цен и трендом; keyset-пагинация (ответ с `next`/`previous`-курсорами); `only_tracked=true` — только watchlist |
| `GET/POST/DELETE` | `/api/watchlist/`, `/api/watchlist/{id}/` | список отслеживаемых товаров пользователя |
| `GET`  | `/api/products/{id}/?currency=` | детали товара |
| `GET`  | `/api/products/{id}/prices/?currency=` | текущие цены товара по магазинам |
| `GET`  | `/api/products/{id}/history/?currency=&shop=&date_from=&date_to=` | история цен (каждая точка — по курсу своей даты); без диапазона — последние 90 дней |
| `POST` | `/api/products/{id}/alerts/` | создать алерт: `{ "target_price": ..., "currency": "..." }` |
| `GET`  | `/api/alerts/` | список своих алертов |
| `DELETE` | `/api/alerts/{id}/` | удалить алерт |

Алерты привязаны к пользователю — каждый видит только свои. Уведомления приходят
письмом (по умолчанию — в консоль), без спама (контроль по `last_notified_date`).

## Запуск через Docker

```bash
cp .env.example .env          # при необходимости поправь секреты
docker compose up --build     # поднимет db, redis, web, worker, beat
```

`web` при старте сам дождётся БД и применит миграции (`deploy/entrypoint.sh`).
Дальше наполни демо-данными и собери первые цены:

```bash
docker compose exec web python manage.py seed_demo       # магазины/товары/демо-watchlist
docker compose exec web python manage.py backfill_rates  # исторические курсы НБУ за 35 дн.
docker compose exec web python manage.py fetch_now       # разовый сбор цен+курсов+агрегатов
```

API будет на `http://localhost:8000/api/`.

## Локальный запуск (без Docker)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

cp .env.example .env          # POSTGRES_HOST=localhost, redis://localhost:6379/...
python manage.py migrate
python manage.py seed_demo
python manage.py runserver

# в отдельных терминалах:
celery -A config worker -l info
celery -A config beat -l info
```

## Тесты и качество

```bash
make test              # тесты (USE_SQLITE=1 — без поднятия Postgres)
make lint              # ruff + mypy
# или против Postgres:  pytest   (нужны POSTGRES_*-переменные окружения)
```

## Структура

```
apps/            доменные приложения (accounts, catalog, currency, pricing, alerts)
config/          settings, urls, wsgi, celery app
deploy/          entrypoint.sh (web)
tests/           тесты
```
