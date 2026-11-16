# Развёртывание с нуля

Выполняйте из корня клонированного репозитория в Bash. Нужны Python 3.12,
Yandex Cloud CLI, jq и права администратора выбранного учебного каталога.
Приведённые команды создания ресурсов выполняются один раз: при повторном
развёртывании используйте существующие ресурсы. Не запускайте команды с секретами
при включённом shell tracing (`set -x`).

## 1. Окружение и сервисный аккаунт

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt -r requirements-rag.txt
yc init
FOLDER_ID=$(yc config get folder-id)
yc iam service-account create --name ai-studio-sa
SA_ID=$(yc iam service-account get --name ai-studio-sa --format json | jq -er .id)
for ROLE in functions.functionInvoker serverless.mcpGateways.invoker lockbox.payloadViewer ai.languageModels.user ai.assistants.editor ydb.editor; do
  yc resource-manager folder add-access-binding "$FOLDER_ID" \
    --role "$ROLE" --service-account-id "$SA_ID"
done
```

Аккаунту, выполняющему деплой, нужны права назначать этот SA ресурсам.
Для локального облачного QA дополнительно нужны чтение YDB/Lockbox и право
создавать токен от имени SA. В функциях используется metadata IAM, не постоянный ключ.

## 2. Ящик, YDB и Lockbox

Создайте отдельный ящик, включите IMAP и пароль приложения «Почта» в Яндекс ID.
Через консоль Lockbox создайте секрет `email-credentials` с ключом `password`.
Не передавайте пароль в аргументе команды или в Git.

```bash
yc ydb database create help-desk-db --serverless
yc ydb database get help-desk-db --format json
```

Дождитесь RUNNING. Endpoint вида grpcs://host:2135 и полный database path
из подключения сохраните в Lockbox: `ydb-endpoint/value` и `ydb-database/value`.
Сохраните ID всех трёх секретов и текущих версий.

Если `.env` ещё нет, скопируйте `.env.example`. Заполните шесть ID секретов/версий,
HELPDESK_MAILBOX, OPERATOR_EMAIL. Установите RAG_SCORE_THRESHOLD=0.35,
GUARDRAIL_FAIL_OPEN=true (режим задания; false — отказ при недоступном классификаторе).
AI_STUDIO_AGENT_ID необязателен. MCP_SERVER_URL и SEARCH_INDEX_ID заполняются далее.

```bash
set -a
source .env
set +a
export YDB_ENDPOINT=$(yc lockbox payload get "$YDB_ENDPOINT_SECRET_ID" --format json | jq -er '.entries[] | select(.key=="value") | .text_value')
export YDB_DATABASE=$(yc lockbox payload get "$YDB_DATABASE_SECRET_ID" --format json | jq -er '.entries[] | select(.key=="value") | .text_value')
export YC_IAM_TOKEN=$(yc iam create-token)
python scripts/init_schema.py src/ydb_tickets/schema.sql
unset YC_IAM_TOKEN YDB_ENDPOINT YDB_DATABASE
```

Скрипт создаёт только отсутствующие таблицы и не удаляет существующие данные.

## 3. Функция тикетов и MCP

```bash
yc serverless function create --name ydb-tickets
bash scripts/deploy-ydb-tickets.sh
```

Скрипты деплоя скачивают совместимые Linux/Python 3.12 wheels локально
в игнорируемый .build и включают их в ZIP. Установка в Cloud Functions
идёт без PyPI; локальной машине нужен доступ к PyPI при подготовке пакета.
Архивы больше 3,5 MB загружаются через уникальный временный приватный бакет
Object Storage; после сборки объект и бакет удаляются. У деплоера должны быть
права на создание, загрузку и удаление этих временных ресурсов (storage.editor).

Получите ID через `yc serverless function get ydb-tickets --format json`.
Замените оба `function_id` в `src/ydb_tickets/mcp-tools.yaml` на свой ID:
файл в репозитории настроен на каталог автора.

```bash
yc serverless mcp-gateway create --name ydb-tickets-mcp \
  --service-account-id "$SA_ID" --tools-file src/ydb_tickets/mcp-tools.yaml
```

Значение base_domain превратите в `https://<base_domain>/sse` и запишите в
MCP_SERVER_URL файла `.env`. Шлюз остаётся приватным; SA имеет роль invoker.

## 4. Индекс — до деплоя поллера

```bash
python scripts/create_search_index.py
set -a
source .env
set +a
```

Команда загружает восемь документов, ждёт готовности индекса и записывает
SEARCH_INDEX_ID в `.env`. При уже заполненном ID повторный индекс не создаётся.
Для своего GitHub измените URL в knowledge-base и src/knowledge_sources.json
до загрузки корпуса. Скрипты создают IAM-токены на время вызова; не записывайте их в .env.

## 5. Поллер и приёмочный тест

```bash
yc serverless function create --name email-poller
bash scripts/deploy-email-poller.sh
python -m unittest discover -s tests -v
python scripts/check_qa_flow.py
```

QA вызывает реальные API и MCP, подменяет SMTP и удаляет синтетические записи.
Создание проходит через локальный контроллер: модель выдаёт proposal, поллер
выполняет один MCP-вызов, request_id обеспечивает повторное использование тикета.
Токены и контроллерный MCP-трейс сохраняются отдельно, без имитации output[] модели.

Отправьте письмо с другого ящика. До создания таймера выполните один ручной запуск:

```bash
yc serverless function invoke email-poller
```

Проверьте ответ по базе, затем явную просьбу создать bug-тикет и список заявок.
При отсутствии письма проверьте **Спам** в обоих ящиках. Входящее обращение
для поллера должно находиться во Входящих и оставаться непрочитанным.
После успешной проверки включите опрос:

```bash
yc serverless trigger create timer --name email-poller-trigger \
  --cron-expression '0/1 * * * ? *' --invoke-function-name email-poller \
  --invoke-function-tag '$latest' --invoke-function-service-account-id "$SA_ID"
```

## 6. Создание workflow и расписания

```bash
yc serverless function create --name email-sender
bash scripts/deploy-escalation.sh
```

Скрипт разворачивает SMTP-функцию, генерирует src/workflow.yaml с ID вашего
каталога и создаёт daily-escalation, если workflow отсутствует; иначе обновляет.
Команда создания, используемая скриптом:

```bash
yc serverless workflow create --name daily-escalation \
  --yaml-spec src/workflow.yaml --service-account-id "$SA_ID" \
  --log-folder-id "$FOLDER_ID"
```

Не выполняйте её второй раз после успешного скрипта. При отсутствии заявок
старше 24 часов ручной запуск завершится без письма — это ожидаемо.
Проверьте выполнение в консоли Workflows, доставку дайджеста и статус escalated
при наличии подходящей тестовой заявки. Затем включите расписание:

```bash
yc serverless workflow update --name daily-escalation \
  --schedule-cron-expression '0 0 9 * * *' --schedule-timezone Europe/Moscow
```

Формат cron workflow включает секунды и отличается от cron таймера поллера.
Функция email-sender принимает фиксированного получателя из окружения;
HTTP-вызов открыт для workflow — ограничение учебной реализации, не публичный SMTP relay.

Облачные стадии не обещают фиксированного времени установки: ожидание YDB,
индекса и сборки функций зависит от платформы.
