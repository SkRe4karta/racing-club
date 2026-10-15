from datetime import date, time
from app import create_app, db
from app.models import Owner, Horse, Jockey, Competition, Result

def seed_database():
    app = create_app()
    with app.app_context():
        if any(db.session.query(model).first() for model in (Owner, Horse, Jockey, Competition, Result)):
            raise SystemExit("Демонстрационные данные разрешены только в пустой БД. Укажите отдельный DATABASE_URL.")

        print("Создание демонстрационных данных...")

        # 1. Владельцы
        owners_data = [
            Owner(full_name="Воронов Михаил Сергеевич", address="г. Москва, Ленинградский пр-т, д. 24", phone="+7 (903) 123-45-67"),
            Owner(full_name="Орлова Екатерина Андреевна", address="Московская обл., Раменское, ул. Луговая, д. 7", phone="+7 (916) 234-56-78"),
            Owner(full_name="Соколов Дмитрий Николаевич", address="г. Казань, ул. Ипподромная, д. 15", phone="+7 (927) 345-67-89"),
            Owner(full_name="Морозов Артем Павлович", address="г. Ростов-на-Дону, пер. Конный, д. 3", phone="+7 (988) 456-78-90"),
        ]
        db.session.add_all(owners_data)
        db.session.flush()

        # 2. Лошади
        horses_data = [
            Horse(nickname="Буцефал", gender="Жеребец", age=4, owner_id=owners_data[0].id),
            Horse(nickname="Громовержец", gender="Жеребец", age=5, owner_id=owners_data[0].id),
            Horse(nickname="Золотая Стрела", gender="Кобыла", age=3, owner_id=owners_data[1].id),
            Horse(nickname="Северный Ветер", gender="Мерин", age=6, owner_id=owners_data[1].id),
            Horse(nickname="Батыр", gender="Жеребец", age=4, owner_id=owners_data[2].id),
            Horse(nickname="Алмазная Звезда", gender="Кобыла", age=5, owner_id=owners_data[2].id),
            Horse(nickname="Ураган", gender="Жеребец", age=3, owner_id=owners_data[3].id),
        ]
        db.session.add_all(horses_data)
        db.session.flush()

        # 3. Жокеи
        jockeys_data = [
            Jockey(full_name="Смирнов Алексей Викторович", address="г. Москва, ул. Беговая, д. 18", age=28, rating=9.4),
            Jockey(full_name="Васильев Денис Игоревич", address="г. Ростов-на-Дону, ул. Степная, д. 41", age=32, rating=8.9),
            Jockey(full_name="Хакимов Руслан Ильдарович", address="г. Казань, пр-т Победы, д. 102", age=24, rating=8.2),
            Jockey(full_name="Кузнецов Игорь Павлович", address="Московская обл., г. Химки, ул. Лесная, д. 9", age=36, rating=7.8),
            Jockey(full_name="Попова Анна Дмитриевна", address="г. Тверь, наб. Волги, д. 14", age=23, rating=8.6),
        ]
        db.session.add_all(jockeys_data)
        db.session.flush()

        # 4. Прошедшее состязание №1 (Кубок Открытия сезона 2026)
        comp_past1 = Competition(
            title="Кубок Открытия сезона 2026",
            event_date=date(2026, 5, 15),
            event_time=time(12, 0),
            location="Центральный Московский ипподром",
            status="completed"
        )
        db.session.add(comp_past1)
        db.session.flush()

        results_past1 = [
            Result(competition_id=comp_past1.id, horse_id=horses_data[0].id, jockey_id=jockeys_data[0].id, finish_time_seconds=122.45, is_disqualified=False, place=1),
            Result(competition_id=comp_past1.id, horse_id=horses_data[2].id, jockey_id=jockeys_data[2].id, finish_time_seconds=124.10, is_disqualified=False, place=2),
            Result(competition_id=comp_past1.id, horse_id=horses_data[3].id, jockey_id=jockeys_data[1].id, finish_time_seconds=125.80, is_disqualified=False, place=3),
            Result(competition_id=comp_past1.id, horse_id=horses_data[4].id, jockey_id=jockeys_data[3].id, finish_time_seconds=None, is_disqualified=True, place=None),
        ]
        db.session.add_all(results_past1)

        # 5. Прошедшее состязание №2 (Летний приз Раменского)
        comp_past2 = Competition(
            title="Летний приз Раменского",
            event_date=date(2026, 7, 20),
            event_time=time(14, 30),
            location="Раменский республиканский ипподром",
            status="completed"
        )
        db.session.add(comp_past2)
        db.session.flush()

        results_past2 = [
            Result(competition_id=comp_past2.id, horse_id=horses_data[4].id, jockey_id=jockeys_data[2].id, finish_time_seconds=118.90, is_disqualified=False, place=1),
            Result(competition_id=comp_past2.id, horse_id=horses_data[1].id, jockey_id=jockeys_data[0].id, finish_time_seconds=120.30, is_disqualified=False, place=2),
            Result(competition_id=comp_past2.id, horse_id=horses_data[5].id, jockey_id=jockeys_data[4].id, finish_time_seconds=121.75, is_disqualified=False, place=3),
        ]
        db.session.add_all(results_past2)

        # 6. Будущее запланированное состязание (Осеннее Дерби Москвы 2026)
        comp_future = Competition(
            title="Осеннее Дерби Москвы 2026",
            event_date=date(2026, 10, 10),
            event_time=time(15, 0),
            location="Центральный Московский ипподром",
            status="planned"
        )
        db.session.add(comp_future)
        db.session.flush()

        results_future = [
            Result(competition_id=comp_future.id, horse_id=horses_data[0].id, jockey_id=jockeys_data[0].id, finish_time_seconds=None, is_disqualified=False, place=None),
            Result(competition_id=comp_future.id, horse_id=horses_data[6].id, jockey_id=jockeys_data[1].id, finish_time_seconds=None, is_disqualified=False, place=None),
            Result(competition_id=comp_future.id, horse_id=horses_data[2].id, jockey_id=jockeys_data[4].id, finish_time_seconds=None, is_disqualified=False, place=None),
            Result(competition_id=comp_future.id, horse_id=horses_data[3].id, jockey_id=jockeys_data[3].id, finish_time_seconds=None, is_disqualified=False, place=None),
        ]
        db.session.add_all(results_future)

        db.session.commit()
        print("База данных успешно инициализирована и наполнена демонстрационными данными!")

if __name__ == '__main__':
    seed_database()
