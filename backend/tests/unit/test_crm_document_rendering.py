import io

import pytest
from crm_document_helpers import listing
from pypdf import PdfReader
from test_crm_document_templates import FULL

from app.crm import document_rendering
from app.crm.document_rendering import RenderError, render_pdf
from app.crm.document_templates import build_snapshot


def text_of(pdf: bytes) -> tuple[int, str]:
    reader = PdfReader(io.BytesIO(pdf))
    return len(reader.pages), "\n".join(page.extract_text() for page in reader.pages)


def snapshot(doc_type, fields=FULL):
    return build_snapshot(listing(), fields, doc_type)


@pytest.mark.parametrize("doc_type", ["noc", "brochure", "lease", "a2a"])
def test_each_type_renders_a_pdf_with_its_own_details(doc_type):
    pdf = render_pdf(doc_type, snapshot(doc_type))
    _, text = text_of(pdf)
    assert pdf.startswith(b"%PDF")
    assert "PF-123" in text and "DRAFT" in text


def test_noc_names_the_owner_and_title_deed():
    _, text = text_of(render_pdf("noc", snapshot("noc")))
    assert "Aisha Khan" in text and "TD-2024-1" in text


def test_long_text_spans_pages_and_keeps_its_end():
    fields = FULL.model_copy(deep=True)
    fields.marketing.description = ("Sea view. " * 190) + "THE-LAST-SENTENCE"
    pages, text = text_of(render_pdf("brochure", snapshot("brochure", fields)))
    assert pages > 1
    assert "THE-LAST-SENTENCE" in text.replace("\n", "")


def test_arabic_owner_name_is_in_the_pdf():
    fields = FULL.model_copy(deep=True)
    fields.owner.full_name = "محمد أحمد"
    _, text = text_of(render_pdf("noc", snapshot("noc", fields)))
    # Shaping may reorder glyphs in extraction; the letters must all be present.
    assert all(word in text or word[::-1] in text for word in ("محمد", "أحمد"))


def test_html_in_input_is_printed_as_text_and_never_fetched(monkeypatch):
    fetched = []
    real = document_rendering._fetch_bundled

    def spy(url, *args, **kwargs):
        fetched.append(url)
        return real(url, *args, **kwargs)

    monkeypatch.setattr(document_rendering, "_fetch_bundled", spy)
    fields = FULL.model_copy(deep=True)
    fields.owner.full_name = '<img src="http://169.254.169.254/latest">Eve'
    _, text = text_of(render_pdf("noc", snapshot("noc", fields)))
    assert "<img" in text
    assert not any(str(url).startswith("http") for url in fetched)


def test_only_bundled_template_files_can_be_fetched():
    for url in ("http://example.com/x.png", "file:///etc/passwd", "file:///tmp/../etc/hosts"):
        with pytest.raises(RenderError):
            document_rendering._fetch_bundled(url)


def test_a_missing_template_value_is_an_error_not_a_blank():
    broken = snapshot("lease")
    del broken["lease"]
    with pytest.raises(RenderError):
        render_pdf("lease", broken)
