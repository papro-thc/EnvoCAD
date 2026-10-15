import sys


def test_log_rotation_and_hook(tmp_path, monkeypatch):
    monkeypatch.setenv("ENVOCAD_HOME", str(tmp_path))
    from envocad import logging_setup
    p1 = logging_setup.setup(show_dialog=False)
    assert p1.exists()
    try:
        raise ValueError("test pádu")
    except ValueError:
        sys.excepthook(*sys.exc_info())
    for h in list(logging_setup.logging.getLogger().handlers):
        h.flush()
    assert "test pádu" in p1.read_text(encoding="utf-8")
    logging_setup.setup(show_dialog=False)
    assert (tmp_path / "log" / "envocad.log.1").exists()
