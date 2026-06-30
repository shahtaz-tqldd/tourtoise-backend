import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


class GeminiEmbeddingService:
    endpoint_template = "https://generativelanguage.googleapis.com/v1beta/models/{model}:embedContent"

    def __init__(self, *, api_key=None, model=None, dimensions=None):
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model = model or settings.GEMINI_EMBEDDING_MODEL
        self.dimensions = dimensions or settings.GEMINI_EMBEDDING_DIMENSIONS
        if not self.api_key:
            raise ImproperlyConfigured("GEMINI_API_KEY is required for embedding generation.")

    def embed_document(self, text):
        return self._embed_text(text, task_type="RETRIEVAL_DOCUMENT")

    def embed_query(self, text):
        return self._embed_text(text, task_type="RETRIEVAL_QUERY")

    def _embed_text(self, text, *, task_type):
        payload = {
            "model": f"models/{self.model}",
            "content": {
                "parts": [{"text": text}],
            },
            "taskType": task_type,
        }
        if self.dimensions:
            payload["outputDimensionality"] = int(self.dimensions)

        request = Request(
            self.endpoint_template.format(model=self.model),
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self.api_key,
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=30) as response:
                data = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"Gemini embedding request failed: {detail or exc.reason}") from exc
        except URLError as exc:
            raise RuntimeError(f"Gemini embedding request failed: {exc.reason}") from exc

        embedding = data.get("embedding")
        if embedding and "values" in embedding:
            return embedding["values"]

        embeddings = data.get("embeddings") or []
        if not embeddings or "values" not in embeddings[0]:
            raise RuntimeError("Gemini embedding response did not include embedding values.")
        return embeddings[0]["values"]
