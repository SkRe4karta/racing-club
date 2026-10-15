# Подготовка TeamCity / ЛР №5

Статус Beta 1: **сценарии подготовлены, серверные сборки не запускались**.
Адреса TeamCity/TEST/STAGE, registry namespace, установленные плагины, права
и теги образов агента нужно проверить на реальной инфраструктуре.
Никакие удалённые подключения в этом этапе не выполнялись.

## Цепочка и доказательства

GitHub feature → TeamCity проверка → настоящий PR feature→dev → одобрение другим
участником → разрешённый merge → TeamCity проверка dev → Docker Hub → отдельный
согласованный deployment на STAGE. Сохранить SHA, URL/номер каждой сборки, отчёты,
URL PR и настоящее review, образ/registry digest, backup и результат health/smoke.
Одобрение автора себе и скриншоты подготовленных команд не заменяют эти доказательства.

## Docker-агент на TEST

Запуск только после отдельного задания пользователя. Сначала проверить версию
TeamCity Server и выбрать совместимый точный тег/ digest регулярного
`jetbrains/teamcity-agent`; `latest` в приёмочной конфигурации не закреплять.
[Официальная инструкция JetBrains](https://www.jetbrains.com/help/teamcity/agent-docker-images.html)
описывает SERVER_URL и постоянный каталог конфигурации агента.

На TEST нужны Docker Engine, Git и Bash; внутри выбранного образа агента проверить
Git, Bash, Docker CLI и Compose v2. Приложение и тесты используют Python 3.14 из
Dockerfile, Python на агент вручную устанавливать не требуется. Если инструмента
нет, подготовить согласованный производный образ; пакеты и права socket не менять
без разрешения. Не использовать privileged и не делать chmod 666 docker.sock.

Шаблон первого подключения (значения подставляются оператором):

```bash
# TEAMCITY_SERVER_URL — реальный URL сервера, TEAMCITY_AGENT_IMAGE — закреплённый образ.
docker volume create racing_tc_agent_conf
docker run -d --name racing-teamcity-agent --restart unless-stopped \
  -e SERVER_URL="$TEAMCITY_SERVER_URL" -e AGENT_NAME=racing-test-docker \
  -v racing_tc_agent_conf:/data/teamcity_agent/conf \
  "$TEAMCITY_AGENT_IMAGE"
```

На TeamCity Server открыть Agents → Unauthorized, сверить TEST/имя агента и
авторизовать его доверенным администратором; назначить pool проекта. Проверить
Connected/Enabled/Compatible и лицензионный лимит агентов. Точное расположение UI
зависит от установленной версии. Полная инструкция образа:
[JetBrains teamcity-agent](https://github.com/JetBrains/teamcity-docker-images/blob/master/dockerhub/teamcity-agent/README.md).

Для сборок нужен доступ к Docker daemon. Отдельно согласовать bind mount
`/var/run/docker.sock:/var/run/docker.sock` и соответствующую socket группу
(например `--group-add` с фактическим GID). Доступ к Docker даёт контроль над TEST;
агент должен исполнять только доверенные feature/dev сборки. После одобрения
пересоздать только контейнер агента с тем же conf volume и socket mount.
Права host socket не менять. Предлагаемые скрипты используют COPY/docker build,
а не host bind mounts checkout, поэтому пути checkout не обязаны совпадать с хостом.

## Минимальное подключение проекта

1. Создать проект Racing Club, Git VCS Root с URL origin из README. Default branch:
   `refs/heads/dev`; branch specification `+:refs/heads/feature/*` и
   `+:refs/heads/dev`. Не использовать legacy, prod/master или непроверенные fork PR.
2. Настроить agent-side checkout с Git-метаданными, clean checkout. Проверить,
   что TeamCity выдаёт текущую ветку как `feature/...` / `dev`, а `git rev-parse HEAD`
   совпадает с revision сборки. На агенте должен быть доступ к Docker registry
   для базовых python:3.14-slim/postgres:18.
3. Build configuration **Feature Verify**: branch filter `+:feature/*`, VCS trigger
   на feature, Command Line runner: `bash scripts/ci/verify.sh`. Секреты публикации
   этой конфигурации не выдавать. Сбой процесса/теста должен проваливать сборку;
   шаги после ошибки не выполнять. Лог тестов хранит stdout/stderr runner.
4. **Dev Verify and Publish**: только `+:dev`. Первый шаг тот же verify.sh,
   второй `bash scripts/ci/publish.sh`, только после успеха предыдущего шага,
   на том же агенте/checkout. env.TC_BRANCH=`%teamcity.build.branch%`.
   env.DOCKERHUB_REPOSITORY — согласованный namespace/racing-club;
   env.DOCKERHUB_USER, env.DOCKERHUB_TOKEN — защищённые параметры, token типа Password.
   Закрыть изменение build settings и запуск с подменой параметров обычным пользователям.
5. Artifact rules: `artifacts/*.txt`. Это метаданные SHA/image ID/digest, без секретов.
   Не публиковать accounts, .env, БД, дампы, Docker config и полные env.
6. **STAGE Deploy**: отдельный manual build, без VCS deployment trigger.
   Оператор после review и backup доставляет compose.stage.yaml/scripts из
   проверенной dev-ревизии на STAGE и выполняет deploy-stage.sh там.
   Этот этап не настраивает SSH/доступ и не развёртывает серверы самостоятельно.

Скрипт verify.sh строит checks target, выполняет 14 выбранных SQLite и 5 PostgreSQL
сценариев; PostgreSQL — отдельный контейнер с tmpfs, без host port/volume, в закрытой
одноразовой сети. Тесты создают случайные БД. Затем строится runtime, в одноразовой
БД выполняются миграции, запускается Gunicorn и read-only HTTP smoke. Cleanup удаляет
только созданные CI-контейнеры и сеть. Именованные рабочие тома не затрагиваются.
Этот будущий CI-прогон включает отдельный deployment smoke и не объявляется
локальным промежуточным набором из 20 сценариев. Браузерный smoke локальной Beta
описан в BETA1_VALIDATION.md. Полный регрессионный набор — финальная приёмка.

## Образы и доставка

Тег: `namespace/racing-club:2.0.0-beta.1-<12 символов SHA>`. OCI label revision хранит
полный SHA. Feature Verify не публикует образ. publish.sh принимает только логическую
ветку dev и сверяет локальный image ID/SHA с результатом успешной проверки. Docker
login использует stdin и одноразовый DOCKER_CONFIG. Не включать shell trace (`set -x`).
Регистрировать RepoDigest в артефактах; STAGE принимает только `repository@sha256:…`.
Не перезаписывать теги и не использовать latest для доставки. Базовые образы пока
закреплены по minor/major tag: перед серверной приёмкой сохранить реальные digest
python/postgres/agent, при необходимости согласованно закрепить их в конфигурации.

На STAGE использовать compose.stage.yaml: image без build, PostgreSQL 18 без
публичного порта, постоянный том postgres_data, явный project name `racing-stage`.
Секреты — существующий защищённый .env или env TeamCity; не заменять рабочий .env.
Не менять параметры/имя проекта существующего PostgreSQL volume.

Перед deployment: окно обслуживания, проверенный backup и репетиция восстановления
на одноразовом PostgreSQL 18. Экспортировать DEPLOY_ENV=STAGE, EXPECTED_SHA (40 hex),
RACING_IMAGE (проверенный registry digest), BACKUP_PATH (существующий backup вне Git),
COMPOSE_PROJECT_NAME=racing-stage и прежние параметры БД/сессий. Затем:

```bash
bash scripts/ci/deploy-stage.sh
```

Сценарий проверяет предусловия/OCI revision, pull, ждёт здоровую БД, останавливает
старые web workers, выполняет один контролируемый upgrade/check, запускает готовый
образ с `--no-build --wait` и проверяет страницы/версию. Compose v2 должен поддерживать
`--wait`/`--wait-timeout`; проверить на TEST до STAGE.
[Документация Compose](https://docs.docker.com/reference/compose-file/services/).
Ошибка любого шага возвращает ненулевой код. При ошибке миграции web остаётся
остановленным для управляемого восстановления. При сбое smoke не объявлять успех:
сохранить журналы, остановить web в окне работ, восстановить совместимый образ и
при необходимости проверенную резервную копию отдельной согласованной процедурой.
Автоматический downgrade/удаление томов не выполняются. Факт наличия BACKUP_PATH
не доказывает корректность backup: её проверяет оператор до запуска.

Не выполнять `down -v`. Seed не находится в runtime-образе и не запускается при
рестартах. Для отдельной демонстрации на TEST используйте явный checks target и
новую demo-БД, никогда основной volume STAGE/PROD.

## Что фактически остаётся проверить

Доступ/авторизацию Docker-агента на TEST; версии Docker CLI/Compose; Git checkout и
branch filters; feature build и провал сборки при тестовой ошибке; настоящий PR и
review; защищённость dev publish; Docker Hub push/digest; backup/restore rehearsal;
реальные миграции/healthcheck/smoke на STAGE с сохранением volume при перезапуске.
Production и HTTPS/Caddy/443 — последующая отдельная приёмка по ROADMAP_V2.md.
