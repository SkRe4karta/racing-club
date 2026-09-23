import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    
    app.config.from_mapping(
        SECRET_KEY=os.environ.get('SECRET_KEY', 'dev-secret-key-race-club-2026'),
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{os.path.join(app.instance_path, 'races.db')}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )

    if test_config:
        app.config.update(test_config)

    # Гарантируем наличие каталога instance
    try:
        os.makedirs(app.instance_path, exist_ok=True)
    except OSError:
        pass

    db.init_app(app)

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
    app.register_blueprint(errors_bp)

    with app.app_context():
        db.create_all()

    return app
