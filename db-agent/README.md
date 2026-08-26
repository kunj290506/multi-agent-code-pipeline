# DB Agent

**Owners**: Member A + Member B — Shared

The DB Agent manages all database-related tasks in the pipeline, including generating SQL migration scripts, writing ORM model definitions, and composing optimised queries based on natural-language requirements from the Planner Agent.
It understands the target application's schema and can automatically produce Alembic (Python) or Knex (Node.js) migration files to keep the database in sync with new features.
This agent is jointly maintained and serves as the data layer bridge between the Code-Gen Agent's output and the running target application.
