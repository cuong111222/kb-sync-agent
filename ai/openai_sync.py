import logging
import os
from pathlib import Path
from typing import List, Optional
from openai import OpenAI

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are OptiBot, the customer-support bot for OptiSigns.com.\n"
    "\u2022 Tone: helpful, factual, concise.\n"
    "\u2022 Only answer using the uploaded docs.\n"
    "\u2022 Max 5 bullet points; else link to the doc.\n"
    "\u2022 Cite up to 3 \"Article URL:\" lines per reply."
)


class OpenAISync:
    """Handles programmatic vector store creation and file upload via OpenAI Assistants API."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("API_KEY") or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY or API_KEY is required.")
        self.client = OpenAI(api_key=self.api_key)

    def get_or_create_vector_store(self, name: str = "Support-KB-VectorStore") -> str:
        """Finds existing or creates a new Vector Store."""
        stores = self.client.vector_stores.list()
        for store in stores.data:
            if store.name == name:
                return store.id

        new_store = self.client.vector_stores.create(
            name=name,
            chunking_strategy={
                "type": "static",
                "static": {
                    "max_chunk_size_tokens": 800,
                    "chunk_overlap_tokens": 100,
                },
            },
        )
        return new_store.id

    def upload_files(self, file_paths: List[str | Path], vector_store_id: str) -> List[str]:
        """
        Uploads files to OpenAI Vector Store in a batch.
        Verifies batch completion, confirms zero failed files, and fetches the
        exact file IDs created for this specific batch.
        """
        if not file_paths:
            return []

        file_streams = [open(p, "rb") for p in file_paths]
        try:
            batch = self.client.vector_stores.file_batches.upload_and_poll(
                vector_store_id=vector_store_id,
                files=file_streams,
            )
            # Verify batch status
            if batch.status != "completed":
                error_msg = f"OpenAI batch upload failed with status: {batch.status}"
                logger.error(error_msg)
                raise RuntimeError(error_msg)

            if getattr(batch.file_counts, "failed", 0) > 0:
                error_msg = f"OpenAI batch had {batch.file_counts.failed} failed file uploads."
                logger.error(error_msg)
                raise RuntimeError(error_msg)

            # Query the exact files belonging to this specific batch
            batch_files = self.client.vector_stores.file_batches.list_files(
                vector_store_id=vector_store_id,
                batch_id=batch.id,
            )
            file_ids = [f.id for f in batch_files.data]
            logger.info(f"OpenAI File batch {batch.id} completed: {len(file_ids)} files indexed.")
            return file_ids
        finally:
            for fs in file_streams:
                fs.close()

    def delete_file_from_vector_store(self, vector_store_id: str, file_id: str) -> bool:
        """Removes a stale file/chunk from the OpenAI Vector Store."""
        try:
            self.client.vector_stores.files.delete(
                vector_store_id=vector_store_id,
                file_id=file_id,
            )
            self.client.files.delete(file_id=file_id)
            logger.info(f"Deleted stale file from OpenAI Vector Store: {file_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete stale OpenAI file {file_id}: {e}")
            return False
