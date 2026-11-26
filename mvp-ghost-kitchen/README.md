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

1. Keep the GitHub repository private. This project currently lives in the `Ghost-Kitchen` repository; change its visibility under **Settings → General → Danger Zone → Change repository visibility** if it is still public.
2. The application files live in `mvp-ghost-kitchen/`. The root-level `render.yaml` already sets Render's `rootDir` to that folder.
3. In Render, use the repository's root-level `render.yaml` to create or update the Blueprint. If configuring an existing web service manually, set its **Root Directory** to `mvp-ghost-kitchen` so `requirements.txt` and `wsgi.py` are found.
4. Configure the environment variables:
   - `SECRET_KEY`: long random secret
   - `ADMIN_PASSWORD`: strong organizer password
   - `DATABASE_URL`: PostgreSQL connection string
   - `BUSINESS_NAME`: Merriman Valley Pizza
   - `RENTAL_RATE`: 150
   - `TIMEZONE`: America/New_York
   - Gmail API email settings: `MAIL_FROM`, `ORGANIZER_EMAIL`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and `GOOGLE_REFRESH_TOKEN`
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

## Email notifications

Email notifications use the Gmail API over HTTPS (not SMTP). Configure the following environment variables on the existing Render web service:

- `MAIL_FROM`: `merrimanvalleypizza@gmail.com`
- `ORGANIZER_EMAIL`: where organizer alerts should be delivered
- `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`: OAuth client credentials
- `GOOGLE_REFRESH_TOKEN`: long-lived OAuth refresh token authorized for Gmail sending

### Set up Gmail API credentials

1. In Google Cloud Console, create/select a project and enable **Gmail API**.
2. Configure the OAuth consent screen. Add the Google account that owns `merrimanvalleypizza@gmail.com` as a test user while testing.
3. Create an OAuth client ID of type **Web application**. Add `https://developers.google.com/oauthplayground` as an authorized redirect URI.
4. Open [Google OAuth 2.0 Playground](https://developers.google.com/oauthplayground). Open its settings (gear), enable **Use your own OAuth credentials**, and enter the client ID and client secret.
5. In Step 1, enter the scope `https://www.googleapis.com/auth/gmail.send`, authorize the account `merrimanvalleypizza@gmail.com`, and grant permission.
6. In Step 2, exchange the authorization code for tokens and copy the **refresh token**.
7. Add the five environment variables above to the existing Render service's Environment page, then redeploy.

Keep the client secret and refresh token private. Do not paste them into chat, GitHub, source code, or logs. The Gmail API `gmail.send` scope permits sending email on behalf of the authorized account; it does not grant mailbox-reading access. Google classifies this as a sensitive scope. If the OAuth consent screen remains in **Testing** mode, refresh tokens for Gmail scopes expire after 7 days; for ongoing production use, move the consent configuration to **In production** (Google may show an unverified-app warning or require verification depending on the app's use).

The organizer Settings page includes a test-email action. A successful result means Google accepted the send request; check the recipient inbox and spam folder for actual receipt.

## Current payment behavior

The app tracks payment status manually (unpaid, invoiced, paid, refunded). It does not collect card payments. Email notifications are sent through the Gmail API when the OAuth environment variables are configured.

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
