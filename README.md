# dormwatch-server

REST API server for DormWatch — a dormitory issue tracking system. Built with Django, Django REST Framework, and PostgreSQL.

## Getting Started

### Prerequisites

- Python 3.11+
- PostgreSQL
- GDAL (geospatial library)
  - **Windows (Python 3.12):** `pip install GDAL-3.10.1-cp312-cp312-win_amd64.whl` (bundled in repo)
  - **Other platforms:** Download from [geospatial-wheels](https://github.com/cgohlke/geospatial-wheels/releases)

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
| GET/POST | `/api/complaints/` | List/create complaints (admin) |
| GET/PUT/DELETE | `/api/complaints/<id>/` | Complaint detail (admin) |
| GET/POST | `/api/me/complaints/` | Current user's complaints |
| GET/PUT/DELETE | `/api/me/complaints/<id>/` | User's complaint detail |
| PATCH | `/api/complaints/<id>/counter/` | Upvote a complaint |
| GET/POST | `/api/complaints/<id>/comments/` | Comments on a complaint |
| DELETE | `/api/comments/<id>/` | Delete a comment |
| PATCH | `/api/admin/complaints/<id>/status/` | Change complaint status (admin) |
| PATCH | `/api/admin/users/<id>/set-admin/` | Toggle admin status |
| GET/PATCH/DELETE | `/api/profile/` | User profile |
| PATCH | `/api/profile/change-room/` | Update user's room |