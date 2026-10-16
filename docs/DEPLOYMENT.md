# Развёртывание и эксплуатация

## Подготовка

На хосте должны быть Docker Engine и Docker Compose v2. Клонируйте репозиторий
в каталог, доступный оператору Docker, и создайте `.env` с правами `600`:

```bash
cp .env.example .env
chmod 600 .env
```

Заполните обязательные Vision, Telegram и/или Email variables. Перед запуском
проверьте конфигурацию без вывода развёрнутых значений:

```bash
docker compose config --quiet
```

## Первый запуск

Сборка сама по себе не запускает adapters:

```bash
docker compose build
docker compose up -d ocr-email
docker compose up -d ocr-telegram
docker compose ps
```

Запускайте сервисы последовательно и проверяйте логи. Не запускайте несколько
Telegram pollers с одним token или несколько Email pollers с одним mailbox и
SQLite state.

## Эксплуатация

```bash
docker compose logs -f ocr-telegram
docker compose logs -f ocr-email
docker compose restart ocr-telegram
docker compose stop ocr-email
docker compose up -d ocr-email
```

Healthcheck подтверждает живой процесс, но не внешнюю связность. Наблюдайте
bounded logs, restart count и внешний canary на разрешённом тестовом документе.
Не включайте `OCR_DIAGNOSTICS_DIR` в read-only контейнере без отдельного
writable volume и retention policy.

## Обновление

Сначала получите проверенный commit, затем соберите образ и пересоздайте только
нужные сервисы. Named volume Email не удаляйте:

```bash
docker compose build
docker compose up -d --no-deps --force-recreate ocr-telegram ocr-email
```

При изменении `.env` пересоздайте только затронутый контейнер тем же способом.
Это необходимо, потому что environment читается при создании контейнера.

## SQLite backup и восстановление

Останавливайте Email перед backup или restore:

```bash
docker compose stop ocr-email
docker run --rm -v ocr-document-bot-email-state:/data -v "$PWD":/backup alpine \
  tar -czf /backup/email-state-backup.tgz -C /data .

# Restore выполняйте только после сохранения отдельной резервной копии.
docker run --rm -v ocr-document-bot-email-state:/data -v "$PWD":/backup alpine \
  tar -xzf /backup/email-state-backup.tgz -C /data
docker compose up -d ocr-email
```

SQLite содержит состояние обработки почты. Потеря или замена volume может
изменить IMAP baseline и привести к повторной обработке, поэтому восстановление
должно быть явным операторским действием.
