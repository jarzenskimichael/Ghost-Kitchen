# MVP Ghost Kitchen

A standalone Flask application for the Merriman Valley Pizza Ghost Kitchen program.

## Included

- Public program website and application form
- Public rotation calendar and published operator profiles
- Private password-protected organizer dashboard
- Application review, approval, rejection, waitlist, and information-request statuses
- Organizer assignment of one business to each two-Monday rotation
- Manual payment tracking
- Editable rental rate (default: $150 per Monday / $300 per rotation)
- PostgreSQL support for Render and SQLite for local development
- CSRF protection on forms
- Optional applicant photo/menu upload

## Important program defaults

- One operator per rotation
- Each rotation contains two consecutive Mondays
- Year-round rolling calendar
- Applications are requests only; nothing is automatically reserved
- Organizer approval is required
- Returning businesses reapply
- Introductory rental fee: $150 per Monday

## Run locally

Requires Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Set an organizer password and secret key before running:

```bash
export ADMIN_PASSWORD="choose-a-strong-password"
export SECRET_KEY="replace-with-a-long-random-secret"
flask --app wsgi run --debug
```

Open http://127.0.0.1:5000

The local database is created automatically. It uses SQLite by default.

## Deploy to Render

1. Create a new **private** GitHub repository named `mvp-ghost-kitchen`.
2. Upload the contents of this ZIP to the repository root (not the containing folder).
3. In Render, create a new Blueprint using the repository and its `render.yaml`, or create a Python web service manually.
4. Configure the environment variables:
   - `SECRET_KEY`: long random secret
   - `ADMIN_PASSWORD`: strong organizer password
   - `DATABASE_URL`: PostgreSQL connection string
   - `BUSINESS_NAME`: Merriman Valley Pizza
   - `RENTAL_RATE`: 150
   - `TIMEZONE`: America/New_York
   - Optional email settings: `SMTP_HOST`, `SMTP_PORT` (usually 587), `SMTP_USER`, `SMTP_PASSWORD`, `MAIL_FROM`, and `ORGANIZER_EMAIL`
5. Deploy. Visit `/admin/login` and sign in with the `ADMIN_PASSWORD`.

The included `render.yaml` defines a web service and a small PostgreSQL database. Confirm current Render plan pricing before provisioning.

## Upload storage warning

Uploaded applicant files are stored under `instance/uploads`. Render's ordinary filesystem is ephemeral. Before accepting real applications with uploaded files, attach a persistent disk and set `UPLOAD_FOLDER` to a directory on that disk, or add durable object storage. The application database is persistent through PostgreSQL, but uploaded files are not automatically backed up.

## Before accepting real applications

This is a working first version intended for deployment and testing, not a substitute for legal, food-safety, or insurance review.

Before opening applications:
- Review the rental agreement, cancellation/refund policy, insurance requirements, food-safety and licensing requirements, kitchen access hours, cleaning rules, equipment rules, and responsibility for ingredients/staff.
- Confirm the exact operator workflow and any local health department requirements.
- Configure durable upload storage if accepting file uploads.
- Set a strong `SECRET_KEY` and `ADMIN_PASSWORD`.
- Test application submission, approval, date assignment, publishing, and payment tracking.

## Current payment behavior

The app tracks payment status manually (unpaid, invoiced, paid, refunded). It does not collect card payments. Optional SMTP notifications are sent for new applications and key review decisions when SMTP environment variables are configured.

## Routes

Public:
- `/`
- `/how-it-works`
- `/calendar`
- `/operators`
- `/apply`

Organizer:
- `/admin/login`
- `/admin`
- `/admin/rotations`
- `/admin/settings`
