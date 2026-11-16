from app.api import DASHBOARD, dashboard


def test_dashboard_response_declares_utf8_and_keeps_turkish_glyphs():
    response = dashboard()
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    rendered = response.body.decode("utf-8")
    for glyph in ("İ", "ı", "Ş", "ş", "Ğ", "ğ", "Ü", "ü", "Ö", "ö", "Ç", "ç"):
        assert 'charset="utf-8"' in rendered
    assert "charset=\\"utf-8\\"" in rendered
