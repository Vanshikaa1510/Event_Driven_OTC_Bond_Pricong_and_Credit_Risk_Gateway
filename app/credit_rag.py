from __future__ import annotations

import os

from langchain_huggingface import HuggingFaceEndpointEmbeddings
from pgvector import Vector
from pgvector.psycopg import register_vector
import psycopg

from app.reference_data import _database_url


EMBEDDING_MODEL = os.getenv("HF_EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")


def retrieve_credit_context(client_id: str, query: str, hf_token: str) -> list[dict[str, str]]:
    embeddings = HuggingFaceEndpointEmbeddings(
        model=EMBEDDING_MODEL,
        provider="hf-inference",
        huggingfacehub_api_token=hf_token,
    )
    with psycopg.connect(_database_url()) as connection:
        register_vector(connection)
        unembedded = connection.execute(
            "SELECT id, content FROM client_credit_documents WHERE client_id = %s AND embedding IS NULL",
            (client_id,),
        ).fetchall()
        if unembedded:
            vectors = embeddings.embed_documents([content for _, content in unembedded])
            with connection.cursor() as cursor:
                for (document_id, _), vector in zip(unembedded, vectors, strict=True):
                    cursor.execute(
                        "UPDATE client_credit_documents SET embedding = %s WHERE id = %s",
                        (Vector(vector), document_id),
                    )

        query_vector = embeddings.embed_query(query)
        rows = connection.execute(
            """
            SELECT source_name, content
            FROM client_credit_documents
            WHERE client_id = %s AND embedding IS NOT NULL
            ORDER BY embedding <=> %s
            LIMIT 3
            """,
            (client_id, Vector(query_vector)),
        ).fetchall()
    return [{"source": source, "content": content} for source, content in rows]