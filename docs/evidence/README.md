# Подтверждения проверок

## Почтовый сценарий и YDB

- [Ответ по базе знаний](qa-printer-answer-final.png): инструкция и документ printer.md.
- [Подтверждение заявки](qa-printer-ticket-final.png): ID a26b4494-1713-488c-8791-464c9fb4279e.
- `qa-printer-ticket-verified.json`: прямое чтение YDB подтвердило open/bug, владельца и связь двух реплик с тикетом.
- `qa-live.json`: реальные inline-трейсы Responses API, RAG и MCP, четыре реплики, точное совпадение usage с YDB. Тестовые записи удалены.
- `qa-token-report.json`: обезличенный экспорт YDB, токены и частичный месячный бюджет.

## Поиск и согласие

- `rag-index.json`: индекс и хеши восьми учебных документов.
- `rag-checks.json`: реальные API-проверки известного и неизвестного вопросов.
- [Ответ про командировку](rag-known-email.png).
- [Вопрос вне базы](rag-unknown-email.png): отсутствие информации и предложение создать тикет.
- [Заявка после согласия](rag-ticket-email.png); `rag-ticket.json` подтверждает запись docs/open в YDB.

## Эскалация

- [Успешный запуск workflow](escalation-success.png).
- [Доставленный дайджест](escalation-email.png).
- `escalation-execution.json`, `escalation-digest.txt`: выполнение и текст дайджеста.
- `escalation-ticket.json`: проверенный статус escalated.
- `escalation-repeat.json`: повтор без повторной отправки.
- `escalation-schedule.json`: расписание 09:00 Europe/Moscow.

## Защита

- `guardrail-checks.json`, `guardrail-injection.json`: реальные проверки классификатора и блокировки инструмента.
- `guardrail-deployment.json`: сведения о развёртывании защиты.
- `pii-storage-check.json`: проверенные маски в tickets/messages и связь реплик.
- [Почтовой тест PII](pii-ticket-email.png).
- `logging-unavailable.json`: предоставленное пользователем сообщение UI об ограниченном режиме платформы. Фактические облачные логи на PII не проверены.

Скриншоты предоставлены пользователем и проверены визуально. Промежуточные
неуспешные проверки и дубли не входят в комплект сдачи. Снимок консоли с балансом
также исключён; информация об ограничении логов сохранена текстом.
