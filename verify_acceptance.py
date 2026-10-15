import unittest
import secrets
from datetime import date, time
from app import create_app, db
from app.models import Owner, Horse, Jockey, Competition, Result, User
from tests.support import isolated_database
from app.services import (
    create_future_competition,
    complete_planned_competition,
    create_completed_competition_direct,
    parse_time_input
)

class VerificationTestCase(unittest.TestCase):
    def setUp(self):
        self.database = isolated_database()
        self.app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': self.database.__enter__(),
            'WTF_CSRF_ENABLED': False
        })
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        # Тестовые базовые данные
        self.owner = Owner(full_name="Иванов Иван", address="Москва", phone="+79991112233")
        db.session.add(self.owner)
        db.session.flush()

        self.horse1 = Horse(nickname="Стрела", gender="Кобыла", age=4, owner_id=self.owner.id)
        self.horse2 = Horse(nickname="Буря", gender="Жеребец", age=5, owner_id=self.owner.id)
        self.horse3 = Horse(nickname="Вихрь", gender="Мерин", age=3, owner_id=self.owner.id)
        db.session.add_all([self.horse1, self.horse2, self.horse3])
        db.session.flush()

        self.jockey1 = Jockey(full_name="Алексеев А.А.", address="Москва", age=25, rating=9.0)
        self.jockey2 = Jockey(full_name="Борисов Б.Б.", address="Тверь", age=30, rating=8.5)
        self.jockey3 = Jockey(full_name="Сергеев С.С.", address="Казань", age=22, rating=8.0)
        db.session.add_all([self.jockey1, self.jockey2, self.jockey3])
        db.session.commit()

        self.client = self.app.test_client()
        # v2 protects writes: run original regression assertions as a real ROOT.
        password = secrets.token_urlsafe(24)
        root = User(email='regression@example.test', role='ROOT', status='active')
        root.set_password(password)
        db.session.add(root)
        db.session.commit()
        response = self.client.post('/auth/login', data={'email': root.email, 'password': password})
        self.assertEqual(response.status_code, 302)

    def tearDown(self):
        db.session.remove()
        db.engine.dispose()
        self.app_context.pop()
        self.database.__exit__(None, None, None)

    def test_1_add_owner_and_view(self):
        # 1. Добавление владельца и отображение его в списке
        res = self.client.post('/owners/add', data={
            'full_name': 'Петров Петр',
            'address': 'СПб',
            'phone': '+78121234567'
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn('Петров Петр'.encode('utf-8'), res.data)

    def test_2_add_horse_and_detail(self):
        # 2. Добавление лошади с выбором существующего владельца и открытие карточки
        res = self.client.post('/horses/add', data={
            'nickname': 'Молния',
            'gender': 'Кобыла',
            'age': 3,
            'owner_id': self.owner.id
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn('Молния'.encode('utf-8'), res.data)

        horse = Horse.query.filter_by(nickname='Молния').first()
        self.assertIsNotNone(horse)
        card_res = self.client.get(f'/horses/{horse.id}')
        self.assertEqual(card_res.status_code, 200)
        self.assertIn('Молния'.encode('utf-8'), card_res.data)

    def test_3_add_jockey_and_detail(self):
        # 3. Добавление жокея и открытие карточки
        res = self.client.post('/jockeys/add', data={
            'full_name': 'Николаев Н.Н.',
            'address': 'Ростов',
            'age': 27,
            'rating': '9.2'
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn('Николаев Н.Н.'.encode('utf-8'), res.data)

        jockey = Jockey.query.filter_by(full_name='Николаев Н.Н.').first()
        self.assertIsNotNone(jockey)
        card_res = self.client.get(f'/jockeys/{jockey.id}')
        self.assertEqual(card_res.status_code, 200)
        self.assertIn('Николаев Н.Н.'.encode('utf-8'), card_res.data)

    def test_4_future_competition_creation_and_listing(self):
        # 4. Создание будущего состязания с заявленными парами
        comp = create_future_competition(
            title="Тестовый Заезд",
            event_date_val=date(2026, 11, 1),
            event_time_val=time(14, 0),
            location="Тестовый Ипподром",
            participants=[
                {'horse_id': self.horse1.id, 'jockey_id': self.jockey1.id},
                {'horse_id': self.horse2.id, 'jockey_id': self.jockey2.id},
            ]
        )
        self.assertEqual(comp.status, 'planned')

        # Должно быть в будущих
        res_future = self.client.get('/competitions/future')
        self.assertIn('Тестовый Заезд'.encode('utf-8'), res_future.data)

        # НЕ должно быть в прошедших
        res_past = self.client.get('/competitions/past')
        self.assertNotIn('Тестовый Заезд'.encode('utf-8'), res_past.data)

    def test_5_and_6_complete_competition_and_calculate_places(self):
        # 5 и 6. Завершение состязания, автоматический расчет мест по времени и отсутствие места у дисквалифицированного
        comp = create_future_competition(
            title="Кубок Осени",
            event_date_val=date(2026, 11, 1),
            event_time_val=time(14, 0),
            location="Тестовый Ипподром",
            participants=[
                {'horse_id': self.horse1.id, 'jockey_id': self.jockey1.id},
                {'horse_id': self.horse2.id, 'jockey_id': self.jockey2.id},
                {'horse_id': self.horse3.id, 'jockey_id': self.jockey3.id},
            ]
        )
        results = Result.query.filter_by(competition_id=comp.id).all()
        # horse1: 125.0 сек -> 2 место
        # horse2: 120.0 сек -> 1 место (победитель)
        # horse3: дисквалификация -> place None
        r1 = [r for r in results if r.horse_id == self.horse1.id][0]
        r2 = [r for r in results if r.horse_id == self.horse2.id][0]
        r3 = [r for r in results if r.horse_id == self.horse3.id][0]

        results_data = {
            r1.id: {'time_str': '125.0', 'is_disqualified': False},
            r2.id: {'time_str': '120.0', 'is_disqualified': False},
            r3.id: {'time_str': '', 'is_disqualified': True},
        }

        completed_comp = complete_planned_competition(comp.id, results_data)
        self.assertEqual(completed_comp.status, 'completed')

        db.session.refresh(r1)
        db.session.refresh(r2)
        db.session.refresh(r3)

        self.assertEqual(r2.place, 1)
        self.assertEqual(r1.place, 2)
        self.assertIsNone(r3.place)
        self.assertTrue(r3.is_disqualified)

    def test_7_no_edit_after_complete(self):
        # 7. Запрет повторного изменения результатов завершенного состязания
        comp = create_future_competition(
            title="Заезд Финал",
            event_date_val=date(2026, 11, 1),
            event_time_val=time(14, 0),
            location="Ипподром",
            participants=[{'horse_id': self.horse1.id, 'jockey_id': self.jockey1.id}]
        )
        r = Result.query.filter_by(competition_id=comp.id).first()
        complete_planned_competition(comp.id, {r.id: {'time_str': '120.0', 'is_disqualified': False}})

        # Попытка снова завершить / изменить
        with self.assertRaises(ValueError) as ctx:
            complete_planned_competition(comp.id, {r.id: {'time_str': '115.0', 'is_disqualified': False}})
        self.assertIn("Результаты завершенного состязания изменять нельзя", str(ctx.exception))

    def test_8_add_past_competition_direct(self):
        # 8. Добавление уже прошедшего состязания сразу с участниками и результатами
        comp = create_completed_competition_direct(
            title="Исторический Заезд",
            event_date_val=date(2026, 6, 1),
            event_time_val=time(15, 0),
            location="Казанский ипподром",
            participants=[
                {'horse_id': self.horse1.id, 'jockey_id': self.jockey1.id, 'time_str': '02:00.00', 'is_disqualified': False},
                {'horse_id': self.horse2.id, 'jockey_id': self.jockey2.id, 'time_str': '01:58.50', 'is_disqualified': False},
            ]
        )
        self.assertEqual(comp.status, 'completed')
        r_list = Result.query.filter_by(competition_id=comp.id).all()
        r_fastest = [r for r in r_list if r.horse_id == self.horse2.id][0]
        self.assertEqual(r_fastest.place, 1)

    def test_9_horse_and_jockey_history(self):
        # 9. Отображение истории состязаний выбранного жокея и лошади
        comp = create_completed_competition_direct(
            title="Гран-При",
            event_date_val=date(2026, 7, 1),
            event_time_val=time(16, 0),
            location="Московский ипподром",
            participants=[
                {'horse_id': self.horse1.id, 'jockey_id': self.jockey1.id, 'time_str': '110.0', 'is_disqualified': False}
            ]
        )
        card_horse = self.client.get(f'/horses/{self.horse1.id}')
        self.assertIn('Гран-При'.encode('utf-8'), card_horse.data)
        self.assertIn('1 место'.encode('utf-8'), card_horse.data)

        card_jockey = self.client.get(f'/jockeys/{self.jockey1.id}')
        self.assertIn('Гран-При'.encode('utf-8'), card_jockey.data)
        self.assertIn('1 место'.encode('utf-8'), card_jockey.data)

    def test_10_validation_and_error_handling(self):
        # 10. Вывод понятного сообщения при некорректном вводе или нарушении ограничений
        # Ошибка времени
        with self.assertRaises(ValueError) as ctx:
            parse_time_input("-5")
        self.assertIn("Некорректно указано время результата", str(ctx.exception))

        with self.assertRaises(ValueError) as ctx:
            parse_time_input("abc")
        self.assertIn("Некорректно указано время результата", str(ctx.exception))

        # Ошибка дубликата лошади в одном состязании
        with self.assertRaises(ValueError) as ctx:
            create_future_competition(
                title="Дубль",
                event_date_val=date(2026, 12, 1),
                event_time_val=time(12, 0),
                location="Ипподром",
                participants=[
                    {'horse_id': self.horse1.id, 'jockey_id': self.jockey1.id},
                    {'horse_id': self.horse1.id, 'jockey_id': self.jockey2.id},
                ]
            )
        self.assertIn("уже заявлена на это состязание", str(ctx.exception))

if __name__ == '__main__':
    unittest.main()
