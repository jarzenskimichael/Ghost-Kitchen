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
    closure = db.relationship(
        "RotationClosure", back_populates="rotation", uselist=False,
        cascade="all, delete-orphan",
    )


class RotationClosure(db.Model):
    """Private organizer record marking a two-Monday rotation unavailable."""
    id = db.Column(db.Integer, primary_key=True)
    rotation_id = db.Column(
        db.Integer, db.ForeignKey("rotation.id"), unique=True, nullable=False
    )
    reason = db.Column(db.String(300))
    closed_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    rotation = db.relationship("Rotation", back_populates="closure")


class MondaySlot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    monday_date = db.Column(db.Date, unique=True, nullable=False, index=True)
    application_id = db.Column(db.Integer, db.ForeignKey("application.id"), nullable=True)
    application = db.relationship("Application", backref=db.backref("monday_slots", lazy="select"))
    closure_reason = db.Column(db.String(300))
    closed_at = db.Column(db.DateTime)


class MondayRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(db.Integer, db.ForeignKey("application.id"), nullable=False, index=True)
    slot_id = db.Column(db.Integer, db.ForeignKey("monday_slot.id"), nullable=False, index=True)
    application = db.relationship("Application", backref=db.backref("monday_requests", lazy="select"))
    slot = db.relationship("MondaySlot")
    __table_args__ = (db.UniqueConstraint("application_id", "slot_id", name="uq_monday_request"),)


class InsuranceRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(db.Integer, db.ForeignKey("application.id"), unique=True, nullable=False)
    carrier = db.Column(db.String(180))
    policy_number = db.Column(db.String(100))
    coverage_amount = db.Column(db.String(80))
    expires_on = db.Column(db.Date)
    certificate_filename = db.Column(db.String(255))
    certificate_data = db.Column(db.LargeBinary)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    application = db.relationship("Application", backref=db.backref("insurance_record", uselist=False))
