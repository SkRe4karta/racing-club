# ЛР8: выделенный доступ PROD — требуется настройка владельцем VM

Диагностика 03.11.2026: SSH-config содержит только два посторонних VPS;
ssh-agent пуст. В доступных TeamCity projects обнаружен только `racing_stage_cd`
в `RacingClub_Deployment` (назначение STAGE). PROD identity/username не подтверждены.
Однократная предыдущая read-only попытка 441 с существующей identity завершилась
`Permission denied (publickey,password)`. Повторные попытки не выполнялись.

VirtualBox подтверждает работающую VM `RACING-PROD`, NAT SSH
`127.0.0.1:2223 -> guest:22`, WEB `127.0.0.1:8083 -> guest:8080`,
внутреннюю сеть `racing-lab`. Настройки NAT не предоставляют SSH username/identity.
Документация проекта содержит адреса, но не подтверждённые PROD credentials.

## Минимальная настройка через собственную консоль VM

1. Открыть консоль **RACING-PROD** в VirtualBox и войти существующим разрешённым
   локальным пользователем. Подтвердить `hostname`, `whoami`, `id` и сетевой адрес.
   Не подбирать пароль и не создавать привилегированный аккаунт ради обхода доступа.
2. После разрешения владельца создать **отдельный** ed25519 ключ для PROD на
   доверенной машине; private key сохранить вне проекта с правами600 и passphrase.
   Не копировать private/public identity STAGE.
3. Через консоль добавить только public key в `~/.ssh/authorized_keys`
   подтверждённого пользователя: каталог700, файл600, корректный владелец.
   Отключить forwarding для ключа (`restrict`); для CI ограничить source IP
   RACING-CI, если сетевой путь подтверждён. Не выключать host-key verification.
4. Получить fingerprint SSH host key непосредственно из консоли VM и сверить
   с известным fingerprint клиента. Не доверять одному `ssh-keyscan`.
5. Сохранить в локальном SSH-config отдельный Host racing-prod с HostName127.0.0.1,
   Port2223, **подтверждённым** User, новым IdentityFile и IdentitiesOnlyyes.
   Выполнить одну команду `hostname; id` без изменения системы.
6. Для TeamCity загрузить отдельный ключ `racing_prod_cd` в отдельный PROD project
   с ограниченными правами; использовать проверенный known_hosts для10.20.0.13.
   Не передавать private key через build parameters/artifacts/Git.

После доступа сначала read-only инвентаризация контейнеров/томов, actual database,
revision/структуры/объёма данных и свободного места. До pg_dump отдельно согласовать
объём и место: private каталог700, dump600, запас места для dump и изолированного
restore; dump не публиковать в TeamCity/Git/ZIP. Production DDL/deploy требуют
отдельного явного разрешения, успешного restore rehearsal и окна обслуживания.
