import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from config import Config

db = SQLAlchemy()
csrf = CSRFProtect()

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    db.init_app(app)
    csrf.init_app(app)

    from app.routes import bp
    app.register_blueprint(bp)

    with app.app_context():
        db.create_all()
        from app.models import Setting
        if not Setting.query.filter_by(key="rental_rate").first():
            db.session.add(Setting(key="rental_rate", value=str(app.config["RENTAL_RATE"])))
            db.session.commit()
    return app
