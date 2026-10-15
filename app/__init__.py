import os
from datetime import timedelta
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect, CSRFError

db = SQLAlchemy()
migrate = Migrate()
csrf = CSRFProtect()

def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    
    app.config.from_mapping(
        SECRET_KEY=os.environ.get('SECRET_KEY'),
        SQLALCHEMY_DATABASE_URI=os.environ.get("DATABASE_URL") or f"sqlite:///{os.path.join(app.instance_path, 'races.db')}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_ENGINE_OPTIONS={'hide_parameters': True},
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=os.environ.get('SESSION_COOKIE_SECURE', 'true').lower() == 'true',
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        MAX_CONTENT_LENGTH=2 * 1024 * 1024,
        AUTH_WINDOW_SECONDS=900,
        LOGIN_LIMIT=5,
        LOGIN_IP_LIMIT=30,
        REGISTER_LIMIT=10,
        VERSION='2.0.0-alpha.4',
        CLUB_TIMEZONE='Europe/Moscow',
    )

    if test_config:
        app.config.update(test_config)
    if not app.config['SECRET_KEY']:
        if app.testing:
            app.config['SECRET_KEY'] = os.urandom(32)
        else:
            raise RuntimeError('Задайте постоянный случайный SECRET_KEY в окружении.')

    # Гарантируем наличие каталога instance
    try:
        os.makedirs(app.instance_path, exist_ok=True)
    except OSError:
        pass

    db.init_app(app)
    migrate.init_app(app, db, compare_type=True, render_as_batch=True)
    csrf.init_app(app)

    from app.auth import setup_auth
    setup_auth(app)
    from app.schema import setup_schema_cli
    setup_schema_cli(app)

    @app.errorhandler(CSRFError)
    def invalid_csrf(error):
        from flask import render_template
        return render_template('errors/message.html', message='Срок действия формы истёк. Обновите страницу и повторите ввод.'), 400

    from app.web import setup_web
    setup_web(app)

    # Регистрация маршрутов
    from app.routes.main import main_bp
    from app.routes.owners import owners_bp
    from app.routes.horses import horses_bp
    from app.routes.jockeys import jockeys_bp
    from app.routes.competitions import competitions_bp
    from app.routes.errors import errors_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(owners_bp, url_prefix='/owners')
    app.register_blueprint(horses_bp, url_prefix='/horses')
    app.register_blueprint(jockeys_bp, url_prefix='/jockeys')
    app.register_blueprint(competitions_bp, url_prefix='/competitions')
    from app.routes.cabinet import cabinet_bp, setup_cabinet_context
    app.register_blueprint(cabinet_bp, url_prefix='/cabinet')
    setup_cabinet_context(app)
    from app.routes.admin import admin_bp, root_bp
    app.register_blueprint(admin_bp)
    app.register_blueprint(root_bp)
    from app.routes.predictions import predictions_bp
    from app.routes.analytics import analytics_bp
    app.register_blueprint(predictions_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(errors_bp)

    return app
