# Database Schema

## Overview

The application uses PostgreSQL 16 with SQLAlchemy 2.0 async ORM and Alembic migrations.

## Entity Relationship Diagram

```
┌─────────┐     ┌─────────┐     ┌──────────┐
│  users  │────<│ threads │────<│ messages │
└─────────┘     └─────────┘     └──────────┘
    │                               │
    │                               │
    ▼                               ▼
┌─────────┐                    ┌──────────┐
│ memory  │                    │ feedback │
└─────────┘                    └──────────┘
    │
    ▼
┌───────────┐     ┌────────────┐
│ documents │────<│ embeddings │
└───────────┘     └────────────┘

┌──────────┐  ┌──────┐
│ settings │  │ logs │
└──────────┘  └──────┘
    │
    ▼
┌───────┐
│ files │
└───────┘
```

## Tables

### users
| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| email | VARCHAR(255) | Unique, indexed |
| username | VARCHAR(100) | Unique, indexed |
| full_name | VARCHAR(255) | |
| hashed_password | VARCHAR(255) | bcrypt hash |
| avatar_url | VARCHAR(500) | |
| role | ENUM | user/admin/moderator |
| provider | ENUM | local/google/github |
| provider_id | VARCHAR(255) | OAuth provider id |
| is_active | BOOLEAN | |
| is_verified | BOOLEAN | |
| last_login_at | TIMESTAMP | |
| preferences | JSON | |
| created_at | TIMESTAMP | |
| updated_at | TIMESTAMP | |

### threads
| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| user_id | UUID | FK → users.id |
| title | VARCHAR(255) | |
| status | ENUM | active/archived/pinned |
| pinned | BOOLEAN | |
| metadata | JSON | |
| last_message_at | TIMESTAMP | |
| model | VARCHAR(255) | Last used model |
| created_at | TIMESTAMP | |
| updated_at | TIMESTAMP | |

Indexes: `(user_id)`, `(user_id, status)`, `(user_id, updated_at)`

### messages
| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| thread_id | UUID | FK → threads.id |
| role | ENUM | user/assistant/system/tool |
| content | TEXT | |
| attachments | JSON | |
| images | JSON | |
| tokens | INTEGER | Token count |
| latency_ms | INTEGER | |
| cost | FLOAT | |
| model | VARCHAR(255) | |
| metadata | JSON | |
| created_at | TIMESTAMP | |
| updated_at | TIMESTAMP | |

Indexes: `(thread_id)`, `(thread_id, role)`, `(thread_id, created_at)`

### memory
| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| user_id | UUID | FK → users.id |
| thread_id | UUID | FK → threads.id (nullable) |
| memory_type | ENUM | short_term/long_term/conversation/summarization/entity/semantic/user_preference/thread |
| content | TEXT | |
| key | VARCHAR(255) | |
| importance | FLOAT | 0-1 |
| metadata | JSON | |
| expires_at | TIMESTAMP | For short-term memory |
| created_at | TIMESTAMP | |
| updated_at | TIMESTAMP | |

Indexes: `(user_id)`, `(thread_id)`, `(user_id, memory_type)`, `(user_id, key)`

### documents
| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| user_id | UUID | FK → users.id |
| filename | VARCHAR(500) | |
| file_path | VARCHAR(1000) | |
| file_type | VARCHAR(50) | |
| file_size | INTEGER | |
| status | ENUM | pending/processing/ready/failed |
| content | TEXT | Extracted text |
| metadata | JSON | |
| chunk_count | INTEGER | |
| created_at | TIMESTAMP | |
| updated_at | TIMESTAMP | |

### embeddings
| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| document_id | UUID | FK → documents.id |
| chunk_index | INTEGER | |
| content | TEXT | |
| vector | JSON | Embedding vector |
| metadata | JSON | |
| created_at | TIMESTAMP | |

Unique constraint: `(document_id, chunk_index)`

### feedback
| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| message_id | UUID | FK → messages.id |
| user_id | UUID | FK → users.id |
| feedback_type | ENUM | thumbs_up/thumbs_down |
| comment | TEXT | |
| created_at | TIMESTAMP | |

### settings
| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| user_id | UUID | FK → users.id |
| key | VARCHAR(100) | |
| value | JSON | |
| created_at | TIMESTAMP | |

Unique constraint: `(user_id, key)`

### logs
| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| user_id | UUID | FK → users.id (nullable) |
| level | VARCHAR(20) | |
| message | TEXT | |
| path | VARCHAR(500) | |
| method | VARCHAR(10) | |
| status_code | INTEGER | |
| duration_ms | INTEGER | |
| request_id | VARCHAR(64) | |
| metadata | JSON | |
| created_at | TIMESTAMP | |

### files
| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| user_id | UUID | FK → users.id |
| filename | VARCHAR(500) | |
| stored_path | VARCHAR(1000) | |
| content_type | VARCHAR(100) | |
| size | INTEGER | |
| category | VARCHAR(50) | document/image/audio/video |
| metadata | JSON | |
| created_at | TIMESTAMP | |

## Migrations

Migrations are managed with Alembic:

```bash
# Create migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Rollback
alembic downgrade -1
```
