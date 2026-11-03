"""Alpha 3 integration/security/concurrency tests on an isolated migrated database."""
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date, time, timedelta
from threading import Barrier
from unittest.mock import patch

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError, OperationalError

from app import create_app, db
from app import admin_services as service
from app.application_services import create_application, decide_application
from app.models import Application, ApplicationEvent, AuditLog, Competition, Horse, Jockey, Notification, Owner, Result, User, utc_now
from tests import test_alpha2 as alpha2


class Alpha3Tests(unittest.TestCase):
    setUp = alpha2.Alpha2Tests.setUp
    tearDown = alpha2.Alpha2Tests.tearDown
    token = alpha2.Alpha2Tests.token
    logged = alpha2.Alpha2Tests.logged
    login = alpha2.Alpha2Tests.login
    post = alpha2.Alpha2Tests.post
    create = alpha2.Alpha2Tests.create
    application_id = alpha2.Alpha2Tests.application_id
    state = alpha2.Alpha2Tests.state
    counts = alpha2.Alpha2Tests.counts

    def pending(self, owner='owner', jockey='jockey'):
        self.assertEqual(self.create(owner, horse_id=self.ids[owner+'_horse'],
            jockey_id=self.ids[jockey+'_profile']).status_code, 302)
        identifier = self.application_id()
        self.login(jockey)
        self.assertEqual(self.post(f'/cabinet/applications/{identifier}/confirm').status_code, 302)
        return identifier

    def approve(self, identifier=None):
        identifier = identifier or self.pending()
        self.login('admin')
        self.assertEqual(self.post(f'/admin/applications/{identifier}/approve').status_code, 302)
        return identifier

    def started(self):
        with self.app.app_context():
            comp = db.session.get(Competition, self.ids['future'])
            comp.event_date = date.today()-timedelta(days=1)
            db.session.commit()

    def rows(self):
        with self.app.app_context():
            return db.session.scalars(sa.select(Result.id).where(Result.competition_id == self.ids['future']).order_by(Result.id)).all()

    def protocol(self, **changes):
        return {identifier: {'time_str':str(120+index), **changes} for index,identifier in enumerate(self.rows())}

    def snapshot_counts(self):
        with self.app.app_context():
            return tuple(db.session.scalar(sa.select(sa.func.count()).select_from(model))
                         for model in (Application, ApplicationEvent, Result, AuditLog, Notification))

    def new_data(self, **changes):
        return {'title':'Новый старт','event_date':(date.today()+timedelta(days=15)).isoformat(),
                'event_time':'15:30','location':'Казань','distance':'1600','max_participants':'2', **changes}

    def test_access_matrix_all_panels_and_post_methods(self):
        admin_paths = ['/admin/', '/admin/competitions', '/admin/applications', '/admin/audit']
        root_paths = ['/root/', '/root/users', f"/root/users/{self.ids['owner']}"]
        for path in admin_paths+root_paths:
            self.assertEqual(self.client.get(path).status_code, 302)
        for role in ('owner','jockey','viewer'):
            self.login(role)
            for path in admin_paths+root_paths:
                self.assertEqual(self.client.get(path).status_code, 403)
            for path in ('/admin/competitions/new', f"/admin/applications/1/approve", f"/root/users/{self.ids['root']}"):
                self.assertEqual(self.post(path, {'role':'ROOT'}).status_code, 403)
        self.login('admin')
        for path in admin_paths:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
        for path in root_paths:
            self.assertEqual(self.client.get(path).status_code, 403)
        self.login('root')
        for path in admin_paths+root_paths:
            self.assertEqual(self.client.get(path).status_code, 200)

    def test_create_edit_empty_competition_audit_and_rules(self):
        self.login('admin')
        response = self.post('/admin/competitions/new', self.new_data())
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            comp = db.session.scalar(sa.select(Competition).where(Competition.title == 'Новый старт'))
            identifier = comp.id
            self.assertEqual((comp.distance, comp.max_participants, len(comp.results)), (1600,2,0))
        self.assertEqual(self.post(f'/admin/competitions/{identifier}/edit', self.new_data(title='Изменённый старт')).status_code, 302)
        with self.app.app_context():
            entries = db.session.scalars(sa.select(AuditLog).order_by(AuditLog.id)).all()
            self.assertEqual([e.action for e in entries], ['competition_created','competition_updated'])
            self.assertEqual(entries[1].old_values['title'], 'Новый старт')
            self.assertEqual(entries[1].actor_id, self.ids['admin'])

    def test_invalid_competition_values_and_injected_status_do_not_write(self):
        self.login('admin')
        for change in ({'event_date':'bad'}, {'event_time':'25:00'}, {'event_date':date.today().isoformat(),'event_time':'00:00'},
                       {'distance':'nan'}, {'distance':'99'}, {'distance':'100001'}, {'max_participants':'0'},
                       {'max_participants':'1001'}, {'title':''}, {'registration_deadline':'bad'},
                       {'registration_deadline':(date.today()+timedelta(days=20)).isoformat()+'T12:00'},
                       {'registration_deadline':(date.today()-timedelta(days=1)).isoformat()+'T12:00'},
                       {'status':'completed'}, {'role':'ROOT'}, {'horse_id[]':'1'}):
            with self.subTest(change=change):
                self.assertEqual(self.post('/admin/competitions/new', self.new_data(**change)).status_code, 400)
        with self.app.app_context():
            self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(Competition)), 2)
            self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(AuditLog)), 0)

    def test_edit_frozen_with_invitations_admitted_and_completed(self):
        self.create()
        identifier = self.application_id()
        self.login('admin')
        self.assertEqual(self.post(f"/admin/competitions/{self.ids['future']}/edit",self.new_data()).status_code,400)
        self.login('jockey')
        self.post(f'/cabinet/applications/{identifier}/confirm')
        self.approve(identifier)
        self.assertEqual(self.post(f"/admin/competitions/{self.ids['future']}/edit",self.new_data()).status_code,400)
        self.assertEqual(self.post(f"/admin/competitions/{self.ids['past']}/edit",self.new_data()).status_code,400)

    def test_pending_is_not_starter_then_admission_provenance_and_idempotence(self):
        identifier = self.pending()
        guest = self.app.test_client()
        path = f"/competitions/future/{self.ids['future']}"
        self.assertNotIn('Лошадь owner', guest.get(path).text)
        self.assertEqual(self.rows(), [])
        self.approve(identifier)
        self.assertEqual(self.state(identifier), 'admin_confirmed')
        self.assertIn('Лошадь owner', guest.get(path).text)
        self.assertIn('Допущен администратором', guest.get(path).text)
        self.assertIn('Лошадь owner', guest.get(f"/competitions/{self.ids['future']}/results.csv").text)
        before = self.snapshot_counts()
        self.assertEqual(self.post(f'/admin/applications/{identifier}/approve').status_code,409)
        self.assertEqual(self.snapshot_counts(),before)
        with self.app.app_context():
            row = db.session.scalar(sa.select(Result).where(Result.application_id == identifier))
            self.assertEqual(row.start_number,1)
            entry = db.session.scalar(sa.select(AuditLog))
            self.assertEqual(entry.actor_id,self.ids['admin'])
            self.assertEqual(entry.new_values['result_id'],row.id)

    def test_one_consent_cannot_be_admitted(self):
        self.create()
        identifier=self.application_id()
        self.login('admin')
        before=self.snapshot_counts()
        self.assertEqual(self.post(f'/admin/applications/{identifier}/approve').status_code,409)
        self.assertEqual(self.snapshot_counts(),before)
        self.assertEqual(self.state(),'awaiting_jockey')

    def test_admission_after_deadline_before_start_allowed_but_after_start_denied(self):
        identifier=self.pending()
        with self.app.app_context():
            db.session.get(Competition,self.ids['future']).registration_deadline=utc_now()-timedelta(seconds=1)
            db.session.commit()
        self.approve(identifier)
        self.started()
        before=self.snapshot_counts()
        self.assertEqual(self.post(f'/admin/applications/{identifier}/approve').status_code,409)
        self.assertEqual(self.snapshot_counts(),before)

    def test_disabled_or_relinked_party_blocks_admission(self):
        identifier=self.pending()
        with self.app.app_context():
            db.session.get(User,self.ids['jockey']).status='disabled'
            db.session.commit()
        self.login('admin')
        self.assertEqual(self.post(f'/admin/applications/{identifier}/approve').status_code,409)
        self.assertEqual(self.rows(),[])
        with self.app.app_context():
            user=db.session.get(User,self.ids['jockey'])
            user.status='active'
            other=db.session.get(User,self.ids['other_jockey'])
            # Simulate an out-of-band historical profile reassignment.
            other.jockey_id=self.ids['legacy_jockey']
            db.session.flush()
            user.jockey_id=self.ids['other_jockey_profile']
            db.session.commit()
        self.assertEqual(self.post(f'/admin/applications/{identifier}/approve').status_code,409)
        self.assertEqual(self.rows(),[])

    def test_review_reject_reason_history_messages_and_filters(self):
        identifier=self.pending()
        self.login('admin')
        self.assertEqual(self.post(f'/admin/applications/{identifier}/reject').status_code,409)
        self.assertEqual(self.post(f'/admin/applications/{identifier}/reject',{'reason':'Несоответствие правилам допуска'}).status_code,302)
        self.assertEqual(self.state(),'rejected')
        before=self.snapshot_counts()
        self.assertEqual(self.post(f'/admin/applications/{identifier}/reject',{'reason':'Повторный отказ'}).status_code,409)
        self.assertEqual(self.snapshot_counts(),before)
        with self.app.app_context():
            entry=db.session.scalar(sa.select(AuditLog))
            self.assertEqual(entry.reason,'Несоответствие правилам допуска')
            self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(Result).where(Result.application_id==identifier)),0)
        self.assertIn('Лошадь owner',self.client.get('/admin/applications?status=rejected').text)
        self.assertNotIn('Лошадь owner',self.client.get('/admin/applications?status=pending_admin').text)
        self.assertNotIn('Лошадь owner',self.client.get('/admin/applications?competition_id=9999').text)
        self.login('owner')
        self.assertIn('Несоответствие правилам допуска',self.client.get('/cabinet/notifications').text)

    def test_capacity_distinct_start_numbers_and_start_list_notifications(self):
        first=self.pending()
        second=self.pending('other_owner','other_jockey')
        with self.app.app_context():
            db.session.get(Competition,self.ids['future']).max_participants=1
            db.session.commit()
        self.approve(first)
        before=self.snapshot_counts()
        self.assertEqual(self.post(f'/admin/applications/{second}/approve').status_code,409)
        self.assertEqual(self.snapshot_counts(),before)
        with self.app.app_context():
            db.session.get(Competition,self.ids['future']).max_participants=2
            db.session.commit()
        self.approve(second)
        with self.app.app_context():
            self.assertEqual(list(db.session.scalars(sa.select(Result.start_number).where(Result.competition_id==self.ids['future']).order_by(Result.start_number))),[1,2])
            entry=db.session.scalar(sa.select(AuditLog).order_by(AuditLog.id.desc()))
            self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(Notification).where(Notification.audit_id==entry.id)),2)

    def test_legacy_participant_conflict_rejected_and_preserved(self):
        identifier=self.pending()
        with self.app.app_context():
            db.session.add(Result(competition_id=self.ids['future'],horse_id=self.ids['owner_horse'],jockey_id=self.ids['other_jockey_profile']))
            db.session.commit()
        self.login('admin')
        self.assertEqual(self.post(f'/admin/applications/{identifier}/approve').status_code,409)
        with self.app.app_context():
            row=db.session.scalar(sa.select(Result).where(Result.competition_id==self.ids['future']))
            self.assertIsNone(row.application_id)
            self.assertIsNone(row.start_number)

    def test_root_cannot_forge_consents_and_explicit_cancel_has_true_actor(self):
        self.assertEqual(self.create('root',side='owner').status_code,403)
        self.create()
        identifier=self.application_id()
        self.login('root')
        for action in ('confirm','cancel','reject'):
            self.assertEqual(self.post(f'/cabinet/applications/{identifier}/{action}').status_code,403)
        self.assertEqual(self.post(f'/admin/applications/{identifier}/root-cancel').status_code,409)
        self.assertEqual(self.post(f'/admin/applications/{identifier}/root-cancel',{'reason':'Отмена ошибочного приглашения ROOT'}).status_code,302)
        with self.app.app_context():
            item=db.session.get(Application,identifier)
            self.assertIsNone(item.jockey_confirmed_at)
            entry=db.session.scalar(sa.select(AuditLog))
            self.assertEqual(entry.actor_id,self.ids['root'])
            self.assertEqual(entry.action,'root_application_cancelled')

    def test_legacy_root_forged_consent_cannot_be_admitted_or_silently_cancelled(self):
        identifier=self.pending()
        with self.app.app_context():
            item=db.session.get(Application,identifier)
            item.initiator_id=self.ids['root']
            events=db.session.scalars(sa.select(ApplicationEvent).where(ApplicationEvent.application_id==identifier)).all()
            for event in events:
                event.actor_id=self.ids['root']
            db.session.commit()
        self.login('root')
        for action in ('confirm','reject','cancel'):
            self.assertEqual(self.post(f'/cabinet/applications/{identifier}/{action}').status_code,403)
        self.assertIn('Согласие владельца: ожидается', self.client.get(f'/cabinet/applications/{identifier}').text)
        self.login('admin')
        self.assertEqual(self.post(f'/admin/applications/{identifier}/approve').status_code,409)
        self.assertEqual(self.rows(),[])

    def test_manual_exception_requires_root_reason_and_has_no_application_consent(self):
        path=f"/admin/competitions/{self.ids['future']}/manual"
        payload={'horse_id':self.ids['legacy_horse'],'jockey_id':self.ids['legacy_jockey'],'reason':'Доверенная регистрация исторической пары'}
        self.login('admin')
        self.assertEqual(self.post(path,payload).status_code,403)
        self.login('root')
        self.assertEqual(self.post(path,{**payload,'reason':''}).status_code,409)
        self.assertEqual(self.post(path,payload).status_code,302)
        self.assertEqual(self.post(path,payload).status_code,409)
        with self.app.app_context():
            row=db.session.scalar(sa.select(Result).where(Result.competition_id==self.ids['future']))
            self.assertIsNone(row.application_id)
            self.assertEqual(row.start_number,1)
            self.assertEqual(db.session.scalar(sa.select(AuditLog.action)),'participant_manually_added')
        self.assertIn('Исключение ROOT',self.app.test_client().get(f"/competitions/future/{self.ids['future']}").text)

    def test_manual_cannot_override_active_application_or_started_race(self):
        self.create()
        self.login('root')
        payload={'horse_id':self.ids['owner_horse'],'jockey_id':self.ids['jockey_profile'],'reason':'Проверка запрета обхода заявки'}
        path=f"/admin/competitions/{self.ids['future']}/manual"
        self.assertEqual(self.post(path,payload).status_code,409)
        self.started()
        self.assertEqual(self.post(path,{**payload,'horse_id':self.ids['legacy_horse']}).status_code,409)
        self.assertEqual(self.rows(),[])

    def test_protocol_full_validation_no_early_or_unapproved_results(self):
        self.pending()
        self.login('admin')
        self.started()
        self.assertEqual(self.post(f"/competitions/complete/{self.ids['future']}").status_code,400)
        # No result can be injected via a forged form ID.
        self.assertEqual(self.post(f"/competitions/complete/{self.ids['future']}",{'time_999':'120'}).status_code,400)
        with self.app.app_context():
            self.assertEqual(db.session.get(Competition,self.ids['future']).status,'planned')

    def test_protocol_rejects_future_missing_extra_nonfinite_and_ambiguous_outcomes(self):
        self.approve()
        row=self.rows()[0]
        path=f"/competitions/complete/{self.ids['future']}"
        self.assertEqual(self.post(path,{f'time_{row}':'120'}).status_code,400)
        self.started()
        for data in ({}, {f'time_{row}':'NaN'}, {f'time_{row}':'-1'}, {f'time_{row}':'120',f'disq_{row}':'on'},
                     {f'disq_{row}':'on',f'dnf_{row}':'on'}, {f'dnf_{row}':'on',f'time_{row}':'120'},
                     {f'time_{row}':'120','role':'ROOT'}, {f'time_{row}':'120','time_9999':'120'}):
            self.assertEqual(self.post(path,data).status_code,400)
        with self.app.app_context():
            result=db.session.get(Result,row)
            self.assertIsNone(result.finish_time_seconds)
            self.assertIsNone(result.place)
            self.assertEqual(result.competition.status,'planned')

    def test_publish_ties_dnf_disqualification_and_statistics(self):
        self.approve()
        self.approve(self.pending('other_owner','other_jockey'))
        with self.app.app_context():
            actor=db.session.get(User,self.ids['root'])
            service.manual_participant(actor,self.ids['future'],self.ids['legacy_horse'],self.ids['legacy_jockey'],'Проверка протокола исторического участника')
        rows=self.rows()
        self.started()
        self.login('admin')
        path=f"/competitions/complete/{self.ids['future']}"
        self.assertEqual(self.post(path,{f'time_{rows[0]}':'120',f'time_{rows[1]}':'120',f'dnf_{rows[2]}':'on'}).status_code,302)
        with self.app.app_context():
            results=db.session.scalars(sa.select(Result).where(Result.competition_id==self.ids['future']).order_by(Result.id)).all()
            self.assertEqual([r.place for r in results],[1,1,None])
            self.assertTrue(results[2].did_not_finish)
            entry=db.session.scalar(sa.select(AuditLog).where(AuditLog.action=='competition_completed'))
            self.assertEqual(entry.actor_id,self.ids['admin'])
            self.assertEqual(len(entry.new_values),3)
        guest=self.app.test_client()
        page=guest.get(f"/competitions/past/{self.ids['future']}")
        self.assertIn('Не финишировал (DNF)',page.text)
        for path in (f"/horses/{self.ids['owner_horse']}", f"/jockeys/{self.ids['jockey_profile']}"):
            self.assertIn('100.0%',guest.get(path).text)
        self.login('owner')
        self.assertIn('Соревнование завершено',self.client.get('/cabinet/notifications').text)
        self.assertIn('100.0%',self.client.get('/cabinet/').text)

    def test_disqualification_counts_performance_and_three_places(self):
        self.approve()
        self.approve(self.pending('other_owner','other_jockey'))
        self.started()
        self.login('admin')
        a,b=self.rows()
        self.assertEqual(self.post(f"/competitions/complete/{self.ids['future']}",{f'disq_{a}':'on',f'time_{b}':'120'}).status_code,302)
        with self.app.app_context():
            self.assertIsNone(db.session.get(Result,a).place)
            self.assertEqual(db.session.get(Result,b).place,1)
        guest=self.app.test_client()
        page=guest.get(f"/horses/{self.ids['owner_horse']}").text
        self.assertIn('Дисквалификация',page)
        self.assertIn('50.0%',page)  # One historical win, two completed starts.

    def test_places_tie_skips_next_place(self):
        with self.app.app_context():
            rows=[Result(id=index,competition_id=1,horse_id=1,jockey_id=1) for index in range(1,5)]
            prepared=service.prepare_protocol(rows,{1:{'time_str':'120'},2:{'time_str':'120'},3:{'time_str':'121'},4:{'did_not_finish':True}})
            self.assertEqual([values['place'] for _,values in prepared],[1,1,3,None])

    def test_repeat_completion_and_ordinary_edit_are_immutable(self):
        self.approve()
        self.started()
        row=self.rows()[0]
        path=f"/competitions/complete/{self.ids['future']}"
        self.assertEqual(self.post(path,{f'time_{row}':'120'}).status_code,302)
        before=self.snapshot_counts()
        # Existing URL redirects to the published immutable protocol.
        self.assertEqual(self.post(path,{f'time_{row}':'110'}).status_code,302)
        self.assertEqual(self.snapshot_counts(),before)
        with self.app.app_context():
            with self.assertRaises(ValueError):
                service.publish_protocol(db.session.get(User,self.ids['admin']),self.ids['future'],{row:{'time_str':'110'}})
            self.assertEqual(db.session.get(Result,row).finish_time_seconds,120)

    def test_root_correction_keeps_old_protocol_recomputes_and_rejects_stale_form(self):
        self.approve()
        self.approve(self.pending('other_owner','other_jockey'))
        self.started()
        a,b=self.rows()
        self.assertEqual(self.post(f"/competitions/complete/{self.ids['future']}",{f'time_{a}':'120',f'time_{b}':'121'}).status_code,302)
        path=f"/admin/competitions/{self.ids['future']}/correct"
        self.assertEqual(self.client.get(path).status_code,403)
        self.login('root')
        self.assertEqual(self.client.get(path).status_code,200)
        with self.app.app_context():
            revision=db.session.get(Competition,self.ids['future']).revision
        payload={f'time_{a}':'122',f'time_{b}':'121','revision':revision,'reason':'Исправление ошибки хронометража'}
        self.assertEqual(self.post(path,{**payload,'reason':''}).status_code,409)
        self.assertEqual(self.post(path,payload).status_code,302)
        before=self.snapshot_counts()
        self.assertEqual(self.post(path,payload).status_code,409)
        self.assertEqual(self.snapshot_counts(),before)
        with self.app.app_context():
            entry=db.session.scalar(sa.select(AuditLog).where(AuditLog.action=='protocol_corrected'))
            self.assertEqual(entry.old_values[str(a)]['place'],1)
            self.assertEqual(entry.new_values[str(a)]['place'],2)
            self.assertEqual(entry.actor_id,self.ids['root'])
            self.assertEqual(db.session.get(Result,a).finish_time_seconds,122)
            self.assertEqual(db.session.get(Result,b).place,1)

    def test_user_block_restore_revokes_sessions_unique_messages(self):
        self.login('owner')
        owner_client=self.client
        self.login('root')
        path=f"/root/users/{self.ids['owner']}"
        payload={'role':'OWNER','status':'disabled','reason':'Тестовое отключение аккаунта'}
        self.assertEqual(self.post(path,payload).status_code,302)
        self.assertEqual(owner_client.get('/cabinet/').status_code,302)
        before=self.snapshot_counts()
        self.assertEqual(self.post(path,payload).status_code,400)
        self.assertEqual(self.snapshot_counts(),before)
        self.assertEqual(self.post(path,{**payload,'status':'active','reason':'Восстановление тестового аккаунта'}).status_code,302)
        with self.app.app_context():
            self.assertEqual(db.session.get(User,self.ids['owner']).status,'active')
            self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(Notification).where(Notification.user_id==self.ids['owner'])),2)

    def test_role_changes_root_protection_profile_integrity_and_search(self):
        self.login('root')
        path=f"/root/users/{self.ids['viewer']}"
        payload={'role':'ADMIN','status':'active','reason':'Назначение администратора клуба'}
        self.assertEqual(self.post(path,payload).status_code,302)
        self.assertEqual(self.post(path,{**payload,'role':'ROOT'}).status_code,400)
        self.assertEqual(self.post(f"/root/users/{self.ids['root']}",{**payload,'status':'disabled'}).status_code,400)
        self.assertEqual(self.post(f"/root/users/{self.ids['owner']}",payload).status_code,400)
        self.assertEqual(self.post(path,{**payload,'role':'OWNER'}).status_code,400)
        page=self.client.get('/root/users?email=viewer&role=ADMIN&status=active').text
        self.assertIn('viewer@example.test',page)
        self.assertNotIn('owner@example.test',page)
        self.assertNotIn('viewer@example.test',self.client.get('/root/users?status=disabled').text)

    def test_trusted_profile_link_retains_history_and_rejects_claims(self):
        path=f"/root/users/{self.ids['viewer']}/link"
        with self.app.app_context():
            owner_id=db.session.get(Horse,self.ids['legacy_horse']).owner_id
        payload={'side':'owner','profile_id':owner_id,'reason':'Внешняя проверка принадлежности выполнена','verified':'yes'}
        self.login('viewer')
        self.assertEqual(self.post(path,payload).status_code,403)
        self.login('root')
        self.assertEqual(self.post(path,{**payload,'verified':'no'}).status_code,400)
        self.assertEqual(self.post(path,{**payload,'profile_id':self.ids['owner_profile']}).status_code,400)
        self.assertEqual(self.post(path,payload).status_code,302)
        with self.app.app_context():
            viewer=db.session.get(User,self.ids['viewer'])
            self.assertEqual((viewer.role,viewer.owner_id),('OWNER',owner_id))
            self.assertEqual(db.session.get(Horse,self.ids['legacy_horse']).owner_id,owner_id)
            entry=db.session.scalar(sa.select(AuditLog))
            self.assertEqual(entry.old_values['role'],'VIEWER')
            self.assertEqual(entry.actor_id,self.ids['root'])
        self.assertEqual(self.post(path,payload).status_code,400)

    def test_jockey_legacy_link_and_no_existing_account_reassignment(self):
        self.login('root')
        data={'side':'jockey','profile_id':self.ids['legacy_jockey'],'reason':'Личность жокея проверена вне системы','verified':'yes'}
        self.assertEqual(self.post(f"/root/users/{self.ids['owner']}/link",data).status_code,400)
        self.assertEqual(self.post(f"/root/users/{self.ids['viewer']}/link",data).status_code,302)
        with self.app.app_context():
            user=db.session.get(User,self.ids['viewer'])
            self.assertEqual(user.jockey_id,self.ids['legacy_jockey'])
            self.assertEqual(user.role,'JOCKEY')

    def test_audit_visibility_append_only_and_no_credential_fields(self):
        self.approve()
        self.login('root')
        self.post('/admin/competitions/new',self.new_data(title='Секретное действие ROOT'))
        root_page=self.client.get('/admin/audit').text
        self.assertIn('competition_created',root_page)
        self.assertIn('application_approved',root_page)
        self.login('admin')
        page=self.client.get('/admin/audit').text
        self.assertNotIn('Секретное действие ROOT',page)
        self.assertIn('application_approved',page)
        self.login('owner')
        self.assertEqual(self.client.get('/admin/audit').status_code,403)
        with self.app.app_context():
            entries=db.session.scalars(sa.select(AuditLog)).all()
            self.assertTrue(all('password' not in str(e.new_values) and 'token' not in str(e.new_values) for e in entries))
            identifier=entries[0].id
            for statement in (sa.update(AuditLog).where(AuditLog.id==identifier).values(action='forged'),sa.delete(AuditLog).where(AuditLog.id==identifier)):
                with self.assertRaises(sa.exc.DBAPIError):
                    db.session.execute(statement)
                    db.session.commit()
                db.session.rollback()
            self.assertEqual(db.session.get(AuditLog,identifier).action,'application_approved')

    def test_all_admin_mutations_require_csrf_and_reject_role_injection(self):
        identifier=self.pending()
        self.login('root')
        paths=['/admin/competitions/new',f"/admin/competitions/{self.ids['future']}/edit",
               f'/admin/applications/{identifier}/approve',f'/admin/applications/{identifier}/reject',
               f'/admin/applications/{identifier}/root-cancel',f"/admin/competitions/{self.ids['future']}/manual",
               f"/admin/competitions/{self.ids['past']}/correct",f"/competitions/complete/{self.ids['future']}",
               f"/root/users/{self.ids['owner']}",f"/root/users/{self.ids['viewer']}/link"]
        foreign=self.token(self.app.test_client())
        for path in paths:
            for data in ({},{'csrf_token':'forged'},{'csrf_token':foreign}):
                self.assertEqual(self.client.post(path,data=data).status_code,400,path)
        self.assertEqual(self.post(f'/admin/applications/{identifier}/approve',{'role':'ROOT'}).status_code,400)
        self.assertEqual(self.state(),'pending_admin')

    def test_database_constraints_start_numbers_application_unique_checks(self):
        self.approve()
        identifier=self.rows()[0]
        with self.app.app_context():
            for changes in ({'start_number':0},{'did_not_finish':True,'is_disqualified':True},{'application_id':999999}):
                with self.assertRaises(IntegrityError):
                    db.session.execute(sa.update(Result).where(Result.id==identifier).values(**changes))
                    db.session.commit()
                db.session.rollback()
            row=db.session.get(Result,identifier)
            for changes in ({'horse_id':self.ids['other_owner_horse'],'jockey_id':self.ids['other_jockey_profile']},):
                with self.assertRaises(IntegrityError):
                    db.session.add(Result(competition_id=row.competition_id,application_id=row.application_id,start_number=row.start_number,**changes))
                    db.session.commit()
                db.session.rollback()
            for changes in ({'distance':0},{'max_participants':0}):
                with self.assertRaises(IntegrityError):
                    db.session.execute(sa.update(Competition).where(Competition.id==self.ids['future']).values(**changes))
                    db.session.commit()
                db.session.rollback()

    def test_notification_failure_rolls_back_admission_and_publication(self):
        identifier=self.pending()
        self.login('admin')
        failure=OperationalError('private',{},Exception('simulated'),hide_parameters=True)
        before=self.snapshot_counts()
        with patch('app.application_services.notify',side_effect=failure):
            self.assertEqual(self.post(f'/admin/applications/{identifier}/approve').status_code,409)
        self.assertEqual(self.snapshot_counts(),before)
        self.assertEqual(self.state(),'pending_admin')
        self.approve(identifier)
        self.started()
        row=self.rows()[0]
        before=self.snapshot_counts()
        with patch('app.admin_services.message',side_effect=failure):
            self.assertEqual(self.post(f"/competitions/complete/{self.ids['future']}",{f'time_{row}':'120'}).status_code,400)
        self.assertEqual(self.snapshot_counts(),before)
        with self.app.app_context():
            self.assertEqual(db.session.get(Competition,self.ids['future']).status,'planned')
            self.assertIsNone(db.session.get(Result,row).place)

    def test_concurrent_admission_across_two_admins_two_apps_only_one_commit(self):
        identifier=self.pending()
        with self.app.app_context():
            admin2=User(email='second@example.test',role='ADMIN',status='active',password_hash='unusable')
            db.session.add(admin2)
            db.session.commit()
            second_id=admin2.id
        other=create_app({'TESTING':True,'SQLALCHEMY_DATABASE_URI':self.app.config['SQLALCHEMY_DATABASE_URI']})
        apps=[self.app,other]
        barrier = Barrier(4)
        def approve(index):
            with apps[index%2].app_context():
                barrier.wait(timeout=15)
                try:
                    service.decide_admission(db.session.get(User,[self.ids['admin'],second_id][index%2]),identifier,'approve')
                    return 'approved'
                except ValueError:
                    return 'conflict'
        try:
            with ThreadPoolExecutor(max_workers=4) as pool:
                outcomes=list(pool.map(approve,range(4)))
            self.assertEqual(outcomes.count('approved'),1)
            self.assertEqual(outcomes.count('conflict'),3)
            with self.app.app_context():
                self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(Result).where(Result.application_id==identifier)),1)
                self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(AuditLog)),1)
                self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(Notification)),5)
        finally:
            with other.app_context():
                db.session.remove()
                db.engine.dispose()

    def test_concurrent_last_capacity_slot_only_one_pair_admitted(self):
        first=self.pending()
        second=self.pending('other_owner','other_jockey')
        with self.app.app_context():
            db.session.get(Competition,self.ids['future']).max_participants=1
            db.session.commit()
        def approve(identifier):
            with self.app.app_context():
                try:
                    service.decide_admission(db.session.get(User,self.ids['admin']),identifier,'approve')
                    return 'approved'
                except ValueError:
                    return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes=list(pool.map(approve,[first,second]))
        self.assertEqual(sorted(outcomes),['approved','conflict'])
        self.assertEqual(len(self.rows()),1)

    def test_concurrent_publication_only_one_protocol_and_notifications(self):
        self.approve()
        self.started()
        row=self.rows()[0]
        with self.app.app_context():
            other = User(email='publisher@example.test', role='ADMIN', status='active', password_hash='unusable')
            db.session.add(other)
            db.session.commit()
            publisher_id = other.id
        barrier = Barrier(4)
        def publish(index):
            with self.app.app_context():
                barrier.wait(timeout=15)
                try:
                    service.publish_protocol(db.session.get(User,[self.ids['admin'],publisher_id][index%2]),self.ids['future'],{row:{'time_str':'120'}})
                    return 'published'
                except ValueError:
                    return 'conflict'
        before=self.snapshot_counts()
        with ThreadPoolExecutor(max_workers=4) as pool:
            outcomes=list(pool.map(publish,range(4)))
        self.assertEqual(outcomes.count('published'),1)
        self.assertEqual(outcomes.count('conflict'),3)
        after=self.snapshot_counts()
        self.assertEqual(after[3]-before[3],1)
        self.assertEqual(after[4]-before[4],2)

    def test_disabled_admin_stale_service_actor_cannot_mutate(self):
        identifier = self.pending()
        self.login('admin')
        with self.app.app_context():
            actor = db.session.get(User, self.ids['admin'])
            db.session.execute(sa.update(User).where(User.id == actor.id).values(status='disabled')
                               .execution_options(synchronize_session=False))
            db.session.commit()
            with self.assertRaises(PermissionError):
                service.decide_admission(actor, identifier, 'approve')
        self.assertEqual(self.client.get('/admin/').status_code, 302)
        self.assertEqual(self.rows(), [])

    def test_manual_and_admission_cannot_race_for_conflicting_horse(self):
        identifier = self.pending()
        barrier = Barrier(2)
        def race(operation):
            with self.app.app_context():
                barrier.wait(timeout=15)
                try:
                    if operation == 'admit':
                        service.decide_admission(db.session.get(User, self.ids['admin']), identifier, 'approve')
                    else:
                        service.manual_participant(db.session.get(User, self.ids['root']), self.ids['future'],
                            self.ids['owner_horse'], self.ids['other_jockey_profile'], 'Попытка конфликтующего ручного допуска')
                    return operation
                except ValueError:
                    return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(race, ['admit', 'manual']))
        # SQLite may reject the admission's stale revision; neither path may ever
        # install the conflicting manual pair while an application is active.
        self.assertNotIn('manual', outcomes)
        self.assertLessEqual(len(self.rows()), 1)
        if self.rows():
            with self.app.app_context():
                row = db.session.get(Result, self.rows()[0])
                self.assertEqual(row.application_id, identifier)

    def test_reasons_with_secrets_and_repeated_correction_are_rejected(self):
        self.login('root')
        for reason in ('postgresql://private/secret', 'password=private', 'token: private', ''):
            self.assertEqual(self.post(f"/root/users/{self.ids['viewer']}",
                {'role':'ADMIN','status':'active','reason':reason}).status_code,400)
        self.approve()
        self.started()
        row = self.rows()[0]
        self.post(f"/competitions/complete/{self.ids['future']}",{f'time_{row}':'120'})
        self.login('root')
        with self.app.app_context():
            revision = db.session.get(Competition, self.ids['future']).revision
        before = self.snapshot_counts()
        self.assertEqual(self.post(f"/admin/competitions/{self.ids['future']}/correct",
            {f'time_{row}':'120','revision':revision,'reason':'Протокол уже содержит верные данные'}).status_code,409)
        self.assertEqual(self.snapshot_counts(), before)

    def test_manual_exception_cannot_bypass_disabled_profile(self):
        self.login('root')
        with self.app.app_context():
            db.session.get(User, self.ids['owner']).status = 'disabled'
            db.session.commit()
        self.assertEqual(self.post(f"/admin/competitions/{self.ids['future']}/manual",
            {'horse_id': self.ids['owner_horse'], 'jockey_id': self.ids['jockey_profile'],
             'reason':'Попытка обойти заблокированный профиль'}).status_code,409)
        self.assertEqual(self.rows(), [])

    def test_concurrent_account_disable_has_one_audit_and_notification(self):
        barrier = Barrier(4)
        def disable(_):
            with self.app.app_context():
                barrier.wait(timeout=15)
                try:
                    service.update_user(db.session.get(User,self.ids['root']), self.ids['viewer'],
                        role='VIEWER', status='disabled', reason='Одновременная блокировка тестового аккаунта')
                    return 'disabled'
                except ValueError:
                    return 'conflict'
        with ThreadPoolExecutor(max_workers=4) as pool:
            outcomes = list(pool.map(disable, range(4)))
        self.assertEqual(outcomes.count('disabled'), 1)
        with self.app.app_context():
            self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(AuditLog)),1)
            self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(Notification)),1)

    def test_manual_invalid_identifiers_no_partial_admission_or_audit(self):
        self.login('root')
        path = f"/admin/competitions/{self.ids['future']}/manual"
        base = {'horse_id':self.ids['legacy_horse'], 'jockey_id':self.ids['legacy_jockey'],
                'reason':'Проверка недопустимых идентификаторов'}
        before = self.snapshot_counts()
        for field in ('horse_id','jockey_id'):
            for value in ('', '0', '-1', 'NaN', '9'*100, '999999'):
                self.assertEqual(self.post(path,{**base,field:value}).status_code,409)
                self.assertEqual(self.snapshot_counts(),before)

    def test_retired_service_paths_cannot_create_participants_or_protocol(self):
        from app.services import create_future_competition, create_completed_competition_direct
        with self.app.app_context():
            before = db.session.scalar(sa.select(sa.func.count()).select_from(Competition))
            with self.assertRaises(ValueError):
                create_future_competition('Обход',date.today()+timedelta(days=10),
                    time(12),'Москва',
                    [{'horse_id':self.ids['owner_horse'],'jockey_id':self.ids['jockey_profile']}])
            with self.assertRaises(ValueError):
                create_completed_competition_direct('Обход',date.today(),time(12),'Москва',[])
            self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(Competition)),before)


if __name__=='__main__':
    unittest.main()
