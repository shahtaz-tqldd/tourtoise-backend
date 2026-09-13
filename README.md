# Tourtoise Core

This is a backend service for a travel discovery and trip-planning platform. The core infrastructure built with Django, runs AI-assisted planning workflows, processes background jobs, and delivers real-time notifications.

## Capabilities

- Account, profile, authentication, credit, and account-lifecycle management
- Structured destination content for attractions, activities, cuisines, tags, and saved destinations
- Multi-destination trip planning with itineraries, budgets, preparation lists, notes, sharing, and lifecycle tracking
- AI-assisted discovery, recommendations, trip planning, and contextual trip conversations
- Hybrid destination retrieval using PostgreSQL full-text search and pgvector semantic search
- Travel journals with comments, reactions, saved posts, visibility controls, reporting, and moderation
- Persistent notifications delivered through REST and authenticated WebSockets
- Scheduled and asynchronous processing for email, data indexing, trip events, and account maintenance
- Separate client and admin API surfaces, including operational analytics and AI-usage tracking

## Architecture

```text
Client / Admin applications
          |
          +-- HTTP --------> Django REST API (WSGI)
          |
          +-- WebSocket ---> Django Channels (ASGI)
                                  |
       +--------------------------+--------------------------+
       |                          |                          |
 PostgreSQL                 Redis / Celery              External services
 application data          jobs, schedules,             AI, email, media,
 + ADK sessions            channel layer                optional Firebase
       |
 PostgreSQL + pgvector
 search and embeddings
```

The codebase is split into domain-oriented Django apps:

| Module | Responsibility |
| --- | --- |
| `accounts` | Users, profiles, JWT authentication, credits, and account lifecycle |
| `destinations` | Destination knowledge and catalog management |
| `trips` | Planning sessions, itineraries, preparation, notes, sharing, and trip chat |
| `chat` | General AI discovery conversations |
| `journals` | Community travel content and moderation |
| `notification` | Persistent and real-time notifications |
| `vector_store` | Full-text and vector search documents in a dedicated database |
| `analytics` | Administrative and AI-usage metrics |
| `app` | Project settings, routing, shared infrastructure, and base abstractions |

## Technology Stack

| Area | Technology |
| --- | --- |
| Language/runtime | Python 3.12 |
| Web framework | Django 5.1, Django REST Framework 3.15 |
| Authentication | Simple JWT; optional Firebase ID-token verification |
| Real-time transport | Django Channels, Uvicorn, Channels Redis |
| Primary datastore | PostgreSQL 16 |
| Search datastore | PostgreSQL 16 with pgvector, GIN full-text search, and HNSW vector indexes |
| Background processing | Celery 5.4, Celery Beat, Redis 7 |
| AI orchestration | Google Agent Development Kit (ADK), Gemini/Vertex AI |
| Media | Cloudinary and Pillow |
| Email | Django SMTP backend |
| Production serving | Gunicorn for WSGI and Uvicorn for ASGI |
| Packaging/deployment | pip, Docker, Docker Compose, GitHub Actions |

## Requirements

The recommended development path uses Docker and requires:

- Git
- Docker Engine with the Docker Compose plugin
- Google Cloud, SMTP, Cloudinary, or Firebase credentials only when developing the corresponding integration

For a native installation, use Python 3.12, PostgreSQL 16 with the pgvector extension available, and Redis 7.

## Quick Start with Docker

1. Clone the repository and enter it:

   ```bash
   git clone <repository-url>
   cd tourtoise-core
   ```

2. Create the local environment file:

   ```bash
   cp .env.example .env
   ```

3. Review `.env`. The example database and Redis values work with the development Compose stack because container-specific hostnames are injected by Compose.

4. If the checkout does not contain a local Google service-account file, create a placeholder for the development bind mount. Replace it with a real credential file only when Google Cloud features are needed:

   ```bash
   mkdir -p secrets
   touch secrets/service-account.json
   ```

5. Start the complete development stack:

   ```bash
   ./startapp.sh
   ```

The script selects the development or production Compose definition from `APP_ENV`. In development it builds and starts PostgreSQL, Redis, the WSGI API, the ASGI server, a Celery worker, and Celery Beat. Database creation and migrations are handled during container startup.

### Development Services

| Service | Default host address | Purpose |
| --- | --- | --- |
| WSGI API | `http://localhost:8000` | REST APIs and Django admin |
| ASGI server | `http://localhost:8001` | ASGI HTTP and WebSockets |
| Django admin | `http://localhost:8000/admin/` | Built-in administration UI |
| PostgreSQL | `localhost:5433` | Host access to container PostgreSQL |
| Redis | `localhost:6380` | Host access to container Redis |

The REST namespaces are `/api/v1/` for client operations and `/api/v1/admin/` for administrative operations. The notification socket is served at `/ws/notifications/` through the ASGI port.

Useful lifecycle commands:

```bash
# Start only selected services
./startapp.sh wsgi asgi

# View logs
docker compose -p tourtoise -f docker/compose.dev.yml logs -f

# Stop the stack
docker compose -p tourtoise -f docker/compose.dev.yml down
```

## Configuration

Configuration is loaded from the project-root `.env` file. Keep secrets out of version control; `.env*` and `secrets/` are ignored except for `.env.example`.

### Application and Security

| Variable | Purpose | Development default/example |
| --- | --- | --- |
| `APP_ENV` | Selects `dev` or `prod` runtime behavior | `dev` |
| `APP_SECRET` | Django secret key; use a strong unique value outside development | insecure local value |
| `DEBUG` | Enables Django debug behavior | `True` |
| `ALLOWED_HOSTS` | Comma-separated accepted hosts | `127.0.0.1,localhost` |
| `CSRF_TRUSTED_ORIGINS` | Comma-separated trusted origins | local API origins |
| `CORS_ALLOWED_ORIGINS` | Comma-separated frontend origins | local frontend origins |
| `TIME_ZONE` | Django application time zone | `Asia/Dhaka` |
| `LOG_LEVEL` | Application log level | `INFO` |

### Data and Runtime Services

| Variable group | Purpose |
| --- | --- |
| `DB_*` or `DATABASE_URL` | Primary Django PostgreSQL connection |
| `VECTOR_DB_*` or `VECTOR_DB_URL` | Dedicated pgvector database connection |
| `ADK_DB_URL` | Async SQLAlchemy connection used for AI agent sessions |
| `CELERY_BROKER_URL` | Celery broker connection |
| `CELERY_RESULT_BACKEND` | Celery result storage |
| `CHANNEL_REDIS_URL` | Optional dedicated Redis URL for the Channels layer |

The Docker stack provisions three PostgreSQL databases: the primary application database, `tourtoise_vector_db` for vector documents, and `adk_session_db` for agent sessions. The `VectorStoreRouter` keeps `vector_store` models on the vector database.

### Optional Integrations

| Variable group | Enables |
| --- | --- |
| `GOOGLE_*`, `PLANNING_AGENT_*` | Google ADK, Gemini planning, and embeddings |
| `GEMINI_EMBEDDING_*` | Embedding model, dimensions, and request pacing |
| `EMAIL_*`, `DEFAULT_FROM_EMAIL` | Transactional email through SMTP |
| `CLOUDINARY_*` | Remote image storage |
| `FIREBASE_*` | Firebase ID-token verification |
| `USER_FRONTEND_URL`, `ADMIN_FRONTEND_URL` | Links generated for frontend workflows |
| `SUPERUSER_*` | Optional initial superuser created during container startup |

For Google Application Default Credentials in Docker, set `GOOGLE_APPLICATION_CREDENTIALS=/app/secrets/service-account.json` and place the credential at `secrets/service-account.json`. Do not commit credential files.

### Port Overrides

Docker host ports can be changed in `.env` without editing Compose files:

```dotenv
WSGI_PORT=8000
ASGI_PORT=8001
POSTGRES_FORWARD_PORT=5433
REDIS_FORWARD_PORT=6380
```

## Native Development

Docker is preferred because it creates all required databases consistently. To run natively:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Create the primary, vector, and ADK session PostgreSQL databases, ensure the pgvector extension is available to the vector database user, then update `.env` for host-based connections. A typical local configuration includes:

```dotenv
DB_HOST=localhost
DB_PORT=5432
VECTOR_DB_HOST=localhost
VECTOR_DB_PORT=5432
ADK_DB_URL=postgresql+asyncpg://<user>:<password>@localhost:5432/adk_session_db
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
```

Apply both database migration sets:

```bash
python manage.py migrate
python manage.py migrate --database=vector
```

Run the required processes in separate terminals:

```bash
python manage.py runserver 0.0.0.0:8000
uvicorn app.asgi:application --host 0.0.0.0 --port 8001 --reload
celery -A app worker -l info
celery -A app beat -l info
```

Create a development administrator when needed:

```bash
python manage.py createsuperuser
```

## Validation and Tests

Run Django's configuration checks and test suite inside the running WSGI container:

```bash
docker compose -p tourtoise -f docker/compose.dev.yml exec wsgi python manage.py check
docker compose -p tourtoise -f docker/compose.dev.yml exec wsgi python manage.py test
```

For a native environment, run the same commands directly:

```bash
python manage.py check
python manage.py test
```
