import json
import hashlib
from pathlib import Path
from typing import Dict, Any, List, Tuple


class DeltaTracker:
    """
    Tracks state of scraped and uploaded documents using MD5 checksums
    and updated_at timestamps to detect Added, Updated, and Skipped items.
    Also tracks uploaded chunk IDs to enable clean deletion of stale chunks when updated.
    """

    def __init__(self, state_file: str = "state.json"):
        self.state_file = Path(state_file)
        self.state: Dict[str, Any] = self._load_state()

    def _load_state(self) -> Dict[str, Any]:
        if self.state_file.exists():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {"articles": {}}
        return {"articles": {}}

    def save_state(self) -> None:
        """Persist state to JSON file with UTF-8 encoding."""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=2, ensure_ascii=False)

    @staticmethod
    def compute_hash(text: str) -> str:
        """Compute MD5 hash for content change detection."""
        return hashlib.md5(text.encode("utf-8")).hexdigest()

    def evaluate_delta(
        self, raw_articles: List[Dict[str, Any]], clean_contents: Dict[int, str]
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Categorizes articles into (added, updated, skipped).
        `clean_contents` maps article_id -> markdown text.
        """
        added: List[Dict[str, Any]] = []
        updated: List[Dict[str, Any]] = []
        skipped: List[Dict[str, Any]] = []

        stored_articles = self.state.get("articles", {})

        for art in raw_articles:
            art_id = str(art["id"])
            content = clean_contents.get(art["id"], "")
            content_hash = self.compute_hash(content)
            updated_at = art.get("updated_at", "")

            if art_id not in stored_articles:
                art_with_meta = {**art, "content_hash": content_hash}
                added.append(art_with_meta)
            else:
                existing = stored_articles[art_id]
                # Detect changes via updated_at timestamp or MD5 content hash
                if (updated_at and existing.get("updated_at") != updated_at) or (existing.get("hash") != content_hash):
                    art_with_meta = {
                        **art,
                        "content_hash": content_hash,
                        "old_chunk_ids": existing.get("chunk_ids", []),
                    }
                    updated.append(art_with_meta)
                else:
                    skipped.append(art)

        return added, updated, skipped

    def record_synced(
        self,
        article_id: int | str,
        title: str,
        slug: str,
        content_hash: str,
        updated_at: str,
        file_path: str,
        chunk_ids: List[str] | None = None,
        ai_file_id: str = "",
    ) -> None:
        """Updates record for an added or updated article including chunk IDs."""
        if "articles" not in self.state:
            self.state["articles"] = {}

        self.state["articles"][str(article_id)] = {
            "title": title,
            "slug": slug,
            "hash": content_hash,
            "updated_at": updated_at,
            "file_path": file_path,
            "chunk_ids": chunk_ids or [],
            "ai_file_id": ai_file_id,
        }

    def get_old_chunk_ids(self, article_id: int | str) -> List[str]:
        """Returns previously recorded chunk IDs for cleanup."""
        art = self.state.get("articles", {}).get(str(article_id), {})
        return art.get("chunk_ids", [])
