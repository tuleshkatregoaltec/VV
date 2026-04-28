from datetime import UTC, datetime

from holocron.domain.news import (
    clean_text,
    extract_first_image_url,
    parse_feed,
    parse_feed_urls,
    parse_publish_date,
)


def test_parse_feed_urls_ignores_comments_and_duplicates() -> None:
    urls = parse_feed_urls(
        """
        # primary feeds
        https://example.com/feed
        https://example.com/feed

        https://example.com/atom
        """
    )

    assert urls == ("https://example.com/feed", "https://example.com/atom")


def test_clean_text_strips_tags_and_collapses_whitespace() -> None:
    assert clean_text(" Hello <b>Dubai</b>\n &amp;  World ") == "Hello Dubai & World"


def test_extract_first_image_prefers_wp_post_image() -> None:
    html = """
    <div>
      <img src="https://example.com/secondary.jpg" class="other-image">
      <img class="wp-post-image hero" src="https://example.com/primary.jpg">
    </div>
    """

    assert extract_first_image_url(html) == "https://example.com/primary.jpg"


def test_parse_publish_date_normalizes_to_utc() -> None:
    parsed = parse_publish_date("Tue, 28 Apr 2026 10:30:00 +0400")

    assert parsed == datetime(2026, 4, 28, 6, 30, tzinfo=UTC)


def test_parse_rss_feed_extracts_articles() -> None:
    xml_text = """
    <rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
      <channel>
        <item>
          <title><![CDATA[Dubai <b>Launch</b>]]></title>
          <link>https://example.com/article-1</link>
          <pubDate>Tue, 28 Apr 2026 10:30:00 +0400</pubDate>
          <content:encoded><![CDATA[
            <p>Text</p>
            <img class="wp-post-image" src="https://example.com/image.jpg" />
          ]]></content:encoded>
        </item>
      </channel>
    </rss>
    """

    articles = parse_feed(xml_text, source_feed_url="https://example.com/feed")

    assert len(articles) == 1
    assert articles[0].headline == "Dubai Launch"
    assert articles[0].url == "https://example.com/article-1"
    assert articles[0].thumbnail_source_url == "https://example.com/image.jpg"
    assert articles[0].publish_date == datetime(2026, 4, 28, 6, 30, tzinfo=UTC)


def test_parse_atom_feed_extracts_articles() -> None:
    xml_text = """
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>Market Update</title>
        <link rel="alternate" href="https://example.com/article-2" />
        <updated>2026-04-28T06:30:00Z</updated>
        <content type="html">&lt;img src="https://example.com/atom.jpg" /&gt;</content>
      </entry>
    </feed>
    """

    articles = parse_feed(xml_text, source_feed_url="https://example.com/atom")

    assert len(articles) == 1
    assert articles[0].headline == "Market Update"
    assert articles[0].url == "https://example.com/article-2"
    assert articles[0].thumbnail_source_url == "https://example.com/atom.jpg"
    assert articles[0].publish_date == datetime(2026, 4, 28, 6, 30, tzinfo=UTC)
