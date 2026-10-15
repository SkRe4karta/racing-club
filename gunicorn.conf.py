def post_fork(server, worker):
    from run import app
    from app import db
    with app.app_context():
        db.engine.dispose(close=False)
