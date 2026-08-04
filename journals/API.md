# Travel Journal API

Base path: `/api/v1/journals/`

Authenticated endpoints require:

```http
Authorization: Bearer <access_token>
```

UUID path parameters must be valid UUID strings. Dates in responses are ISO 8601 timestamps.

## Shared query parameters

All list endpoints support:

| Parameter | Type | Required | Description |
|---|---|---:|---|
| `page` | integer | No | Page number. Default: `1`. |
| `page_size` | integer | No | Items per page. Default: `20`, maximum: `100`. |

## Shared response schemas

### Journal

```json
{
  "id": "a6d0b466-d74d-4aa2-831e-cc6f434d750b",
  "author": {
    "id": "1bccac4e-34ee-4618-b07b-82e2b94582db",
    "name": "Traveler Name",
    "username": "traveler",
    "avatar_url": "https://example.com/avatar.jpg"
  },
  "content": "My travel journal content.",
  "visibility": "public",
  "tags": ["Beach", "Food"],
  "images": [
    {
      "id": "8491fdb9-8a30-447a-9a40-b2ec8eb06893",
      "image_url": "https://example.com/bali.jpg",
      "caption": "",
      "sort_order": 0
    }
  ],
  "comments_count": 3,
  "saves_count": 5,
  "reactions_count": 8,
  "is_saved": true,
  "is_reacted": true,
  "created_at": "2026-06-21T10:00:00Z",
  "updated_at": "2026-06-21T10:00:00Z"
}
```

`is_saved` and `is_reacted` are always `false` for anonymous requests. Private journals are only visible to their author.

### Comment or reply

```json
{
  "id": "b33192e0-e0f1-44ae-b29c-d4c9b940fda6",
  "author": {
    "id": "1bccac4e-34ee-4618-b07b-82e2b94582db",
    "name": "Traveler Name",
    "username": "traveler",
    "avatar_url": "https://example.com/avatar.jpg"
  },
  "parent": null,
  "text": "Great journal!",
  "image_url": "",
  "replies_count": 2,
  "created_at": "2026-06-21T10:05:00Z",
  "updated_at": "2026-06-21T10:05:00Z"
}
```

For a reply, `parent` contains the parent comment UUID and `replies_count` is `0`.

### Paginated success

```json
{
  "status": 200,
  "success": true,
  "message": "Journals fetched successfully.",
  "meta": {
    "count": 24,
    "page": 1,
    "page_size": 20,
    "num_pages": 2,
    "next": "http://localhost:8000/api/v1/journals/list/?page=2",
    "previous": null
  },
  "data": []
}
```

`data` contains journal objects for journal lists and comment objects for comment/reply lists.

## Journal endpoints

### List public journals

```http
GET /api/v1/journals/list/
```

Authentication: optional.

| Query parameter | Type | Required | Description |
|---|---|---:|---|
| `page` | integer | No | Page number. |
| `page_size` | integer | No | Items per page. |
| `search` | string | No | Case-insensitive content or tag search. |
| `tags` | string | No | Comma-separated exact tag names, for example `Beach,Food`. Matches any supplied tag. |

Response: `200 OK`, paginated journals. Only public journals are returned.

### List a user's journals

```http
GET /api/v1/journals/users/{user_id}/list/
```

Authentication: optional. Query parameters: `page`, `page_size`.

Response: `200 OK`, paginated journals. Other users and anonymous callers see public journals only. The matching authenticated owner sees both public and private journals.

### List my journals

```http
GET /api/v1/journals/mine/list/
```

Authentication: required. Query parameters: `page`, `page_size`.

Response: `200 OK`, paginated public and private journals owned by the authenticated user.

### List saved journals

```http
GET /api/v1/journals/saved/list/
```

Authentication: required. Query parameters: `page`, `page_size`.

Response: `200 OK`, paginated accessible journals saved by the authenticated user, newest save first.

### Get journal detail

```http
GET /api/v1/journals/{journal_id}/detail/
```

Authentication: optional.

Response:

```json
{
  "status": 200,
  "success": true,
  "message": "Journal fetched successfully.",
  "data": { "id": "a6d0b466-d74d-4aa2-831e-cc6f434d750b" }
}
```

`data` uses the complete Journal schema. A private journal returns `404` unless requested by its author.

### Create journal

```http
POST /api/v1/journals/create/
Content-Type: application/json
```

Authentication: required.

| Body field | Type | Required | Description |
|---|---|---:|---|
| `content` | string | Yes | Journal text. |
| `visibility` | `public` or `private` | No | Default: `public`. |
| `tags` | string array | No | Tag names, each at most 50 characters. Duplicates are removed case-insensitively. |
| `image_urls` | URL array | No | Existing hosted image URLs. |
| `images` | image file array | No | Files uploaded to Cloudinary. Use `multipart/form-data`. |

JSON example:

```json
{
  "content": "My travel journal content.",
  "visibility": "public",
  "tags": ["Beach", "Food"],
  "image_urls": ["https://example.com/bali.jpg"]
}
```

For file uploads, send `content` and optional `visibility` as multipart fields and repeat the `images` field for each file.

Response: `201 Created` using the standard success envelope with a complete Journal object and message `Journal created successfully.`

### Update journal

```http
PATCH /api/v1/journals/{journal_id}/update/
PUT /api/v1/journals/{journal_id}/update/
```

Authentication: required; journal author only. Use `PATCH` for partial updates. `PUT` requires `content`.

| Body field | Type | Required for PATCH | Description |
|---|---|---:|---|
| `content` | string | No | Updated content. |
| `visibility` | `public` or `private` | No | Updated visibility. |
| `tags` | string array | No | Replaces all tags. Send `[]` to clear them. Omit to preserve them. |
| `image_urls` | URL array | No | Appends hosted images. |
| `images` | image file array | No | Uploads and appends image files. |
| `remove_image_ids` | UUID array | No | Removes the journal images with these IDs. |

```json
{
  "visibility": "private",
  "tags": ["Solo Travel"],
  "image_urls": ["https://example.com/new-image.jpg"],
  "remove_image_ids": ["8491fdb9-8a30-447a-9a40-b2ec8eb06893"]
}
```

Response: `200 OK` with a complete Journal object and message `Journal updated successfully.`

### Delete journal

```http
DELETE /api/v1/journals/{journal_id}/delete/
```

Authentication: required; journal author only. No body.

```json
{
  "status": 200,
  "success": true,
  "message": "Journal deleted successfully."
}
```

Deleting a journal also deletes its image records, comments, replies, saves, and reactions.

## Save endpoints

### Save journal

```http
POST /api/v1/journals/{journal_id}/save/
```

Authentication: required. No body. The operation is idempotent.

```json
{
  "status": 200,
  "success": true,
  "message": "Journal saved successfully.",
  "data": {
    "journal_id": "a6d0b466-d74d-4aa2-831e-cc6f434d750b",
    "saved": true
  }
}
```

### Remove saved journal

```http
DELETE /api/v1/journals/{journal_id}/save/
```

Authentication: required. No body. The operation is idempotent.

```json
{
  "status": 200,
  "success": true,
  "message": "Journal removed from saved list successfully.",
  "data": {
    "journal_id": "a6d0b466-d74d-4aa2-831e-cc6f434d750b",
    "saved": false
  }
}
```

## Reaction endpoints

Journal reactions are simple heart reactions. Each authenticated user can react once to an accessible journal.

### React to journal

```http
POST /api/v1/journals/{journal_id}/react/
```

Authentication: required. No body. The operation is idempotent.

```json
{
  "status": 200,
  "success": true,
  "message": "Journal reacted successfully.",
  "data": {
    "journal_id": "a6d0b466-d74d-4aa2-831e-cc6f434d750b",
    "reacted": true,
    "reactions_count": 8
  }
}
```

### Remove journal reaction

```http
DELETE /api/v1/journals/{journal_id}/react/
```

Authentication: required. No body. The operation is idempotent.

```json
{
  "status": 200,
  "success": true,
  "message": "Journal reaction removed successfully.",
  "data": {
    "journal_id": "a6d0b466-d74d-4aa2-831e-cc6f434d750b",
    "reacted": false,
    "reactions_count": 7
  }
}
```

## Comment and reply endpoints

### List journal comments

```http
GET /api/v1/journals/{journal_id}/comments/
```

Authentication: optional. Query parameters: `page`, `page_size`.

Response: `200 OK`, paginated root comments in oldest-first order. Replies are retrieved separately.

### Create journal comment

```http
POST /api/v1/journals/{journal_id}/comments/
```

Authentication: required.

| Body field | Type | Required | Description |
|---|---|---:|---|
| `text` | string | Conditional | Comment text. |
| `image_url` | URL | Conditional | Existing hosted image URL. |
| `image` | image file | Conditional | Image uploaded to Cloudinary using `multipart/form-data`. |

At least one of `text`, `image_url`, or `image` is required. Do not send both `image_url` and `image`.

```json
{
  "text": "Great journal!",
  "image_url": "https://example.com/comment.jpg"
}
```

Response: `201 Created` with a Comment object and message `Comment created successfully.`

### List replies

```http
GET /api/v1/journals/{journal_id}/comments/{comment_id}/replies/
```

Authentication: optional. Query parameters: `page`, `page_size`. `comment_id` must identify a root comment belonging to the journal.

Response: `200 OK`, paginated replies in oldest-first order.

### Create reply

```http
POST /api/v1/journals/{journal_id}/comments/{comment_id}/replies/
```

Authentication: required. Body fields and validation are identical to Create journal comment. Replies cannot contain nested replies.

Response: `201 Created` with a Comment object whose `parent` is the root comment UUID, and message `Reply created successfully.`

### Update comment or reply

```http
PATCH /api/v1/journals/comments/{comment_id}/update/
PUT /api/v1/journals/comments/{comment_id}/update/
```

Authentication: required; comment/reply author only. Body fields and validation are identical to Create journal comment. Use `PATCH` for normal edits; `PUT` is also accepted with the same validation.

```json
{
  "text": "Updated comment text",
  "image_url": "https://example.com/updated-comment.jpg"
}
```

Response: `200 OK` with a Comment object and message `Comment updated successfully.`

### Delete comment or reply

```http
DELETE /api/v1/journals/comments/{comment_id}/delete/
```

Authentication: required; comment/reply author only. No body.

```json
{
  "status": 200,
  "success": true,
  "message": "Comment deleted successfully."
}
```

Deleting a root comment also deletes all of its replies.

## Error responses

Validation errors use Django REST Framework's field-error format:

```json
{
  "content": ["This field is required."]
}
```

```json
{
  "non_field_errors": ["A comment must contain text or an image."]
}
```

Authentication error (`401 Unauthorized`):

```json
{
  "detail": "Authentication credentials were not provided."
}
```

Missing, inaccessible private, or non-owned resource (`404 Not Found`):

```json
{
  "detail": "No Journal matches the given query."
}
```
