# Ежедневная эскалация — шаг 6

## Рабочая конфигурация

Workflow daily-escalation (dfqcg7luvnnfbou3ehgm) развёрнут и запускается ежедневно
в 09:00 Europe/Moscow. Отправитель — почтовый ящик Help Desk; получатель задан
переменной OPERATOR_EMAIL в email-sender. Пароль SMTP подключён из Lockbox.

## Замена шага по согласованию с преподавателем

Новый runtime-agent help-desk (aac7c230uu7tlo9vhck0) несовместим с
aiStudioAgent.promptTemplateId: пробный запуск вернул HTTP 404.
Преподаватель разрешил заменить этот шаг на foundationModelsCall с YandexGPT
и системным промптом. ID агента из шага 3 для дайджеста не требуется.
Промпт из prompts/daily-escalation.md включается в workflow.yaml при генерации.

Реальный запуск подтвердил поле текста: alternatives[0].message.text.
usage сохраняется в model_usage; в проверке получено 227 входных и 75 выходных токенов.

## Граф

1. DatabaseQuery выбирает до 20 открытых заявок старше 24 часов, сокращая каждый
   текст до 500 Unicode-символов.
2. Switch завершает процесс при пустой выборке.
3. FoundationModelsCall составляет дайджест. Проверка пустого ответа выполняется до UPDATE.
4. DatabaseQuery переводит только выбранные ID из open в escalated.
5. HTTPCall отправляет JSON {subject, body} функции email-sender.
6. При окончательном сбое отправки выбранные заявки возвращаются в open, процесс падает.

Повторы ограничены тремя попытками с задержкой 2–15 секунд для тайм-аутов,
недоступности YDB и HTTP 502/503/504. Ошибки прав не повторяются.
DATABASE_QUERY_CONNECTION_FAILED исключён: сервис также возвращает его при
PermissionDenied во время discovery YDB.

email-sender принимает только POST с subject/body; получатель берётся из окружения.
Поле to отклоняется. HTTP-функция открыта для вызова по схеме задания,
но отправить письмо на произвольный адрес через неё нельзя.

## Развёртывание

Локальная конфигурация — OPERATOR_EMAIL и идентификаторы секретов в .env.
Значения паролей не переносить в файлы.

```bash
source .venv/bin/activate
pip install -r requirements-dev.txt
set -a
source .env
set +a
bash scripts/deploy-escalation.sh
yc serverless workflow execution start daily-escalation
```

Скрипт упаковывает sender, подключает секрет SMTP, открывает HTTP-вызов,
генерирует и валидирует src/workflow.yaml, обновляет workflow и выдаёт SA
роли serverless.workflows.executor и serverless.workflows.viewer на workflow.
Для нового каталога сначала создайте функции и workflow, как описано в комментариях скрипта.

После проверки доставки задайте расписание:

```bash
yc serverless workflow update \
  --name daily-escalation --yaml-spec src/workflow.yaml \
  --schedule-cron-expression "0 0 9 * * *" \
  --schedule-timezone Europe/Moscow
```

**Отличие от задания:** фактический API на 2026-11-05 требует шесть полей
секунда, минута, час, день месяца, месяц, день недели. Выражение из задания
0 9 * * ? * отклонено сервером. Проверка значения 2099 в последнем поле вернула
диапазон [0,7], подтвердив, что это день недели, а не год.
Принятое и прочитанное обратно расписание: 0 0 9 * * * / Europe/Moscow.
Формат таймера email-poller из шага 4 относится к другому API.

## Подтверждённые проверки

20 локальных тестов проходят. Реальный запуск от 2026-11-05:
dfqcg7luvnnfbou3ehgm-89dadae1-2adf-480e-9a5f-0e9bfc137833, FINISHED.
Успешны select_overdue, compose_digest, mark_escalated и send_digest.
SMTP принял письмо; получение в интерфейсе оператора подтверждает пользователь.

Тикет 3903c8f8-c727-4711-9ffa-84d79b9b8bd8 получил статус escalated,
что отдельно проверено запросом YDB.
Повторный запуск dfqcg7luvnnfbou3ehgm-22448463-c9eb-4198-a88e-e12da2a56fd4
вернул tickets=[] и завершился без генерации и повторной отправки.

Проверка прав ранее выполнена на отдельном SA без ролей:
DatabaseQuery завершился DATABASE_QUERY_CONNECTION_FAILED с PermissionDenied внутри,
attempts=1. Временные ресурсы этой проверки удалены.

Подлинные результаты сохранены в [evidence](evidence/README.md):
история полного запуска, текст дайджеста, статус тикета, повторный запуск и расписание.
Пользователь предоставил скрин успешного запуска и скрин письма с дайджестом.
Оба изображения проверены и приложены в docs/evidence.
Следующий плановый запуск по расписанию отдельно ещё не наблюдался.

## Ограничения и объяснение архитектуры

SMTP и UPDATE не образуют общей транзакции: при потере ответа после успешной
доставки возможен повтор. Компенсация не гарантирует строго однократную отправку.
За запуск выбирается до 20 заявок; остаток обрабатывается следующим запуском.

Почтовый poller каждую минуту забирает новые письма.
Workflow раз в день выполняет последовательность шагов над уже сохранёнными
тикетами. История выполнения показывает результаты, время и ошибки каждого шага.

[FoundationModelsCall](https://aistudio.yandex.ru/ru/docs/ai-studio/concepts/workflows/yawl/integration/foundationmodelscall)
