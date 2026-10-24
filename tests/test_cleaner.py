from scraper.cleaner import clean_html_to_markdown, slugify


def test_clean_html_removes_scripts_styles_and_nav():
    raw_html = """
    <div>
        <nav class="navbar"><a href="/home">Home</a></nav>
        <script>alert('bad');</script>
        <style>body { color: red; }</style>
        <div class="feedback-widget">Was this article helpful? Yes/No</div>
        <h2>Step 1: Install App</h2>
        <p>Click on <strong>Files/Assets</strong> to proceed.</p>
        <div class="cta-banner">Sign up now!</div>
    </div>
    """
    md = clean_html_to_markdown(raw_html)
    assert "alert" not in md
    assert "color: red" not in md
    assert "Home" not in md
    assert "Was this article helpful" not in md
    assert "Sign up now" not in md
    assert "## Step 1: Install App" in md
    assert "**Files/Assets**" in md


def test_clean_html_removes_table_of_contents_jump_links():
    raw_html = """
    <h2>Overview</h2>
    <ul>
        <li><a href="#Step1">Step 1</a></li>
        <li><a href="#Step2">Step 2</a></li>
    </ul>
    <p>This is the actual tutorial text.</p>
    """
    md = clean_html_to_markdown(raw_html)
    assert "#Step1" not in md
    assert "This is the actual tutorial text." in md


def test_clean_html_preserves_meaningful_links_and_headings():
    raw_html = """
    <h1>Main Title</h1>
    <p>Read more at <a href="https://example.com/guide">our guide</a>.</p>
    <pre><code>code block content</code></pre>
    """
    md = clean_html_to_markdown(raw_html)
    assert "# Main Title" in md
    assert "[our guide](https://example.com/guide)" in md
    assert "code block content" in md


def test_frontmatter_generation():
    meta = {
        "id": 12345,
        "title": "How to Configure Screens",
        "html_url": "https://support.example.com/articles/12345",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    md = clean_html_to_markdown("<p>Welcome</p>", metadata=meta)
    assert "article_id: 12345" in md
    assert 'title: "How to Configure Screens"' in md
    assert "url: https://support.example.com/articles/12345" in md


def test_slugify():
    assert slugify("How to Add YouTube Video?") == "how-to-add-youtube-video"
    assert slugify("Screen & Zone Management 101!") == "screen-zone-management-101"
