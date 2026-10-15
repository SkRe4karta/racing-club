from flask import Blueprint, render_template
from sqlalchemy.exc import SQLAlchemyError
from app import db

errors_bp = Blueprint('errors', __name__)

@errors_bp.app_errorhandler(404)
def not_found_error(error):
    return render_template('errors/404.html'), 404

@errors_bp.app_errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template('errors/500.html'), 500


@errors_bp.app_errorhandler(SQLAlchemyError)
def database_error(error):
    db.session.rollback()
    from flask import current_app
    current_app.logger.exception('Database operation failed')
    return render_template('errors/message.html', message='Не удалось сохранить или загрузить данные. Повторите попытку.'), 503


@errors_bp.app_errorhandler(413)
def too_large(error):
    return render_template('errors/message.html', message='Размер отправленной формы превышает допустимый.'), 413
