"""Additional Lab 7 regression checks for stale browser form submissions."""
from app import db
from app.models import Prediction
from tests.test_alpha4 import Alpha4Fixture


class PredictionRevisionRegression(Alpha4Fixture):
    def test_stale_edit_does_not_replace_current_prediction(self):
        self.login('viewer')
        self.assertEqual(self.predict().status_code, 302)
        self.assertEqual(self.predict(revision=1, horses=[self.horses[1]]).status_code, 302)

        response = self.predict(revision=1, horses=[self.horses[2]])
        self.assertEqual(response.status_code, 409)
        with self.app.app_context():
            prediction = db.session.query(Prediction).filter_by(
                user_id=self.ids['viewer'], competition_id=self.ids['future'], mode='winner'
            ).one()
            self.assertEqual(prediction.revision, 2)
            self.assertEqual([choice.horse_id for choice in prediction.choices], [self.horses[1]])
