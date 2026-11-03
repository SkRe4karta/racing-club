"""Free predictions: locked writes and deterministic assessment within publication.

No GET writes assessments. A tie makes occupied ordinal slots indeterminate;
any official place <= 3 is a named medallist. Exact trio needs unique 1/2/3.
"""
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app import db
from app.models import Prediction, PredictionChoice, Result, User, utc_now
from app.admin_services import lock_competition, start_at, transaction
from app.permissions import can
from app.services import participant_id


def predictions_open(comp):
    return comp.status == 'planned' and utc_now() < start_at(comp)


def prediction_query():
    return select(Prediction).options(selectinload(Prediction.competition),
        selectinload(Prediction.choices).selectinload(PredictionChoice.horse))


@transaction
def save_prediction(actor, competition_id, mode, horse_ids, expected_revision):
    """Never accepts user/status from HTTP; uses race lock shared with admission."""
    actor = db.session.scalar(select(User).where(User.id == actor.id).with_for_update()
                              .execution_options(populate_existing=True)) if actor else None
    if actor is None or not can('predict', user=actor):
        raise PermissionError('Войдите в активный аккаунт для создания прогноза.')
    if mode not in ('winner', 'trio'):
        raise ValueError('Неизвестный режим прогноза.')
    comp = lock_competition(competition_id)
    if not predictions_open(comp):
        raise ValueError('Приём прогнозов закрыт. Выбор сохранён без изменений.')
    identifiers = [participant_id(value) for value in horse_ids]
    required = 1 if mode == 'winner' else 3
    if len(identifiers) != required or len(set(identifiers)) != required:
        raise ValueError('Выберите одну лошадь или три разные лошади по порядку.')
    official = set(db.session.scalars(select(Result.horse_id).where(Result.competition_id == comp.id)))
    if not set(identifiers) <= official:
        raise ValueError('Выбирайте только лошадей из текущего официального стартового списка.')
    prediction = db.session.scalar(prediction_query().where(Prediction.user_id == actor.id,
        Prediction.competition_id == comp.id, Prediction.mode == mode))
    try:
        revision = int(expected_revision)
    except (ValueError, TypeError):
        raise ValueError('Обновите форму прогноза.') from None
    if revision != (prediction.revision if prediction else 0):
        raise ValueError('Прогноз уже изменён. Обновите страницу перед повторной отправкой.')
    if prediction:
        prediction.choices.clear()
        db.session.flush()  # release unique positions before inserting replacements
        prediction.revision += 1
        prediction.updated_at = utc_now()
    else:
        prediction = Prediction(user_id=actor.id, competition_id=comp.id, mode=mode)
        db.session.add(prediction)
    prediction.choices = [PredictionChoice(horse_id=identifier, position=index)
                          for index, identifier in enumerate(identifiers, 1)]
    db.session.commit()
    return prediction


def assess_predictions(comp, rows):
    """Called only by publication/correction, in the same transaction and race lock."""
    db.session.flush()
    predictions = db.session.scalars(prediction_query().where(Prediction.competition_id == comp.id)).all()
    official = {row.horse_id: row for row in rows}
    groups = {}
    for row in rows:
        if row.place and not row.is_disqualified and not row.did_not_finish:
            groups.setdefault(row.place, []).append(row.horse_id)
    podium = {horse for place, horses in groups.items() if place <= 3 for horse in horses}
    unique_trio = all(len(groups.get(slot, [])) == 1 for slot in (1, 2, 3))
    ambiguous = {slot for place, horses in groups.items() if len(horses) > 1
                 for slot in range(place, place + len(horses))}
    for prediction in predictions:
        prediction.protocol_revision = comp.revision
        prediction.evaluated_at = utc_now()
        prediction.winner_correct = prediction.exact_trio = prediction.podium_hits = None
        for choice in prediction.choices:
            choice.position_correct = None
        if any(choice.horse_id not in official for choice in prediction.choices):
            prediction.outcome = 'void'
            continue
        prediction.outcome = 'evaluated'
        if prediction.mode == 'winner':
            prediction.winner_correct = (prediction.choices[0].horse_id in groups[1]) if groups.get(1) else None
            prediction.choices[0].position_correct = prediction.winner_correct
        else:
            prediction.podium_hits = sum(choice.horse_id in podium for choice in prediction.choices)
            for choice in prediction.choices:
                if choice.position not in ambiguous and groups.get(choice.position):
                    choice.position_correct = choice.horse_id in groups[choice.position]
            prediction.exact_trio = all(c.position_correct for c in prediction.choices) if unique_trio else None


def accuracy_summary(predictions):
    """Indeterminate and void outcomes never count as incorrect predictions."""
    winners = [p.winner_correct for p in predictions if p.outcome == 'evaluated' and p.winner_correct is not None]
    trios = [p.exact_trio for p in predictions if p.outcome == 'evaluated' and p.exact_trio is not None]
    slots = [c.position_correct for p in predictions if p.outcome == 'evaluated' and p.mode == 'trio'
             for c in p.choices if c.position_correct is not None]
    rate = lambda values: round(100 * sum(values) / len(values), 1) if values else None
    return dict(total=len(predictions), winners=len(winners), winner_rate=rate(winners),
                trios=len(trios), trio_rate=rate(trios), slot_rate=rate(slots), slots=len(slots))


def account_accuracy(user_id):
    """Aggregate account accuracy in SQL; no full prediction/choice history load."""
    from sqlalchemy import func, case
    evaluated = Prediction.outcome == 'evaluated'
    query = select(func.count(Prediction.id),
        func.sum(case((evaluated & Prediction.winner_correct.is_not(None), 1), else_=0)),
        func.sum(case((evaluated & Prediction.winner_correct.is_(True), 1), else_=0)),
        func.sum(case((evaluated & Prediction.exact_trio.is_not(None), 1), else_=0)),
        func.sum(case((evaluated & Prediction.exact_trio.is_(True), 1), else_=0))).where(Prediction.user_id == user_id)
    total, winners, correct_winners, trios, correct_trios = db.session.execute(query).one()
    slots, correct_slots = db.session.execute(select(func.count(PredictionChoice.id),
        func.sum(case((PredictionChoice.position_correct.is_(True), 1), else_=0)))
        .join(Prediction).where(Prediction.user_id == user_id, evaluated, Prediction.mode == 'trio',
                              PredictionChoice.position_correct.is_not(None))).one()
    rate = lambda correct, count: round(100 * (correct or 0) / count, 1) if count else None
    return dict(total=total, winners=winners or 0, trios=trios or 0, slots=slots,
                winner_rate=rate(correct_winners, winners), trio_rate=rate(correct_trios, trios),
                slot_rate=rate(correct_slots, slots))
