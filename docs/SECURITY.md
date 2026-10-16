# Безопасность и данные

## Секреты

- Храните API keys, IAM tokens, Telegram token и IMAP/SMTP credentials только
  в `.env` или внешнем secret store.
- Не коммитьте `.env`, service-account keys, SQLite, diagnostic records,
  OCR JSON, исходные документы или generated artifacts.
- Используйте один способ Vision auth за раз и ограниченные по scope/сроку
  credentials. Регулярно ротируйте ключи.
- Ограничьте права `.env` (`chmod 600`) и доступ к Docker operator account.

## Пользовательские документы

Документы и OCR JSON могут содержать персональные и коммерческие данные.
Храните их вне Git, ограничивайте retention и не включайте в issue, PR или
логи. Не записывайте raw OCR response в production diagnostics.

`OCR_DIAGNOSTICS_DIR` предназначен только для минимизированных локальных
diagnostic records. Он не сохраняет исходный текст, но может хранить геометрию
и числовые tokens; используйте его только в контролируемом writable location.

## Транспорт

- Telegram polling не удаляет существующий webhook.
- Email принимает задания только от exact normalized allowlist. Не используйте
  `Reply-To` для доставки результата.
- Заголовок `From` не защищает от spoofing: включите SPF/DKIM/DMARC на почтовом
  хостинге и применяйте его результаты на уровне mailbox policy.
- Автоматические письма, mailing-list сообщения и собственные ответы
  игнорируются для предотвращения циклов.

## Эксплуатация

Контейнеры работают non-root с read-only root filesystem и ограниченным `/tmp`.
Email state хранится в отдельном named volume. Не запускайте destructive Docker
команды без подтверждённого backup. Перед публикацией выполните проверку:

```bash
git status --short
git diff --cached --check
git ls-files | rg '(^|/)(\.env|.*\.(sqlite|db|pdf|png|jpe?g|json)$)'
```
