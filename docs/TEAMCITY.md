# TeamCity / ЛР №5 — доставка на существующий STAGE

## Стенд и сохранённые результаты

GitHub: https://github.com/SkRe4karta/racing-club. PR №1 объединён в dev после
APPROVED от dro4karta; принятый SHA `0fb75e47259adfda9a609438904149bf106f8ab6`.
Feature Verify #2 (ID 202) и Dev Verify and Publish #1 (ID 203) успешны.
Образ исходной Beta: `skre4karta/racing-club:2.0.0-beta.1-0fb75e47259a`,
digest `sha256:b376a97e90d65e4d62b07b4cb16fc8763a9764c1beb08f56c55d0b620e7c5f74`.

02.11.2026 подтверждены живые VM, SSH, TeamCity Server 2026.2.1 и два
подключённых, авторизованных, включённых агента: RACING-CI и RACING-TEST.
TEST использует `jetbrains/teamcity-agent:2026.2.1` с доступным Docker Engine.

| VM | Внутренняя сеть | SSH основного компьютера | Назначение |
| --- | --- | --- | --- |
| RACING-TEST | 10.20.0.11 | 127.0.0.1:2221 | TEST, feature verify agent |
| RACING-STAGE | 10.20.0.12 | 127.0.0.1:2222 | Beta 1 и существующая PostgreSQL |
| RACING-PROD | 10.20.0.13 | 127.0.0.1:2223 | PROD, не изменяется |
| RACING-CI | 10.20.0.14 | 127.0.0.1:2224 | TeamCity Server и publish/deploy agent |

TeamCity UI: http://127.0.0.1:8111. TEST/PROD web: localhost:8081/8083.
Требуемый STAGE web: localhost:8082 → guest:8081, bind 0.0.0.0.
При начале сессии 02.11 проброс ещё указывал guest:8080, а Beta слушала только
10.20.0.12:8081. Результат окончательного переключения фиксируется отдельно
в техническом отчёте лабораторной после фактической проверки.

## Настройки, внесённые в TeamCity Server 02.11.2026

Общий VCS root: `RacingClub_RacingClubGitHub1`, agent-side checkout с `.git`.

| Конфигурация | Шаги | Триггер / агент |
| --- | --- | --- |
| RacingClub_FeatureVerify | verify.sh | VCS +:feature/*; RACING-TEST |
| RacingClub_DevVerifyPublish | verify.sh, publish.sh | VCS +:dev; RACING-CI |
| RacingClub_StageDeploy | deploy-remote.sh | успешное завершение Dev/dev; RACING-CI |

Для обеих verify-конфигураций `env.EXPECTED_SHA=%build.vcs.number%`.
Dev: `env.BUILD_ID=%teamcity.build.id%`, `env.TC_BRANCH=dev`,
`env.DOCKERHUB_REPOSITORY=skre4karta/racing-club`; существующий Docker Hub token
сохранён как Password только в Dev. Feature не получает registry/deploy secrets.
Для всех трёх конфигураций максимум одновременных сборок — 1.

Dev artifacts: `artifacts/*.txt`, `artifacts/published-image.json`,
`artifacts/stage-deploy.tar.gz`. Publish проверяет verify receipt, image ID и OCI
revision; digest берёт из ответа конкретного docker push и проверяет docker pull.
Manifest связывает SHA, upstream build.id, image digest и SHA256 deploy-архива.

STAGE расположен в отдельном подпроекте `RacingClub_Deployment`. Snapshot dependency
на Dev: sync-revisions=true, reuse only successful, cancel on failure/cancel.
Artifact dependency: строго **sameChain**, без fallback lastSuccessful;
`published-image.json => artifacts`, `stage-deploy.tar.gz => artifacts`.

Параметры STAGE:
- `env.EXPECTED_SHA=%dep.RacingClub_DevVerifyPublish.build.vcs.number%`;
- `env.UPSTREAM_BUILD_ID=%dep.RacingClub_DevVerifyPublish.teamcity.build.id%`;
- `env.STAGE_KNOWN_HOSTS=/data/teamcity_agent/conf/stage_known_hosts`.

SSH Agent build feature использует прежний ключ `racing_stage_cd`, установленный
в штатное хранилище SSH keys только подпроекта доставки. Закрытый ключ не хранится
в Git, параметрах окружения или отчётах. Pinned ED25519 fingerprint STAGE:
`SHA256:FgZyaoh6hzbjDVTi3J+KVlsk/HHUqHcWNTmWFQsztiM`.
Он независимо совпал с исходными сведениями; StrictHostKeyChecking=yes.

## Обновление Beta без повторной миграции

На STAGE приватный файл `/home/zelyonka/racing-cd/stage-deploy.env` (600),
значения DATABASE_URL/SECRET_KEY сохранены из работающего контейнера:
STAGE_DATABASE_NAME=racing_club_beta1, WEB_BIND=0.0.0.0, WEB_PORT=8081.
Файл одновременно имеет доверенный shell-синтаксис и формат Compose env file.

`compose.stage.yaml` содержит только Beta web проекта `racing-club-beta1` и
использует внешнюю сеть `racing-club-stage_default`. Существующие контейнер
`racing-club-stage-db-1`, postgres:18-alpine, том
`racing-club-stage_postgres_data:/var/lib/postgresql`, историческая БД racing_club
и старый web:8080 сохраняются. Deployment допускает только racing_club_beta1,
racing_stage_* или racing_demo_*; реальная current_database() проверяется до записи.

Каждый deployment проверяет SHA/digest/build ID, архив, PostgreSQL и схему целевой
БД. При совпадении revision с Alembic head образа (сейчас 0005_predictions):
**нет pg_dump, rehearsal DB, adopt-legacy или db upgrade**. Обновляется только web,
затем Compose --wait, сверка image ID и 10 HTTP-проверок версии/health.

При изменении head: остановка Beta web, проверка стабильного снимка данных,
минимальный pg_dump целевой БД, репетиция на отдельной копии, upgrade/check и
сравнение спортивных строк. Legacy на активной БД явно отклоняется; первичное
adopt-legacy выполняется отдельно. Исходная ручная репетиция уже выполнена до этой
доработки, повторять её для неизменной схемы не требуется.

Файлы блокировок pipeline.lock/deploy.lock и success.json находятся в постоянном
`/home/zelyonka/racing-cd/state`. Старший успешный upstream build ID не может быть
заменён меньшим. Репетиция использует отдельный rehearsal.lock, чтобы не блокировать
сама себя внутри deployment. Ошибка SSH, миграции, health или smoke возвращает
ненулевой код; success.json обновляется атомарно только после успеха. Автоматический
downgrade БД не выполняется. При сбое миграции требуется разбор сохранённого backup
и журналов; после остановки web он может остаться остановлен.

## Проверка изменений и оставшаяся приёмка

02.11 локально: 13 CI contract tests успешны (включая отсутствие миграции при
актуальной схеме, отказ legacy/PROD/старой сборки, ошибки миграции/health).
Это тесты управления с подставным Docker, не доказательство живой доставки.
Bash syntax и git diff --check успешны. Настройки уже внесены на настоящий сервер.
Фактические номера нового feature/dev/deploy-прогона и конечный SHA на STAGE
фиксируются в итоговом техническом отчёте после review/merge PR №2.

Документация, использованная при настройке:
- https://www.jetbrains.com/help/teamcity/rest/teamcity-rest-api-documentation.html
- https://www.jetbrains.com/help/teamcity/configuring-dependencies.html
- https://www.jetbrains.com/help/teamcity/artifact-dependencies.html
- https://www.jetbrains.com/help/teamcity/ssh-keys-management.html
