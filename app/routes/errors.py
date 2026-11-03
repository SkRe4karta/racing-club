from flask import Blueprint, g, render_template
from flask_login import AnonymousUserMixin
from sqlalchemy.exc import SQLAlchemyError
from app import db

errors_bp = Blueprint('errors', __name__)

@errors_bp.app_errorhandler(403)
def forbidden(error):
    return render_template('errors/message.html', message='Недостаточно прав для этого действия.'), 403

@errors_bp.app_errorhandler(404)
def not_found_error(error):
    return render_template('errors/404.html'), 404

@errors_bp.app_errorhandler(500)
def internal_error(error):
    db.session.rollback()
    g._login_user = AnonymousUserMixin()
    return render_template('errors/500.html'), 500


@errors_bp.app_errorhandler(SQLAlchemyError)
def database_error(error):
    db.session.rollback()
    # Error rendering must not query the unavailable users table a second time.
    g._login_user = AnonymousUserMixin()
    from flask import current_app
    current_app.logger.exception('Database operation failed')
    return render_template('errors/message.html', message='Не удалось сохранить или загрузить данные. Повторите попытку.'), 503


@errors_bp.app_errorhandler(413)
def too_large(error):
    return render_template('errors/message.html', message='Размер отправленной формы превышает допустимый.'), 413
