# Healthcare Image Analysis API Documentation

## Authentication

### OAuth2 Authentication

The API uses OAuth2 with JWT tokens for authentication.

#### Get Access Token

```
POST /api/token
```

**Request:**
- Form data:
  - `username`: User's username
  - `password`: User's password

**Response:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 86400,
  "user_id": "demo",
  "name": "Demo User",
  "role": "healthcare_professional"
}
```

### API Key Authentication

Some endpoints require an API key for authentication.

**Headers:**
```
X-API-Key: your-api-key
```

## Job Management

### Create Job

```
POST /api/jobs
```

**Headers:**
```
Authorization: Bearer {access_token}
```

**Request:**
```json
{
  "user_id": "demo",
  "image_key": "uploads/demo/image.jpg"
}
```

**Response:**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "user_id": "demo",
  "original_image_key": "uploads/demo/image.jpg",
  "status": "UPLOADED",
  "created_at": "2025-07-21T14:30:00Z",
  "updated_at": "2025-07-21T14:30:00Z",
  "error_message": null
}
```

### Get Jobs

```
GET /api/jobs
```

**Headers:**
```
Authorization: Bearer {access_token}
```

**Query Parameters:**
- `user_id` (optional): Filter by user ID
- `status` (optional): Filter by status
- `limit` (optional): Maximum number of jobs to return (default: 100)
- `offset` (optional): Number of jobs to skip (default: 0)

**Response:**
```json
[
  {
    "job_id": "550e8400-e29b-41d4-a716-446655440000",
    "user_id": "demo",
    "original_image_key": "uploads/demo/image.jpg",
    "status": "SEGMENTING",
    "created_at": "2025-07-21T14:30:00Z",
    "updated_at": "2025-07-21T14:30:05Z",
    "error_message": null
  },
  {
    "job_id": "550e8400-e29b-41d4-a716-446655440001",
    "user_id": "demo",
    "original_image_key": "uploads/demo/image2.jpg",
    "status": "COMPLETED",
    "created_at": "2025-07-20T10:15:00Z",
    "updated_at": "2025-07-20T10:25:30Z",
    "error_message": null
  }
]
```

### Get Job Details

```
GET /api/jobs/{job_id}
```

**Headers:**
```
Authorization: Bearer {access_token}
```

**Response:**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "user_id": "demo",
  "original_image_key": "uploads/demo/image.jpg",
  "status": "COMPLETED",
  "created_at": "2025-07-21T14:30:00Z",
  "updated_at": "2025-07-21T14:45:30Z",
  "error_message": null,
  "results": {
    "result_id": "660f9500-f30c-52e5-b827-557766550000",
    "job_id": "550e8400-e29b-41d4-a716-446655440000",
    "segmentation_result_key": "results/demo/segmentation_result.jpg",
    "image_description": "The MRI scan shows...",
    "enhanced_report": "# Medical Analysis Report\n\n## Key Findings\n...",
    "confidence_scores": {
      "segmentation_model": 0.94,
      "vlm_model": 0.89,
      "llm_enhancement": 0.92
    },
    "processing_metrics": {
      "segmentation_time_ms": 2450,
      "vlm_processing_time_ms": 1830,
      "llm_enhancement_time_ms": 3200,
      "total_processing_time_ms": 7480
    },
    "created_at": "2025-07-21T14:45:30Z"
  }
}
```

## File Upload

### Direct Upload

```
POST /api/upload
```

**Headers:**
```
Authorization: Bearer {access_token}
```

**Request:**
- Form data:
  - `file`: The file to upload
  - `user_id`: The user ID

**Response:**
```json
{
  "s3_key": "uploads/demo/550e8400-e29b-41d4-a716-446655440000.jpg"
}
```

### Presigned URL for Direct S3 Upload

```
POST /api/presigned-url
```

**Headers:**
```
Authorization: Bearer {access_token}
```

**Request:**
- Form data:
  - `filename`: The name of the file to upload
  - `user_id`: The user ID
  - `content_type`: The content type of the file

**Response:**
```json
{
  "presigned_url": "https://healthcare-mri-images.s3.amazonaws.com/uploads/demo/550e8400-e29b-41d4-a716-446655440000.jpg?AWSAccessKeyId=...",
  "s3_key": "uploads/demo/550e8400-e29b-41d4-a716-446655440000.jpg"
}
```

## Job Status Updates

### Update Job Status

```
POST /api/jobs/{job_id}/update
```

**Headers:**
```
X-API-Key: your-api-key
```

**Request:**
- Form data:
  - `status`: The new status
  - `progress` (optional): The progress percentage
  - `message` (optional): Additional message

**Response:**
```json
{
  "status": "success",
  "message": "Update broadcast for job 550e8400-e29b-41d4-a716-446655440000"
}
```

## WebSocket API

### Connect to WebSocket

```
WebSocket: /ws
```

**Headers:**
```
X-API-Key: your-api-key
```

### Subscribe to Job Updates

**Send:**
```json
{
  "action": "subscribe",
  "job_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

**Receive:**
```json
{
  "action": "subscribed",
  "job_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

### Unsubscribe from Job Updates

**Send:**
```json
{
  "action": "unsubscribe",
  "job_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

**Receive:**
```json
{
  "action": "unsubscribed",
  "job_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

### Receive Job Updates

**Receive:**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "SEGMENTING",
  "progress": 0.45,
  "timestamp": "2025-07-21T14:35:10Z",
  "message": "Processing segment 3 of 8"
}
```