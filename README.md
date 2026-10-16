# OCR Bot v2

OCR Bot v2 восстанавливает редактируемые документы из изображений и PDF. Он
использует Yandex Vision OCR, сохраняет смысловую структуру документа во
внутренней модели и отдаёт короткий текст прямо в канал доставки либо создаёт
редактируемый DOCX.

Поддерживаются два независимых канала: Telegram long polling и электронная
почта через стандартные IMAP/SMTP. Они используют один OCR pipeline и не
содержат собственной логики распознавания.

## Возможности

- Приём JPG/JPEG, PNG, WEBP, BMP, TIFF/TIF и PDF.
- Постраничная обработка многостраничных TIFF и PDF в исходном порядке.
- Извлечение пригодного текстового слоя PDF через PyMuPDF без повторного OCR;
  сканированные страницы направляются в Vision.
- Восстановление абзацев, заголовков, порядка чтения и геометрии OCR-блоков.
- Преобразование нативных таблиц Yandex Vision в редактируемые таблицы DOCX,
  включая пустые и объединённые ячейки.
- Осторожное визуальное восстановление таблиц с видимой сеткой через OpenCV.
  Оно отключено по умолчанию и не заменяет неподтверждённую структуру.
- Генерация DOCX с абзацами, заголовками, разрывами страниц и таблицами.
- Smart Output Delivery: простой текст до заданного лимита отправляется в
  Telegram или в тело ответного письма; таблицы и длинные документы — DOCX.
  В Telegram для inline-ответа доступна кнопка «Получить DOCX».
- Telegram и Email с allowlist отправителей, защитой от повторной обработки и
  сохранением состояния Email-доставки в SQLite.

OCR не гарантирует стопроцентную точность. Особенно внимательно проверяйте
небольшие числовые значения, сложные таблицы, объединения ячеек и исходное
оформление документа.

## Архитектура

```text
Telegram Adapter ─┐
                  ├─> DocumentOCRService ─> InputPreprocessor
Email Adapter ────┘             │                    │
                                │                    ├─> native PDF text
                                │                    └─> Yandex Vision Client
                                │                              │
                                └─> Document Model <───────────┘
                                          │
                         OutputPolicy ───┴───> inline text / DOCX Renderer
```

`DocumentOCRService`, Document Model, OutputPolicy и DOCX Renderer не зависят
от Telegram или IMAP/SMTP. Детали Yandex JSON ограничены provider mapper;
рендерер получает только независимую Document Model. Подробнее — в
[архитектуре](docs/ARCHITECTURE.md).

## Технологии

- Python 3.12 и [uv](https://docs.astral.sh/uv/);
- httpx и Yandex Vision OCR;
- Pydantic v2, Pillow, PyMuPDF и OpenCV;
- python-docx;
- aiogram 3;
- стандартные `imaplib`, `smtplib` и SQLite;
- Docker Compose.

## Локальный запуск

Установите `uv`, затем создайте окружение по зафиксированному `uv.lock`:

```bash
uv sync --locked
uv run pytest -q
```

Создайте локальный `.env` из шаблона. `.env` не коммитится:

```bash
cp .env.example .env
```

Заполните ровно один метод авторизации Vision (`YANDEX_VISION_API_KEY` или
`YANDEX_VISION_IAM_TOKEN`) и `YANDEX_CLOUD_FOLDER_ID`. Для Telegram нужен
`TELEGRAM_BOT_TOKEN`. Для Email заполните блок `OCR_EMAIL_*`, включая
`OCR_EMAIL_ALLOWED_SENDERS` с полными адресами через запятую.

Запуск адаптеров выполняйте раздельно. Сам запуск не отправляет OCR-запрос:

```bash
uv run python -m ocr_document_bot.telegram_bot
uv run python -m ocr_document_bot.email_bot
```

Не запускайте второй polling-процесс с тем же Telegram token или тем же
почтовым ящиком и SQLite state. Перед Telegram polling приложение проверяет
webhook и отказывается запускаться, не удаляя существующий webhook.

## Конфигурация и лимиты

Все имена переменных и безопасные значения по умолчанию находятся в
[.env.example](.env.example). Важные параметры:

- `OCR_MAX_FILE_SIZE_BYTES`, `OCR_MAX_PAGES`, `OCR_MAX_JOB_SIZE_BYTES` —
  ограничения входного задания;
- `OCR_PDF_RENDER_DPI`, `OCR_MAX_RENDERED_PIXELS`,
  `OCR_PDF_TEXT_MIN_CHARS` — обработка PDF;
- `OCR_INLINE_TEXT_MAX_CHARS` — лимит inline-текста, по умолчанию 2500;
- `OCR_ENABLE_VISUAL_TABLE_DETECTION` — опциональное восстановление сетки
  таблиц, по умолчанию выключено;
- `OCR_ENABLE_CELL_RECOVERY` — ограниченное дополнительное OCR пустых ячеек,
  по умолчанию выключено и потенциально тарифицируется;
- `OCR_DIAGNOSTICS_DIR` — только для локальной обезличенной диагностики; в
  контейнере оставляйте пустым, если не подготовлен отдельный writable volume.

Email allowlist сравнивает нормализованные полные адреса, а не домены или
подстроки. Заголовок `From` сам по себе не является криптографическим
доказательством личности: настройте SPF/DKIM/DMARC на стороне почтового
хостинга.

## Docker Compose

Один образ обслуживает оба сервиса; порты не публикуются. Email SQLite хранится
в named volume `ocr-document-bot-email-state` и переживает пересоздание
контейнера.

```bash
# Проверка конфигурации и сборка без запуска polling.
docker compose config --quiet
docker compose build

# Явный запуск нужного сервиса.
docker compose up -d ocr-telegram
docker compose up -d ocr-email

# Эксплуатация.
docker compose ps
docker compose logs -f ocr-telegram
docker compose logs -f ocr-email
docker compose stop ocr-telegram
docker compose restart ocr-email
```

Для обновления образа без потери Email-state оставьте named volume нетронутым:

```bash
docker compose build
docker compose up -d --no-deps --force-recreate ocr-telegram ocr-email
```

Healthcheck подтверждает, что процесс жив, но не может доказать доступность
внешних Telegram, IMAP, SMTP или Vision. Для production нужен внешний canary
и мониторинг логов. См. [DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Ограничения

- Используется синхронный постраничный OCR: очень большие документы требуют
  отдельного async-процесса с durable job state.
- Таблицы без нативной структуры или надёжной видимой сетки могут остаться
  обычным текстом — это безопаснее ложной таблицы.
- Исходный дизайн не воспроизводится пиксель-в-пиксель; DOCX ориентирован на
  редактирование.
- XLSX, Web UI, публичный API и монетизация пока не реализованы.

Документы по эксплуатации, безопасности и дальнейшему развитию:
[архитектура](docs/ARCHITECTURE.md), [развёртывание](docs/DEPLOYMENT.md),
[безопасность](docs/SECURITY.md), [roadmap](docs/ROADMAP.md).
