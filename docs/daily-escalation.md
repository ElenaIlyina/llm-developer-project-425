# Ежедневная эскалация

## Назначение

Workflow daily-escalation ежедневно в 09:00 Europe/Moscow выбирает открытые
заявки старше 24 часов и отправляет дайджест оператору. Спецификация находится
в src/workflow.yaml, промпт — в prompts/daily-escalation.md.

По согласованию с преподавателем aiStudioAgent заменён на foundationModelsCall:
runtime-agent ID несовместим с ожидаемым promptTemplateId. Системный промпт
передаётся прямо в workflow; отдельный ID агента для дайджеста не нужен.

## Последовательность

1. DatabaseQuery выбирает до 20 open-заявок старше 24 часов, обрезая текст до
   500 Unicode-символов. Возраст рассчитывается в UTC.
2. Switch завершает процесс без письма при пустой выборке.
3. FoundationModelsCall формирует дайджест. Текст берётся из
   alternatives[0].message.text, usage сохраняется в model_usage.
4. Пустой дайджест останавливает процесс до изменения заявок.
5. DatabaseQuery переводит только выбранные ID в escalated.
6. HTTPCall передаёт subject/body функции email-sender.
7. При окончательном сбое отправки выбранные заявки возвращаются в open,
   выполнение завершается с ошибкой.

Повторы: retryCount=3 с задержкой 2–15 секунд для настроенных тайм-аутов,
недоступности БД и HTTP 502/503/504. Ошибки прав не включены в повторы.
email-sender отправляет только фиксированному OPERATOR_EMAIL из окружения;
передать произвольного получателя в запросе нельзя. Пароль SMTP — в Lockbox.

## Развёртывание и обновление

Для нового каталога следуйте [setup.md](setup.md), раздел 6. Функция email-sender
должна существовать до запуска скрипта:

```bash
source .venv/bin/activate
set -a
source .env
set +a
bash scripts/deploy-escalation.sh
```

Скрипт разворачивает sender, генерирует и валидирует src/workflow.yaml,
создаёт отсутствующий workflow либо обновляет существующий и назначает SA
роли executor/viewer на workflow. Сам скрипт не задаёт новое расписание.

Ручной запуск отправляет настоящее письмо, если есть подходящие заявки:

```bash
yc serverless workflow execution start daily-escalation
```

После проверки включите расписание:

```bash
yc serverless workflow update --name daily-escalation \
  --schedule-cron-expression '0 0 9 * * *' --schedule-timezone Europe/Moscow
```

Cron workflow имеет шесть полей с секундами; формат таймера поллера отличается.
Проверьте доставку письма, статусы заявок через ydb-tickets и историю выполнения
в Workflows. Подтверждения — [evidence/README.md](evidence/README.md).

## Ограничения

SMTP и UPDATE не образуют общей транзакции: при потере ответа после доставки
возможен повтор письма. Компенсация не гарантирует exactly-once. За один запуск
выбирается до 20 заявок; остальные подходят для следующего запуска.
HTTP-вызов email-sender открыт в рамках учебной схемы, получатель фиксирован.
