from openai import OpenAI

from database.models import EMBEDDING_DIMENSIONS

EMBEDDING_MODEL = "text-embedding-3-small"


def create_embedding(text: str) -> list[float]:
    """Turn text into a vector with OpenAI, so similar meanings get similar vectors."""
    response = OpenAI().embeddings.create(
        model=EMBEDDING_MODEL, input=text, dimensions=EMBEDDING_DIMENSIONS
    )
    return response.data[0].embedding
