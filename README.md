# dormwatch-server

REST API server for DormWatch — a dormitory issue tracking system. Built with Django, Django REST Framework, and PostgreSQL.

## Getting Started

### Prerequisites

- Python 3.11+
- PostgreSQL

### Setup

1.  **Create and activate a virtual environment:**

    ```sh
    python -m venv .venv
    source .venv/bin/activate  # Linux/macOS
    # or
    .venv\Scripts\activate  # Windows
    ```

2.  **Install dependencies:**

    ```sh
    pip install -r requirements.txt
    # or, with uv:
    uv pip install -r requirements.txt
    ```

3.  **Configure environment variables** — copy `.env.example` to `.env` and fill in your values:

    ```sh
    cp .env.example .env
    ```

4.  **Run database migrations:**

    ```sh
    python manage.py migrate
    ```

5.  **Start the development server:**

    ```sh
    python manage.py runserver
    ```

    The API will be available at `http://localhost:8000/api/`.

### Docker

```sh
docker build -t dormwatch-server .
docker run -p 8000:80 --env-file .env dormwatch-server
```

### API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/complaints/` | Board feed (admin: all; others: anonymized building feed) |
| GET | `/api/complaints/<id>/` | Complaint detail (role-scoped serializer) |
| GET/POST | `/api/me/complaints/` | Current user's complaints / create one |
| GET/PATCH/DELETE | `/api/me/complaints/<id>/` | Own complaint detail (edit/delete only while pending) |
| POST | `/api/me/complaints/<id>/accept/` | Owner accepts completed work (→ Вирішено) |
| POST | `/api/me/complaints/<id>/reject/` | Owner rejects with `rework_reason` (→ Не прийнято) |
| POST | `/api/me/complaints/<id>/withdraw/` | Owner withdraws while pending (→ Скасовано) |
| POST | `/api/complaints/<id>/refile/` | Re-file a closed complaint (≤1 open follow-up) |
| GET | `/api/worker/complaints/` | Assigned job list for the signed-in worker |
| PATCH | `/api/worker/complaints/<id>/` | Worker stamps (start/finish + undos, note) |
| GET/POST | `/api/complaints/<id>/comments/` | Comments on a complaint |
| DELETE | `/api/comments/<id>/` | Delete a comment |
| GET/PATCH/DELETE | `/api/admin/complaints/<id>/` | Admin: full record / assignment+transitions / delete-or-archive |
| PATCH | `/api/admin/users/<id>/set-admin/` | Toggle admin status |
| GET/PATCH/DELETE | `/api/profile/` | User profile |
| PATCH | `/api/profile/change-room/` | Update user's room |