import os
import mimetypes
from io import BytesIO, StringIO
import secrets
import csv
import smtplib
from email.message import EmailMessage
from datetime import date, datetime, timedelta
from functools import wraps
from urllib.parse import urlsplit
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from flask import (
    Blueprint, current_app, render_template, request, redirect,
    url_for, flash, session, abort, send_from_directory, send_file,
)
from app import db
from app.models import Application, Rotation, RotationClosure, MondaySlot, MondayRequest, InsuranceRecord, Setting

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


def status_serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="vendor-application-status")


def insurance_checklist(record):
    return {"carrier": bool(record and record.carrier),
            "policy_number": bool(record and record.policy_number),
            "coverage": bool(record and record.coverage_amount),
            "expiration": bool(record and record.expires_on),
            "certificate": bool(record and record.certificate_data)}


def release_assigned_rotation(person):
    """Free an operator's current rotation before changing their application status."""
    if not person.assigned_rotation_id:
        return

    rotation = Rotation.query.get(person.assigned_rotation_id)
    if rotation and rotation.application_id == person.id:
        rotation.application_id = None
        rotation.status = "available"

    person.assigned_rotation_id = None
    person.published = False


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


def get_rotation_choices(include_closed=False):
    ensure_rotations()
    query = Rotation.query.filter(Rotation.start_date >= date.today())
    if not include_closed:
        query = query.filter(~Rotation.closure.has())
    return query.order_by(Rotation.start_date).all()


def ensure_monday_slots(months=24):
    """Create individual Monday slots and migrate existing rotation assignments."""
    today = date.today()
    first = today + timedelta(days=(7 - today.weekday()) % 7)
    end = today + timedelta(days=months * 31)
    cursor = first
    while cursor <= end:
        if not MondaySlot.query.filter_by(monday_date=cursor).first():
            db.session.add(MondaySlot(monday_date=cursor))
        cursor += timedelta(days=7)
    for legacy in Rotation.query.all():
        for monday in (legacy.start_date, legacy.second_date):
            slot = MondaySlot.query.filter_by(monday_date=monday).first()
            if not slot:
                slot = MondaySlot(monday_date=monday)
                db.session.add(slot)
                db.session.flush()
            if legacy.application_id and not slot.application_id:
                slot.application_id = legacy.application_id
            if legacy.closure and not slot.closed_at:
                slot.closure_reason = legacy.closure.reason
                slot.closed_at = legacy.closure.closed_at
    db.session.commit()

def get_monday_slots(include_unavailable=True):
    ensure_monday_slots()
    query = MondaySlot.query.filter(MondaySlot.monday_date >= date.today())
    if not include_unavailable:
        query = query.filter(MondaySlot.application_id.is_(None), MondaySlot.closed_at.is_(None))
    return query.order_by(MondaySlot.monday_date).all()

def release_monday_assignments(person):
    for slot in MondaySlot.query.filter_by(application_id=person.id).all():
        slot.application_id = None

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@bp.app_context_processor
def inject_globals():
    return {
        "business_name": current_app.config["BUSINESS_NAME"],
        "rental_rate": rental_rate(),
    }


@bp.route("/privacy")
def privacy():
    return render_template("privacy.html")


@bp.route("/terms")
def terms():
    return render_template("terms.html")


@bp.route("/")
def home():
    upcoming = get_monday_slots(include_unavailable=False)[:4]
    featured = (
        Application.query.filter_by(status="approved", published=True)
        .order_by(Application.created_at.desc())
        .limit(3)
        .all()
    )
    return render_template("home.html", upcoming=upcoming, featured=featured)


@bp.route("/how-it-works")
def how_it_works():
    return render_template("how_it_works.html")


@bp.route("/calendar")
def calendar():
    monday_slots = get_monday_slots()
    return render_template("calendar.html", monday_slots=monday_slots)


@bp.route("/operators")
def operators():
    people = (
        Application.query.filter_by(status="approved", published=True)
        .order_by(Application.business_name)
        .all()
    )
    return render_template("operators.html", operators=people)


@bp.route("/operators/<int:application_id>")
def operator_detail(application_id):
    person = Application.query.filter_by(
        id=application_id, status="approved", published=True
    ).first_or_404()
    return render_template("operator_detail.html", person=person)


@bp.route("/apply", methods=["GET", "POST"])
def apply():
    choices = get_monday_slots(include_unavailable=False)
    if request.method == "POST":
        required = [
            "business_name", "owner_name", "email", "phone", "business_type",
            "description", "concept", "menu", "equipment", "license_info",
            "insurance_carrier", "insurance_start_date",
        ]
        missing = [
            field for field in required
            if not request.form.get(field, "").strip()
        ]
        if missing:
            flash("Please complete all required fields.", "error")
            return render_template("apply.html", monday_slots=choices, form=request.form)

        insurance_start_value = request.form.get("insurance_start_date", "").strip()
        try:
            insurance_start_date = date.fromisoformat(insurance_start_value)
        except ValueError:
            flash("Please provide a valid insurance policy start date.", "error")
            return render_template("apply.html", monday_slots=choices, form=request.form)

        raw_monday_ids = request.form.getlist("preferred_mondays")
        try:
            selected_ids = [int(value) for value in raw_monday_ids]
        except (TypeError, ValueError):
            selected_ids = []
            flash("Please select valid Monday dates.", "error")
            return render_template("apply.html", monday_slots=choices, form=request.form)
        if len(selected_ids) != len(set(selected_ids)):
            flash("A Monday can only be selected once.", "error")
            return render_template("apply.html", monday_slots=choices, form=request.form)

        # Each application may request up to three separate sessions.
        # A session is one Monday or two consecutive Mondays.
        requested_dates = sorted(
            MondaySlot.query.filter(MondaySlot.id.in_(selected_ids)).with_entities(
                MondaySlot.monday_date
            ).all()
        ) if selected_ids else []
        requested_dates = [row[0] for row in requested_dates]
        sessions = []
        for requested_date in requested_dates:
            if not sessions or (requested_date - sessions[-1][-1]).days != 7:
                sessions.append([requested_date])
            else:
                sessions[-1].append(requested_date)

        if len(sessions) > 3 or any(len(group) > 2 for group in sessions):
            flash(
                "Please request up to three sessions. Each session can be one Monday "
                "or two consecutive Mondays. Separate sessions may be in different months.",
                "error",
            )
            return render_template("apply.html", monday_slots=choices, form=request.form)

        selected_slots = []
        legacy_preference = request.form.get("preferred_rotation", "").strip()
        if legacy_preference and not selected_ids:
            try:
                legacy_id = int(legacy_preference)
            except (TypeError, ValueError):
                legacy_id = None
            legacy_rotation = Rotation.query.filter_by(id=legacy_id).first() if legacy_id else None
            if not legacy_rotation or legacy_rotation.closure:
                flash("Please select a valid available Monday date.", "error")
                return render_template("apply.html", monday_slots=choices, form=request.form)
            selected_slots = MondaySlot.query.filter(
                MondaySlot.monday_date.in_([legacy_rotation.start_date, legacy_rotation.second_date]),
                MondaySlot.application_id.is_(None),
                MondaySlot.closed_at.is_(None),
            ).all()
            if len(selected_slots) != 2:
                flash("One or both Mondays in that legacy rotation are unavailable.", "error")
                return render_template("apply.html", monday_slots=choices, form=request.form)
        if selected_ids:
            selected_slots = MondaySlot.query.filter(
                MondaySlot.id.in_(selected_ids),
                MondaySlot.monday_date >= date.today(),
                MondaySlot.application_id.is_(None),
                MondaySlot.closed_at.is_(None),
            ).all()
            if len(selected_slots) != len(selected_ids):
                flash("One or more selected Mondays are no longer available. Please choose again.", "error")
                return render_template("apply.html", monday_slots=choices, form=request.form)

        photo_name = None
        upload = request.files.get("food_photo")
        if upload and upload.filename:
            if not allowed_file(upload.filename):
                flash("Please upload a JPG, PNG, WEBP, or PDF file.", "error")
                return render_template("apply.html", monday_slots=choices, form=request.form)

            extension = upload.filename.rsplit(".", 1)[1].lower()
            photo_name = secrets.token_hex(12) + "." + extension
            upload.save(os.path.join(current_app.config["UPLOAD_FOLDER"], photo_name))


        application = Application(
            business_name=request.form["business_name"].strip(),
            owner_name=request.form["owner_name"].strip(),
            email=request.form["email"].strip(),
            phone=request.form["phone"].strip(),
            business_type=request.form["business_type"].strip(),
            description=request.form["description"].strip(),
            concept=request.form["concept"].strip(),
            menu=request.form["menu"].strip(),
            social_links=request.form.get("social_links", "").strip(),
            website=request.form.get("website", "").strip(),
            equipment=request.form["equipment"].strip(),
            license_info=request.form["license_info"].strip(),
            insurance_info=f"Policy start date: {insurance_start_date.strftime('%B %-d, %Y')}",
            preferred_rotation=None,
            photo_filename=photo_name,
        )
        db.session.add(application)
        db.session.flush()

        for slot in selected_slots:
            db.session.add(MondayRequest(application_id=application.id, slot_id=slot.id))
        insurance_upload = request.files.get("insurance_certificate")
        insurance_filename = None
        if insurance_upload and insurance_upload.filename:
            if not allowed_file(insurance_upload.filename):
                db.session.rollback()
                flash("Please upload the insurance certificate as PDF, JPG, PNG, or WEBP.", "error")
                return render_template("apply.html", monday_slots=choices, form=request.form)
            insurance_filename = os.path.basename(insurance_upload.filename).replace("\\", "_")
            insurance_data = insurance_upload.read()
        else:
            insurance_data = None
        expires_value = request.form.get("insurance_expires_on", "").strip()
        try:
            expires_on = date.fromisoformat(expires_value) if expires_value else None
        except ValueError:
            db.session.rollback()
            flash("Enter a valid insurance expiration date.", "error")
            return render_template("apply.html", monday_slots=choices, form=request.form)
        db.session.add(InsuranceRecord(
            application_id=application.id,
            carrier=request.form.get("insurance_carrier", "").strip() or None,
            policy_number=request.form.get("insurance_policy_number", "").strip() or None,
            coverage_amount=request.form.get("insurance_coverage", "").strip() or None,
            expires_on=expires_on,
            certificate_filename=insurance_filename,
            certificate_data=insurance_data,
        ))
        db.session.commit()

        admin_url = url_for("main.admin_dashboard", _external=True)
        notify_organizer(
            f"New Ghost Kitchen application: {application.business_name}",
            (
                f"A new application was submitted by {application.owner_name} "
                f"({application.email}, {application.phone}). Review it in the "
                f"organizer dashboard: {admin_url}"
            ),
        )
        send_notice(
            application.email,
            "MVP Ghost Kitchen application received",
            (
                f"Hi {application.owner_name},\n\n"
                "Thank you for applying to the MVP Ghost Kitchen program. "
                f"Your application for {application.business_name} has been received. "
                "This is not a date confirmation; MVP will review your application "
                "and contact you.\n\nMerriman Valley Pizza"
            ),
        )
        status_token = status_serializer().dumps({"id": application.id, "email": application.email})
        return redirect(url_for("main.vendor_status", token=status_token))

    return render_template("apply.html", monday_slots=choices, form={})


@bp.route("/application-status/<token>")
def vendor_status(token):
    try:
        payload = status_serializer().loads(token, max_age=60 * 60 * 24 * 365)
    except (BadSignature, SignatureExpired):
        abort(404)
    person = Application.query.filter_by(id=payload.get("id"), email=payload.get("email")).first_or_404()
    requests = MondayRequest.query.filter_by(application_id=person.id).all()
    assigned = MondaySlot.query.filter_by(application_id=person.id).order_by(MondaySlot.monday_date).all()
    return render_template("vendor_status.html", person=person, requests=requests, assigned=assigned)


@bp.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        supplied = request.form.get("password", "")
        configured = os.environ.get("ADMIN_PASSWORD", "")
        if configured and secrets.compare_digest(supplied, configured):
            session.clear()
            session["admin_logged_in"] = True
            session.permanent = True

            # Only allow a same-site relative path; never redirect to an external host.
            next_url = request.args.get("next", "")
            parsed_next = urlsplit(next_url)
            if (
                not next_url.startswith("/")
                or next_url.startswith("//")
                or parsed_next.scheme
                or parsed_next.netloc
                or "\\" in next_url
            ):
                next_url = url_for("main.admin_dashboard")
            return redirect(next_url)

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
    query = Application.query
    status_filter = request.args.get("status", "").strip()
    search = request.args.get("q", "").strip()
    if status_filter in {"pending", "approved", "rejected", "waitlist", "info_requested"}:
        query = query.filter(Application.status == status_filter)
    if search:
        term = f"%{search}%"
        query = query.filter(db.or_(Application.business_name.ilike(term), Application.owner_name.ilike(term), Application.email.ilike(term)))
    applications = query.order_by(Application.created_at.desc()).all()
    pending = [application for application in applications if application.status == "pending"]
    upcoming = get_monday_slots()[:10]
    status_links = {
        application.id: url_for("main.vendor_status", token=status_serializer().dumps({"id": application.id, "email": application.email}))
        for application in applications
    }
    return render_template("admin_dashboard.html", applications=applications, pending=pending,
                           monday_slots=upcoming, status_filter=status_filter, search=search,
                           status_links=status_links)


@bp.route("/admin/schedule.csv")
@admin_required
def export_schedule():
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Monday", "Business", "Owner", "Email", "Phone", "Menu", "Payment", "Insurance"])
    slots = MondaySlot.query.filter(MondaySlot.application_id.isnot(None)).order_by(MondaySlot.monday_date).all()
    for slot in slots:
        person = slot.application
        record = person.insurance_record
        complete = bool(record and record.carrier and record.policy_number and record.coverage_amount and record.expires_on and record.certificate_data)
        writer.writerow([slot.monday_date.isoformat(), person.business_name, person.owner_name, person.email, person.phone, person.menu, person.payment_status, "Complete" if complete else "Incomplete"])
    return current_app.response_class(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=ghost-kitchen-schedule.csv"})


@bp.route("/admin/weekly-print")
@admin_required
def weekly_print():
    try:
        start = date.fromisoformat(request.args.get("week", ""))
    except ValueError:
        start = date.today() + timedelta(days=(7 - date.today().weekday()) % 7)
    end = start + timedelta(days=6)
    slots = MondaySlot.query.filter(MondaySlot.monday_date >= start, MondaySlot.monday_date <= end, MondaySlot.application_id.isnot(None)).order_by(MondaySlot.monday_date).all()
    return render_template("weekly_print.html", slots=slots, start=start, end=end)


@bp.route("/admin/applications/<int:application_id>", methods=["GET", "POST"])
@admin_required
def admin_application(application_id):
    person = Application.query.get_or_404(application_id)
    monday_slots = get_monday_slots()

    if request.method == "POST":
        action = request.form.get("action")
        person.admin_notes = request.form.get("admin_notes", "").strip()

        if action == "approve" and request.form.getlist("monday_slot_ids"):
            try:
                chosen_ids = [int(value) for value in request.form.getlist("monday_slot_ids")]
            except (TypeError, ValueError):
                chosen_ids = []
            selected = MondaySlot.query.filter(MondaySlot.id.in_(chosen_ids), MondaySlot.monday_date >= date.today()).with_for_update().all() if chosen_ids else []
            invalid = not chosen_ids or len(selected) != len(set(chosen_ids)) or any(slot.closed_at or slot.application_id not in (None, person.id) for slot in selected)
            if invalid:
                flash("Select one or more available Mondays. Closed or assigned dates cannot be approved.", "error")
            else:
                release_assigned_rotation(person)
                release_monday_assignments(person)
                db.session.flush()
                for slot in selected:
                    slot.application_id = person.id
                person.assigned_rotation_id = None
                person.status = "approved"
                person.published = request.form.get("published") == "yes"
                db.session.commit()
                dates_text = ", ".join(slot.monday_date.strftime("%B %-d, %Y") for slot in selected)
                total = rental_rate() * len(selected)
                body = f"Hi {person.owner_name}, your application for {person.business_name} is approved for {dates_text}. Total rental: ${total} (${rental_rate()} per Monday)."
                send_notice(person.email, "MVP Ghost Kitchen application approved", body)
                notify_organizer(f"Approved: {person.business_name}", f"Dates: {dates_text}")
                flash("Application approved and Monday date(s) assigned.", "success")
                return redirect(url_for("main.admin_application", application_id=person.id))

        if action == "approve" and not request.form.getlist("monday_slot_ids") and not request.form.get("rotation_id"):
            flash("Select at least one Monday date before approving.", "error")

        if action == "approve" and not request.form.getlist("monday_slot_ids") and request.form.get("rotation_id"):
            rotation_id = request.form.get("rotation_id", "").strip()
            try:
                rotation_id = int(rotation_id)
            except (TypeError, ValueError):
                rotation_id = None

            rotation = (
                Rotation.query.filter(
                    Rotation.id == rotation_id,
                    Rotation.start_date >= date.today(),
                    ~Rotation.closure.has(),
                ).first()
                if rotation_id is not None
                else None
            )

            if not rotation:
                flash("Choose a valid upcoming rotation before approving.", "error")
            elif rotation.application_id not in (None, person.id):
                flash("That rotation has already been assigned.", "error")
            else:
                release_assigned_rotation(person)
                # Flush the old assignment first because Rotation.application_id is unique.
                db.session.flush()
                rotation.application_id = person.id
                rotation.status = "approved"
                person.assigned_rotation_id = rotation.id
                person.status = "approved"
                person.published = request.form.get("published") == "yes"
                db.session.commit()

                send_notice(
                    person.email,
                    "MVP Ghost Kitchen application approved",
                    (
                        f"Hi {person.owner_name},\n\n"
                        f"Your application for {person.business_name} has been approved "
                        f"for the two-Monday rotation beginning "
                        f"{rotation.start_date.strftime('%B %-d, %Y')} and continuing "
                        f"{rotation.second_date.strftime('%B %-d, %Y')}. The rental fee "
                        f"is ${rental_rate() * 2} total. MVP will follow up with the "
                        "remaining operating details and payment instructions.\n\n"
                        "Merriman Valley Pizza"
                    ),
                )
                notify_organizer(
                    f"Ghost Kitchen application approved: {person.business_name}",
                    (
                        f"{person.business_name} was approved for "
                        f"{rotation.start_date} and {rotation.second_date}."
                    ),
                )
                flash("Application approved and rotation assigned.", "success")
                return redirect(
                    url_for("main.admin_application", application_id=person.id)
                )

        elif action == "reject":
            release_assigned_rotation(person)
            release_monday_assignments(person)
            person.status = "rejected"
            send_notice(
                person.email,
                "MVP Ghost Kitchen application update",
                (
                    f"Hi {person.owner_name},\n\n"
                    "Thank you for your interest in the MVP Ghost Kitchen program. "
                    "We are unable to move forward with this application at this time. "
                    "We appreciate you considering MVP.\n\nMerriman Valley Pizza"
                ),
            )

        elif action == "waitlist":
            release_assigned_rotation(person)
            release_monday_assignments(person)
            person.status = "waitlist"
            send_notice(
                person.email,
                "MVP Ghost Kitchen application update",
                (
                    f"Hi {person.owner_name},\n\n"
                    f"Your application for {person.business_name} has been placed on our waitlist. "
                    "We will contact you if an opportunity becomes available.\n\n"
                    "Merriman Valley Pizza"
                ),
            )

        elif action == "request_info":
            release_assigned_rotation(person)
            release_monday_assignments(person)
            person.status = "info_requested"
            send_notice(
                person.email,
                "MVP Ghost Kitchen — additional information requested",
                (
                    f"Hi {person.owner_name},\n\n"
                    f"MVP has reviewed your application for {person.business_name} "
                    "and would like to discuss a few additional details. Please reply "
                    "to this email or contact MVP directly.\n\nMerriman Valley Pizza"
                ),
            )

        elif action == "save":
            pass

        elif action == "approve":
            # Approval was submitted without a valid date selection.
            pass

        else:
            abort(400)

        db.session.commit()
        flash("Application updated.", "success")

    return render_template(
        "admin_application.html", person=person, monday_slots=monday_slots,
        requested_monday_ids={item.slot_id for item in MondayRequest.query.filter_by(application_id=person.id).all()}
    )


@bp.route("/admin/rotations")
@admin_required
def admin_rotations():
    monday_slots = get_monday_slots()
    return render_template("admin_rotations.html", monday_slots=monday_slots, today=date.today())


@bp.route("/admin/mondays/<int:slot_id>/availability", methods=["POST"])
@admin_required
def update_monday_availability(slot_id):
    slot = MondaySlot.query.get_or_404(slot_id)
    action = request.form.get("action")
    if slot.monday_date < date.today():
        flash("Past Mondays cannot be changed.", "error")
    elif action == "close":
        if slot.application_id:
            flash("Clear the assignment before closing this Monday.", "error")
        elif not slot.closed_at:
            from datetime import datetime
            slot.closure_reason = request.form.get("reason", "").strip()[:300] or None
            slot.closed_at = datetime.utcnow()
            db.session.commit()
            flash("Monday marked unavailable.", "success")
    elif action == "reopen":
        slot.closure_reason = None
        slot.closed_at = None
        # Remove legacy paired-date closures so migration never recloses this slot.
        for legacy in Rotation.query.filter(
            (Rotation.start_date == slot.monday_date) | (Rotation.second_date == slot.monday_date)
        ).all():
            if legacy.closure:
                db.session.delete(legacy.closure)
        db.session.commit()
        flash("Monday reopened.", "success")
    else:
        abort(400)
    return redirect(url_for("main.admin_rotations"))


@bp.route("/admin/mondays/<int:slot_id>/clear", methods=["POST"])
@admin_required
def clear_monday_slot(slot_id):
    slot = MondaySlot.query.get_or_404(slot_id)
    notice = None
    if slot.application_id:
        person = Application.query.get(slot.application_id)
        slot.application_id = None
        # Break a legacy paired rotation link; keep the neighboring Monday assigned.
        if person and person.assigned_rotation_id:
            legacy = Rotation.query.get(person.assigned_rotation_id)
            if legacy and legacy.application_id == person.id:
                legacy.application_id = None
                legacy.status = "available"
            person.assigned_rotation_id = None
        if person:
            remaining = MondaySlot.query.filter_by(application_id=person.id).filter(MondaySlot.id != slot.id).first()
            if not remaining:
                person.status = "pending"
                person.published = False
                notice = (
                    person.email,
                    "MVP Ghost Kitchen scheduling update",
                    f"Hi {person.owner_name},\n\nThe Monday booking for {slot.monday_date.strftime('%B %-d, %Y')} "
                    "has been removed. Your application has returned to pending review. "
                    "Please contact MVP if you have questions.\n\nMerriman Valley Pizza",
                )
            else:
                notice = (
                    person.email,
                    "MVP Ghost Kitchen scheduling update",
                    f"Hi {person.owner_name},\n\nThe Monday booking for {slot.monday_date.strftime('%B %-d, %Y')} "
                    "has been removed. Any other approved dates remain unchanged. "
                    "Please contact MVP if you have questions.\n\nMerriman Valley Pizza",
                )
    db.session.commit()
    if notice:
        send_notice(*notice)
    flash("Monday assignment cleared.", "success")
    return redirect(url_for("main.admin_rotations"))



@bp.route("/admin/rotations/<int:rotation_id>/availability", methods=["POST"])
@admin_required
def update_rotation_availability(rotation_id):
    rotation = Rotation.query.get_or_404(rotation_id)
    action = request.form.get("action")

    if rotation.start_date < date.today():
        flash("Past rotations cannot be changed.", "error")
        return redirect(url_for("main.admin_rotations"))

    closure = RotationClosure.query.filter_by(rotation_id=rotation.id).first()
    if action == "close":
        if rotation.application_id:
            flash("Clear the existing assignment before closing this rotation.", "error")
        elif not closure:
            reason = request.form.get("reason", "").strip()
            db.session.add(
                RotationClosure(
                    rotation_id=rotation.id,
                    reason=reason[:300] or None,
                )
            )
            db.session.commit()
            flash("Both Mondays in this rotation are now unavailable.", "success")
        else:
            flash("This rotation is already closed.", "error")
    elif action == "reopen":
        if closure:
            db.session.delete(closure)
            db.session.commit()
            flash("This rotation is available for applications again.", "success")
        else:
            flash("This rotation is already open.", "error")
    else:
        abort(400)

    return redirect(url_for("main.admin_rotations"))


@bp.route("/admin/rotations/<int:rotation_id>/clear", methods=["POST"])
@admin_required
def clear_rotation(rotation_id):
    rotation = Rotation.query.get_or_404(rotation_id)
    notice = None
    if rotation.application:
        person = rotation.application
        person.assigned_rotation_id = None
        person.status = "pending"
        person.published = False
        notice = (
            person.email,
            "MVP Ghost Kitchen scheduling update",
            f"Hi {person.owner_name},\n\nYour two-Monday rotation beginning "
            f"{rotation.start_date.strftime('%B %-d, %Y')} has been cleared and your application "
            "has returned to pending review. Please contact MVP if you have questions.\n\n"
            "Merriman Valley Pizza",
        )

    rotation.application_id = None
    rotation.status = "available"
    db.session.commit()
    if notice:
        send_notice(*notice)
    flash(
        "Rotation cleared. The applicant is back in pending applications.",
        "success",
    )
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


@bp.route("/admin/applications/<int:application_id>/insurance", methods=["POST"])
@admin_required
def admin_update_insurance(application_id):
    person = Application.query.get_or_404(application_id)
    record = InsuranceRecord.query.filter_by(application_id=person.id).first()
    if not record:
        record = InsuranceRecord(application_id=person.id)
        db.session.add(record)
    record.carrier = request.form.get("insurance_carrier", "").strip() or None
    record.policy_number = request.form.get("insurance_policy_number", "").strip() or None
    record.coverage_amount = request.form.get("insurance_coverage", "").strip() or None
    expires_value = request.form.get("insurance_expires_on", "").strip()
    try:
        record.expires_on = date.fromisoformat(expires_value) if expires_value else None
    except ValueError:
        flash("Enter a valid insurance expiration date.", "error")
        return redirect(url_for("main.admin_application", application_id=person.id))
    upload = request.files.get("insurance_certificate")
    if upload and upload.filename:
        if not allowed_file(upload.filename):
            flash("Upload the certificate as PDF, JPG, PNG, or WEBP.", "error")
            return redirect(url_for("main.admin_application", application_id=person.id))
        record.certificate_filename = os.path.basename(upload.filename).replace("\\", "_")
        record.certificate_data = upload.read()
    db.session.commit()
    flash("Insurance information updated.", "success")
    return redirect(url_for("main.admin_application", application_id=person.id))

@bp.route("/admin/applications/<int:application_id>/insurance-certificate")
@admin_required
def admin_insurance_certificate(application_id):
    record = InsuranceRecord.query.filter_by(application_id=application_id).first_or_404()
    if not record.certificate_data:
        abort(404)
    filename = record.certificate_filename or "insurance-certificate"
    mimetype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return send_file(BytesIO(record.certificate_data), mimetype=mimetype, download_name=filename, as_attachment=False)


@bp.route("/admin/uploads/<filename>")
@admin_required
def admin_upload(filename):
    return send_from_directory(
        current_app.config["UPLOAD_FOLDER"], filename, as_attachment=False
    )
