import re
from bs4 import BeautifulSoup, Comment
from markdownify import markdownify as md


def clean_html_to_markdown(html_content: str, metadata: dict | None = None) -> str:
    """
    Cleans raw HTML from Zendesk Help Center and converts it to clean Markdown.
    Preserves:
      - Headings (h1-h6)
      - Code blocks and inline code
      - Meaningful links and lists
      - Relevant tables
    Removes:
      - Navigation bars, sidebars, breadcrumbs
      - Ads, promotional banners, CTA buttons
      - Voting widgets ('Was this article helpful?'), feedback forms
      - Author cards, share widgets, social links
      - Jump-anchor table of contents lists
    """
    if not html_content:
        return ""

    soup = BeautifulSoup(html_content, "html.parser")

    # 1. Remove non-content structural & interactive tags
    for tag in soup(["script", "style", "noscript", "svg", "button", "form", "nav", "aside", "header", "footer", "iframe"]):
        tag.decompose()

    # 2. Remove HTML comments
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()

    # 3. Remove noise elements by class, id, or role (ads, feedback, nav, breadcrumbs, social)
    noise_patterns = re.compile(
        r"(breadcrumb|sidenav|sidebar|nav-|navbar|menu|footer|vote|feedback|rating|helpful|"
        r"author|social|share|cta|banner|promo|ad-|ad_|widget|related-articles)",
        re.IGNORECASE
    )
    for element in soup.find_all(attrs={"class": noise_patterns}):
        element.decompose()
    for element in soup.find_all(attrs={"id": noise_patterns}):
        element.decompose()

    # 4. Remove internal Table of Contents anchor jump lists (e.g. lists containing only #hash links)
    for ul in soup.find_all(["ul", "ol"]):
        links = ul.find_all("a", href=True)
        if links and all(a["href"].startswith("#") for a in links):
            ul.decompose()

    # 5. Remove tracking pixels or tiny decorative spacer images
    for img in soup.find_all("img"):
        width = img.get("width")
        height = img.get("height")
        src = img.get("src", "")
        if (width in ["1", "0"]) or (height in ["1", "0"]) or "pixel" in src.lower() or "spacer" in src.lower():
            img.decompose()

    # 6. Convert cleaned HTML tree to Markdown
    markdown_text = md(
        str(soup),
        heading_style="ATX",
        strip=["script", "style"],
        autolinks=True,
        default_title=False
    )

    # 7. Strip boilerplate support phrases from text
    boilerplate_patterns = [
        r"(?i)was this article helpful\?.*",
        r"(?i)have more questions\?.*submit a request.*",
        r"(?i)related articles.*",
        r"(?i)if you have any additional questions.*contact our support team.*",
    ]
    for bp in boilerplate_patterns:
        markdown_text = re.sub(bp, "", markdown_text)

    # 8. Normalize whitespace and newlines
    markdown_text = re.sub(r"\n{3,}", "\n\n", markdown_text).strip()

    # 9. Format structured metadata frontmatter
    header_parts = []
    if metadata:
        header_parts.append("---")
        if "id" in metadata:
            header_parts.append(f"article_id: {metadata['id']}")
        if "title" in metadata:
            clean_title = metadata["title"].replace('"', '\\"')
            header_parts.append(f"title: \"{clean_title}\"")
        if "html_url" in metadata:
            header_parts.append(f"url: {metadata['html_url']}")
        if "updated_at" in metadata:
            header_parts.append(f"updated_at: {metadata['updated_at']}")
        header_parts.append("---")
        header_parts.append("")

    if metadata and "title" in metadata:
        header_parts.append(f"# {metadata['title']}\n")

    return "\n".join(header_parts) + markdown_text + "\n"


def slugify(text: str) -> str:
    """Generate a clean slug for filenames."""
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text).strip("-")
    return text or "article"
