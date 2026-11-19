from app.api import DASHBOARD


def test_dashboard_exposes_required_two_row_kpi_contract():
    required = (
        'id=\"top_eq\"', 'id=\"net\"', 'id=\"sessionpnl\"',
        'id=\"dd\"', 'id=\"tc\"', 'id=\"wr\"',
        'id=\"top_fees\"', 'id=\"top_expect\"',
        'id=\"top_maker\"', 'id=\"top_spread\"',
        'id=\"top_age\"', 'id=\"top_events\"',
    )
    for element_id in required:
        assert element_id in DASHBOARD


def test_dashboard_uses_status_api_and_displays_unmeasured_maker_as_na():
    assert "fetch('/status'" in DASHBOARD
    assert "topMaker.fill_rate==null?'N/A'" in DASHBOARD
