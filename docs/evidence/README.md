# Подтверждения проверок

## Почтовый сценарий и YDB

- [Ответ по базе знаний](qa-printer-answer-final.png): инструкция и документ printer.md.
- [Подтверждение заявки](qa-printer-ticket-final.png): ID a26b4494-1713-488c-8791-464c9fb4279e.
- [Прямое чтение YDB](qa-printer-ydb.png): ticket_found=true, open/bug, владелец совпадает; две реплики связаны с ID из письма.
- `qa-printer-ticket-verified.json`: прямое чтение YDB подтвердило open/bug, владельца и связь двух реплик с тикетом.
- [Учёт токенов API QA](qa-trace-usage.png): вход 907, выход 113, инструменты 1118, всего 2138; исходный usage первого ответа.
- [Поисковый трейс API QA](qa-trace-search.png): file_search_call завершён, найден printer.md со score=1.0.
- [MCP-трейс API QA](qa-trace-mcp.png): create-ticket, error=false и результат инструмента. Это отдельный синтетический QA-запуск; его тикет 6265437e-… удалён после проверки и отличается от финального почтового тикета.
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
