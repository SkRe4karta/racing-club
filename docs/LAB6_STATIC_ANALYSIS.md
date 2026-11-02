# Лабораторная работа №6: статический анализ

## Выбор средств

| Средство | Назначение | Python | TeamCity/форматы | Критичность и ограничения |
|---|---|---|---|---|
| Ruff | Быстрый lint и ошибки Python | Да | Shell, JSON/строка/Checkstyle | Не имеет BLOCKER; проект определяет BLOCKER-профиль из F-кодов |
| Pylint | Глубокие lint и design-проверки | Да | Shell, JSON/JSON2, text/parseable | Fatal/Error/Warning/Refactor/Convention/Information, не BLOCKER; глубокие проверки, тяжелее и требует настройки |
| Flake8 | Плагинная проверка стиля и ошибок | Да | Shell, текст/JSON-плагины | Нет встроенных уровней критичности |
| Bandit | SAST для опасных конструкций | Да | Shell, JSON | Нет CRITICAL; проект блокирует HIGH severity + HIGH confidence как консервативный эквивалент |
| Semgrep | Правила SAST и собственные patterns | Да | Shell, JSON/SARIF/text | CRITICAL/HIGH/MEDIUM/LOW/INFO (и прежние ERROR/WARNING/INFO), зависят от правил; локальные rules без сети, registry требует сети |
| Gitleaks | Поиск секретов в дереве и истории Git | Да и язык не ограничен | Shell, JSON/SARIF/JUnit | Любая находка блокирует; значения редактируются |
| TruffleHog | Поиск и верификация секретов | Да и язык не ограничен | Shell, JSON | Верификация может требовать сеть; heavier than Gitleaks |

Выбраны Ruff, Bandit и Gitleaks: они воспроизводимо устанавливаются на Python-агенте, имеют машинные форматы и покрывают качество, безопасность и секреты. Pylint/Flake8/Semgrep/TruffleHog рассмотрены как альтернативы, но не добавлены в обязательный pipeline, чтобы не дублировать правила и не делать сборку зависимой от удалённых rulesets.

## Политика блокирования

Ruff запускается по `app`, `migrations`, `scripts`, `tests` и Python entrypoints. BLOCKER проекта: `invalid-syntax`, E9xx и неопределённые/некорректные конструкции `F821`, `F822`, `F823` (undefined names/exports/local), `F631` (tuple в assert), `F701`, `F702`, `F704`, `F706` (break/continue/await/return вне допустимого контекста), `F707` (except без типа не последний), `F722` (ошибка аннотации), `F901` (raise NotImplemented). Это вероятные ошибки выполнения/загрузки, а не косметика. Остальные E4/E7/E9/F-находки отображаются как advisory. BLOCKER — категория политики проекта, не native уровень Ruff.

Bandit не поддерживает собственный уровень CRITICAL. Поэтому `HIGH severity AND HIGH confidence` является документированным консервативным порогом проекта и не называется native CRITICAL.

Gitleaks блокирует любую находку. Сканируются `--all` reachable Git history и текущие текстовые файлы. Выводы и отчёты не содержат значения совпадения; узкие allowlist исключают только отрицательные синтетические пароли тестов и `${...}` Compose-интерполяции.

## Локальный запуск

```bash
bash scripts/ci/prepare-static-analysis.sh
bash scripts/ci/static-analysis.sh
```

Инструменты закреплены в `scripts/ci/static-analysis-requirements.txt` (Ruff 0.14.14,
Bandit 1.9.4 и транзитивные зависимости), Gitleaks v8.28.0 с проверкой SHA-256.
Bandit 1.8.6 проверен и отвергнут: внутренняя ошибка `ast.Num` на Python 3.14.
Bootstrap рассчитан на Linux x86_64, Python с venv, git, curl, tar, sha256sum;
sudo и установка системных пакетов не нужны. Другую архитектуру он отклоняет.
Результаты: `artifacts/static-analysis/{quality,security,secrets}/{report.json,index.html}`,
`summary.html` и `summary.json`. Ошибка инструмента — код 2, нарушение — 1, PASS — 0;
`|| true` не используется. В `all` выполняются все три проверки, возвращается максимум кодов.

Тестирование gate-контрактов (не использует рабочую БД):

```bash
PATH="$PWD/.static-tools/bin:$PATH" .static-tools/bin/python -m unittest tests.test_static_analysis -v
```

Исключены виртуальные окружения, кеши, instance, node_modules, артефакты, симлинки
и бинарные файлы текущего дерева. Git scan проверяет всю доступную историю; shallow
clone даёт ERROR. Это не гарантия отсутствия секрета любого формата: реальные утечки
требуют немедленного отзыва/ротации, а не allowlist. `--ignore-noqa`/`--ignore-nosec`
исключают локальное подавление блокирующих правил. Report JSON/HTML содержат только
путь, строку, rule, severity/confidence и revision, без исходного кода, match и secret.

## TeamCity

В существующие `Feature Verify` и `Dev Verify and Publish` добавлены шаги подготовки и трёх проверок перед тестами/публикацией. Quality/Security/Secrets/Summary имеют `execute_always`, тесты и publish — `default`: отчёты сохраняются даже после отказа, публикация не выполняется.
Артефакты публикуются дополнительным правилом `artifacts/static-analysis => static-analysis`,
прежние artifact rules сохранены. Build Report Tab `Static Analysis` использует
`startPage=static-analysis/summary.html`, обязательный `type=BuildReportTab`.
`publish.sh` дополнительно проверяет PASS для точной Git-ревизии.

Фактические шаги и правила без секретных параметров экспортированы в
`scripts/ci/teamcity-static-steps.json`. Это управляемый REST/UI-экспорт, а не
фиктивный Kotlin DSL: server-owned конфигурация не заменялась. Before-снимок
сохранён локально вне Git в `/tmp/opencode/teamcity-before-lab6.json`.
Версии обновлять отдельным commit с positive/negative gate-тестами и Feature Verify.

## Фактическая проверка 02.11.2026

- Первичная проверка: [Feature Verify #8, build 409](http://localhost:8111/buildConfiguration/RacingClub_FeatureVerify/409), revision `24bdcdd`, RACING-TEST, SUCCESS; до добавления нового теста реального Gitleaks и publish guard. Сохранён `verified-image.txt`.
- Негативный сценарий: [Feature Verify #9, build 410](http://localhost:8111/buildConfiguration/RacingClub_FeatureVerify/410), временный Ruff F821, FAILURE на quality step. Временный файл удалён из ветки.
- Негативный Dev-сценарий: [Dev Verify and Publish #4, build 413](http://localhost:8111/buildConfiguration/RacingClub_DevVerifyPublish/413), FAILURE на том же quality step; publish Docker image не запускался. Артефакт `static-analysis` присутствовал и содержал отчёты.

Тестовая ветка `feature/lab6-negative-probe` после проверки очищена от дефекта; branch filter Dev возвращён к `+:dev`. Feature и Dev configuration изменены, registry credentials не менялись. Build Report Tab создан штатной UI-формой и проверен на `static-analysis/summary.html`.

На рабочем дереве после финальных изменений: quality PASS (144 находки, 0 blocker),
security PASS (40 находок, 0 HIGH/HIGH), secrets PASS (0; вся доступная история
и рабочее дерево). Контрактные тесты `tests.test_static_analysis`: 7 passed.

## Восстановление и повтор

При ошибке анализатора сначала открыть `static-analysis/summary.html` и JSON конкретного раздела, исправить код, затем повторить сборку. При ошибке bootstrap проверить Python 3.14, сеть агента и доступность pinned package/release. Для отката TeamCity сохранить прежние build steps и artifact rules из аудита перед изменением; текущая публикация всё равно блокируется без отчётов точной ревизии.

## Источники

- Ruff integrations: https://docs.astral.sh/ruff/integrations/
- Bandit documentation: https://bandit.readthedocs.io/en/latest/man/bandit.html
- Gitleaks: https://github.com/gitleaks/gitleaks
- Pylint output: https://pylint.readthedocs.io/en/latest/user_guide/usage/output.html
- Flake8 options: https://flake8.pycqa.org/en/latest/user/options.html
- Semgrep rules: https://semgrep.dev/docs/running-rules
- TruffleHog: https://github.com/trufflesecurity/trufflehog
- TeamCity build steps: https://www.jetbrains.com/help/teamcity/configuring-build-steps.html
