# ЛР №7 — техническая документация тестов

## Фреймворк и организация

Используется стандартный `unittest`, который уже применён в проекте. Существующие тесты Alpha 1–4, миграций, конкурентности и CI-контрактов сохранены. Для выбранного прогона добавлены:

- `tests/lab7_unit_suite.py` — чистые проверки парсера спортивного времени и политики разрешений.
- `tests/lab7_integration_suite.py` — 16 явно выбранных HTTP/DB-сценариев из существующих модулей и новый регрессионный тест.
- `tests/test_lab7_integration.py` — устаревшая форма прогноза не перезаписывает сохранённый выбор.
- `scripts/ci/run_tests.py` — запуск named unittest suite, JUnit XML, свойство Git SHA и TeamCity import service message.
- `scripts/ci/test-suite.sh` — воспроизводимые локальные команды.

Полный регрессионный набор остаётся доступен через существующие тестовые модули и suite-файлы. Выбранный набор ЛР7 не заменяет их.

## Локальный запуск

После установки зависимостей из `requirements.txt`:

```bash
PYTHON=.venv/bin/python bash scripts/ci/test-suite.sh unit
PYTHON=.venv/bin/python bash scripts/ci/test-suite.sh integration
```

Команды создают `artifacts/tests/unit.xml` и `artifacts/tests/integration.xml`; код завершения ненулевой при ошибке теста. При наличии `RACING_TEST_POSTGRES_URL` существующая фабрика `tests.support.isolated_database` создаёт временную БД PostgreSQL с префиксом `racing_test_` и удаляет её после теста. Без этого параметра используется временная SQLite БД. `DATABASE_URL` приложения тестами не читается.

## Разделение и изоляция

- **Unit:** функции парсинга времени и централизованная матрица разрешений с контролируемыми простыми объектами пользователя.
- **Integration:** реальные Flask test client HTTP-запросы, CSRF включён, миграции и транзакции на отдельной SQLite БД для каждого fixture.
- **Database/PostgreSQL:** CI запускает существующий `tests.beta1_postgres_suite` на отдельном одноразовом PostgreSQL 18 контейнере с tmpfs; создание/удаление тестовых баз выполняет `tests.support.isolated_database`.
- Рабочие аккаунты и пароли не используются. Приложение не подключается к STAGE/PROD; секреты не передаются.

## TeamCity

Общий `scripts/ci/verify.sh` запускает unit и integration на собранном checks-образе до дальнейших Docker build/publish шагов. Отчёт PostgreSQL suite также сохраняется как JUnit. И Feature Verify, и Dev Verify and Publish используют общий verify script; существующие Ruff, Bandit и Gitleaks шаги не меняются. `scripts/ci/teamcity-static-steps.json` включает `artifacts/tests/*.xml => tests` в правила публикации обоих конфигурационных экспортов. Отчёты содержат Git SHA, чтобы связать результат с checkout revision. Ошибка unittest возвращает ненулевой exit code и останавливает verify до Docker publish.

Изменения подготовлены в конфигурационном экспорте и общем скрипте, но действующие TeamCity-конфигурации API/сборкой не проверялись на этом этапе.

## Покрытие и результаты

Функциональные требования и результаты сопоставлены поштучно в [матрице покрытия](LAB7_COVERAGE_MATRIX.md). Функциональный процент считается как число требований с подтверждённым PASS, делённое на все 35 функциональных требований из дорожной карты. Line coverage — отдельная метрика; `coverage.py` в окружении отсутствует, поэтому line coverage не заявляется.

Новые тесты:

| Тест | Модуль | Входные данные | Ожидание | Фактический результат |
|---|---|---|---|---|
| `test_seconds_and_minute_formats_normalize_to_hundredths` | `app.services.parse_time_input` | `124,567`, `02:04.5`, `1:45` | Секунды округлены до сотых | PASS: 124.57, 124.5, 105.0 |
| `test_invalid_nonpositive_nonfinite_and_out_of_range_times_are_rejected` | `app.services.parse_time_input` | Пустая строка, ноль, отрицательное, NaN/Inf, 1:60, лишний компонент, текст | `ValueError` для каждого из 8 вариантов | PASS: 8 subTest вариантов |
| `test_permission_matrix_allows_only_declared_roles` | `app.permissions.can` | OWNER create_application, VIEWER create_application, ROOT/ADMIN manage_system | разрешить только предписанные роли | PASS |
| `test_inactive_and_unknown_permission_default_to_denied` | `app.permissions.can` | неактивный OWNER, ROOT с неизвестным разрешением | отказать обоим | PASS |
| `test_stale_edit_does_not_replace_current_prediction` | `app.prediction_services.save_prediction` через HTTP | VIEWER сохраняет revision 1, обновляет до 2, затем посылает старую revision 1 | HTTP 409; revision 2 и текущая лошадь сохранены | PASS |

Результат последнего выбранного набора на SQLite: **4 unit + 16 integration = 20 test methods, PASS**. Отдельный отрицательный эксперимент приведён в handoff; контрольная ошибка была восстановлена.


## Аудит этапа 2

Матрица пересчитана: 15/35 = 42,9% полного ТЗ, 15/32 = 46,9% реализованных функций. Дублирование F05/F21 устранено; регистрация всех ролей не засчитана по одному OWNER-сценарию. Пропущенные функции включены в знаменатель.

Runner теперь корректно отражает failures/errors внутри subTest, unexpected success и expected failure. Перед запуском удаляется прежний отчёт; нормальная запись XML атомарна, KeyboardInterrupt даёт error и exit 130. Аварийное завершение процесса не оставляет старый PASS. Режим postgres требует явно заданный RACING_TEST_POSTGRES_URL.

CI использует tests.lab7_ci_suite: объединение выбранных 16 интеграционных сценариев и 14 прежних Beta-сценариев даёт 28 уникальных методов (2 дубликата исключены). Все прежние проверки сохранены. Полный CI: 4 unit + 28 SQLite integration + 5 PostgreSQL = 37 методов; это превышает промежуточный лимит 20 ради сохранения принятых регрессий и доказательства покрытия ЛР7, число не скрывается wrapper-командой. Браузер не запускается.

Контроль этапа 2: SQLite 4 unit и 16 integration PASS. Дополнительные искусственно отказавшие мини-сценарии проверили контракты runner (subTest, exception, unexpected success, skip, interrupt), без повторного внесения дефекта в приложение. PostgreSQL и действующая TeamCity-конфигурация требуют доступа к инфраструктуре.
