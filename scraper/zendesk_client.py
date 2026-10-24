import logging
from typing import List, Dict, Any, Set
import requests

logger = logging.getLogger(__name__)

ZENDESK_ARTICLES_URL = "https://support.optisigns.com/api/v2/help_center/en-us/articles.json"
ZENDESK_SEARCH_URL = "https://support.optisigns.com/api/v2/help_center/articles/search.json"


class ZendeskClient:
    """Client for pulling articles from Zendesk Help Center API."""

    def __init__(self, base_url: str = ZENDESK_ARTICLES_URL):
        self.base_url = base_url
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "KBAgent/1.0",
            "Accept": "application/json",
        })

    def fetch_articles(self, min_articles: int = 35) -> List[Dict[str, Any]]:
        """
        Fetch at least `min_articles` articles.
        Also explicitly includes key core topics (e.g. YouTube, Screen, Playlist)
        to ensure the knowledge base can answer common sanity check questions.
        """
        articles: List[Dict[str, Any]] = []
        seen_ids: Set[int] = set()

        # Step 1: Ingest key core guides via search (guarantees YouTube & essential tutorials exist)
        core_queries = ["youtube", "add screen", "create playlist", "schedule content"]
        for query in core_queries:
            try:
                res = self.session.get(f"{ZENDESK_SEARCH_URL}?query={query}", timeout=10)
                if res.status_code == 200:
                    for item in res.json().get("results", []):
                        art_id = item.get("id")
                        if art_id and art_id not in seen_ids and item.get("body"):
                            seen_ids.add(art_id)
                            articles.append(self._normalize(item))
            except Exception as e:
                logger.warning(f"Error querying {query}: {e}")

        # Step 2: Fetch articles chronologically until reaching min_articles
        page = 1
        per_page = 50
        while len(articles) < min_articles:
            url = f"{self.base_url}?per_page={per_page}&page={page}"
            try:
                res = self.session.get(url, timeout=15)
                res.raise_for_status()
                data = res.json()
            except Exception as e:
                logger.error(f"Failed to fetch {url}: {e}")
                break

            page_items = data.get("articles", [])
            if not page_items:
                break

            for item in page_items:
                art_id = item.get("id")
                if not art_id or art_id in seen_ids or item.get("draft") is True or not item.get("body"):
                    continue

                seen_ids.add(art_id)
                articles.append(self._normalize(item))
                if len(articles) >= min_articles:
                    break

            if not data.get("next_page"):
                break
            page += 1

        logger.info(f"Retrieved {len(articles)} articles total.")
        return articles

    def _normalize(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize Zendesk article structure."""
        return {
            "id": raw["id"],
            "title": (raw.get("title") or raw.get("name") or "Untitled").strip(),
            "html_url": raw.get("html_url", ""),
            "created_at": raw.get("created_at", ""),
            "updated_at": raw.get("updated_at", ""),
            "body": raw.get("body", ""),
        }
