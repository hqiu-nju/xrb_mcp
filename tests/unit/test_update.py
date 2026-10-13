import json
import sys
from pathlib import Path

import pytest

from xrb_mcp.scripts import update


def test_recursive_update_excludes_slides_and_uses_separate_sidecars(tmp_path, monkeypatch, capsys):
    inbox = tmp_path / "papers"
    nested = inbox / "source"
    nested.mkdir(parents=True)
    for name in ("good.pdf", "bad.pdf", "slides.pdf", "video.mp4"):
        (nested / name).touch()
    sidecars = tmp_path / "metadata"
    sidecars.mkdir()
    calls = []

    def ingest(path, metadata_path, collections):
        calls.append((path, metadata_path, collections))
        if path.name == "bad.pdf":
            raise ValueError("Unparseable PDF")
        return {"status": "ingested"}

    monkeypatch.setattr(update, "ingest_file", ingest)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "xrb-update",
            str(inbox),
            "--recursive",
            "--metadata-dir",
            str(sidecars),
            "--collection",
            "VAST_XRB",
            "--exclude",
            "*/slides.pdf",
        ],
    )
    with pytest.raises(SystemExit) as exc:
        update.main()
    assert exc.value.code == 1
    assert [call[0].name for call in calls] == ["bad.pdf", "good.pdf"]
    assert calls[1][1] == sidecars / "source" / "good.json"
    assert calls[1][2] == ["VAST_XRB"]
    reports = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [report["status"] for report in reports] == ["failed", "ingested", "excluded"]
    assert all(Path(report["file"]).parent == Path("source") for report in reports)
