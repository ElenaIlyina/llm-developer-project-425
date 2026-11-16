# Подтверждения проверок

## Почтовый канал и тикеты

| Сценарий | Письмо | Проверка данных |
| --- | --- | --- |
| Опасная просьба → отказ | [Ответ](review-dangerous-request-email.png) | [Регрессии](review-security-regressions.json) |
| Согласие на опасную просьбу → отказ | [Ответ](review-dangerous-consent-email.png) | Регрессия с подставленным опасным предложением |
| Принтер → инструкция с источником | [Ответ](review-printer-rag-email.png) | [Поиск с историей](review-rag-context.json) |
| Явная просьба → один тикет | [Ответ](review-printer-ticket-email.png) | [Тикет и две связанные реплики](review-printer-ticket-verified.json) |
| Благодарность с цитатой → ответ без действия | [Ответ](review-quoted-thanks-email.png) | [Переписка и отсутствие новой заявки](review-quoted-thanks-verified.json) |

Почтовые снимки таблицы получены 16.11.2026. Область проверки указана в JSON;
скрин ответа сам по себе не подтверждает запись или отсутствие тикета в YDB.

## RAG и API

- [Индекс](rag-index.json): состав и хеши восьми учебных документов.
- [RAG](rag-checks.json): вопрос из базы и неизвестная сумма компенсации.
  Почта: [известный вопрос](rag-known-email.png), [неизвестный](rag-unknown-email.png),
  [согласие](rag-ticket-email.png), [запись тикета](rag-ticket.json).
- [Соответствие вопросу](additional-rag-scope-check.json): проверяющая модель с
  явно обозначенной фикстурой VPN и полный запрос про YouTube; без писем и записей.
- [Полный QA](qa-live.json): output[] Responses API, usage и сверка с YDB,
  четыре реплики, две связи и идемпотентный повтор. Контроллерный MCP-вызов
  записан отдельно от предложения модели. SMTP подменён; тестовые строки удалены.
- [Трейс поиска](qa-trace-search.png), [MCP](qa-trace-mcp.png),
  [usage](qa-trace-usage.png): снимки запуска 05.11.2026, отдельного от qa-live.json.

## Защита и маскирование

- [Классификатор](guardrail-checks.json), [блокировка](guardrail-injection.json).
- [Маски хранения](pii-storage-check.json), [почтовой тест](pii-ticket-email.png).
- [Паспорт, пропуск и адрес](additional-pii-storage-check.json): развёрнутый MCP
  и локальный Store с реальной YDB; синтетические строки удалены.
- [Очистка текстов](additional-pii-cleanup.json): только количества, без исходных PII.
- [Ограничение Cloud Logging](logging-unavailable.json): сообщение UI.
  Облачные логи на отсутствие PII не проверены.

Уведомления об ошибках проверены unit-тестами с подменённым SMTP;
аварийная отправка из облака отдельно не воспроизводилась.

## Эскалация

- [Успешный workflow](escalation-success.png), [письмо](escalation-email.png).
- [Дайджест четырёх заявок](escalation-digest-four-tickets.png),
  [статусы escalated](escalation-four-tickets-ydb.png),
  [сверка ID](escalation-four-tickets-verified.json).
- [Выполнение](escalation-execution.json), [текст](escalation-digest.txt),
  [тикет](escalation-ticket.json), [повтор](escalation-repeat.json),
  [расписание](escalation-schedule.json).

## Конфигурация и стоимость

- [Развёртывание](additional-deployment.json): версии функций и состояние таймера
  на момент проверки; актуальное состояние запрашивается через yc.
- [Токены и частичный бюджет](qa-token-report.json): обезличенная выборка и расчёт
  по тарифам 06.11.2026. Допущения и исключённые расходы — в [qa.md](../qa.md).
