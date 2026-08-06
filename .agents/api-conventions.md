# API Conventions

Deeper stable patterns for `dormwatch-server`. The entry point is `AGENTS.md`;
this file documents the hows that don't fit there.

## Auth flow

Endpoints (`complaints/urls.py`):

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/auth/login/` | Exchange email+password for tokens (sets refresh cookie) |
| POST | `/api/auth/register/` | Create account + send verification email |
| POST | `/api/auth/refresh/` | Rotate refresh token via cookie |
| POST | `/api/auth/logout/` | Blacklist refresh, clear cookie |
| POST | `/api/auth/verify-email/` | Confirm email-verification code |
| POST | `/api/auth/password-reset/request/` | Send reset code |
| POST | `/api/auth/password-reset/confirm/` | Redeem reset code + new password |
| POST | `/api/auth/password-change/` | Change password while authenticated |

Cookie mechanics: the refresh token is a `refresh_token` httpOnly cookie on
path `/api/auth` (SameSite `Lax`, Secure when `DEBUG` off). Token shape is
produced by `_get_tokens_for_user` in `complaints/auth_views.py` — it returns
`{access: str, refresh: str}` and sets the `email` claim, which
`EmailDomainJWTAuthentication` requires. If you touch the token shape, update
both `_get_tokens_for_user` and the verification snippet in `AGENTS.md`.

## Permissions

`complaints/permissions.py`:

- `IsCustomAdmin` — authenticated and `UserProfile.role.role_name` in
  `["admin", "адміністратор"]` (case-insensitive).
- `IsAdminOrCustomAdmin` — `IsAdminUser` (Django `is_staff`) **or**
  `IsCustomAdmin`. This is the default for admin operations because the system
  also grants admin access via the `Role` profile.
- Prefer plain `IsAdminUser` only where staff-flag semantics are genuinely
  intended (e.g. role toggling itself, `UpdateUserRoleView`).

## Serializers & views

- Every view is an `APIView` subclass with explicit `permission_classes`; no
  ViewSets, no generics. Public list endpoints use `AllowAny`.
- Serializers are `ModelSerializer` with explicit `fields` — never `__all__`.
- **Cross-model invariants go in module-level helpers**, not ad hoc checks
  inside views. The canonical pattern is `_validate_assignable_place` in
  `serializers.py` (shared places and `capacity == 0` rooms are unassignable;
  `exclude_profile_pk` lets a profile re-save without tripping the occupancy
  check). It raises `serializers.ValidationError({'place_id': ...})` → HTTP 400.
- Pass `context={'request': request}` (or the relevant user) into serializers
  that need request/user data.
- Photo uploads are processed inside the serializer's `create`/`update` via
  `process_complaint_photo` (see Media below) — never in the view.
- **All user-facing validation messages are Ukrainian.**

## URLs

- Keep every route under `/api/` (root `urls.py` includes `complaints.urls`).
- `snake_case` path segments; `<int:pk>` / `<int:model_id>` for most ids,
  but some resources use `str` ids (e.g. `admin/users/<str:user_id>/`) —
  follow the existing pattern for the resource you touch.
- Every route has a `name=`. `if settings.DEBUG:` appends the media static
  serve for `/media/`.

## Error shape

DRF defaults; do not invent a custom envelope:

- Field-level validation → HTTP 400 with `{field_name: [message, ...]}`.
- Permission/not-found failures → `{detail: "..."}` with the appropriate
  status (403 / 404 / 401).

## Settings & env

- All configuration is env-driven (`dormwatch/settings.py` reads `os.environ`
  with sane defaults); `.env` stays uncommitted and `.env.example` documents
  every key.
- CORS and CSRF origins are both derived from the same `CORS_ALLOWED_ORIGINS`
  env var (`CSRF_TRUSTED_ORIGINS = CORS_ALLOWED_ORIGINS`), and
  `CORS_ALLOW_CREDENTIALS` is on — keep the two lists in sync when adding an
  origin.

## Media & storage

- `MEDIA_URL = '/media/'`, `MEDIA_ROOT = BASE_DIR / 'media'`; served by Django
  in DEBUG via `static()` in `urls.py`.
- Upload caps: 20 MB (`DATA_UPLOAD_MAX_MEMORY_SIZE` /
  `FILE_UPLOAD_MAX_MEMORY_SIZE`) and 25 MP dimension cap.
- `process_complaint_photo` (in `complaints/image_utils.py`) is the single
  entry point: validates content type, transposes EXIF, re-encodes to WebP,
  and returns a full + thumbnail file pair. Serializers attach both to the
  complaint.
