"""Deterministic HTML-to-text fixtures for the Technical Documentation Comparator."""

import pytest

from sourced_grid.html_to_text import extract_text_and_title


@pytest.fixture
def heading_fixture():
    return {
        "html": "<h1>Main Title</h1><h2>Subtitle</h2><p>Some content here.</p>",
        "expected_title": "Main Title",
        "expected_text": "Main Title\nSubtitle\nSome content here.",
    }


@pytest.fixture
def navigation_noise_fixture():
    return {
        "html": "<nav><a href='/'>Home</a><a href='/about'>About</a></nav><main><p>Real content.</p></main>",
        "expected_title": "",
        "expected_text": "Real content.",
    }


@pytest.fixture
def code_block_fixture():
    return {
        "html": "<h1>Code Example</h1><pre><code>def hello():\n    print('hello')\n</code></pre>",
        "expected_title": "Code Example",
        "expected_text": "Code Example\ndef hello():\n    print('hello')\n",
    }


@pytest.fixture
def updated_time_fixture():
    return {
        "html": "<article><h1>Article Title</h1><time datetime='2024-01-15'>Updated: Jan 15, 2024</time><p>Body text.</p></article>",
        "expected_title": "Article Title",
        "expected_text": "Article Title\nUpdated: Jan 15, 2024\nBody text.",
    }


@pytest.mark.parametrize(
    "fixture_name",
    ["heading_fixture", "navigation_noise_fixture", "code_block_fixture", "updated_time_fixture"],
)
@pytest.fixture
class TestHtmlToTextFixtures:
    pass


@pytest.mark.usefixtures("heading_fixture")
class TestHeadingExtraction:
    def test_title_extraction(self, heading_fixture):
        title, text = extract_text_and_title(heading_fixture["html"])
        assert title == heading_fixture["expected_title"]

    def test_text_extraction(self, heading_fixture):
        title, text = extract_text_and_title(heading_fixture["html"])
        assert text == heading_fixture["expected_text"]


@pytest.mark.usefixtures("navigation_noise_fixture")
class TestNavigationNoiseExtraction:
    def test_title_extraction(self, navigation_noise_fixture):
        title, text = extract_text_and_title(navigation_fixture["html"])
        assert title == navigation_noise_fixture["expected_title"]

    def test_text_extraction(self, navigation_noise_fixture):
        title, text = extract_text_and_title(navigation_noise_fixture["html"])
        assert text == navigation_noise_fixture["expected_text"]


@pytest.mark.usefixtures("code_block_fixture")
class TestCodeBlockExtraction:
    def test_title_extraction(self, code_block_fixture):
        title, text = extract_text_and_title(code_block_fixture["html"])
        assert title == code_block_fixture["expected_title"]

    def test_text_extraction(self, code_block_fixture):
        title, text = extract_text_and_title(code_block_fixture["html"])
        assert text == code_block_fixture["expected_text"]


@pytest.mark.usefixtures("updated_time_fixture")
class TestUpdatedTimeExtraction:
    def test_title_extraction(self, updated_time_fixture):
        title, text = extract_text_and_title(updated_time_fixture["html"])
        assert title == updated_time_fixture["expected_title"]

    def test_text_extraction(self, updated_time_fixture):
        title, text = extract_text_and_title(updated_time_fixture["html"])
        assert text == updated_time_fixture["expected_text"]
