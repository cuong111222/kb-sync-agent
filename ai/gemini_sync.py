import logging
import os
import time
from pathlib import Path
from typing import List, Optional
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are OptiBot, the customer-support bot for OptiSigns.com.\n"
    "\u2022 Tone: helpful, factual, concise.\n"
    "\u2022 Only answer using the uploaded docs.\n"
    "\u2022 Max 5 bullet points; else link to the doc.\n"
    "\u2022 Cite up to 3 \"Article URL:\" lines per reply."
)


class GeminiSync:
    """
    Handles programmatic Vector Store (File Search Store) creation,
    chunk uploading with operation polling, stale chunk deletion with force=True,
    and RAG retrieval using Google GenAI SDK.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("API_KEY") or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY or API_KEY is required.")
        self.client = genai.Client(api_key=self.api_key)

    def get_or_create_vector_store(self, display_name: str = "OptiSigns-KB-Store") -> str:
        """Finds existing File Search Store or creates a new one."""
        try:
            stores = list(self.client.file_search_stores.list())
            for s in stores:
                if s.display_name == display_name or "optisign" in s.name.lower():
                    return s.name
        except Exception as e:
            logger.warning(f"Could not list stores: {e}")

        new_store = self.client.file_search_stores.create(
            config=types.CreateFileSearchStoreConfig(display_name=display_name)
        )
        logger.info(f"Created new Gemini File Search Store: {new_store.name}")
        return new_store.name

    def upload_chunk_to_store(self, file_path: str | Path, store_name: str) -> str:
        """
        Uploads a markdown chunk to the Gemini File Search Store and polls the
        long-running operation until indexing is fully complete.
        Returns the confirmed document_name (e.g. fileSearchStores/.../documents/...).
        """
        path = Path(file_path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        max_retries = 3
        op = None
        for attempt in range(max_retries):
            try:
                op = self.client.file_search_stores.upload_to_file_search_store(
                    file_search_store_name=store_name,
                    file=str(path),
                    config=types.UploadToFileSearchStoreConfig(mime_type="text/markdown"),
                )
                break
            except Exception as e:
                err_msg = str(e).lower()
                if ("429" in err_msg or "resource_exhausted" in err_msg) and attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 3
                    logger.warning(f"Rate limited uploading {path.name}. Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    raise

        if not op:
            raise RuntimeError(f"Failed to initiate upload for {path.name}")

        # Poll operation until indexing is complete as required by Gemini File Search docs
        max_attempts = 60
        attempts = 0
        while not op.done and attempts < max_attempts:
            time.sleep(1)
            try:
                op = self.client.operations.get(op)
            except Exception as poll_err:
                logger.warning(f"Poll check hiccup for {path.name} (attempt {attempts}): {poll_err}")
            attempts += 1

        if not op.done:
            raise TimeoutError(f"Indexing timed out for {path.name} after {max_attempts} seconds.")

        if getattr(op, "error", None):
            raise RuntimeError(f"Gemini indexing failed for {path.name}: {op.error}")

        if not op.response or not getattr(op.response, "document_name", None):
            raise ValueError(f"Operation completed without a valid document_name for {path.name}.")

        doc_name = op.response.document_name
        logger.debug(f"Chunk indexed successfully: {doc_name}")
        return doc_name

    def delete_document(self, document_name: str) -> bool:
        """
        Deletes a stale chunk from the File Search Store with force=True.
        Returns True if deleted, False otherwise.
        """
        try:
            self.client.file_search_stores.documents.delete(
                name=document_name,
                config=types.DeleteDocumentConfig(force=True),
            )
            logger.info(f"Deleted stale chunk from store: {document_name}")
            return True
        except Exception as e:
            err_msg = str(e)
            if "404" in err_msg or "NOT_FOUND" in err_msg:
                logger.info(f"Stale chunk already removed from store: {document_name}")
                return True
            logger.error(f"Failed to delete stale chunk {document_name}: {e}")
            return False

    def ask(self, query: str, store_name: str) -> str:
        """
        Executes a real RAG retrieval query against the File Search Store.
        """
        response = self.client.models.generate_content(
            model="gemini-3.8-flash",
            contents=query,
            config=types.GenerateContentConfig(
                tools=[types.Tool(file_search=types.FileSearch(file_search_store_names=[store_name]))],
                system_instruction=SYSTEM_PROMPT,
                temperature=0.2,
            ),
        )
        return response.text or ""
