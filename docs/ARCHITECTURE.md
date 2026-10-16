# Архитектура OCR Bot v2

## Границы системы

OCR Bot v2 — детерминированный сервис восстановления документов. Транспортные
адаптеры получают файл и доставляют готовый результат; распознавание и
формирование документа находятся в общем application layer.

```text
Telegram / IMAP
      │
      ▼
InputFile → InputPreprocessor → DocumentOCRService → Document Model
                    │                    │                   │
             native PDF text       Yandex Vision       OutputPolicy
                                         │                   │
                                 Yandex mapper       inline / DOCX Renderer
```

## Модули

| Модуль | Ответственность | Не делает |
| --- | --- | --- |
| `adapters.telegram` | Telegram update, скачивание, inline/DOCX delivery | Не интерпретирует OCR JSON. |
| `adapters.email` | IMAP polling, allowlist, MIME-вложения, SMTP reply, SQLite ledger | Не выполняет OCR parsing или rendering rules. |
| `preprocessing` | Форматы, лимиты, TIFF/PDF pages, native PDF text | Не принимает решения о доставке. |
| `ocr_engine` | Постраничная оркестрация, cell recovery | Не зависит от транспорта. |
| `providers` | Vision HTTP, конфигурация, mapper, диагностическая обёртка | Не рендерит DOCX. |
| `document_model` | Pydantic Document/Page/Paragraph/Heading/Table/Picture и reading order | Не хранит credentials или raw JSON. |
| `renderers` | Document Model → DOCX | Не читает Yandex JSON. |
| `output_policy` | Решение inline или DOCX по структуре и лимиту текста | Не отправляет сообщение или письмо. |

## Обработка входа

`InputPreprocessor` допускает JPG/JPEG, PNG, WEBP, BMP, TIFF/TIF и PDF.
WEBP/BMP/TIFF приводятся к JPEG; TIFF обрабатывается покадрово. PDF проверяется
постранично: пригодный текстовый слой извлекается локально, а scan page
растеризуется в ограниченный JPEG для Vision. Порядок страниц сохраняется.

Для OCR-page `DocumentOCRService` вызывает Vision, передаёт ответ в mapper и
добавляет результат в Document Model. Внутренняя модель не привязана к схеме
провайдера. Native `tables[]` имеют приоритет; при их отсутствии опциональный
visual detector создаёт таблицу только при подтверждённой геометрии. Неуверенный
результат сохраняет исходные блоки.

## Модель и рендеринг

Document Model сохраняет страницы, исходный порядок, текст, геометрию и
provenance. Reading Order Resolver не предполагает корректность `blocks[]`.
DOCX renderer сохраняет порядок элементов, абзацы, заголовки, таблицы,
объединения ячеек и разрывы страниц. Оформление является удобным стандартным,
а не копией исходного дизайна.

`OutputPolicy` уважает явный выбор формата. В автоматическом режиме простой
текст в пределах `OCR_INLINE_TEXT_MAX_CHARS` идёт inline; таблицы, сложная
структура и длинный текст становятся DOCX.

## Надёжность

Email хранит IMAP baseline и delivery states в SQLite. Письмо помечается
завершённым только после SMTP success; неопределённая отправка не повторяется
автоматически. Allowlist включён по умолчанию, циклические и автоматические
письма отсеиваются.

OCRJob type хранит базовый lifecycle (`received → preprocessing → recognizing
→ rendering → completed/failed`). Полный durable event log и мониторинг пока
не реализованы. Необязательная Vision-диагностика не должна быть зависимостью
OCR: ошибки её persistence не отменяют уже полученный provider response.

## Runtime и безопасность

Docker Compose запускает Telegram и Email как независимые процессы одного
образа, без опубликованных портов. Root filesystem read-only; `/tmp` —
ограниченный tmpfs. Email SQLite вынесен в named volume. Секреты поступают
только из runtime environment; `.env` не входит в image или Git.

Подробнее об эксплуатационных действиях — [DEPLOYMENT.md](DEPLOYMENT.md), о
границах обработки данных — [SECURITY.md](SECURITY.md).
