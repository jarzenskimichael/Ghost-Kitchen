import os
from io import BytesIO
from datetime import date, timedelta

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ADMIN_PASSWORD", "test-organizer-password")
os.environ.setdefault("DATABASE_URL", "sqlite://")

import pytest
from unittest.mock import patch
from urllib.parse import parse_qs
from app import create_app, db
from app.routes import send_sms
from app.models import Application, Rotation, RotationClosure, MondaySlot, MondayRequest, InsuranceRecord, SmsConsent


@pytest.fixture()
def app(tmp_path):
    application = create_app()
    application.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    application.config["UPLOAD_FOLDER"] = str(tmp_path)
    with application.app_context():
        db.drop_all()
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def make_rotation():
    start = date.today() + timedelta(days=(7 - date.today().weekday()) % 7 or 7)
    rotation = Rotation(start_date=start, second_date=start + timedelta(days=7))
    db.session.add(rotation)
    db.session.commit()
    return rotation


def make_application():
    person = Application(
        business_name="Test Dumplings",
        owner_name="Test Owner",
        email="test@example.com",
        phone="3305550100",
        business_type="Food truck",
        description="A test business",
        concept="Dumplings",
        menu="Pork and vegetable dumplings",
        equipment="Steamers",
        license_info="Permit in progress",
        insurance_info="Insured",
    )
    db.session.add(person)
    db.session.commit()
    return person


def login(client):
    response = client.post(
        "/admin/login",
        data={"password": "test-organizer-password"},
        follow_redirects=False,
    )
    assert response.status_code == 302


def test_public_pages_and_admin_auth(client):
    for path in ("/", "/how-it-works", "/calendar", "/apply", "/operators"):
        assert client.get(path).status_code == 200
    assert client.get("/admin").status_code == 302
    assert client.post("/admin/login", data={"password": "wrong"}).status_code == 200
    login(client)
    assert client.get("/admin").status_code == 200
    assert client.get("/admin/rotations").status_code == 200


def test_closing_rotation_hides_it_from_applications_but_not_public_calendar(app, client):
    with app.app_context():
        rotation = make_rotation()
        rotation_id = rotation.id

    login(client)
    response = client.post(
        f"/admin/rotations/{rotation_id}/availability",
        data={"action": "close", "reason": "Private maintenance note"},
        follow_redirects=True,
    )
    assert response.status_code == 200

    with app.app_context():
        closure = RotationClosure.query.filter_by(rotation_id=rotation_id).one()
        assert closure.reason == "Private maintenance note"

    calendar = client.get("/calendar").get_data(as_text=True)
    assert "Unavailable" in calendar
    assert "Private maintenance note" not in calendar

    application_form = client.get("/apply").get_data(as_text=True)
    assert f'value="{rotation_id}"' not in application_form

    organizer_page = client.get("/admin/rotations").get_data(as_text=True)
    assert "Private maintenance note" in organizer_page


def test_reopening_rotation_restores_application_choice(app, client):
    with app.app_context():
        rotation = make_rotation()
        rotation_id = rotation.id
        db.session.add(RotationClosure(rotation_id=rotation_id, reason="Closed"))
        db.session.commit()

    login(client)
    response = client.post(
        f"/admin/rotations/{rotation_id}/availability",
        data={"action": "reopen"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    with app.app_context():
        assert RotationClosure.query.filter_by(rotation_id=rotation_id).first() is None
    assert f'value="{rotation_id}"' in client.get("/apply").get_data(as_text=True)


def test_assigned_rotation_cannot_be_closed(app, client):
    with app.app_context():
        rotation = make_rotation()
        person = make_application()
        rotation.application_id = person.id
        rotation.status = "approved"
        person.assigned_rotation_id = rotation.id
        person.status = "approved"
        db.session.commit()
        rotation_id = rotation.id

    login(client)
    client.post(
        f"/admin/rotations/{rotation_id}/availability",
        data={"action": "close"},
        follow_redirects=True,
    )
    with app.app_context():
        assert RotationClosure.query.filter_by(rotation_id=rotation_id).first() is None
        assert Rotation.query.get(rotation_id).application_id is not None


def test_applicant_cannot_submit_forged_closed_rotation(app, client):
    with app.app_context():
        rotation = make_rotation()
        rotation_id = rotation.id
        db.session.add(RotationClosure(rotation_id=rotation_id, reason="Unavailable"))
        db.session.commit()

    response = client.post(
        "/apply",
        data={
            "business_name": "Forged Date Foods",
            "owner_name": "Applicant",
            "email": "applicant@example.com",
            "phone": "3305550101",
            "business_type": "Food truck",
            "description": "Description",
            "concept": "Concept",
            "menu": "Menu",
            "equipment": "Equipment",
            "license_info": "Licensing",
            "insurance_info": "Insurance",
            "preferred_rotation": str(rotation_id),
        },
    )
    assert response.status_code == 200
    with app.app_context():
        assert Application.query.filter_by(business_name="Forged Date Foods").count() == 0


def test_approval_assigns_rotation_and_rejection_releases_it(app, client):
    with app.app_context():
        rotation = make_rotation()
        person = make_application()
        rotation_id, person_id = rotation.id, person.id

    login(client)
    response = client.post(
        f"/admin/applications/{person_id}",
        data={"action": "approve", "rotation_id": str(rotation_id), "published": "yes"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    with app.app_context():
        person = db.session.get(Application, person_id)
        rotation = db.session.get(Rotation, rotation_id)
        assert person.status == "approved"
        assert person.assigned_rotation_id == rotation_id
        assert person.published is True
        assert rotation.application_id == person_id

    client.post(
        f"/admin/applications/{person_id}",
        data={"action": "reject"},
        follow_redirects=True,
    )
    with app.app_context():
        person = db.session.get(Application, person_id)
        rotation = db.session.get(Rotation, rotation_id)
        assert person.status == "rejected"
        assert person.assigned_rotation_id is None
        assert person.published is False
        assert rotation.application_id is None
        assert rotation.status == "available"


def test_login_rejects_external_next_redirect(client):
    response = client.post(
        "/admin/login?next=https://evil.example",
        data={"password": "test-organizer-password"},
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/admin")



def test_sms_sends_through_twilio_when_configured(app, monkeypatch):
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC123")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("TWILIO_FROM_NUMBER", "+15550000001")

    with app.app_context():
        with patch("app.routes.urllib.request.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.status = 201
            assert send_sms(
                "+15550000002",
                "New Ghost Kitchen application",
            ) is True

    request = urlopen.call_args.args[0]
    assert request.full_url.endswith("/Accounts/AC123/Messages.json")
    payload = parse_qs(request.data.decode("utf-8"))
    assert payload["To"] == ["+15550000002"]
    assert payload["From"] == ["+15550000001"]
    assert payload["Body"] == ["New Ghost Kitchen application"]


def test_sms_is_skipped_when_twilio_is_not_configured(app, monkeypatch):
    for key in (
        "TWILIO_ACCOUNT_SID",
        "TWILIO_AUTH_TOKEN",
        "TWILIO_FROM_NUMBER",
        "ORGANIZER_PHONE",
    ):
        monkeypatch.delenv(key, raising=False)

    with app.app_context():
        with patch("app.routes.urllib.request.urlopen") as urlopen:
            assert send_sms("+15550000002", "Test") is False
            urlopen.assert_not_called()


def test_single_monday_application_approval_and_insurance_certificate(app, client):
    with app.app_context():
        first_date = date.today() + timedelta(days=(7 - date.today().weekday()) % 7 or 7)
        second_date = first_date + timedelta(days=7)
        first = MondaySlot(monday_date=first_date)
        second = MondaySlot(monday_date=second_date)
        db.session.add_all([first, second])
        db.session.commit()
        first_id, second_id = first.id, second.id

    response = client.post(
        "/apply",
        data={
            "business_name": "One Monday Dumplings",
            "owner_name": "Test Owner",
            "email": "one@example.com",
            "phone": "3305550101",
            "business_type": "Food truck",
            "description": "A test business",
            "concept": "Dumplings",
            "menu": "Dumplings",
            "equipment": "Steamers",
            "license_info": "Licensed",
            "insurance_info": "General liability coverage",
            "insurance_carrier": "Test Mutual",
            "insurance_policy_number": "POL-123",
            "insurance_coverage": "$1,000,000",
            "insurance_expires_on": "2027-12-31",
            "preferred_mondays": [str(first_id)],
            "insurance_certificate": (BytesIO(b"test certificate"), "certificate.pdf"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 302
    with app.app_context():
        person = Application.query.filter_by(business_name="One Monday Dumplings").one()
        assert MondayRequest.query.filter_by(application_id=person.id, slot_id=first_id).count() == 1
        insurance = InsuranceRecord.query.filter_by(application_id=person.id).one()
        assert insurance.carrier == "Test Mutual"
        assert insurance.policy_number == "POL-123"
        assert insurance.certificate_data == b"test certificate"
        person_id = person.id

    login(client)
    response = client.post(
        f"/admin/applications/{person_id}",
        data={"action": "approve", "monday_slot_ids": [str(first_id)], "published": "yes"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    with app.app_context():
        first = db.session.get(MondaySlot, first_id)
        second = db.session.get(MondaySlot, second_id)
        person = db.session.get(Application, person_id)
        assert first.application_id == person_id
        assert second.application_id is None
        assert person.assigned_rotation_id is None
        assert person.status == "approved"
    assert client.get(f"/admin/applications/{person_id}/insurance-certificate").data == b"test certificate"
    update_response = client.post(
        f"/admin/applications/{person_id}/insurance",
        data={
            "insurance_carrier": "Updated Mutual",
            "insurance_policy_number": "POL-456",
            "insurance_coverage": "$2,000,000",
            "insurance_expires_on": "2028-12-31",
            "insurance_certificate": (BytesIO(b"updated certificate"), "updated.pdf"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert update_response.status_code == 200
    assert client.get(f"/admin/applications/{person_id}/insurance-certificate").data == b"updated certificate"
    with app.app_context():
        insurance = InsuranceRecord.query.filter_by(application_id=person_id).one()
        assert insurance.carrier == "Updated Mutual"
        assert insurance.policy_number == "POL-456"
        assert insurance.certificate_data == b"updated certificate"


def test_sms_opt_in_requires_phone_and_explicit_consent(app, client):
    page = client.get("/sms-opt-in").get_data(as_text=True)
    assert 'name="phone"' in page
    assert 'name="sms_consent"' in page
    assert "Chef MJ" in page

    missing_consent = client.post(
        "/sms-opt-in",
        data={"phone": "(330) 555-0123"},
        follow_redirects=True,
    )
    assert missing_consent.status_code == 200
    assert "Please check the SMS consent box" in missing_consent.get_data(as_text=True)
    with app.app_context():
        assert SmsConsent.query.count() == 0

    invalid_phone = client.post(
        "/sms-opt-in",
        data={"phone": "123", "sms_consent": "yes"},
        follow_redirects=True,
    )
    assert "Enter a valid 10-digit US phone number" in invalid_phone.get_data(as_text=True)

    accepted = client.post(
        "/sms-opt-in",
        data={"phone": "(330) 555-0123", "sms_consent": "yes"},
        follow_redirects=True,
    )
    assert accepted.status_code == 200
    assert "Your SMS opt-in has been recorded" in accepted.get_data(as_text=True)
    with app.app_context():
        consent = SmsConsent.query.filter_by(phone="+13305550123").one()
        assert consent.active is True
        assert consent.consent_source == "Website SMS opt-in form"
        assert consent.consent_text_version == "2026-11-17"
        assert consent.consent_at is not None


def test_registered_campaign_brand_is_visible_in_site_header_and_footer(client):
    page = client.get("/").get_data(as_text=True)
    assert "CHEF MJ&#39;S FEEL GOOD BBQ" in page
    assert "Chef MJs Feel Good BBQ LLC" in page
    assert "Merriman Valley Pizza" in page
