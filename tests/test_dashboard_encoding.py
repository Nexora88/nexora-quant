from app.api import dashboard


def test_dashboard_response_declares_utf8_and_keeps_turkish_glyphs():
    response = dashboard()
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    rendered = response.body.decode("utf-8")
    for phrase in ("İşlem", "BAĞLI", "Portföy Değeri", "Görünümü"):
        assert phrase in rendered
    assert 'charset="utf-8"' in rendered


def test_dashboard_uses_text_nodes_not_dynamic_inner_html():
    response = dashboard()
    rendered = response.body.decode("utf-8")
    assert ".innerHTML" not in rendered
    assert "textContent" in rendered
    assert "replaceChildren" in rendered
