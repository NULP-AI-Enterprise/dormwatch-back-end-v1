# dormwatch-server

Django 5.2 + Django REST Framework + PostgreSQL REST API for DormWatch — a
dormitory issue tracking system at LPNU. The single Django app is `complaints/`
(models, serializers, views, auth); project config lives in `dormwatch/`
(settings, URLs). All endpoints are under `/api/` (see `complaints/urls.py`).
Settings are env-driven via `.env` (see `.env.example` for keys). The sibling
repo `dormwatch-web-app` (Vite/React) is the only consumer. Workspace-level
conventions live in the root `CLAUDE.md`.

## Commands

- `.venv/bin/python manage.py runserver` — dev server on `:8000`
- `.venv/bin/python manage.py makemigrations` / `migrate` — schema changes
- `.venv/bin/python manage.py shell` — REPL (testing only, see Verification)
- `.venv/bin/python manage.py check` — config sanity check

There is **no test suite**. Verification is end-to-end: mint a JWT and drive
the endpoint with `curl` (see Verification).

## Auth

`djangorestframework-simplejwt`:

- **Access token:** 30-min lifetime, sent as `Authorization: Bearer <token>`.
- **Refresh token:** 7-day lifetime, httpOnly cookie named `refresh_token`,
  path `/api/auth`, SameSite `Lax`, Secure when `DEBUG` is off. Rotation +
  blacklisting on refresh.
- **`EmailDomainJWTAuthentication`** (`complaints/authentication.py`) wraps
  simplejwt and **requires a non-empty `email` claim** in the token — minted
  tokens must carry it (see Verification).
- Registration is restricted to `ALLOWED_EMAIL_DOMAINS` (default `lpnu.ua`).
- Email-verification and password-reset/change flows live in
  `complaints/auth_views.py`. The canonical token shape is produced by
  `_get_tokens_for_user` (access + refresh strings, `email` claim set).
- Default auth classes: `SessionAuthentication` + `EmailDomainJWTAuthentication`; default
  permission is `IsAuthenticated`.

## Domain

- Django `User` + `UserProfile` (role, building, place, photo).
- **Admin** = `is_staff` **or** `UserProfile.role.role_name` in
  `["admin", "адміністратор"]` (see `complaints/permissions.py`).
- Models (16): `Role`, `DormitoryBuilding`, `Place`, `UserProfile`,
  `ComplaintCategory`, `Complaint`, `Worker`, `Ticket`, `Comment`,
  `Notification`, `Announcement`, `InviteToken`, `EmailVerificationCode`,
  `PasswordResetCode`.

## API conventions

- Class-based `APIView`s only — **no ViewSets** — with explicit
  `permission_classes`.
- Public/`AllowAny`: auth endpoints, categories, buildings, places (GET).
  Everything else requires `IsAuthenticated`; admin operations use
  `IsAdminOrCustomAdmin`. User-scoped resources live under `me/*`.
- `ModelSerializer`s with explicit `fields` and **Ukrainian user-facing
  validation messages**; field-level errors → HTTP 400.
- See `.agents/api-conventions.md` for the deeper patterns.

## Workspace conventions

- **Commits:** work on a feature branch (`feature/<name>`) — never commit
  directly to `main`. Conventional Commits (`type(scope): summary`), 1–2 lines,
  only after end-to-end verification. A green `manage.py check` is not
  verification.
- **Full-loop rule:** a persisted field is only "done" when the whole loop
  exists in-app: model field → serializer → API endpoint (read *and* write) →
  a real UI control in `dormwatch-web-app`. Edits via `/admin/` or
  `manage.py shell` are not a valid feature surface — trace the write path.
  Shell/DB use is fine for testing.

## Verification

Authenticated requests against the API are made with a **minted JWT — never
change a user's password**. Passwords are real state; overwriting them is
destructive and unrecoverable.

```bash
.venv/bin/python manage.py shell -c "
from django.contrib.auth.models import User
from rest_framework_simplejwt.tokens import RefreshToken
u = User.objects.get(email='admin@lpnu.ua')   # any existing user
t = RefreshToken.for_user(u)
t['email'] = u.email                            # matches auth_views._get_tokens_for_user
print(str(t.access_token))
"
```

Use the printed token as `Authorization: Bearer <token>` against
`http://127.0.0.1:8000/api/...`. This mirrors exactly what `LoginView` issues
(the `email` claim satisfies `EmailDomainJWTAuthentication`), so it exercises
the same code paths without mutating any account.

If a test genuinely requires a *new* user, `create_user(...)` a throwaway and
delete it afterward. Leave the seeded accounts (`admin@lpnu.ua`,
`user@lpnu.ua`, …) and their passwords untouched.

## Migrations & media

- Migrations are additive and committed, one per logical change (0001–0020).
- Complaint photos go through `complaints/image_utils.py`
  (`process_complaint_photo`): strips EXIF rotation, re-encodes to WebP,
  produces a full + thumbnail pair, enforces a 20 MB upload cap (settings) and
  a 25 MP dimension cap.

## References

- `.agents/api-conventions.md` — deeper stable API patterns
- Root `CLAUDE.md` — workspace-wide conventions
- `README.md` — endpoint inventory
- `DEPLOY.md` — deployment
