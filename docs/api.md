# API Documentation

Base URL: `/api/v1`

## Authentication

All endpoints except `/auth/*` require a Bearer token.

### Register
```
POST /auth/register
```
```json
{
  "email": "user@example.com",
  "username": "user",
  "password": "StrongPass123",
  "full_name": "User"
}
```

### Login
```
POST /auth/login
```
```json
{"email": "user@example.com", "password": "StrongPass123"}
```
Returns:
```json
{
  "access_token": "...",
  "refresh_token": "...",
  "token_type": "bearer",
  "expires_in": 1800
}
```

### Refresh Token
```
POST /auth/refresh
```
```json
{"refresh_token": "..."}
```

### OAuth
```
GET  /auth/oauth/{provider}/login
GET  /auth/oauth/{provider}/callback
```

### Forgot / Reset Password
```
POST /auth/forgot-password
POST /auth/reset-password
```

## Users

### Get Profile
```
GET /users/me
```

### Update Profile
```
PATCH /users/me
```

### Get Settings
```
GET /users/me/settings
```

### Update Settings
```
PATCH /users/me/settings
```

## Threads

### Create Thread
```
POST /threads
```

### List Threads
```
GET /threads?page=1&page_size=20&search=query
```

### Get Thread
```
GET /threads/{id}
```

### Update Thread
```
PATCH /threads/{id}
```

### Delete Thread
```
DELETE /threads/{id}
```

## Messages

### List Messages
```
GET /threads/{id}/messages
```

## Chat

### Send Message (Streaming)
```
POST /chat/stream
```
SSE events:
```
data: {"type": "token", "content": "Hello"}
data: {"type": "done", "content": "..."}
```

### Send Message (Non-streaming)
```
POST /chat
```

### Stop Generation
```
POST /chat/stop
```

## Models

### List Available Models
```
GET /models
```
Returns available models with provider, capabilities, and fallback chain.

## Memory

### List Memories
```
GET /memories
```

### Create Memory
```
POST /memories
```

### Delete Memory
```
DELETE /memories/{id}
```

## Files

### Upload File
```
POST /files/upload
```
Multipart form data with `file` field.

### List Files
```
GET /files
```

### Get Document
```
GET /files/documents/{id}
```

## Error Format

All errors follow a consistent structure:
```json
{
  "success": false,
  "error": {
    "code": "error_code",
    "message": "Human readable message",
    "details": {}
  }
}
```

## Rate Limits

- Standard requests: 60 per minute
- Streaming requests: 30 per minute
- Rate limit headers: `X-RateLimit-Limit`, `X-RateLimit-Remaining`
