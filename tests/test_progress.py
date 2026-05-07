from qrtunnel.utils import format_progress


def test_format_progress_with_total():
    assert format_progress(50, 100, width=10) == "[#####-----]  50.0% 50.0 B / 100.0 B"


def test_format_progress_without_total():
    assert format_progress(50, 0) == "50.0 B transferred"
