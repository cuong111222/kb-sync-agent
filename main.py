import os
import sys
import logging
from pathlib import Path
from dotenv import load_dotenv

# Ensure UTF-8 stdout encoding on Windows
if sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("kb-sync-agent")

# Load environment variables
load_dotenv()

from scraper.zendesk_client import ZendeskClient
from scraper.cleaner import clean_html_to_markdown, slugify
from storage.delta_tracker import DeltaTracker
from ai.chunker import MarkdownChunker


def run_sync() -> int:
    """
    Main orchestration routine for daily knowledge base synchronization:
    1. Validates API key upfront (fail-fast: API upload is mandatory).
    2. Fetches articles from Zendesk Help Center API.
    3. Strips navigation, ads, feedback widgets, and converts to clean Markdown.
    4. Evaluates delta (Added, Updated, Skipped) using content hash and timestamps.
    5. Cleans up stale chunks from vector store for updated articles with verified deletion.
    6. Splits delta documents into semantic heading-aware chunks.
    7. Programmatically uploads verified chunks to AI Vector Store / File Search Store.
    8. Records successful syncs with their chunk IDs; exits 1 on failure, 0 on success.
    """
    logger.info("==================================================")
    logger.info("Starting Daily Knowledge Base Sync Job")
    logger.info("==================================================")

    is_ci_mode = "--ci-mode" in sys.argv

    # 1. API Key Resolution & Validation
    api_key = os.getenv("API_KEY") or os.getenv("GEMINI_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key and not is_ci_mode:
        logger.error("FATAL: No API_KEY provided (or GEMINI_API_KEY / OPENAI_API_KEY). API upload is mandatory.")
        return 1

    is_openai = bool(api_key and str(api_key).startswith("sk-"))

    data_dir = Path(os.getenv("DATA_DIR", "data/markdown"))
    data_dir.mkdir(parents=True, exist_ok=True)

    chunks_dir = Path("data/chunks")
    chunks_dir.mkdir(parents=True, exist_ok=True)

    state_file = os.getenv("STATE_FILE", "state.json")
    min_articles = int(os.getenv("MIN_ARTICLES", "35"))

    # Step 1: Re-scrape articles
    logger.info(f"Step 1: Pulling >= {min_articles} articles from Zendesk API...")
    client = ZendeskClient()
    raw_articles = client.fetch_articles(min_articles=min_articles)
    logger.info(f"Successfully retrieved {len(raw_articles)} articles.")

    # Step 2: Clean HTML & Convert to Markdown
    logger.info("Step 2: Normalizing HTML to clean Markdown (removing nav, ads, feedback)...")
    clean_contents = {}
    file_map = {}

    for art in raw_articles:
        art_id = art["id"]
        slug = slugify(art["title"])
        filename = f"{slug}.md"
        filepath = data_dir / filename

        md_text = clean_html_to_markdown(art.get("body", ""), art)
        clean_contents[art_id] = md_text

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(md_text)

        file_map[art_id] = {
            "slug": slug,
            "filepath": str(filepath),
        }

    # Step 3: Delta Evaluation (Detect Added / Updated / Skipped)
    logger.info("Step 3: Calculating Delta against previous state...")
    tracker = DeltaTracker(state_file=state_file)
    added, updated, skipped = tracker.evaluate_delta(raw_articles, clean_contents)

    logger.info(f"Delta Analysis Result: Added={len(added)}, Updated={len(updated)}, Skipped={len(skipped)}")

    # Step 4: Heading-Aware Chunking Strategy
    delta_items = added + updated
    chunker = MarkdownChunker(max_chars=1200, overlap_chars=150)
    delta_chunk_map = {}
    total_chunks_prepared = 0

    for item in delta_items:
        art_id = item["id"]
        content = clean_contents[art_id]
        chunks = chunker.chunk_document(content, item)
        delta_chunk_map[art_id] = chunks
        total_chunks_prepared += len(chunks)

        # Write discrete chunk files
        for c_idx, c_text in enumerate(chunks, start=1):
            chunk_file = chunks_dir / f"{file_map[art_id]['slug']}_chunk_{c_idx:02d}.md"
            with open(chunk_file, "w", encoding="utf-8") as cf:
                cf.write(c_text)

    logger.info(f"Chunking Strategy applied: {len(delta_items)} delta articles -> {total_chunks_prepared} semantic chunks.")

    # Step 5: Vector Store Ingestion & Stale Chunk Deletion
    verified_chunks_embedded = 0
    failed_items_count = 0

    if delta_items and is_ci_mode and not api_key:
        logger.info("Step 5 (CI Dry-Run): Validating chunking without mutating state.json...")
        verified_chunks_embedded = sum(len(c) for c in delta_chunk_map.values())
        # Note: Do not write mock IDs to state.json in dry-run mode

    elif delta_items and api_key:
        if not is_openai:
            logger.info("Step 5: Ingesting chunks into Google Gemini File Search Store...")
            from ai.gemini_sync import GeminiSync
            try:
                ai_sync = GeminiSync(api_key=api_key)
                store_name = ai_sync.get_or_create_vector_store()
                logger.info(f"Target Gemini File Search Store: {store_name}")

                for item in delta_items:
                    art_id = item["id"]
                    f_info = file_map[art_id]
                    item_chunks = delta_chunk_map[art_id]
                    item_success = True
                    uploaded_chunk_ids = []

                    # 1. Clean up stale chunks from previous version with verified deletion
                    old_chunks = item.get("old_chunk_ids", []) or tracker.get_old_chunk_ids(art_id)
                    for old_chunk_id in old_chunks:
                        del_ok = ai_sync.delete_document(old_chunk_id)
                        if not del_ok:
                            logger.error(f"Failed to delete stale chunk {old_chunk_id} for article {art_id}. Aborting replacement to avoid drift.")
                            item_success = False
                            break

                    if not item_success:
                        failed_items_count += 1
                        continue

                    # 2. Upload and poll index completion for new chunks
                    for c_idx in range(1, len(item_chunks) + 1):
                        chunk_path = chunks_dir / f"{f_info['slug']}_chunk_{c_idx:02d}.md"
                        try:
                            doc_name = ai_sync.upload_chunk_to_store(chunk_path, store_name)
                            uploaded_chunk_ids.append(doc_name)
                            verified_chunks_embedded += 1
                        except Exception as e:
                            logger.error(f"Failed to upload and index chunk {chunk_path.name}: {e}")
                            item_success = False
                            break

                    if item_success:
                        tracker.record_synced(
                            article_id=art_id,
                            title=item["title"],
                            slug=f_info["slug"],
                            content_hash=item["content_hash"],
                            updated_at=item.get("updated_at", ""),
                            file_path=f_info["filepath"],
                            chunk_ids=uploaded_chunk_ids,
                            ai_file_id=store_name,
                        )
                    else:
                        failed_items_count += 1
                        logger.error(f"Article {art_id} ({f_info['slug']}) failed chunk upload. State NOT updated.")

            except Exception as e:
                logger.error(f"Critical error communicating with Gemini Vector Store: {e}")
                return 1

        else:
            logger.info("Step 5: Ingesting chunks into OpenAI Vector Store...")
            from ai.openai_sync import OpenAISync
            try:
                ai_sync = OpenAISync(api_key=api_key)
                store_id = ai_sync.get_or_create_vector_store()
                logger.info(f"Target OpenAI Vector Store: {store_id}")

                for item in delta_items:
                    art_id = item["id"]
                    f_info = file_map[art_id]
                    item_success = True

                    # 1. Clean up stale chunks from vector store
                    old_chunks = item.get("old_chunk_ids", []) or tracker.get_old_chunk_ids(art_id)
                    for old_file_id in old_chunks:
                        del_ok = ai_sync.delete_file_from_vector_store(store_id, old_file_id)
                        if not del_ok:
                            logger.error(f"Failed to delete stale OpenAI file {old_file_id}. Aborting replacement.")
                            item_success = False
                            break

                    if not item_success:
                        failed_items_count += 1
                        continue

                    chunk_paths = [
                        chunks_dir / f"{f_info['slug']}_chunk_{c_idx:02d}.md"
                        for c_idx in range(1, len(delta_chunk_map[art_id]) + 1)
                    ]

                    try:
                        uploaded_ids = ai_sync.upload_files(chunk_paths, store_id)
                        verified_chunks_embedded += len(uploaded_ids)
                        tracker.record_synced(
                            article_id=art_id,
                            title=item["title"],
                            slug=f_info["slug"],
                            content_hash=item["content_hash"],
                            updated_at=item.get("updated_at", ""),
                            file_path=f_info["filepath"],
                            chunk_ids=uploaded_ids,
                            ai_file_id=store_id,
                        )
                    except Exception as e:
                        logger.error(f"OpenAI batch upload failed for article {art_id}: {e}")
                        failed_items_count += 1

            except Exception as e:
                logger.error(f"Critical error communicating with OpenAI Vector Store: {e}")
                return 1

    # Persist updated delta state (only on real sync)
    if not (is_ci_mode and not api_key):
        tracker.save_state()

    # Final summary log
    logger.info("==================================================")
    logger.info(f"[JOB COMPLETE] added: {len(added)}, updated: {len(updated)}, skipped: {len(skipped)}")
    logger.info(f"[EMBED STATS] Synced Articles: {len(delta_items) - failed_items_count} | Verified Embedded Chunks: {verified_chunks_embedded}")
    logger.info("==================================================")

    if failed_items_count > 0:
        logger.error(f"Job completed with {failed_items_count} failed articles. Exiting with status 1.")
        return 1

    return 0


if __name__ == "__main__":
    exit_code = run_sync()
    sys.exit(exit_code)
