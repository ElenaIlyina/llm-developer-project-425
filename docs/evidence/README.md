# Подтверждения проверок

## Почтовые проверки после исправлений ревью

| Сценарий | Скрин | Проверка данных |
| --- | --- | --- |
| Опасная просьба → отказ без предложения заявки | [Отказ](review-dangerous-request-email.png) | Автоматическая регрессия в review-security-regressions.json |
| «Да» после опасной просьбы → отказ | [Повторный отказ](review-dangerous-consent-email.png) | Регрессия включает намеренно подставленное старое опасное предложение |
| Вопрос про принтер → инструкция и источник printer.md | [Ответ из базы](review-printer-rag-email.png) | review-rag-context.json: поиск с пустой и доступной историей |
| Явная просьба → один тикет | [Подтверждение](review-printer-ticket-email.png) | review-printer-ticket-verified.json: open/bug, владелец, две связанные реплики; одна заявка в окне ±2 минуты |
| Благодарность с цитатой → ответ без действия | [Благодарность](review-quoted-thanks-email.png) | review-quoted-thanks-verified.json: текст без цитаты, ticket_id=null, новых заявок в цикле нет |

Новые почтовые материалы получены 16.11.2026. ID проверенного тикета:
5e9db75c-46d4-5ce3-923a-452905c3b57f. Ограничения области проверки указаны
в соответствующих JSON; скрин сам по себе не доказывает запись в YDB.

## Актуальные автоматические проверки

- `qa-live.json`: настоящий output[] модели, корневой usage, сравнение с YDB,
  четыре реплики и две связи. controller_mcp_calls содержит отдельно выполненный
  MCP-вызов; повтор request_id проверен без второго тикета. SMTP подменён,
  случайные тестовые строки удалены.
- `review-security-regressions.json`: отказ на приказ и согласие, команда в
  Gmail-цитате без создания, блокировка реального прямого MCP. Для старого опасного
  предложения явно используется fixture; SMTP подменён, YDB очищена от тестовых строк.
- `review-rag-context.json`: поиск printer.md с пустой и текущей историей,
  без отправки писем и записи в YDB.
- `review-deployment.json`: версии развёрнутых компонентов и состояние таймера.

## RAG, согласие и маскирование

- `rag-index.json`: состав индекса, хеши восьми учебных документов.
- `rag-checks.json`: реальные API-проверки вопроса из базы и вопроса вне базы.
- [Командировка](rag-known-email.png), [нет информации](rag-unknown-email.png),
  [согласие на заявку](rag-ticket-email.png); `rag-ticket.json` — чтение тикета.
- `guardrail-checks.json`, `guardrail-injection.json`: классификатор и блокировка.
- `pii-storage-check.json`: маски в tickets/messages, включая прямую запись;
  [почтовой тест PII](pii-ticket-email.png).
- `logging-unavailable.json`: предоставленное пользователем сообщение UI об
  ограниченном режиме платформы. Облачные логи на отсутствие PII не проверены.

## Эскалация

- [Успешный workflow](escalation-success.png), [письмо](escalation-email.png).
- [Дайджест четырёх заявок](escalation-digest-four-tickets.png) и
  [статусы escalated в YDB](escalation-four-tickets-ydb.png).
- `escalation-execution.json`, `escalation-digest.txt`, `escalation-ticket.json`:
  выполнение, текст и проверенный статус.
- `escalation-repeat.json`: повтор без повторной отправки;
  `escalation-schedule.json`: расписание 09:00 Europe/Moscow.
- `escalation-four-tickets-verified.json`: сверка четырёх ID с дайджестом.

## Первоначальные снимки для сопоставления

Материалы 5–7 ноября относятся к предыдущей версии; не являются новыми прогонами:

- [Ответ](qa-printer-answer-final.png), [тикет](qa-printer-ticket-final.png),
  [YDB](qa-printer-ydb.png); `qa-printer-ticket-verified.json`.
- [Поиск](qa-trace-search.png), [MCP](qa-trace-mcp.png), [usage](qa-trace-usage.png).
  ID этих трейсов отличаются от текущего qa-live.json. Их синтетические тикеты удалены.
- `guardrail-deployment.json`: первоначальное развёртывание защиты.
- `qa-token-report.json`: обезличенный исторический экспорт и частичный бюджет
  по тарифам 06.11.2026; не полный и не текущий счёт.

Скриншоты предоставлены пользователем и просмотрены. Личные адреса и баланс
не публикуются. Промежуточные неуспешные прогоны и рабочие заметки вынесены
за пределы репозитория; подлинные результаты не переписываются под новый код.
