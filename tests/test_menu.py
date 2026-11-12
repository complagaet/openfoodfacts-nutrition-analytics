from offna.config import Profile
from offna.hypotheses import holm_adjust
from offna.menu import ask_number, run_menu


def scripted(answers: list[str]):
    queue = iter(answers)
    return lambda _prompt: next(queue)


def test_ask_number_rejects_text_and_out_of_range() -> None:
    messages: list[str] = []
    value = ask_number(scripted(["abc", "-1", "4,5"]), messages.append, "Sugars", 100)
    assert value == 4.5
    assert any("not a number" in message for message in messages)
    assert any("between" in message for message in messages)


def test_menu_handles_unknown_option_and_manual_score(tmp_path) -> None:
    profile = Profile("demo", tmp_path / "raw.parquet", tmp_path / "data", tmp_path / "outputs")
    messages: list[str] = []
    answers = ["9", "5", "2524", "32", "10", "48", "0.01", "0", "8", "0", "2", "0"]
    run_menu(profile, scripted(answers), messages.append)
    output = "\n".join(messages)
    assert "unknown option '9'" in output
    assert "grade E" in output
    assert "cannot do that yet" in output


def test_holm_adjustment_is_monotone_and_capped() -> None:
    assert holm_adjust([0.01, 0.04, 0.03]) == [0.03, 0.06, 0.06]


def test_sql_option_does_not_create_an_empty_database(tmp_path) -> None:
    profile = Profile("demo", tmp_path / "raw.parquet", tmp_path / "data", tmp_path / "outputs")
    profile.data_dir.mkdir()
    messages: list[str] = []
    run_menu(profile, scripted(["4", "0"]), messages.append)
    assert not profile.sqlite_path.exists()
    assert any("cannot do that yet" in message for message in messages)
