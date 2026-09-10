"""distill(): HTML -> clean, boilerplate-free content via trafilatura.

All tests use fixed local HTML fixtures -- no network, no live site.
"""

from pagedistiller.distill import distill


def _page_with_boilerplate() -> str:
    return """
    <html>
      <head><title>  The Real Title    </title>
        <meta name="description" content="page summary"></head>
      <body>
        <nav id="mainnav">
          <a href="/">Home</a><a href="/about">About</a>
          <a href="/login">Log in</a><a href="/shop">Shop</a>
        </nav>
        <aside class="ads">Sponsored: buy this product now</aside>
        <article id="content">
          <h1>Article Heading</h1>
          <p>This is the real body of the page. It has several sentences so that
           a content extractor keeps it as the main content rather than discarding
           it. Sentences keep coming so the paragraph is long enough to be real
           prose and not a snippet.</p>
          <p>A second paragraph reinforces that this is the genuine main content
           of the page, distinct from the navigation and advertising surrounding
           it on both sides of the document.</p>
        </article>
        <footer>
          <small>&copy; 2026 Example Corp, all rights reserved.
           Privacy &middot; Terms &middot; Cookie Settings &middot; Contact</small>
        </footer>
      </body>
    </html>
    """


def _js_shell() -> str:
    return """
     <html>
       <head><title>Loader</title></head>
       <body>
         <div id="root"></div>
         <script src="/app.js"></script>
       </body>
     </html>
     """


def test_distill_strips_nav_and_footer():
    result = distill(_page_with_boilerplate(), "http://example.com")
    assert "Home" not in result.content
    assert "Sponsored" not in result.content
    assert "all rights reserved" not in result.content.lower()
    assert "Cookie Settings" not in result.content
    assert "Article Heading" in result.content
    assert "real body of the page" in result.content


def test_distill_extracts_title():
    result = distill(_page_with_boilerplate(), "http://example.com")
    assert result.title.strip() != ""
    assert "   " not in result.title
    assert result.title == result.title.strip()


def test_distill_no_front_matter():
    result = distill(_page_with_boilerplate(), "http://example.com")
    assert not result.content.startswith("---")
    for bad in ("title:", "url: http", "hostname:", "sitename:"):
        assert bad not in result.content


def test_distill_records_url():
    result = distill(_page_with_boilerplate(), "http://example.com/article")
    assert result.url == "http://example.com/article"


def test_distill_js_shell_is_empty():
    result = distill(_js_shell(), "http://example.com")
    assert result.content == ""


def test_distill_url_defaults_to_empty():
    result = distill(_page_with_boilerplate())
    assert result.url == ""


def test_distill_markdown_vs_text_shape():
    page = _page_with_boilerplate()
    text = distill(page, "http://example.com", markdown=False)
    md = distill(page, "http://example.com", markdown=True)
    assert "real body of the page" in text.content
    assert "real body of the page" in md.content
    assert ("#" in md.content) or ("*" in md.content)
    assert "#" not in text.content
