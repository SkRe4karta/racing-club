"""Focused UI correction and password security checks. No ambient DATABASE_URL."""
import re
import secrets
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

import sqlalchemy as sa
from werkzeug.datastructures import MultiDict
from app import db
from app.models import User, Horse, Application, AuditLog, Competition
from tests import test_alpha2 as alpha2


class UICorrectionFixture(unittest.TestCase):
    setUp = alpha2.Alpha2Tests.setUp
    tearDown = alpha2.Alpha2Tests.tearDown
    token = alpha2.Alpha2Tests.token
    logged = alpha2.Alpha2Tests.logged
    login = alpha2.Alpha2Tests.login
    post = alpha2.Alpha2Tests.post

    def password_data(self, **changes):
        password = secrets.token_urlsafe(20)
        return {'current_password': self.password, 'new_password': password,
                'confirm_password': password, **changes}


class UICorrectionTests(UICorrectionFixture):
    def test_settings_all_roles_and_cabinet_destinations(self):
        self.assertEqual(self.client.get('/auth/account').status_code, 302)
        self.assertEqual(self.client.post('/auth/account/password', data={'csrf_token': self.token()}).status_code, 302)
        targets = {'root':'/root/', 'admin':'/admin/', 'owner':'/cabinet/',
                   'jockey':'/cabinet/', 'viewer':'/predictions/history'}
        for role, destination in targets.items():
            self.login(role)
            response = self.client.get('/auth/account')
            self.assertEqual(response.status_code, 200)
            self.assertIn('Настройки аккаунта', response.text)
            self.assertIn('Текущий пароль', response.text)
            self.assertIn('Последний вход', response.text)
            self.assertNotIn('Ваш аккаунт</h1>', response.text)
            self.assertRegex(response.text, 'class="login-link" href="'+re.escape(destination)+'"')
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            self.assertIn('Редактировать профиль',response.text) if role in ('owner','jockey') else None

    def test_password_change_revokes_all_sessions_and_old_password(self):
        first = self.login('viewer')
        second = self.app.test_client(); self.login('viewer', client=second)
        self.client = first
        old_cookie = first.get_cookie('session').value
        with self.app.app_context():
            original_other = db.session.get(User, self.ids['owner']).password_hash
        payload = self.password_data()
        response = self.post('/auth/account/password', payload)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, '/auth/login')
        self.assertIn('Все сеансы завершены',first.get('/auth/login').text)
        self.assertEqual(second.get('/auth/account').status_code, 302)
        replay = self.app.test_client();replay.set_cookie('session',old_cookie)
        self.assertEqual(replay.get('/auth/account').status_code, 302)
        self.assertEqual(first.get('/auth/account').status_code, 302)
        with self.app.app_context():
            user = db.session.get(User,self.ids['viewer'])
            self.assertTrue(user.check_password(payload['new_password']))
            self.assertFalse(user.check_password(self.password))
            self.assertEqual(db.session.get(User,self.ids['owner']).password_hash, original_other)
        self.assertEqual(self.post('/auth/login',{'email':'viewer@example.test','password':self.password}).status_code,400)
        self.assertEqual(self.post('/auth/login',{'email':'viewer@example.test','password':payload['new_password']}).status_code,302)
        self.assertEqual(self.client.get('/auth/account').status_code,200)

    def test_password_validation_preserves_hash_and_hides_values(self):
        self.login('owner')
        with self.app.app_context():original=db.session.get(User,self.ids['owner']).password_hash
        invalid = [self.password_data(current_password='incorrect-password'),
                   self.password_data(new_password='short',confirm_password='short'),
                   self.password_data(confirm_password='not-the-new-password'),
                   self.password_data(new_password=self.password,confirm_password=self.password)]
        for payload in invalid:
            response=self.post('/auth/account/password',payload)
            self.assertEqual(response.status_code,400)
            self.assertNotIn('value="'+payload['current_password']+'"',response.text)
            self.assertNotIn('value="'+payload['new_password']+'"',response.text)
        with self.app.app_context():self.assertEqual(db.session.get(User,self.ids['owner']).password_hash,original)

    def test_password_csrf_foreign_fields_and_disabled_session(self):
        self.login('jockey')
        payload=self.password_data()
        self.assertEqual(self.client.post('/auth/account/password',data=payload).status_code,400)
        self.assertEqual(self.post('/auth/account/password',{**payload,'user_id':self.ids['root']}).status_code,400)
        self.assertEqual(self.post('/auth/account/password',{**payload,'role':'ROOT'}).status_code,400)
        duplicate=MultiDict({**payload,'csrf_token':self.token()});duplicate.add('new_password',secrets.token_urlsafe(20))
        self.assertEqual(self.client.post('/auth/account/password',data=duplicate).status_code,400)
        with self.client.session_transaction() as session:session.pop('credential_stamp')
        self.assertEqual(self.client.get('/auth/account').status_code,302)
        self.clients.pop('jockey');self.login('jockey')
        token=self.token()
        with self.app.app_context():db.session.get(User,self.ids['jockey']).status='disabled';db.session.commit()
        self.assertEqual(self.client.post('/auth/account/password',data={**payload,'csrf_token':token}).status_code,302)
        with self.app.app_context():self.assertTrue(db.session.get(User,self.ids['jockey']).check_password(self.password))

    def test_password_attempt_limit_is_shared(self):
        self.login('viewer')
        for _ in range(self.app.config['LOGIN_LIMIT']):
            self.assertEqual(self.post('/auth/account/password',self.password_data(current_password='wrong')).status_code,400)
        other=self.app.test_client();self.login('viewer',client=other)
        response=self.post('/auth/account/password',self.password_data(),client=other)
        self.assertEqual(response.status_code,429)
        with self.app.app_context():self.assertTrue(db.session.get(User,self.ids['viewer']).check_password(self.password))

    def test_dashboard_counts_and_scoped_administrative_actions(self):
        self.login('root')
        with self.app.app_context():
            expected={'Зарегистрированные пользователи':db.session.query(User).count(),
                'Соревнования':db.session.query(Competition).count(),
                'Заявки, ожидающие решения':db.session.query(Application).filter_by(status='pending_admin').count(),
                'Административные события':db.session.query(AuditLog).count()}
        response=self.client.get('/root/')
        self.assertEqual(response.status_code,200)
        for label,count in expected.items():self.assertIn(f'<span>{label}</span><strong>{count}</strong>',response.text)
        self.assertIn('Исторические профили',response.text)
        self.assertIn('Последние административные события',response.text)
        self.login('admin');response=self.client.get('/admin/')
        self.assertEqual(response.status_code,200)
        self.assertNotIn('href="/root/users"',response.text)
        self.assertNotIn('Исторические профили',response.text)
        self.assertEqual(self.client.get('/root/').status_code,403)
        self.login('owner');self.assertEqual(self.client.get('/admin/').status_code,403)

    def test_sport_cards_use_own_completed_results(self):
        self.login('owner');response=self.client.get('/cabinet/')
        self.assertEqual(response.status_code,200)
        self.assertIn('sport-card-heading',response.text)
        self.assertIn('Выступления',response.text)
        self.assertIn('Призовые',response.text)
        self.assertIn('<dt>Победы</dt><dd>1</dd>',response.text)
        self.assertNotIn('Лошадь other_owner',response.text)
        self.assertIn(f'/horses/{self.ids["owner_horse"]}/edit',response.text)
        self.login('jockey');response=self.client.get('/cabinet/')
        self.assertEqual(response.status_code,200)
        self.assertIn('Мои предстоящие участия',response.text)
        self.assertNotIn('href="/horses/'+str(self.ids['owner_horse'])+'/edit"',response.text)

    def test_historical_profiles_are_root_only_and_read_only(self):
        self.assertEqual(self.client.get('/root/profiles').status_code,302)
        self.login('admin');self.assertEqual(self.client.get('/root/profiles').status_code,403)
        self.login('root')
        for path in ('/root/profiles','/root/profiles?side=jockey'):
            response=self.client.get(path);self.assertEqual(response.status_code,200)
            self.assertIn('Без аккаунта',response.text)
            self.assertNotIn('Владелец owner',response.text)
        self.assertEqual(self.post('/root/profiles',{'profile_id':self.ids['legacy_horse']}).status_code,405)


class PasswordTransactionTests(UICorrectionFixture):
    def test_concurrent_password_change_has_single_winner(self):
        clients=[];payloads=[]
        for _ in range(2):
            client=self.app.test_client();self.login('viewer',client=client)
            clients.append(client);payloads.append({**self.password_data(),'csrf_token':self.token(client)})
        barrier=Barrier(2)
        original=User.set_password
        def synchronized(instance,password):
            original(instance,password);barrier.wait(timeout=10)
        def submit(index):
            return clients[index].post('/auth/account/password',data=payloads[index]).status_code
        with patch.object(User,'set_password',synchronized):
            with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(submit,range(2)))
        self.assertEqual(sorted(results),[302,400])
        with self.app.app_context():
            user=db.session.get(User,self.ids['viewer'])
            self.assertEqual(sum(user.check_password(p['new_password']) for p in payloads),1)
            self.assertFalse(user.check_password(self.password))
