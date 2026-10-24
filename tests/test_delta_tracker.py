import tempfile
from pathlib import Path
from storage.delta_tracker import DeltaTracker


def test_delta_detection_lifecycle():
    with tempfile.TemporaryDirectory() as tmpdir:
        state_path = Path(tmpdir) / "state.json"
        tracker = DeltaTracker(state_file=str(state_path))

        raw_articles = [
            {"id": 101, "title": "Article 1", "updated_at": "2026-01-01T00:00:00Z"},
            {"id": 102, "title": "Article 2", "updated_at": "2026-01-01T00:00:00Z"},
        ]
        clean_contents = {
            101: "Content 101 initial",
            102: "Content 102 initial",
        }

        # Run 1: Both should be added
        added, updated, skipped = tracker.evaluate_delta(raw_articles, clean_contents)
        assert len(added) == 2
        assert len(updated) == 0
        assert len(skipped) == 0

        # Simulate recording sync with chunk IDs
        for item in added:
            tracker.record_synced(
                article_id=item["id"],
                title=item["title"],
                slug=f"article-{item['id']}",
                content_hash=item["content_hash"],
                updated_at=item["updated_at"],
                file_path=f"data/{item['id']}.md",
                chunk_ids=[f"chunk-{item['id']}-1", f"chunk-{item['id']}-2"],
            )
        tracker.save_state()

        # Run 2: Without changes, both should be skipped
        tracker2 = DeltaTracker(state_file=str(state_path))
        added2, updated2, skipped2 = tracker2.evaluate_delta(raw_articles, clean_contents)
        assert len(added2) == 0
        assert len(updated2) == 0
        assert len(skipped2) == 2

        # Run 3: Article 101 updated (should contain old_chunk_ids for cleanup)
        raw_articles_v2 = [
            {"id": 101, "title": "Article 1", "updated_at": "2026-02-01T00:00:00Z"},
            {"id": 102, "title": "Article 2", "updated_at": "2026-01-01T00:00:00Z"},
        ]
        clean_contents_v2 = {
            101: "Content 101 has been modified",
            102: "Content 102 initial",
        }
        added3, updated3, skipped3 = tracker2.evaluate_delta(raw_articles_v2, clean_contents_v2)
        assert len(updated3) == 1
        assert updated3[0]["id"] == 101
        assert updated3[0]["old_chunk_ids"] == ["chunk-101-1", "chunk-101-2"]
