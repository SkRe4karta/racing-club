# Отчёт по лабораторной работе №6

## Автоматизация процессов жизненного цикла программных средств

**Студент:** Зелёнкин Дмитрий Владимирович  
**Группа:** 241-327  
**Преподаватель:** Красников А. С.  
**Проект:** Racing Club, АИС «Скачки»

## 1. Цель

Освоить включение статического анализа Python-кода в существующий CI/CD pipeline,
определить блокирующие пороги и обеспечить сохранение безопасных машинных и HTML-отчётов.

## 2. Задание и исследование

Рассмотрены Ruff, Pylint, Flake8, Bandit, Semgrep, Gitleaks и TruffleHog.
Сравнительная таблица и ссылки на официальную документацию приведены в
`docs/LAB6_STATIC_ANALYSIS.md`. Выбраны Ruff для качества, Bandit для SAST и
Gitleaks для секретов. Они устанавливаются с закреплёнными версиями.

## 3. Политика порогов

Ruff BLOCKER означает ошибки корректности и неопределённые имена (`F821`, `F822`,
`F823`, `F631`, `F701`, `F702`, `F704`, `F706`, `F707`, `F722`, `F901`). Остальные
E4/E7/E9/F-находки публикуются как advisory. Bandit блокирует только HIGH severity
и HIGH confidence; Bandit не имеет нативного CRITICAL, поэтому это документированный
консервативный эквивалент, не переименованный в CRITICAL. Любая находка Gitleaks
блокирует сборку. Пустой/неполный scan, shallow checkout и ошибка инструмента также
завершают шаг с ошибкой.

## 4. Реализация

Запуск выполняют командами:

```bash
bash scripts/ci/prepare-static-analysis.sh
STATIC_PYTHON=.static-tools/bin/python bash scripts/ci/static-analysis.sh
python -m unittest tests.test_static_analysis -v
```

Скрипты создают `artifacts/static-analysis/{quality,security,secrets}`,
`summary.html` и `summary.json`. Значения секретов и исходные строки в отчёты не
попадают. Общий runner возвращает 0 для PASS, 1 для policy BLOCKED и 2 для ошибки
инструмента/отчёта. `publish.sh` повторно проверяет PASS отчётов той же ревизии.

## 5. TeamCity

В существующие `Feature Verify` и `Dev Verify and Publish` добавлены подготовка,
quality, security, secrets и summary до тестов и Docker publish. Результаты собраны
в TeamCity Artifacts как `static-analysis`; создан Build Report Tab `Static Analysis`.
Публикация образа выполняется только после успешного анализа и тестов.

## 6. Результаты

Первичная успешная проверка: [Feature Verify #8](http://localhost:8111/buildConfiguration/RacingClub_FeatureVerify/409),
revision `24bdcdd`, RACING-TEST, статус SUCCESS. В негативной ветке с временным
Ruff F821 [Feature Verify #9](http://localhost:8111/buildConfiguration/RacingClub_FeatureVerify/410)
получил FAILURE на quality step. [Dev Verify and Publish #4](http://localhost:8111/buildConfiguration/RacingClub_DevVerifyPublish/413)
также получил FAILURE на quality step; Docker publish не запускался, а отчёты
`static-analysis` были опубликованы.

Локальный финальный скан: Ruff 144 advisory и 0 blocker, Bandit 40 findings и
0 HIGH/HIGH, Gitleaks 0; `tests.test_static_analysis` дал 7 passed. Временный
дефект удалён из `feature/lab6-negative-probe`, ветка не вливалась в dev/master/prod.

## 7. Иллюстрации

Скриншоты получены из реального TeamCity и сохранены в `docs/screenshots/`:

1. `teamcity-success.png` — успешная сборка Feature Verify.
2. `teamcity-feature-failure.png` — отказ Feature Verify на Ruff.
3. `teamcity-dev-failure.png` — отказ Dev Verify and Publish до публикации.
4. `teamcity-artifacts.png` — опубликованные артефакты static-analysis.
5. `teamcity-report.png` — вкладка Static Analysis.
6. `teamcity-report-tab-settings.png` — настройка Build Report Tab.

## 8. Вывод

Выбранные анализаторы интегрированы в существующую цепочку. Блокирующие правила
проверены положительным и отрицательным сценариями, отчёты доступны как TeamCity
Artifacts и Report Tab, а Docker publish защищён повторной проверкой результата.
