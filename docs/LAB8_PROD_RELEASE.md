# ЛР8: подготовка PROD Release

Состояние на 2026-11-03. Рабочая PROD-БД и web в этом продолжении не менялись.

## Принцип запуска

Релиз разделён на две ручные TeamCity-конфигурации в отдельном под-проекте
`RacingClub_Production`:

1. `RacingClub_ProdReleaseCheck` запускает 15 unit-проверок и режим
   `runner --mode check`. Он читает реальные DEV/STAGE metadata, digest и
   успешную snapshot-зависимость через TeamCity API; SSH/PROD не затрагивает.
2. `RacingClub_ProdRelease` сначала выполняет те же проверки, затем запускает
   `runner --mode release` только с root-managed файлом запроса на агенте.

В обеих конфигурациях должны отсутствовать VCS/build-finish triggers. Не
добавлять credential `racing_stage_cd`; PROD требует отдельный SSH Agent key
`racing_prod_cd`. Агенту нужны только read-only TeamCity API credentials,
доступ к выделенному SSH Agent и доверенный `known_hosts`. Ни токен, ни ключ не
хранятся в репозитории или artifacts. Техническая спецификация шагов находится
в `scripts/ci/prod/teamcity-steps.json`.

Защита владельца проверяется на PROD root wrapper:
`/etc/racing-club/prod-release-approval.json`, mode 600, root-owned. Одобрение
связывает точный хеш запроса, SHA, digest, DEV/STAGE IDs, target schema,
source fingerprint/revision, уникальный nonce, владельца, UTC maintenance
window и recovery plan. Ключ `zelyonka` может вызвать только фиксированный
`sudo -n /usr/local/sbin/racing-prod-release`; никаких произвольных shell
команд или Docker-доступа ему не выдаётся.

## Backup и проверка перед DDL

В `scripts/ci/prod/gates.py` порядок операций закреплён fail-closed: preflight
точной БД/ревизии/fingerprint/PG18 → остановка web → полный fingerprint данных
→ свежий custom `pg_dump` в private state → ненулевой размер и SHA-256 → restore
в отдельный временный PostgreSQL 18 → сравнение схемы и всех исторических
записей → репетиция миграции и SQLAlchemy model check на копии → повторная
проверка исходной схемы и данных → live DDL → post-check → web-only deploy.
Временные контейнеры и сеть именуются nonce и удаляются только при подтверждённом
создании. Дамп и stderr остаются в private PROD state, никогда не публикуются.
Нет автоматического downgrade или destructive restore.

Проверенная ранее изолированная PROD-копия успешно восстановилась и прошла
миграцию до `0007_organizer_contact` (старое доказательство сохранено в
`.lab8-work/current`). Новая реализация transaction backend не запускалась на
рабочей PROD-БД: отдельного разрешения владельца и окна обслуживания нет.
FakeBackend-тесты подтверждают блокировку каждого этапа при ошибке и порядок
backup → restore → rehearsal → DDL.

## Настоящий TeamCity

Подпроект `RacingClub_Production` создан. Конфигурации `RacingClub_ProdReleaseCheck`
и `RacingClub_ProdRelease` созданы через REST API, используют существующий VCS
root, агент `RACING-CI`, публикуют `artifacts/prod-release/**` и не имеют
автоматических triggers. Check разрешён на feature/dev; Release — только на
dev. Обе проверки целостности зависимостей выполняют адресные REST-запросы к
конкретным DEV/STAGE Build IDs, не вызывая повторные сборки.

Для REST чтения в под-проект помещён отдельный TeamCity password parameter с
новым токеном, ограниченным `view_project` для RacingClub. Проверено: токен
читает DEV build #528, но попытка изменить Build Configuration получает HTTP
403. Исходный пользовательский API token не копировался в проект или логи.
Триггеры, VCS roots, agent requirements, steps, branch filters, artifact rules
и secret-parameter type прочитаны обратно через REST. Safe Check ещё нужно
запустить после push feature branch; Build ID пока отсутствует.

У Production Release пока нет SSH Agent feature или `racing_prod_cd` key. В
TeamCity Production project доступен только ранее существовавший
`racing_stage_cd` под `RacingClub_Deployment`; этот ключ не использован.
Release runner завершится fail-closed, пока отдельный PROD credential,
fingerprint/known_hosts и root-owned wrapper не настроены.

## Проверка этой версии

- `python -m unittest tests.test_prod_release -v` — 15/15 PASS.
- `ruff check scripts/ci/prod tests/test_prod_release.py` — PASS.
- `python -m py_compile scripts/ci/prod/*.py tests/test_prod_release.py` — PASS.
- Реальный read-only REST provenance check прошёл для DEV #528 и STAGE #530:
  SHA `10cfdbb5c1db6b83e2f0ac08235d5dcab494c6bc`, digest
  `sha256:8ecca872b60748f1781626352eca1009031acc57ed2b3b7bf66b27ce93e9021d`,
  target `0007_organizer_contact`, fingerprint
  `3fe4b3f00e1799f2c7543b192fcec778eb2cb48f6287bfd2e3725b056b5ca5da`.
  Receipt: `.lab8-work/current/prod-release-check.json` (локальный ignored-файл).
- Существующие TeamCity конфигурации не менялись. Исходный REST snapshot до
  добавления нового под-проекта сохранён вне Git как
  `.lab8-work/teamcity-before-prod-release.json`.
- На TeamCity нет отдельного PROD SSH credential: ранее найден только
  `racing_stage_cd`; он здесь не используется. PROD known_hosts и SSH Agent
  feature не установлены. `TC_TOKEN_FILE` для read-only API build account также
  должен быть размещён оператором на агенте; личный локальный токен туда не
  копировался.

## Что требуется для активации

TeamCity administrator должен создать под-проект и две конфигурации по
`scripts/ci/prod/teamcity-steps.json`, оставить trigger list пустым и разрешить
доступ только release operators. Также требуется выданный владельцем read-only
TeamCity API credential, отдельный `racing_prod_cd` SSH Agent credential,
независимо проверенный PROD host key в known_hosts и установка root-owned
wrapper/settings/approval на PROD через консоль VM. Пока эти пункты отсутствуют,
release конфигурация не может получить PASS. Любая реальная миграция требует
отдельного разрешения владельца PROD и согласованного окна обслуживания.
