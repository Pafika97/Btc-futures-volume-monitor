# BTC Futures Volume Monitor

Отслеживает объём торговли BTC-фьючерсами на нескольких биржах (Binance, Bybit, OKX, Deribit), сохраняет временной ряд в SQLite и присылает оповещения, когда 24h объём заметно меняется относительно недавнего окна.

## Что умеет
- Каждую `POLL_INTERVAL_SEC` секунду обращается к публичным REST-эндпоинтам бирж
- Суммирует и логирует 24h объёмы в USD-эквиваленте
- Сохраняет значения в SQLite (`btc_futures_volumes.sqlite`)
- Считает изменение объёма относительно среднего за последние `WINDOW_MINUTES` минут и шлёт алерты в Telegram при превышении порога `ALERT_CHANGE_PCT`

> Примечание: 24h volume — скользящая метрика самой биржи. Изменения в течение минут отражают динамику притока/оттока объёма и волатильность рынка.

## Быстрый старт
1) Установите Python 3.10+
2) Создайте окружение и зависимости:
```bash
python -m venv .venv
. .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```
3) Скопируйте конфиг и укажите параметры (опционально Telegram):
```bash
cp .env.example .env
# Отредактируйте .env
```
4) Запустите монитор:
```bash
python btc_futures_volume_monitor.py
```

## Настройки (`.env`)
- `POLL_INTERVAL_SEC` — период опроса (сек), по умолчанию 60
- `ALERT_CHANGE_PCT` — порог изменения (%) относительно среднего за окно
- `WINDOW_MINUTES` — ширина окна усреднения (мин)
- `LOG_TO_STDOUT` — true/false логировать в консоль
- `EXCHANGES` — список через запятую: `binance,bybit,okx,deribit`
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` — чтобы получать алерты в Telegram

## Что за метрики
Мы агрегируем 24h объёмы по бессрочным контрактам (perpetuals):
- **Binance**: USDT-M (BTCUSDT perpetual), Coin-M (BTCUSD_PERP)
- **Bybit**: linear (BTCUSDT), inverse (BTCUSD)
- **OKX**: BTC-USDT-SWAP, BTC-USD-SWAP
- **Deribit**: BTC-PERPETUAL

Части API возвращают объём в BTC, части — в quote (USDT/USD). Скрипт пересчитывает всё в USD по актуальной цене инструмента на той же бирже. Это приблизительная, но практически полезная консолидация.

## База данных
Файл `btc_futures_volumes.sqlite` содержит таблицу `volumes`:
```
ts (unix seconds), exchange (text), base_volume_btc (real), quote_volume_usd (real)
```
Пример запроса для выгрузки последних значений:
```sql
SELECT datetime(ts, 'unixepoch') as utc_time, exchange, quote_volume_usd
FROM volumes
ORDER BY ts DESC
LIMIT 50;
```

## Telegram-алерты
Создайте бота у @BotFather, получите `TELEGRAM_BOT_TOKEN` и свой `TELEGRAM_CHAT_ID`.
Укажите их в `.env`, чтобы получать уведомления при резком изменении объёма.

## Расширение
- Добавьте новые источники в `exchanges.py` (функция должна возвращать dict с ключами: `exchange`, `base_volume_btc`, `quote_volume_usd`, `last_price_usd`).
- Можно подключить CME (непубличные/отложенные источники), Coinglass/Laevitas (обычно требуют ключ/подписку): добавьте адаптер и расчёт.

## Ограничения и дисклеймер
- Публичные API могут менять поля или лимиты. Обработчики написаны с защитой от ошибок, но периодически стоит проверять.
- 24h объём на каждой бирже считается по их правилам — агрегировано это *не* официальная сумма рынка, а удобная прокси.