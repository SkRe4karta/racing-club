# TeamCity / ЛР №5: подтверждённое состояние и приёмка исправлений

На 16.10.2026 PR №1 действительно объединён в dev после APPROVED от dro4karta.
Dev SHA: `0fb75e47259adfda9a609438904149bf106f8ab6`. Существующий скриншот
16.10.2026 04:54:32 показывает успешную Dev Verify and Publish #1 (build ID 203),
агент RACING-CI, шаги Verify Racing Club и Publish Docker Image. Feature Verify #2
указана в PR №1; текущий сервер повторно проверить не удалось.

**Новые сценарии ниже подготовлены и проверены локально. В TeamCity они ещё не
установлены и на VM не запускались. CD пока нельзя считать принятым.** Текущий
sandbox запрещает даже localhost/SSH sockets; VirtualBox IPC недоступен. Файлы
конфигурации VM прочитаны без изменений. Настоящие VCS triggers, состояние агентов,
SSH host keys и deployment требуется проверить в сессии с доступом к хосту.

## Зафиксированные окружения

Сохранённые `.vbox`: TEST `127.0.0.1:8081 → guest:8080`, STAGE `8082 → guest:8080`,
PROD `8083 → guest:8080`. SSH host-порты соответственно 2221, 2222, 2223, CI 2224;
CI UI `8111 → guest:8111`. Guest IP в NAT-правилах не задан. Это NAT-адаптер VM,
а не буквальный проброс в 10.20.0.x. Внутренняя сеть `racing-lab` — другой адаптер.

По исходным сведениям Beta работает на STAGE guest:8081, старый web — guest:8080.
Поэтому сохранённое правило STAGE направляет обычный URL к старому web.
После проверки новой версии и данных изменить только правило WEB:

```bash
# Для работающей VM; сначала сохранить полный showvminfo и исходное WEB-правило.
VBoxManage controlvm RACING-STAGE natpf1 delete WEB
VBoxManage controlvm RACING-STAGE natpf1 'WEB,tcp,127.0.0.1,8082,,8081'
# Откат маршрута при проблеме: удалить WEB и вернуть порт guest 8080.
```

Эти команды **в данной сессии не выполнены**. Перед переключением проверить
Beta через SSH `127.0.0.1:2222`, затем `/health`, страницы, image ID/OCI revision и
БД; после — `http://127.0.0.1:8082`. TEST/PROD маршруты сохраняются.
Не редактировать `.vbox` напрямую при неизвестном состоянии VirtualBox.

## Модель STAGE и сохранность данных

Старый проект `/opt/racing-club/compose.yaml`, `racing-club-stage`, его web:8080,
`postgres:18-alpine`, БД `racing_club` и том
`racing-club-stage_postgres_data:/var/lib/postgresql` сохраняются.
Новый `compose.stage.yaml` определяет **только web** проекта `racing-club-beta1`,
порт VM 8081 и внешнюю сеть `racing-club-stage_default`. Существование этой сети
и Docker DNS `db` проверить на VM до приёмки. Новый PostgreSQL не создаётся.
Имена проекта Beta и legacy специально различаются; это не переименование БД.

CD принимает отдельно выбранную БД `racing_club_beta1`, `racing_stage_*` или
`racing_demo_*`; историческая `racing_club` запрещена для этого deployment.
Для спортивных данных сначала восстановить исторический dump в уникальную
`racing_stage_*`, подтвердить 3/7/5/4/11 записей, выполнить adopt-legacy/upgrade/check
на копии, проверить страницы и выбрать эту копию в приватных настройках Beta.
Это первичное наполнение **ещё не выполнено**. Генератор seed и его ограничения
не менялись: использовать только checks target и новую пустую `racing_demo_*`,
accounts сохранять вне Git с 600. Runtime seed.py не содержит.

Каждый новый dev deployment делает свежий pg_dump выбранной STAGE-БД, восстанавливает
его в уникальную логическую rehearsal-БД на существующем PostgreSQL, проверяет
baseline, миграции, `db check`, валидность ограничений и число/хеш строк пяти старых
таблиц. Репетиционные БД не удаляются автоматически; количество и память контролировать.
Репетиция и deployment выполняются последовательно, Python-образ на STAGE не собирается.
При ошибке после остановки Beta автоматический downgrade не выполняется. Старый
web:8080 продолжает работать; возврат NAT на 8080 возвращает отдельную старую систему,
а не откатывает записи новой БД. Совместимый откат Beta проверяется отдельно.

## Обязательные настройки TeamCity до merge

Не добавлять Docker Hub/SSH-секреты на уровень общего проекта: feature не должна их
наследовать. Не включать shell trace. Доступ к изменению параметров и настройкам
deployment — только доверенным администраторам. Связать всю цепочку с одним Git VCS
Root origin; clean agent-side checkout должен содержать `.git`.

| Конфигурация | Шаги | Триггер и ограничения |
|---|---|---|
| Feature Verify | `bash scripts/ci/verify.sh` | VCS `+:feature/*`; без registry/deploy secrets |
| Dev Verify and Publish (`RacingClub_DevVerifyPublish`) | verify.sh, затем publish.sh только после успеха | VCS только dev; `env.TC_BRANCH=dev` |
| STAGE Deploy | `bash scripts/ci/deploy-remote.sh` | Finish build trigger только успешного Dev/dev; max running builds 1 |
| PROD release/deployment | отдельная будущая приёмка релиза | без dev/feature trigger; только reviewed prod/release и ручное разрешение |

Для verify обеих конфигураций: `env.EXPECTED_SHA=%build.vcs.number%`.
Для Dev дополнительно: `env.BUILD_ID=%teamcity.build.id%`,
`env.DOCKERHUB_REPOSITORY=skre4karta/racing-club`, protected `env.DOCKERHUB_USER`,
`env.DOCKERHUB_TOKEN` типа Password. Feature не вызывает publish, publish отклоняет
любую логическую ветку кроме dev и сверяет checkout/image ID/OCI SHA с verify receipt.
Новые обязательные параметры нужно добавить **до merge**: старые настройки
TeamCity иначе получат явный отказ, а не ложный успех.

Artifact rules Dev: `artifacts/*.txt`, `artifacts/published-image.json`,
`artifacts/stage-deploy.tar.gz`. Manifest содержит version, полный sha, tag,
точный repository@digest, ID исходной сборки и SHA256 архива deployment.
Из артефактов не исполняется shell `source`; manifest разбирается как JSON.
Для новых коммитов digest вычисляется заново; исходный Beta digest нигде не зашит.

STAGE Deploy: snapshot dependency на Dev с enforce revisions synchronization,
только успешной зависимостью, cancel при failed/cancelled upstream. Artifact dependency
**Build from the same chain**, правила:

```text
published-image.json => artifacts
stage-deploy.tar.gz => artifacts
```

Не брать lastSuccessful независимо от snapshot: так можно смешать разные SHA.
`env.EXPECTED_SHA=%dep.RacingClub_DevVerifyPublish.build.vcs.number%`,
`env.UPSTREAM_BUILD_ID=%dep.RacingClub_DevVerifyPublish.teamcity.build.id%`.
Проверить фактические имена dependency parameters на установленном сервере.
Диспетчер сверяет оба значения с manifest и SHA256 архива до SSH.
Одна snapshot dependency не передаёт файлы — нужна также artifact dependency.
[Документация зависимостей JetBrains](https://www.jetbrains.com/help/teamcity/configuring-dependencies.html).

## SSH и приватные настройки STAGE

На доверенном deployment-агенте — отдельный SSH Agent build feature с отдельным
загруженным ключом; закрытая часть вне Git и не в обычных env-параметрах. На STAGE
проверить минимальные необходимые права пользователя; скрипты не делают sudo,
не меняют Docker socket и не устанавливают агентов. Docker-права дают большой
контроль над VM, поэтому доступ к запуску цепочки ограничить доверенным проектом.
Ограничения authorized_keys: запрет forwarding/pty; при необходимости отдельный
проверенный forced-command dispatcher. Реальный ключ и права здесь не установлены.

`env.STAGE_KNOWN_HOSTS` — путь на агенте к закрытому файлу с независимо проверенным
host key 10.20.0.12. `ssh-keyscan` сам по себе не является проверкой личности.
Скрипт использует `BatchMode=yes`, `StrictHostKeyChecking=yes`, pinned
UserKnownHostsFile и фиксированный адрес zelyonka@10.20.0.12; PROD не параметризуется.

На STAGE один раз создать `/home/zelyonka/racing-cd/stage-deploy.env`, владелец
zelyonka, 600, обычный файл. Это доверенный shell-файл с корректно quoted значениями,
одновременно пригодный для Compose env file:

```bash
STAGE_DATABASE_NAME='racing_stage_<проверенная_копия>'
STAGE_DATABASE_URL='postgresql+psycopg://<user>:<url-safe-password>@db:5432/<та_же_БД>'
SECRET_KEY='<постоянный_секрет>'
SESSION_COOKIE_SECURE='false'
WEB_BIND='0.0.0.0'
WEB_PORT='8081'
```

Секреты заполняются из защищённого источника без печати. Для HTTPS Secure=true.
Настройки прежней `/opt/racing-club/.env` не перезаписываются. В shell-файле не должно
быть исполняемых команд. Только доверенный владелец может его менять.

## Приёмочный прогон, который ещё требуется

После настоящего review PR и merge проверить VCS обнаружение нового SHA, успешные
verify/push, manifest/build ID/digest, автоматический запуск STAGE dependency chain,
свежий backup, фактический restore/adopt/migrate, совпадение данных, новый container
image ID, health и 10 страниц. Проверить браузер на обычном localhost:8082 после NAT
переключения. Убедиться, что старая сборка не перезаписывает новую: pipeline.lock,
deploy.lock и сравнение upstream build ID; настройки max running=1 на сервере.
Сохранить реальные build links, артефакты и скриншоты, затем повторить deployment
того же разрешённого образа. Только после этого фиксировать CD как рабочий.
PROD-БД/образ/маршрутизация в этой доработке не меняются.
