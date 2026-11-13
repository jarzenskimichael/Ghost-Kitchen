from datetime import datetime
from app import db

class Setting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(80), unique=True, nullable=False)
    value = db.Column(db.String(500), nullable=False)

class Application(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    business_name = db.Column(db.String(160), nullable=False)
    owner_name = db.Column(db.String(160), nullable=False)
    email = db.Column(db.String(180), nullable=False)
    phone = db.Column(db.String(60), nullable=False)
    business_type = db.Column(db.String(80), nullable=False)
    description = db.Column(db.Text, nullable=False)
    concept = db.Column(db.Text, nullable=False)
    menu = db.Column(db.Text, nullable=False)
    social_links = db.Column(db.String(500))
    website = db.Column(db.String(300))
    equipment = db.Column(db.Text, nullable=False)
    license_info = db.Column(db.Text, nullable=False)
    insurance_info = db.Column(db.Text, nullable=False)
    preferred_rotation = db.Column(db.String(20))
    photo_filename = db.Column(db.String(255))
    status = db.Column(db.String(30), default="pending", nullable=False)
    admin_notes = db.Column(db.Text)
    assigned_rotation_id = db.Column(db.Integer, db.ForeignKey("rotation.id"))
    assigned_rotation = db.relationship("Rotation", foreign_keys=[assigned_rotation_id], uselist=False)
    payment_status = db.Column(db.String(30), default="unpaid", nullable=False)
    agreement_filename = db.Column(db.String(255))
    published = db.Column(db.Boolean, default=False, nullable=False)

class Rotation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    start_date = db.Column(db.Date, unique=True, nullable=False)
    second_date = db.Column(db.Date, nullable=False)
    application_id = db.Column(db.Integer, db.ForeignKey("application.id"), unique=True)
    status = db.Column(db.String(30), default="available", nullable=False)

    application = db.relationship("Application", foreign_keys=[application_id], uselist=False)
