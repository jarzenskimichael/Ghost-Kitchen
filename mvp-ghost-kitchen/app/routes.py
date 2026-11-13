import os, secrets, smtplib
from email.message import EmailMessage
from datetime import date, datetime, timedelta
from functools import wraps
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash
from flask import (Blueprint, current_app, render_template, request, redirect,
                   url_for, flash, session, abort, send_from_directory)
from app import db
from app.models import Application, Rotation, Setting

bp = Blueprint("main", __name__)
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "pdf"}


def send_notice(to_address, subject, body):
    """Send optional SMTP email. If SMTP is not configured, keep the app usable."""
    host = os.environ.get("SMTP_HOST")
    sender = os.environ.get("MAIL_FROM")
    if not host or not sender or not to_address:
        return False
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = to_address
    message.set_content(body)
    try:
        port = int(os.environ.get("SMTP_PORT", "587"))
        with smtplib.SMTP(host, port, timeout=12) as smtp:
            smtp.starttls()
            username = os.environ.get("SMTP_USER")
            password = os.environ.get("SMTP_PASSWORD")
            if username and password:
                smtp.login(username, password)
            smtp.send_message(message)
        return True
    except Exception:
        current_app.logger.exception("Unable to send ghost kitchen email notification")
        return False

def notify_organizer(subject, body):
    send_notice(os.environ.get("ORGANIZER_EMAIL"), subject, body)

def admin_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("main.admin_login", next=request.path))
        return fn(*args, **kwargs)
    return wrapped

def rental_rate():
    item = Setting.query.filter_by(key="rental_rate").first()
    return int(item.value) if item else current_app.config["RENTAL_RATE"]

def ensure_rotations(months=15):
    today = date.today()
    # Anchor every-other-Monday blocks to the first Monday on or after today.
    first = today + timedelta(days=(7 - today.weekday()) % 7)
    if first.weekday() != 0:
        first += timedelta(days=(7 - first.weekday()) % 7)
    # Preserve the same two-week cadence once established.
    existing = Rotation.query.order_by(Rotation.start_date.asc()).first()
    if existing:
        first = existing.start_date
        while first + timedelta(days=14) <= today:
            first += timedelta(days=14)
    end = today + timedelta(days=months * 31)
    cursor = first
    while cursor <= end:
        second = cursor + timedelta(days=7)
        if not Rotation.query.filter_by(start_date=cursor).first():
            db.session.add(Rotation(start_date=cursor, second_date=second))
        cursor += timedelta(days=14)
    db.session.commit()

def get_rotation_choices():
    ensure_rotations()
    return Rotation.query.filter(Rotation.start_date >= date.today()).order_by(Rotation.start_date).all()

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

@bp.app_context_processor
def inject_globals():
    return {"business_name": current_app.config["BUSINESS_NAME"], "rental_rate": rental_rate()}

@bp.route("/")
def home():
    ensure_rotations()
    upcoming = (Rotation.query.filter(Rotation.start_date >= date.today(), Rotation.application_id.is_(None))
                .order_by(Rotation.start_date).limit(4).all())
    featured = (Application.query.filter_by(status="approved", published=True)
                .order_by(Application.created_at.desc()).limit(3).all())
    return render_template("home.html", upcoming=upcoming, featured=featured)

@bp.route("/how-it-works")
def how_it_works():
    return render_template("how_it_works.html")

@bp.route("/calendar")
def calendar():
    rotations = get_rotation_choices()
    return render_template("calendar.html", rotations=rotations)

@bp.route("/operators")
def operators():
    people = Application.query.filter_by(status="approved", published=True).order_by(Application.business_name).all()
    return render_template("operators.html", operators=people)

@bp.route("/operators/<int:application_id>")
def operator_detail(application_id):
    person = Application.query.filter_by(id=application_id, status="approved", published=True).first_or_404()
    return render_template("operator_detail.html", person=person)

@bp.route("/apply", methods=["GET", "POST"])
def apply():
    choices = get_rotation_choices()
    if request.method == "POST":
        required = ["business_name","owner_name","email","phone","business_type","description",
                    "concept","menu","equipment","license_info","insurance_info"]
        missing = [field for field in required if not request.form.get(field, "").strip()]
        if missing:
            flash("Please complete all required fields.", "error")
            return render_template("apply.html", rotations=choices, form=request.form)
        preferred = request.form.get("preferred_rotation", "")
        if preferred and not Rotation.query.filter_by(id=int(preferred)).first():
            flash("Please select a valid rotation.", "error")
            return render_template("apply.html", rotations=choices, form=request.form)
        photo_name = None
        upload = request.files.get("food_photo")
        if upload and upload.filename:
            if not allowed_file(upload.filename):
                flash("Please upload a JPG, PNG, WEBP, or PDF file.", "error")
                return render_template("apply.html", rotations=choices, form=request.form)
            ext = upload.filename.rsplit(".", 1)[1].lower()
            photo_name = secrets.token_hex(12) + "." + ext
            upload.save(os.path.join(current_app.config["UPLOAD_FOLDER"], photo_name))
        app = Application(
            business_name=request.form["business_name"].strip(),
            owner_name=request.form["owner_name"].strip(),
            email=request.form["email"].strip(),
            phone=request.form["phone"].strip(),
            business_type=request.form["business_type"],
            description=request.form["description"].strip(),
            concept=request.form["concept"].strip(),
            menu=request.form["menu"].strip(),
            social_links=request.form.get("social_links","").strip(),
            website=request.form.get("website","").strip(),
            equipment=request.form["equipment"].strip(),
            license_info=request.form["license_info"].strip(),
            insurance_info=request.form["insurance_info"].strip(),
            preferred_rotation=preferred or None,
            photo_filename=photo_name
        )
        db.session.add(app)
        db.session.commit()
        notify_organizer(
            f"New Ghost Kitchen application: {app.business_name}",
            f"A new application was submitted by {app.owner_name} ({app.email}, {app.phone}). Review it in the organizer dashboard."
        )
        send_notice(
            app.email,
            "MVP Ghost Kitchen application received",
            f"Hi {app.owner_name},\\n\\nThank you for applying to the MVP Ghost Kitchen program. Your application for {app.business_name} has been received. This is not a date confirmation; MVP will review your application and contact you.\\n\\nMerriman Valley Pizza"
        )
        flash("Your application has been submitted. MVP will review it and contact you.", "success")
        return redirect(url_for("main.apply"))
    return render_template("apply.html", rotations=choices, form={})

@bp.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        supplied = request.form.get("password", "")
        configured = os.environ.get("ADMIN_PASSWORD", "")
        if configured and secrets.compare_digest(supplied, configured):
            session.clear()
            session["admin_logged_in"] = True
            session.permanent = True
            return redirect(request.args.get("next") or url_for("main.admin_dashboard"))
        flash("Incorrect password, or ADMIN_PASSWORD has not been configured.", "error")
    return render_template("admin_login.html")

@bp.route("/admin/logout")
def admin_logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("main.home"))

@bp.route("/admin")
@admin_required
def admin_dashboard():
    ensure_rotations()
    apps = Application.query.order_by(Application.created_at.desc()).all()
    pending = [a for a in apps if a.status == "pending"]
    upcoming = Rotation.query.filter(Rotation.start_date >= date.today()).order_by(Rotation.start_date).limit(10).all()
    return render_template("admin_dashboard.html", applications=apps, pending=pending, rotations=upcoming)

@bp.route("/admin/applications/<int:application_id>", methods=["GET", "POST"])
@admin_required
def admin_application(application_id):
    person = Application.query.get_or_404(application_id)
    choices = get_rotation_choices()
    if request.method == "POST":
        action = request.form.get("action")
        person.admin_notes = request.form.get("admin_notes", "").strip()
        if action == "approve":
            rotation_id = request.form.get("rotation_id", "")
            rotation = Rotation.query.get(int(rotation_id)) if rotation_id else None
            if not rotation:
                flash("Choose a rotation before approving.", "error")
            elif rotation.application_id not in (None, person.id):
                flash("That rotation has already been assigned.", "error")
            else:
                if person.assigned_rotation_id:
                    old = Rotation.query.get(person.assigned_rotation_id)
                    if old and old.application_id == person.id:
                        old.application_id = None
                        old.status = "available"
                rotation.application_id = person.id
                rotation.status = "approved"
                person.assigned_rotation_id = rotation.id
                person.status = "approved"
                person.published = request.form.get("published") == "yes"
                db.session.commit()
                send_notice(
                    person.email,
                    "MVP Ghost Kitchen application approved",
                    f"Hi {person.owner_name},\\n\\nYour application for {person.business_name} has been approved for the two-Monday rotation beginning {rotation.start_date.strftime('%B %-d, %Y')} and continuing {rotation.second_date.strftime('%B %-d, %Y')}. The rental fee is ${rental_rate() * 2} total. MVP will follow up with the remaining operating details and payment instructions.\\n\\nMerriman Valley Pizza"
                )
                notify_organizer(
                    f"Ghost Kitchen application approved: {person.business_name}",
                    f"{person.business_name} was approved for {rotation.start_date} and {rotation.second_date}."
                )
                flash("Application approved and rotation assigned.", "success")
                return redirect(url_for("main.admin_application", application_id=person.id))
        elif action == "reject":
            person.status = "rejected"
            person.published = False
            send_notice(person.email, "MVP Ghost Kitchen application update",
                        f"Hi {person.owner_name},\\n\\nThank you for your interest in the MVP Ghost Kitchen program. We are unable to move forward with this application at this time. We appreciate you considering MVP.\\n\\nMerriman Valley Pizza")
        elif action == "waitlist":
            person.status = "waitlist"
        elif action == "request_info":
            person.status = "info_requested"
            send_notice(person.email, "MVP Ghost Kitchen — additional information requested",
                        f"Hi {person.owner_name},\\n\\nMVP has reviewed your application for {person.business_name} and would like to discuss a few additional details. Please reply to this email or contact MVP directly.\\n\\nMerriman Valley Pizza")
        elif action == "save":
            pass
        db.session.commit()
        flash("Application updated.", "success")
    return render_template("admin_application.html", person=person, rotations=choices)

@bp.route("/admin/rotations")
@admin_required
def admin_rotations():
    ensure_rotations(24)
    rotations = Rotation.query.order_by(Rotation.start_date).all()
    return render_template("admin_rotations.html", rotations=rotations)

@bp.route("/admin/rotations/<int:rotation_id>/clear", methods=["POST"])
@admin_required
def clear_rotation(rotation_id):
    rotation = Rotation.query.get_or_404(rotation_id)
    if rotation.application:
        rotation.application.assigned_rotation_id = None
        rotation.application.status = "pending"
        rotation.application.published = False
    rotation.application_id = None
    rotation.status = "available"
    db.session.commit()
    flash("Rotation cleared. The applicant is back in pending applications.", "success")
    return redirect(url_for("main.admin_rotations"))

@bp.route("/admin/settings", methods=["GET", "POST"])
@admin_required
def admin_settings():
    if request.method == "POST":
        try:
            amount = int(request.form.get("rental_rate", "150"))
            if amount < 0 or amount > 10000:
                raise ValueError()
            setting = Setting.query.filter_by(key="rental_rate").first()
            if not setting:
                setting = Setting(key="rental_rate", value=str(amount))
                db.session.add(setting)
            else:
                setting.value = str(amount)
            db.session.commit()
            flash("Rental rate updated.", "success")
        except ValueError:
            flash("Enter a valid rental amount.", "error")
    return render_template("admin_settings.html", rate=rental_rate())

@bp.route("/admin/applications/<int:application_id>/payment", methods=["POST"])
@admin_required
def payment_status(application_id):
    person = Application.query.get_or_404(application_id)
    status = request.form.get("payment_status")
    if status not in {"unpaid", "invoiced", "paid", "refunded"}:
        abort(400)
    person.payment_status = status
    db.session.commit()
    flash("Payment status updated.", "success")
    return redirect(url_for("main.admin_application", application_id=person.id))

@bp.route("/admin/uploads/<filename>")
@admin_required
def admin_upload(filename):
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], filename, as_attachment=False)
