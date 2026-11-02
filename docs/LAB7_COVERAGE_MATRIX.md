# ЛР №7 — матрица функционального покрытия

Источник требований: `docs/ROADMAP_V2.md`, разделы «Сценарии и приёмка конечных функций», «Роли и матрица доступа», «Предметная модель конечной системы» и критерии ЛР №7. Единица подсчёта — самостоятельное пользовательское поведение/бизнес-операция; отдельные роли и стадии разделены, когда их результат отличается. Нефункциональные пункты (адаптивность, доступность, SQL healthcheck, производительность) не подменяют функциональные требования.

`PASS` присваивается только после успешного запуска названного сценария. `NOT TESTED` означает, что проверка в этом выбранном наборе не запускалась; это не означает ошибку реализации. Покрытие полного ТЗ включает ещё не реализованное требование. Покрытие реализованных функций исключает только явно не реализованные требования.

| ID | Функциональное требование | Реализация | Модуль | Проверка | Вид | Результат |
|---|---|---|---|---|---|---|
| F01 | Публичная регистрация OWNER/JOCKEY/VIEWER создаёт корректный профиль | Реализовано | `app/auth.py` | `test_register_owner_creates_new_profile` | integration/HTTP+DB | NOT TESTED |
| F03 | Вход, одинаковый ответ для неверного/неизвестного/отключённого аккаунта | Реализовано | `app/auth.py` | `test_login_wrong_password_unknown_and_disabled_same_message` | integration/HTTP+DB | PASS |
| F04 | Выход через POST с очисткой сессии | Реализовано | `app/auth.py` | `test_logout_post_and_session_cleared` (существует, не выбран) | integration/HTTP | NOT TESTED |
| F05 | Блокировка аккаунта отзывает текущий доступ; ROOT может восстановить пользователя | Реализовано | `app/auth.py`, `app/admin_services.py` | `test_user_block_restore_revokes_sessions_unique_messages` | integration/HTTP+DB | PASS |
| F06 | Смена пароля с проверкой текущего пароля и отзывом прежних сессий | Реализовано | `app/auth.py` | `test_password_change_revokes_all_sessions_and_old_password` (существует, не выбран) | integration/HTTP | NOT TESTED |
| F07 | Восстановление доступа пользователем | Не реализовано | `app/auth.py` | — | integration/HTTP | NOT TESTED |
| F08 | Проверка роли и принадлежности объектов на сервере | Реализовано | `app/permissions.py`, `app/auth.py` | `test_owner_cannot_assign_horse_to_other_owner`; `test_permission_matrix_allows_only_declared_roles` | unit + integration/HTTP | PASS |
| F09 | Кабинет OWNER: профиль, лошади, история, статистика | Реализовано | `app/routes/cabinet.py` | `test_owner_dashboard_profile_horses_statistics_and_invitation` (существует, не выбран) | integration/HTTP+DB | NOT TESTED |
| F10 | Кабинет JOCKEY: профиль, выступления, рейтинг и статистика | Реализовано | `app/routes/cabinet.py` | `test_jockey_dashboard_history_win_rate_and_invitations` (существует, не выбран) | integration/HTTP+DB | NOT TESTED |
| F11 | Редактирование собственного профиля OWNER и запрет чужого профиля | Реализовано | `app/routes/owners.py`, `app/routes/jockeys.py` | `test_owner_profile_edit_and_foreign_profile_denied` | integration/HTTP+DB | PASS |
| F12 | Создание/редактирование лошади с проверкой владения | Реализовано | `app/routes/horses.py` | `test_horse_creation_edit_ownership_and_history_preserved` (существует, не выбран) | integration/HTTP+DB | NOT TESTED |
| F13 | Создание заявки с допустимой парой и начальным согласием стороны | Реализовано | `app/application_services.py`, `app/routes/cabinet.py` | `test_owner_submission_initial_consent_notification_and_no_result` | integration/HTTP+DB | PASS |
| F14 | Подтверждение второй стороны и переход заявки к административному решению | Реализовано | `app/application_services.py` | `test_pending_is_not_starter_then_admission_provenance_and_idempotence` | integration/HTTP+DB | PASS |
| F15 | Создание уведомления при событии заявки | Реализовано | `app/application_services.py` | `test_owner_submission_initial_consent_notification_and_no_result` | integration/HTTP+DB | PASS |
| F16 | ADMIN создаёт и редактирует соревнование, сроки и правила | Реализовано | `app/admin_services.py`, `app/routes/admin.py` | `test_create_edit_empty_competition_audit_and_rules` (существует, не выбран) | integration/HTTP+DB | NOT TESTED |
| F17 | Только подтверждённая заявка допускается в официальный стартовый список | Реализовано | `app/admin_services.py` | `test_pending_is_not_starter_then_admission_provenance_and_idempotence` | integration/HTTP+DB | PASS |
| F18 | Внесение времени/места и дисквалификации в протокол | Реализовано | `app/admin_services.py` | `test_publish_ties_dnf_disqualification_and_statistics` (существует, не выбран) | integration/HTTP+DB | NOT TESTED |
| F19 | Проверка формата/диапазона спортивного времени и данных протокола | Реализовано | `app/services.py`, `app/admin_services.py` | `test_seconds_and_minute_formats_normalize_to_hundredths`; `test_invalid_nonpositive_nonfinite_and_out_of_range_times_are_rejected`; `test_protocol_full_validation_no_early_or_unapproved_results` | unit + integration/DB | PASS |
| F20 | Атомарное завершение протокола и защита/аудируемая коррекция завершённого старта | Реализовано | `app/admin_services.py` | `test_repeat_completion_and_ordinary_edit_are_immutable` (существует, не выбран) | integration/DB | NOT TESTED |
| F22 | Append-only аудит изменений без полей учётных данных | Реализовано | `app/admin_services.py`, `app/routes/admin.py` | `test_audit_visibility_append_only_and_no_credential_fields` | integration/HTTP+DB | PASS |
| F23 | Публичные страницы владельцев, лошадей и жокеев | Реализовано | `app/routes/owners.py`, `app/routes/horses.py`, `app/routes/jockeys.py` | — | integration/HTTP | NOT TESTED |
| F24 | Поиск, фильтры, пагинация и CSV сохраняют выбранные параметры | Реализовано | `app/web.py`, `app/routes/main.py` | — | integration/HTTP+DB | NOT TESTED |
| F25 | Календарь показывает даты и состояния соревнований | Реализовано | `app/routes/competitions.py` | — | integration/HTTP+DB | NOT TESTED |
| F26 | История выступлений доступна из спортивных профилей | Реализовано | `app/analytics.py`, `app/routes/owners.py`, `app/routes/jockeys.py` | — | integration/HTTP+DB | NOT TESTED |
| F27 | Рейтинги и аналитика завершённых стартов с фильтром периода | Реализовано | `app/analytics.py`, `app/routes/analytics.py` | `test_public_analytics_and_period` | integration/HTTP+DB | PASS |
| F28 | Healthcheck проверяет доступность приложения и БД | Реализовано | `app/routes/main.py` | — | integration/HTTP+DB | NOT TESTED |
| F29 | VIEWER сохраняет прогноз победителя по официальным участникам | Реализовано | `app/prediction_services.py`, `app/routes/predictions.py` | `test_assessment_and_gets_do_not_write` | integration/HTTP+DB | PASS |
| F30 | VIEWER сохраняет упорядоченную тройку прогноза | Реализовано | `app/prediction_services.py`, `app/routes/predictions.py` | `test_assessment_and_gets_do_not_write` | integration/HTTP+DB | PASS |
| F31 | Срок приёма и revision предотвращают позднюю/устаревшую перезапись прогноза | Реализовано | `app/prediction_services.py` | `test_deadline_exact_and_completed_immutable`; `test_stale_edit_does_not_replace_current_prediction` | integration/HTTP+DB | PASS |
| F32 | Точность прогнозов пересчитывается по опубликованному протоколу; GET не пишет результат | Реализовано | `app/prediction_services.py` | `test_assessment_and_gets_do_not_write` | integration/HTTP+DB | PASS |

| F33 | Уведомления видны только получателю; прочтение и счётчик | Реализовано | `app/routes/cabinet.py` | — | integration | NOT TESTED |
| F34 | Отклонение и отмена заявки с фиксацией перехода | Реализовано | `app/application_services.py` | — | integration | NOT TESTED |
| F35 | ROOT меняет роли и доверенно связывает исторические профили | Реализовано | `app/admin_services.py` | — | integration | NOT TESTED |
| F36 | ROOT управляет системными настройками | Не реализовано | — | — | integration | NOT TESTED |
| F37 | Отменённые старты исключаются из точности прогнозов | Не реализовано | `app/prediction_services.py` | — | integration | NOT TESTED |

## Подсчёт

- Полное функциональное ТЗ: **15 / 35 = 42,9%**.
- Только реализованные функции (F07/F36/F37 исключены): **15 / 32 = 46,9%**.
- Этап 2: F05/F21 объединены; F01/F02 объединены и снят PASS (не все роли проверены выбранным набором); добавлены ранее пропущенные функции F33–F37. Старые ID сохранены для сопоставления.
- F29/F30/F32 подтверждены отдельными значениями winner_rate/trio_rate/slot_rate = 100 в `test_assessment_and_gets_do_not_write`; сравнение снимков до/после GET проверяет отсутствие записи. Сохранение каждого типа необходимо для получения ненулевой метрики соответствующего режима.
- Выбранный набор: 4 unit и 16 integration methods. Невыполненные сценарии не засчитываются. PostgreSQL и дополнительные CI-регрессии учитываются отдельно.
- Line coverage не измерялось; функциональная метрика не заменяется line coverage.
