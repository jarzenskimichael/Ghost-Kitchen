import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from config import Config
from sqlalchemy import inspect, text

db = SQLAlchemy()
csrf = CSRFProtect()


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    if not app.config.get("SECRET_KEY"):
        raise RuntimeError(
            "SECRET_KEY must be configured before running the application in production."
        )

    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    db.init_app(app)
    csrf.init_app(app)

    from app.routes import bp
    app.register_blueprint(bp)

    with app.app_context():
        db.create_all()

        # db.create_all() creates new tables but does not add columns to a table
        # created by an earlier preview build. Apply these additive columns safely.
        inspector = inspect(db.engine)
        if "monday_slot" in inspector.get_table_names():
            monday_columns = {column["name"] for column in inspector.get_columns("monday_slot")}
            additive_columns = {
                "closure_reason": "VARCHAR(300)",
                "closed_at": "TIMESTAMP",
            }
            for column_name, column_type in additive_columns.items():
                if column_name not in monday_columns:
                    db.session.execute(
                        text(f"ALTER TABLE monday_slot ADD COLUMN {column_name} {column_type}")
                    )
            db.session.commit()

        from app.models import Setting
        if not Setting.query.filter_by(key="rental_rate").first():
            db.session.add(
                Setting(key="rental_rate", value=str(app.config["RENTAL_RATE"]))
            )
            db.session.commit()

    return app
