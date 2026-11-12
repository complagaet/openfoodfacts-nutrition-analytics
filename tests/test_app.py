from streamlit.testing.v1 import AppTest

from offna.config import PROFILES, PROJECT_ROOT


def test_dashboard_script_runs_without_exceptions() -> None:
    app = AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=60).run()
    assert not app.exception
    aggregates_ready = (PROFILES["demo"].aggregates_dir / "country_food_group.parquet").exists()
    if aggregates_ready:
        assert len(app.metric) == 4
        app.sidebar.selectbox[0].select("france").run()
        assert not app.exception
    else:
        assert app.error
