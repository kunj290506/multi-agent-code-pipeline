# Target Application -- Task Manager

## Purpose

A sample REST API for managing users, tasks, comments, and projects, built with
Python FastAPI and a local SQLite database. This application serves as the
reference codebase that the RAG agent indexes and that the Code-Gen agent
generates additions for.

---

## API Endpoints

| Method | Path                       | Description                              |
|--------|----------------------------|------------------------------------------|
| GET    | `/health`                  | Health check                             |
| GET    | `/users`                   | List all users                           |
| GET    | `/users/{id}`              | Get a user by ID                         |
| POST   | `/users`                   | Create a new user                        |
| GET    | `/tasks`                   | List tasks (filterable by status/priority) |
| GET    | `/tasks/{id}`              | Get a task by ID                         |
| POST   | `/tasks`                   | Create a new task                        |
| PUT    | `/tasks/{id}`              | Update an existing task                  |
| DELETE | `/tasks/{id}`              | Delete a task                            |
| GET    | `/tasks/{id}/comments`     | List comments on a task                  |
| POST   | `/comments`                | Create a comment                         |
| GET    | `/projects`                | List all projects (filterable by status) |
| GET    | `/projects/{id}`           | Get a project by ID                      |
| POST   | `/projects`                | Create a new project                     |
| PUT    | `/projects/{id}`           | Update an existing project               |

---

## Database Schema

Four tables: `users`, `projects`, `tasks`, and `comments`. The schema is
initialized automatically on startup, along with seed data (5 users, 5 tasks,
2 projects, 3 comments).

### `users`

| Column       | Type      | Notes                                    |
|--------------|-----------|------------------------------------------|
| `id`         | INTEGER   | Primary key, auto-increment              |
| `username`   | TEXT      | Unique, not null                         |
| `email`      | TEXT      | Unique, not null                         |
| `role`       | TEXT      | `admin` / `member` / `viewer` (default `member`) |
| `created_at` | TIMESTAMP | Default `CURRENT_TIMESTAMP`              |

### `projects`

| Column        | Type      | Notes                                    |
|---------------|-----------|------------------------------------------|
| `id`          | INTEGER   | Primary key, auto-increment              |
| `name`        | TEXT      | Unique, not null                         |
| `description` | TEXT      | Default `''`                             |
| `owner_id`    | INTEGER   | FK → `users(id)` ON DELETE SET NULL      |
| `status`      | TEXT      | `active` / `archived` (default `active`) |
| `created_at`  | TIMESTAMP | Default `CURRENT_TIMESTAMP`              |

### `tasks`

| Column        | Type      | Notes                                                      |
|---------------|-----------|------------------------------------------------------------|
| `id`          | INTEGER   | Primary key, auto-increment                                |
| `title`       | TEXT      | Not null                                                   |
| `description` | TEXT      | Default `''`                                               |
| `status`      | TEXT      | `pending` / `in_progress` / `completed` / `cancelled`     |
| `assigned_to` | INTEGER   | FK → `users(id)` ON DELETE SET NULL                        |
| `priority`    | TEXT      | `low` / `medium` / `high` / `critical` (default `medium`)  |
| `project_id`  | INTEGER   | FK → `projects(id)` ON DELETE SET NULL                     |
| `created_at`  | TIMESTAMP | Default `CURRENT_TIMESTAMP`                                |
| `updated_at`  | TIMESTAMP | Default `CURRENT_TIMESTAMP`                                |

### `comments`

| Column       | Type      | Notes                                    |
|--------------|-----------|------------------------------------------|
| `id`         | INTEGER   | Primary key, auto-increment              |
| `task_id`    | INTEGER   | FK → `tasks(id)` ON DELETE CASCADE       |
| `user_id`    | INTEGER   | FK → `users(id)` ON DELETE CASCADE       |
| `content`    | TEXT      | Not null                                 |
| `created_at` | TIMESTAMP | Default `CURRENT_TIMESTAMP`              |

---

## Setup

```bash
cd target-app
pip install -r requirements.txt
python app.py
# Server starts at http://localhost:8000
```

Interactive API docs are available at `http://localhost:8000/docs`.

---

## Configuration

| Variable           | Default            | Description             |
|--------------------|--------------------|-------------------------|
| `TARGET_APP_DB`    | `./taskmanager.db` | SQLite database path    |
| `TARGET_APP_HOST`  | `0.0.0.0`          | API bind address        |
| `TARGET_APP_PORT`  | `8000`             | API port                |
