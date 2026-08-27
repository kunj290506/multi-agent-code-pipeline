# Task Manager Application

## Overview

The Task Manager is a REST API built with Python FastAPI. It allows users to
create accounts, manage tasks, and assign tasks to team members.

## Database Schema

### Users Table
| Column     | Type      | Constraints                    |
|------------|-----------|--------------------------------|
| id         | INTEGER   | PRIMARY KEY AUTOINCREMENT      |
| username   | TEXT      | NOT NULL, UNIQUE               |
| email      | TEXT      | NOT NULL, UNIQUE               |
| role       | TEXT      | DEFAULT 'member'               |
| created_at | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP      |

### Tasks Table
| Column      | Type      | Constraints                   |
|-------------|-----------|-------------------------------|
| id          | INTEGER   | PRIMARY KEY AUTOINCREMENT     |
| title       | TEXT      | NOT NULL                      |
| description | TEXT      | DEFAULT ''                    |
| status      | TEXT      | DEFAULT 'pending'             |
| assigned_to | INTEGER   | FOREIGN KEY -> users(id)      |
| priority    | TEXT      | DEFAULT 'medium'              |
| created_at  | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP     |

## API Endpoints

- `GET /users` -- List all users.
- `POST /users` -- Create a new user. Body: `{ "username": "...", "email": "...", "role": "..." }`.
- `GET /tasks` -- List all tasks.
- `POST /tasks` -- Create a new task. Body: `{ "title": "...", "description": "...", "priority": "..." }`.
- `GET /tasks/{task_id}` -- Retrieve a single task by its ID.

## Authentication

Authentication is not yet implemented. All endpoints are currently public.

## Configuration

The application uses a local SQLite database stored at `taskmanager.db`.
No external database server is required.
