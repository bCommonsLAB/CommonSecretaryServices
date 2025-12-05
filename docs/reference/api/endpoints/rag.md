# RAG API Endpoints

Endpoints for RAG (Retrieval-Augmented Generation) text embedding generation. These endpoints process Markdown text and generate embeddings using Voyage AI models without storing results in the backend database. Clients receive chunks with embeddings and can store them in their own vector database.

## Overview

The RAG API provides text embedding capabilities for building RAG (Retrieval-Augmented Generation) systems. Documents are chunked intelligently (respecting Markdown structure) and converted to vector embeddings that can be stored in any vector database.

**Key Features:**
- Markdown-aware chunking (respects headings, paragraphs)
- Configurable chunk size and overlap
- Support for multiple Voyage AI embedding models
- No backend storage - all results returned to client
- Support for both JSON and form-data requests

## Authentication

All RAG endpoints require authentication via API key:

**Header**: `Authorization: Bearer <token>`  
**Alternative Header**: `X-Secretary-Api-Key: <token>`

The API key is configured via the `SECRETARY_SERVICE_API_KEY` environment variable.

**Note**: For local development, you can set `ALLOW_LOCALHOST_NO_AUTH=true` to bypass authentication on localhost.

## Base URL

All endpoints are prefixed with `/api/rag`:
- Production: `https://commonsecretaryservices.bcommonslab.org/api/rag`
- Local: `http://localhost:5001/api/rag`

## Required Configuration

### Environment Variables

The RAG API requires a Voyage AI API key:

```bash
VOYAGE_API_KEY=pa-your-voyage-key-here
```

Set this in your `.env` file or as an environment variable. See [Environment Variables](../environment-variables.md) for details.

### Supported Embedding Models

The API supports all Voyage AI embedding models. Default models:

**Recommended (Current Generation):**
- `voyage-3-large` - Best general-purpose model (default, 1024 dimensions)
- `voyage-3.5` - Optimized for general-purpose retrieval
- `voyage-3.5-lite` - Optimized for latency and cost
- `voyage-code-3` - Optimized for code retrieval
- `voyage-finance-2` - Optimized for finance documents
- `voyage-law-2` - Optimized for legal documents

**Older Models (Still Supported):**
- `voyage-3`, `voyage-3-lite`
- `voyage-large-2`, `voyage-large-2-instruct`
- `voyage-2`, `voyage-multilingual-2`

**Model Dimensions:**
- `voyage-3-large`, `voyage-3.5`, `voyage-3.5-lite`, `voyage-code-3`: 256, 512, 1024 (default), 2048
- Other models: Mostly 1024 or 1536 (fixed)

See [Voyage AI Documentation](https://docs.voyageai.com/docs/embeddings) for complete model information.

---

## POST /api/rag/embed-text

Embed Markdown text and return chunks with embeddings. Results are **not stored** in the backend database - clients receive all chunks with embeddings and can store them in their own vector database.

### Request

**Content-Type**: `application/json` or `multipart/form-data`

**Parameters**:

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `markdown` | String | Yes | - | Markdown text to embed |
| `document_id` | String | No | Auto-generated UUID | Optional document ID |
| `chunk_size` | Integer | No | 1000 | Chunk size in characters |
| `chunk_overlap` | Integer | No | 200 | Chunk overlap in characters |
| `embedding_model` | String | No | `voyage-3-large` | Voyage AI embedding model name |
| `metadata` | Object/String | No | `{}` | Optional metadata (JSON object or JSON string) |

### Chunking Behavior

The chunking algorithm:
- Respects Markdown structure (headings, paragraphs)
- Splits on double line breaks (`\n\n`)
- Preserves heading context for each chunk
- Handles oversized paragraphs by splitting on word boundaries
- Ensures chunks don't exceed `chunk_size` while respecting `chunk_overlap`

### Request Examples

#### JSON Request

```bash
curl -X POST "http://localhost:5001/api/rag/embed-text" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "markdown": "# Introduction\n\nThis is a sample document with multiple paragraphs.\n\n## Section 1\n\nMore content here.",
    "document_id": "doc-123",
    "chunk_size": 500,
    "chunk_overlap": 100,
    "embedding_model": "voyage-3-large",
    "metadata": {
      "source": "example.md",
      "author": "John Doe"
    }
  }'
```

#### Form-Data Request (Swagger UI Compatible)

```bash
curl -X POST "http://localhost:5001/api/rag/embed-text" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -F "markdown=# Introduction\n\nThis is a sample document." \
  -F "document_id=doc-123" \
  -F "chunk_size=500" \
  -F "chunk_overlap=100" \
  -F "embedding_model=voyage-3-large" \
  -F "metadata={\"source\":\"example.md\"}"
```

#### Python Example

```python
import requests
import json

url = "http://localhost:5001/api/rag/embed-text"
headers = {
    "Authorization": "Bearer YOUR_API_KEY",
    "Content-Type": "application/json"
}

payload = {
    "markdown": """# Introduction

This is a sample document with multiple paragraphs.

## Section 1

More content here.""",
    "document_id": "doc-123",
    "chunk_size": 500,
    "chunk_overlap": 100,
    "embedding_model": "voyage-3-large",
    "metadata": {
        "source": "example.md",
        "author": "John Doe"
    }
}

response = requests.post(url, headers=headers, json=payload)
result = response.json()

# Access chunks and embeddings
if result["status"] == "success":
    data = result["data"]
    print(f"Document ID: {data['document_id']}")
    print(f"Total Chunks: {data['total_chunks']}")
    print(f"Embedding Model: {data['embedding_model']}")
    print(f"Embedding Dimensions: {data['embedding_dimensions']}")
    
    for chunk in data["chunks"]:
        print(f"\nChunk {chunk['chunk_index']}:")
        print(f"  Text: {chunk['text'][:100]}...")
        print(f"  Heading Context: {chunk.get('heading_context')}")
        print(f"  Embedding Length: {len(chunk['embedding'])}")
```

### Response (Success)

**Status Code**: `200 OK`

```json
{
  "status": "success",
  "request": {
    "endpoint": "embed_text",
    "document_id": "doc-123",
    "chunk_size": 500,
    "chunk_overlap": 100,
    "input_length": 156,
    "embedding_model": "voyage-3-large",
    "client_metadata_present": true
  },
  "process": {
    "process_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "processor_name": "rag",
    "status": "success",
    "duration_ms": 1234,
    "llm_info": {
      "total_tokens": 0,
      "total_cost_usd": 0.0,
      "requests": []
    }
  },
  "data": {
    "document_id": "doc-123",
    "chunks": [
      {
        "text": "# Introduction\n\nThis is a sample document with multiple paragraphs.",
        "chunk_index": 0,
        "document_id": "doc-123",
        "embedding": [0.123, -0.456, 0.789, ...],
        "heading_context": "Introduction",
        "start_char": 0,
        "end_char": 65,
        "metadata": {}
      },
      {
        "text": "## Section 1\n\nMore content here.",
        "chunk_index": 1,
        "document_id": "doc-123",
        "embedding": [-0.234, 0.567, -0.890, ...],
        "heading_context": "Section 1",
        "start_char": 65,
        "end_char": 95,
        "metadata": {}
      }
    ],
    "total_chunks": 2,
    "embedding_dimensions": 1024,
    "embedding_model": "voyage-3-large",
    "created_at": "2025-11-28T12:00:00.000000",
    "metadata": {
      "source": "example.md",
      "author": "John Doe"
    }
  }
}
```

### Response Fields

**Top Level:**
- `status` (string): Request status (`"success"` or `"error"`)
- `request` (object): Request information
- `process` (object): Processing information
- `data` (object): Embedding result data

**Data Object:**
- `document_id` (string): Document identifier
- `chunks` (array): List of text chunks with embeddings
- `total_chunks` (integer): Total number of chunks
- `embedding_dimensions` (integer): Dimension of embedding vectors (e.g., 1024)
- `embedding_model` (string): Voyage AI model used for embeddings
- `created_at` (string): ISO 8601 timestamp
- `metadata` (object): Client-provided metadata

**Chunk Object:**
- `text` (string): Chunk text content
- `chunk_index` (integer): Zero-based chunk index
- `document_id` (string): Document identifier
- `embedding` (array[float]): Embedding vector (length = `embedding_dimensions`)
- `heading_context` (string|null): Nearest heading context
- `start_char` (integer|null): Start character position in original text
- `end_char` (integer|null): End character position in original text
- `metadata` (object): Chunk-specific metadata

### Error Responses

#### Missing Markdown (400)

```json
{
  "status": "error",
  "error": {
    "code": "MISSING_MARKDOWN",
    "message": "Feld \"markdown\" mit nicht-leerem Text ist erforderlich",
    "details": {}
  }
}
```

#### Invalid API Key (400)

```json
{
  "status": "error",
  "error": {
    "code": "ProcessingError",
    "message": "Fehler bei der Embedding-Generierung: Provided API key is invalid.",
    "details": null
  }
}
```

#### Unsupported Model (400)

```json
{
  "status": "error",
  "error": {
    "code": "ProcessingError",
    "message": "Fehler bei der Embedding-Generierung: Model voyage-context-3 is not supported.",
    "details": null
  }
}
```

#### Internal Server Error (500)

```json
{
  "status": "error",
  "error": {
    "code": "INTERNAL_ERROR",
    "message": "Ein unerwarteter Fehler ist aufgetreten",
    "details": {
      "error_type": "ValueError",
      "error_message": "Chunk-Größe muss positiv sein"
    }
  }
}
```

### Error Codes

| Code | Description | HTTP Status |
|------|-------------|-------------|
| `MISSING_MARKDOWN` | Markdown field is missing or empty | 400 |
| `ProcessingError` | Processing error (API key, model, etc.) | 400 |
| `INTERNAL_ERROR` | Unexpected server error | 500 |

---

## Future: Multimodal Embeddings

A future endpoint `/api/rag/embed-multimodal` will support multimodal embeddings (text + images) using Voyage AI's `voyage-multimodal-3` model. This will allow embedding documents that contain both text and images.

**Planned Features:**
- Support for Base64-encoded images
- Mixed content (text and images in sequence)
- Same response structure as text-only embeddings

**Image Format:**
Images must be Base64-encoded with data URL prefix:
```
data:image/jpeg;base64,{base64_string}
```
or
```
data:image/png;base64,{base64_string}
```

---

## Best Practices

### Chunk Size Selection

- **Small chunks (200-500 chars)**: Better for precise retrieval, more chunks to manage
- **Medium chunks (500-1000 chars)**: Good balance (default: 1000)
- **Large chunks (1000-2000 chars)**: Better context, fewer chunks

### Chunk Overlap

- **10-20% of chunk_size**: Recommended overlap (default: 200 for chunk_size 1000)
- Prevents information loss at chunk boundaries
- Helps maintain context continuity

### Model Selection

- **General documents**: `voyage-3-large` (default) or `voyage-3.5`
- **Code**: `voyage-code-3`
- **Legal documents**: `voyage-law-2`
- **Finance documents**: `voyage-finance-2`
- **Cost-sensitive**: `voyage-3.5-lite`

### Storing Embeddings

After receiving embeddings, store them in your vector database:

```python
# Example: Store in vector database
for chunk in result["data"]["chunks"]:
    vector_db.insert(
        id=f"{chunk['document_id']}_{chunk['chunk_index']}",
        vector=chunk["embedding"],
        metadata={
            "text": chunk["text"],
            "document_id": chunk["document_id"],
            "chunk_index": chunk["chunk_index"],
            "heading_context": chunk.get("heading_context"),
            **chunk.get("metadata", {})
        }
    )
```

### Query Embeddings

When querying, use the same embedding model and dimensions:

```python
# Query embedding (use same model)
query_text = "What is the main topic?"
query_embedding = voyage_client.embed(
    texts=[query_text],
    model="voyage-3-large",
    input_type="query"
).embeddings[0]

# Search in vector database
results = vector_db.search(
    query_vector=query_embedding,
    top_k=5
)
```

---

## Related Documentation

- [Environment Variables](../environment-variables.md) - Required environment variables
- [Configuration Reference](../configuration.md) - Configuration options
- [Voyage AI Documentation](https://docs.voyageai.com/docs/embeddings) - Voyage AI model information
- [API Overview](../overview.md) - General API information

---

## Interactive Documentation

The complete interactive API documentation is available via **Swagger UI** at:
- `/api/doc` - Navigate to the `rag` namespace







