from qrtunnel.utils import format_progress


def test_format_progress_with_total():
    assert format_progress(50, 100, width=10) == "[#####-----]  50.0% 50.0 B / 100.0 B"


def test_format_progress_without_total():
    assert format_progress(50, 0) == "50.0 B transferred"


def test_format_progress_boundary_exceeded():
    # Should cap ratio at 1.0 (100.0%)
    res = format_progress(150, 100, width=10)
    assert "[##########] 100.0%" in res
