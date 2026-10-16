"""Selected Alpha 4 scenarios; every fixture migrates an isolated database with CSRF on."""
import unittest
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from app import db
from app.models import Competition, Horse, Jockey, Result, User, Prediction, PredictionChoice, utc_now
from app.admin_services import publish_protocol
from app.prediction_services import save_prediction, prediction_query, accuracy_summary, start_at
from tests import test_alpha2 as alpha2, test_migrations as migrations


class Alpha4Fixture(unittest.TestCase):
    setUpBase = alpha2.Alpha2Tests.setUp
    tearDown = alpha2.Alpha2Tests.tearDown
    token = alpha2.Alpha2Tests.token
    logged = alpha2.Alpha2Tests.logged
    login = alpha2.Alpha2Tests.login
    post = alpha2.Alpha2Tests.post

    def setUp(self):
        self.setUpBase()
        with self.app.app_context():
            comp = db.session.get(Competition, self.ids['future'])
            comp.distance = 1600
            horses = [self.ids['owner_horse'], self.ids['other_owner_horse'], self.ids['legacy_horse']]
            jockeys = [self.ids['jockey_profile'], self.ids['other_jockey_profile'], self.ids['legacy_jockey']]
            for h, j in zip(horses, jockeys):
                db.session.add(Result(competition_id=comp.id, horse_id=h, jockey_id=j))
            horse = Horse(nickname='Четвёртый', gender='Мерин', age=5, owner_id=self.ids['owner_profile'])
            jockey = Jockey(full_name='Четвёртый жокей', age=29, rating=0)
            db.session.add_all([horse, jockey]);db.session.flush()
            db.session.add(Result(competition_id=comp.id, horse_id=horse.id, jockey_id=jockey.id))
            db.session.commit()
            self.horses = horses + [horse.id]
        self.url = f"/predictions/{self.ids['future']}"

    def predict(self, mode='winner', revision=0, horses=None, **extra):
        selected = horses if horses is not None else self.horses[:1 if mode == 'winner' else 3]
        return self.post(self.url, {'mode':mode,'revision':revision,
            **{f'horse_{index}':identifier for index,identifier in enumerate(selected,1)}, **extra})

    def mine(self, user='viewer'):
        return db.session.scalars(prediction_query().where(Prediction.user_id == self.ids[user])).all()

    def publish(self, times=('100','101','102','103'), correction=False):
        comp = db.session.get(Competition, self.ids['future'])
        if not correction:
            comp.event_date = date.today()-timedelta(days=1);db.session.commit()
        rows = db.session.scalars(sa.select(Result).where(Result.competition_id == comp.id).order_by(Result.id)).all()
        data = {r.id: ({'did_not_finish':True} if value == 'DNF' else {'is_disqualified':True} if value == 'DSQ'
                      else {'time_str':value}) for r,value in zip(rows,times)}
        return publish_protocol(db.session.get(User,self.ids['root' if correction else 'admin']),comp.id,data,
            **({'correction_reason':'Исправление фотофиниша', 'expected_revision':comp.revision} if correction else {}))



class Alpha4Tests(Alpha4Fixture):
    def test_public_analytics_and_period(self):
        for path in ('/','/horses/','/jockeys/','/owners/','/competitions/future','/competitions/past',
                     '/competitions/future?view=calendar','/rankings','/statistics','/predictions/',self.url,'/health'):
            self.assertEqual(self.client.get(path).status_code,200,path)
        self.assertIn('Распределение и число ответов скрыты',self.client.get(self.url).text)
        from app.analytics import rankings, distance_averages
        with self.app.app_context():
            rows = db.session.execute(rankings()).all()
            self.assertEqual([(r[1],r[2]) for r in rows],[(1,1)])  # planned rows excluded
            self.assertEqual(distance_averages(),[])
        self.assertEqual(self.client.get('/rankings?from=bad').status_code,400)
        self.assertEqual(self.client.get('/rankings?from=2026-12-01&to=2026-01-01').status_code,400)
        self.assertIn('завершённых выступлений нет',self.client.get('/rankings?from=2090-01-01').text)

    def test_winner_save_edit_and_repeat(self):
        self.login('viewer')
        self.assertEqual(self.predict().status_code,302)
        self.assertEqual(self.predict().status_code,409)
        self.assertEqual(self.predict(revision=1,horses=[self.horses[1]]).status_code,302)
        with self.app.app_context():
            rows = self.mine();self.assertEqual(len(rows),1)
            self.assertEqual((rows[0].revision,rows[0].choices[0].horse_id),(2,self.horses[1]))
        self.assertEqual(self.client.delete(self.url).status_code,405)

    def test_trio_validation_and_independent_modes(self):
        self.login('viewer')
        self.assertEqual(self.predict('trio',horses=[self.horses[0]]*3).status_code,409)
        self.assertEqual(self.predict('trio',horses=[*self.horses[:2],2147483647]).status_code,409)
        self.assertEqual(self.predict('trio',horses=self.horses[:2]).status_code,409)
        self.assertEqual(self.predict('trio').status_code,302)
        self.assertEqual(self.predict().status_code,302)
        with self.app.app_context():
            self.assertEqual(len(self.mine()),2)
        self.assertEqual(self.predict('trio',1,list(reversed(self.horses[:3]))).status_code,302)

    def test_security_csrf_roles_and_forged_user(self):
        self.assertEqual(self.predict().status_code,302)  # login redirect
        for name in ('viewer','owner','jockey','admin','root'):
            self.login(name)
            self.assertEqual(self.client.post(self.url,data={'mode':'winner'}).status_code,400)
            self.assertEqual(self.predict(user_id=self.ids['other_owner']).status_code,400)
            self.assertEqual(self.predict().status_code,302)
        self.login('viewer')
        with self.app.app_context():
            db.session.get(User,self.ids['viewer']).status='disabled';db.session.commit()
        self.assertEqual(self.client.get('/predictions/history').status_code,302)
        self.assertEqual(self.predict(revision=1).status_code,302)
        with self.app.app_context():
            self.assertEqual(self.mine()[0].revision,1)

    def test_deadline_exact_and_completed_immutable(self):
        self.login('viewer');self.assertEqual(self.predict().status_code,302)
        with self.app.app_context():
            instant = start_at(db.session.get(Competition,self.ids['future']))
        with patch('app.prediction_services.utc_now',return_value=instant):
            self.assertEqual(self.predict(revision=1,horses=[self.horses[1]]).status_code,409)
        with self.app.app_context():self.publish()
        self.assertEqual(self.predict('trio').status_code,409)
        with self.app.app_context():self.assertEqual(self.mine()[0].choices[0].horse_id,self.horses[0])

    def test_assessment_and_gets_do_not_write(self):
        self.login('viewer');self.predict();self.predict('trio')
        with self.app.app_context():
            self.publish()
            predictions=self.mine();summary=accuracy_summary(predictions)
            self.assertEqual((summary['winner_rate'],summary['trio_rate'],summary['slot_rate']),(100,100,100))
            before=[(p.updated_at,p.evaluated_at,p.protocol_revision) for p in predictions]
        for path in (self.url,'/predictions/history',self.url):self.assertEqual(self.client.get(path).status_code,200)
        with self.app.app_context():self.assertEqual([(p.updated_at,p.evaluated_at,p.protocol_revision) for p in self.mine()],before)
        self.assertIn('точных: 1',self.client.get(self.url).text)

    def test_ties_dnf_dsq_and_indeterminate(self):
        self.login('viewer');self.predict(horses=[self.horses[1]]);self.predict('trio')
        with self.app.app_context():
            self.publish(('100','100','DNF','DSQ'))
            predictions={p.mode:p for p in self.mine()}
            self.assertTrue(predictions['winner'].winner_correct)
            trio=predictions['trio'];self.assertIsNone(trio.exact_trio)
            self.assertEqual([c.position_correct for c in trio.choices],[None,None,None])
            self.assertEqual(trio.podium_hits,2)
            self.assertIsNone(accuracy_summary(list(predictions.values()))['trio_rate'])
            self.publish(('DNF','DSQ','DNF','DSQ'),correction=True)
            self.assertIsNone(self.mine()[0].winner_correct)

    def test_correction_reassesses_without_changing_choices(self):
        self.login('viewer');self.predict();self.predict('trio')
        with self.app.app_context():
            self.publish();before=[(p.id,p.revision,[(c.position,c.horse_id) for c in p.choices]) for p in self.mine()]
            self.publish(('101','100','102','103'),correction=True)
            rows=self.mine();self.assertEqual([(p.id,p.revision,[(c.position,c.horse_id) for c in p.choices]) for p in rows],before)
            self.assertFalse(rows[0].winner_correct)
            self.assertFalse(rows[1].exact_trio)
            self.assertEqual([c.position_correct for c in rows[1].choices],[False,False,True])

    def test_withdrawn_selection_and_small_field(self):
        self.login('viewer');self.predict();self.predict('trio')
        with self.app.app_context():
            # Controlled fixture mutation simulates a changed official list.
            db.session.execute(sa.delete(Result).where(Result.competition_id==self.ids['future'],Result.horse_id==self.horses[0]));db.session.commit()
        self.assertIn('выбранный участник выбыл',self.client.get(self.url).text)
        self.assertEqual(self.predict(revision=1,horses=[self.horses[1]]).status_code,302)
        with self.app.app_context():
            self.publish(('100','101','102'))
            self.assertEqual({p.mode:p.outcome for p in self.mine()},{'winner':'evaluated','trio':'void'})
        self.assertIn('не будет оцениваться',self.client.get(self.url).text)

    def test_no_n_plus_one_rankings_and_hidden_community(self):
        self.login('viewer');self.predict()
        guest=self.app.test_client()
        self.assertNotIn('точных:',guest.get(self.url).text)
        self.assertIn('Распределение и число ответов скрыты',guest.get(self.url).text)
        with self.app.app_context():
            calls=[]
            def count(*args):calls.append(1)
            sa.event.listen(db.engine,'before_cursor_execute',count)
            try:
                self.assertEqual(guest.get('/rankings').status_code,200)
                self.assertLessEqual(len(calls),6)
            finally:sa.event.remove(db.engine,'before_cursor_execute',count)


class Alpha4DatabaseTests(Alpha4Fixture):
    # Only explicitly selected methods below are run on PostgreSQL.
    def test_prediction_constraints(self):
        self.login('viewer');self.predict('trio');self.predict()
        with self.app.app_context():
            prediction=self.mine()[0]
            trials=[PredictionChoice(prediction_id=prediction.id,horse_id=self.horses[0],position=3),
                    PredictionChoice(prediction_id=prediction.id,horse_id=self.horses[3],position=1),
                    PredictionChoice(prediction_id=prediction.id,horse_id=self.horses[3],position=4),
                    PredictionChoice(prediction_id=prediction.id,horse_id=2147483647,position=3),
                    Prediction(user_id=self.ids['viewer'],competition_id=self.ids['future'],mode=prediction.mode),
                    Prediction(user_id=2147483647,competition_id=self.ids['future'],mode='winner')]
            for row in trials:
                with self.assertRaises(IntegrityError):
                    db.session.add(row);db.session.commit()
                db.session.rollback()

    def test_concurrent_create_one_prediction(self):
        barrier=Barrier(2)
        def create():
            with self.app.app_context():
                actor=db.session.get(User,self.ids['viewer']);barrier.wait(timeout=10)
                try:
                    save_prediction(actor,self.ids['future'],'winner',[self.horses[0]],0)
                    return True
                except ValueError:return False
                finally:db.session.remove()
        with ThreadPoolExecutor(max_workers=2) as pool:outcomes=list(pool.map(lambda _:create(),range(2)))
        self.assertEqual(sorted(outcomes),[False,True])
        with self.app.app_context():self.assertEqual(len(self.mine()),1)


class Alpha4MigrationTests(unittest.TestCase):
    setUp = migrations.MigrationTests.setUp
    tearDown = migrations.MigrationTests.tearDown
    cli = migrations.MigrationTests.cli

    def test_populated_alpha3_upgrade(self):
        self.cli('db','upgrade','0004_administration')
        # Freeze Alpha 3 schema and store all columns of every existing table.
        with db.engine.begin() as conn:
            conn.execute(sa.text("INSERT INTO owners(id,full_name) VALUES (1,'Исторический владелец')"))
            conn.execute(sa.text("INSERT INTO horses(id,nickname,gender,age,owner_id) VALUES (1,'Сохранённая','Кобыла',5,1)"))
            conn.execute(sa.text("INSERT INTO jockeys(id,full_name,age,rating) VALUES (1,'Исторический жокей',25,0)"))
            conn.execute(sa.text("INSERT INTO competitions(id,title,event_date,event_time,location,status,revision) VALUES (1,'Архив','2025-01-01','12:00:00','Москва','completed',2)"))
            conn.execute(sa.text("INSERT INTO results(id,competition_id,horse_id,jockey_id,place,finish_time_seconds,is_disqualified,did_not_finish) VALUES (1,1,1,1,1,102.5,false,false)"))
        names=[n for n in sa.inspect(db.engine).get_table_names() if n!='alembic_version']
        def snapshot():
            with db.engine.connect() as conn:return {n:list(conn.exec_driver_sql(f'SELECT * FROM {n}')) for n in names}
        before=snapshot();self.cli('db','upgrade');self.assertEqual(snapshot(),before)
        self.cli('db','upgrade');self.cli('db','check')
        self.assertEqual(db.session.scalar(sa.text('SELECT version_num FROM alembic_version')),'0005_predictions')
