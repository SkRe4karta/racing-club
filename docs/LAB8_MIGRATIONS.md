# ЛР8 — SQL и миграции (технический документ)

## Выбор анализа

| Инструмент | Что проверяет | Ограничения |
|---|---|---|
| SQLFluff | PostgreSQL dialect, syntax/style | Не является доказательством отсутствия injection; templating нуждается в ограничении. https://docs.sqlfluff.com/en/stable/production/security.html |
| pglast8.7 + AST policy | PostgreSQL parser, destructiveDDL, unbounded UPDATE/DELETE, COPY PROGRAM, PUBLIC grants, role/procedural operations | Не определяет все логические риски и injection в Python. https://pglast.readthedocs.io/en/latest/api.html |
| Bandit (сохранённый) | Небезопасное конструирование SQL в Python, включая B608 | Эвристика, не заменяет DB tests/review |

Выбраны pglast8.7 + явные AST security rules и прежний Bandit. Parse/dependency errors и выбранные CRITICAL findings дают FAIL; строки/комментарии не маскируются regex-сканированием. Все Git-applicable .sql, включая экспорт схемы, сканируются; Python Alembic покрывается Bandit/review и фактическим upgrade. Opaque DO/functions требуют отдельного review и по умолчанию блокируются. Это ограниченная fail-closed policy, не универсальная гарантия безопасности SQL. Reports содержат SHA и hashes каждого SQL файла.

## Выбор миграций

| Средство | Применимость |
|---|---|
| Alembic/Flask-Migrate | Уже принятая история, ORM integration, transactional PostgreSQL DDL, проверяемые revisions; выбран |
| Flyway | SQL versioning/checksums, отдельный runtime и вторая история нежелательны |
| Liquibase | Богатые changelog/preconditions; дополнительная конфигурация/runtime вместо текущей истории |

## Миграция1:0006_registration_notes

Условия участия (ветеринарные документы/особые требования) задаёт ADMIN; OWNER/JOCKEY видят опубликованный текст до подачи заявки. Не меняются личные согласия, дедлайн и допуск. Необязательная колонка varchar2000 с CHECK, UI maxlength и серверная проверка; пользовательский HTML экранируется. Старые соревнования получают NULL.

Предусловия: подтверждённая STAGE racing_club_beta1, revision0005_predictions, fingerprint ожидаемой0005 структуры, backup с проверенным restore. До feature TEST PASS изменения STAGE не применять. Ручное применение: один явный `flask db upgrade 0006_registration_notes` в контролируемом maintenance job с целевым image digest, после pg_dump/pg_restore rehearsal. Это пока инструкция, не утверждение об исполнении.

PostgreSQL: ADD nullable column не переписывает строки, ACCESS EXCLUSIVE кратковременно; CHECK validation сканирует таблицу. lock_timeout5s, statement_timeout60s прерывают операцию при недоступности блокировки; транзакционный DDL откатывается. До/после сверить все counts, sporting hashes, FK/CHECK/indexes и revision. Ожидаемые изменения — только registration_notes и её CHECK.

Rollback приложения: старый образ может читать additive схему; новую колонку сохранять. Destructive downgrade запрещён. Восстановление данных — только из проверенного backup в согласованном окне, не автоматическое удаление колонки.

Вторая миграция и автоматическое подтверждение выполняются после отдельной ручной фазы и настоящего командного review первого PR. Production требует отдельного разрешения/окна, backup непосредственно перед изменением и restore rehearsal. Подготовка скрипта не считается фактической миграцией.

## Исключение SQL-policy

Нативный DDL содержит историческую `public.racing_audit_immutable()` из 0004.
Её единственное действие — RAISE EXCEPTION для защиты append-only истории.
Разрешена только точная AST SHA256 этой проверенной функции в
`database/sql-policy-exceptions.json`. Изменение тела, языка, аргументов или
атрибутов снова блокируется. Удаляются лишь позиции токенов из AST.
CI берёт policy из того же закреплённого commit, что и scanner, а не из
проверяемой ветки. Любые другие функции/DO остаются запрещены.
Локально подтверждено: исходный dump PASS, изменённый текст тела FAIL.

## Restore и CHECK

PostgreSQL18 pg_dump/restore может переписать `ARRAY[varchar literals]::text[]`
как `ARRAY[varchar literal::text, ...]`. Сравнение нормализует только эту форму,
состоящую целиком из строковых литералов; не удаляет приведения колонок, значения,
операторы или предикаты. Unit-проверка подтверждает эквивалентный restore и отказ
при изменении значения ограничения, nullable либо Alembic revision.

## Миграция2: 0007_organizer_contact

Независимая полезная функция — необязательный публичный email организатора.
ADMIN задаёт адрес; сервер использует общий normalize_email, сохраняет lowercase,
отклоняет некорректные/длинные адреса; UI показывает контакт без исполнения HTML.
Схема добавляет nullable varchar254 с именованным CHECK. Старые заметки/данные
сохраняются; 0007 применяется автоматически только после TEST и peer review.

DEV export содержит baseline непосредственного предка и target текущего head.
Подписанный SHA256 bundle связывает эти структуры с конкретным successful DEV.
STAGE сравнивает всю поддерживаемую структуру, а не только revision. До DDL —
backup, restore в новую БД, сверка структуры, hashes всех прежних колонок всех
публичных таблиц, репетиция upgrade и target comparison. После DDL проверки
повторяются; новая колонка не включается в baseline hashes. Репетиционные БД
сохраняются private для разбора (тома не удаляются).

`rehearse-isolated.sh` — отдельная безопасная репетиция PROD-процесса на TEST.
Она не имеет SSH/deploy/publish, создаёт временный PostgreSQL18 и синтетический
старый старт, проверяет custom backup/restore, upgrade, сохранность старых колонок
и соответствие fresh target. Это не реальная PROD-доставка.
