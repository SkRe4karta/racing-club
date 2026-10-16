"""Целевые регрессии модернизации; только изолированная тестовая БД."""
import csv
import io
import re
import unittest
from datetime import date, time, timedelta
from app import db
from app.models import Owner, Horse, Jockey, Competition, Result
from app.services import create_future_competition, create_completed_competition_direct, complete_planned_competition, parse_time_input
from tests.support import legacy_competition, legacy_completed
import verify_acceptance as acceptance


class ModernizationTests(unittest.TestCase):
    setUp = acceptance.VerificationTestCase.setUp
    tearDown = acceptance.VerificationTestCase.tearDown

    def planned(self):
        return legacy_competition('Проверка старта', date(2026, 11, 10), time(12), 'Москва', [
            {'horse_id': self.horse1.id, 'jockey_id': self.jockey1.id},
            {'horse_id': self.horse2.id, 'jockey_id': self.jockey2.id},
        ])

    def test_routes_empty_states_and_assets(self):
        for url in ['/', '/health', '/owners/', '/horses/', '/jockeys/', '/owners/add', '/horses/add', '/jockeys/add', '/competitions/future', '/competitions/past', '/competitions/future/add', '/competitions/past/add', '/competitions/complete', '/competitions/future?view=calendar', '/static/css/style.css', '/static/js/app.js', '/static/js/theme.js', '/static/js/dynamic_rows.js']:
            with self.subTest(url=url):
                with self.client.get(url) as response:
                    self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get('/missing').status_code, 404)
        self.assertEqual(self.client.get('/horses/' + '9'*100).status_code, 404)
        self.assertEqual(self.client.get('/horses/?age=' + '9'*100).status_code, 200)
        for model in [Result, Competition, Horse, Jockey, Owner]:
            model.query.delete()
        db.session.commit()
        for url in ['/', '/owners/', '/horses/', '/jockeys/', '/competitions/future', '/competitions/past', '/competitions/complete', '/horses/add', '/competitions/future/add', '/competitions/past/add']:
            self.assertEqual(self.client.get(url).status_code, 200)

    def test_cyrillic_search_filters_sort_and_pagination(self):
        self.assertIn('Стрела', self.client.get('/horses/?q=СТРЕЛА&gender=Кобыла&age=4&owner=ИВАНОВ').text)
        self.assertNotIn('Стрела</a>', self.client.get('/horses/?q=СТРЕЛА&age=5').text)
        self.assertIn('Иванов Иван', self.client.get('/owners/?q=ИВАНОВ&phone=999').text)
        self.assertIn('Алексеев', self.client.get('/jockeys/?q=АЛЕКСЕЕВ&sort=rating').text)
        for i in range(45):
            db.session.add(Owner(full_name=f'Тест {i:03}', phone='555'))
        db.session.commit()
        page = self.client.get('/owners/?q=ТЕСТ&phone=555&sort=name_desc&page=2').text
        self.assertIn('Тест 024', page)
        self.assertNotIn('Тест 044</a>', page)
        self.assertIn('phone=555', page)
        for value in ['-2','abc','99999999999999999999']:
            self.assertEqual(self.client.get('/owners/?page='+value+'&sort=DROP%20TABLE').status_code, 200)
        self.assertIn('Записи не найдены', self.client.get('/owners/?q=%25').text)

    def test_competition_list_calendar_and_export(self):
        comp = self.planned()
        for url in ['/competitions/future?q=ПРОВЕРКА&location=МОСКВА&date=2026-11-10', '/competitions/future?view=calendar&month=2026-11', '/competitions/future?view=calendar&month=garbage', '/competitions/future?view=calendar&month=0001-01', '/competitions/future?date=invalid', f'/competitions/future/{comp.id}', f'/competitions/complete/{comp.id}']:
            self.assertEqual(self.client.get(url).status_code, 200)
        self.assertIn('Проверка старта', self.client.get('/competitions/future?view=calendar&month=2026-11').text)
        for kind in ['owners/', 'horses/', 'jockeys/', 'competitions/future', 'competitions/past']:
            response = self.client.get('/'+kind+'?export=csv')
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.data.startswith(b'\xef\xbb\xbf'))
            self.assertIn('attachment', response.headers['Content-Disposition'])
        self.assertIn('Стрела', self.client.get(f'/competitions/{comp.id}/results.csv').text)

    def test_nonfinite_and_ambiguous_results_rejected(self):
        for value in ['NaN','inf','-inf','1:NaN','0','-4','1:60','abc','0.001','9'*400+':01']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_time_input(value)
        self.assertEqual(parse_time_input('02:04,50'), 124.5)
        comp = self.planned()
        comp.event_date = date.today() - timedelta(days=1)
        db.session.commit()
        rows = list(comp.results)
        with self.assertRaises(ValueError):
            complete_planned_competition(comp.id, {rows[0].id:{'time_str':'120', 'is_disqualified':True}, rows[1].id:{'time_str':'121'}}, actor=self.actor)
        self.assertEqual(db.session.get(Competition, comp.id).status, 'planned')
        self.assertTrue(all(r.finish_time_seconds is None for r in comp.results))

    def test_atomic_failure_missing_result_and_foreign_ids(self):
        comp = self.planned()
        comp.event_date = date.today() - timedelta(days=1)
        db.session.commit()
        row = comp.results[0]
        for data in [{row.id:{'time_str':'120'}}, {r.id:{'time_str':'bad' if r.id != row.id else '120'} for r in comp.results}]:
            with self.assertRaises(ValueError):
                complete_planned_competition(comp.id, data, actor=self.actor)
            self.assertEqual(db.session.get(Competition, comp.id).status, 'planned')
            self.assertTrue(all(r.place is None and r.finish_time_seconds is None for r in comp.results))
        count = Competition.query.count()
        for participants in [[{'horse_id':'9'*100,'jockey_id':self.jockey1.id}], [{'horse_id':99999,'jockey_id':self.jockey1.id}], [{'horse_id':self.horse1.id,'jockey_id':None}], [{'horse_id':self.horse1.id,'jockey_id':self.jockey1.id}, {'horse_id':self.horse2.id,'jockey_id':self.jockey1.id}]]:
            with self.assertRaises(ValueError):
                create_future_competition('Ошибка', date.today(), time(12), 'Москва', participants)
            self.assertEqual(Competition.query.count(), count)

    def test_post_flows_disqualification_alignment_and_readonly(self):
        comp = self.planned()
        comp.event_date = date.today() - timedelta(days=1)
        db.session.commit()
        first, second = comp.results
        payload = {f'disq_{first.id}':'on', f'time_{second.id}':'121.5'}
        self.assertEqual(self.client.post(f'/competitions/complete/{comp.id}', data=payload).status_code, 302)
        db.session.refresh(comp)
        self.assertTrue(first.is_disqualified)
        self.assertEqual(second.finish_time_seconds, 121.5)
        self.assertEqual(second.place, 1)
        response = self.client.post(f'/competitions/complete/{comp.id}', data={f'time_{second.id}':'1'}, follow_redirects=True)
        self.assertIn('изменять нельзя', response.text)
        self.assertEqual(second.finish_time_seconds, 121.5)
        self.assertEqual(comp.status, 'completed')

    def test_future_post_and_retired_participant_bypasses(self):
        payload = {'title':'Форма старта','event_date':(date.today()+timedelta(days=10)).isoformat(),
                   'event_time':'12:00','location':'Москва','distance':'1600','max_participants':'20'}
        self.assertEqual(self.client.post('/competitions/future/add',data=payload).status_code,302)
        comp = Competition.query.filter_by(title='Форма старта').one()
        self.assertEqual(comp.results, [])
        count = Competition.query.count()
        payload['horse_id[]'] = str(self.horse1.id)
        payload['jockey_id[]'] = str(self.jockey1.id)
        self.assertEqual(self.client.post('/competitions/future/add',data=payload).status_code,400)
        self.assertEqual(self.client.post('/competitions/past/add',data=payload).status_code,410)
        self.assertEqual(Competition.query.count(),count)

    def test_invalid_forms_keep_values_and_do_not_write(self):
        counts = (Owner.query.count(),Horse.query.count(),Jockey.query.count())
        for url,payload,retained in [('/owners/add',{'full_name':'','phone':'123'},'123'),('/horses/add',{'nickname':'Ошибка возраста','gender':'Кобыла','age':'-1','owner_id':self.owner.id},'Ошибка возраста'),('/horses/add',{'nickname':'Неверный владелец','gender':'Кобыла','age':'3','owner_id':99999},'Неверный владелец'),('/jockeys/add',{'full_name':'Неверный рейтинг','age':'25','rating':'NaN'},'Неверный рейтинг')]:
            response=self.client.post(url,data=payload)
            self.assertEqual(response.status_code,200)
            self.assertIn(retained,response.text)
        self.assertEqual(counts,(Owner.query.count(),Horse.query.count(),Jockey.query.count()))

    def test_csrf_and_html_csv_injection(self):
        self.app.config['WTF_CSRF_ENABLED']=True
        self.assertEqual(self.client.post('/owners/add',data={'full_name':'Заблокировано'}).status_code,400)
        form = self.client.get('/owners/add').text
        token=re.search('name="csrf_token" value="([^"]+)"',form).group(1)
        self.assertEqual(self.client.post('/owners/add',data={'full_name':'=HYPERLINK("test")','csrf_token':token}).status_code,302)
        db.session.add(Owner(full_name='<script>alert(1)</script>'))
        db.session.commit()
        html=self.client.get('/owners/').text
        self.assertNotIn('<script>alert(1)</script>',html)
        self.assertIn('&lt;script&gt;',html)
        rows=list(csv.reader(io.StringIO(self.client.get('/owners/?export=csv').text.lstrip('\ufeff')),delimiter=';'))
        self.assertTrue(any(row[0].startswith("'=HYPERLINK") for row in rows))

    def test_statistics_ties_and_unmodified_rating(self):
        initial=self.jockey1.rating
        comp=legacy_completed('Ничья',date.today(),time(12),'Москва',[
            {'horse_id':self.horse1.id,'jockey_id':self.jockey1.id,'time_str':'120'},
            {'horse_id':self.horse2.id,'jockey_id':self.jockey2.id,'time_str':'120'},
            {'horse_id':self.horse3.id,'jockey_id':self.jockey3.id,'time_str':'121'},
        ])
        self.assertEqual([r.place for r in comp.results],[1,1,3])
        for url in ['/',f'/horses/{self.horse1.id}',f'/jockeys/{self.jockey1.id}',f'/owners/{self.owner.id}',f'/competitions/past/{comp.id}']:
            self.assertEqual(self.client.get(url).status_code,200)
        self.assertIn('100.0%',self.client.get(f'/jockeys/{self.jockey1.id}').text)
        self.assertEqual(self.jockey1.rating,initial)


if __name__ == '__main__':
    unittest.main()
