from __future__ import annotations

import pytest

from app.template import TemplateValidationError, parse_template, validate_dag

BASE = """
apiVersion: sourcedgrid/v1alpha1
kind: ResearchTemplate
metadata:
  slug: test
  name: Test
columns:
  - key: url
    label: URL
    kind: input
  - key: name
    label: Name
    kind: transform
    depends_on: [url]
"""


def test_valid_template_is_topologically_sorted() -> None:
    template = parse_template(BASE)
    assert validate_dag(template) == ["url", "name"]


@pytest.mark.parametrize(
    "document, message",
    [
        (BASE.replace("key: name", "key: url"), "duplicate"),
        (BASE.replace("depends_on: [url]", "depends_on: [missing]"), "missing"),
        (BASE.replace("depends_on: [url]", "depends_on: [name]"), "cycle"),
    ],
)
def test_invalid_templates_are_rejected(document: str, message: str) -> None:
    with pytest.raises(TemplateValidationError, match=message):
        parse_template(document)
