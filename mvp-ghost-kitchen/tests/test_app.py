import os
from datetime import date, timedelta

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ADMIN_PASSWORD", "test-organizer-password")
os.environ.setdefault("DATABASE_URL", "sqlite://")

import pytest
from app import create_app, db
from app.models import Application, Rotation, RotationClosure


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
