"""Explicit developer self-test used to validate the packaged executable."""
import json
from pathlib import Path
import sys
import traceback
from uuid import uuid4


def self_test(app, report_path, screenshots=()):
    from . import __version__
    from .catalog import load_catalog, model_directory
    from .domain import League, Round, Result, add_drivers, apply_results, standings
    from .export_png import render_sheet, save_png
    from .storage import save_league, load_league, serialize_league
    from .ocr import TextRecognizer, recognize_screenshot
    from .export_csv import save_csv
    from .ui import MainWindow
    from .update_ui import UpdateDialog
    from .online_updates import default_manifest_url
    path = Path(report_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    output = path.parent / f"self-test-{uuid4().hex}"
    output.mkdir()
    report = {"version": __version__, "frozen": bool(getattr(sys, "frozen", False)), "executable": sys.executable, "model_directory": str(model_directory()), "checks": {}}
    try:
        tracks = load_catalog()["tracks"]
        assert len(tracks) >= 121
        report["checks"]["tracks"] = len(tracks)
        league = League("배포본 자체 검사")
        add_drivers(league, ["한글 드라이버", "Example Driver"])
        league.rounds = [Round("R01", tracks[0]["id"], tracks[0]["name"])]
        apply_results(league, league.rounds[0].id, {league.drivers[0].id: Result("FINISHED", 1, pole=True, fastest=True)}, "자체 검사")
        save_league(output / "league.gtlb", league)
        assert load_league(output / "league.gtlb") == league
        image = render_sheet(league, 1)
        save_png(output / "league.png", image, serialize_league(league))
        assert load_league(output / "league.png") == league
        assert standings(load_league(output / "league.png"))[0]["total"] == 31
        report["checks"]["json_png_roundtrip"] = True
        save_csv(output / "leaderboard.csv", league)
        assert (output / "leaderboard.csv").read_bytes().startswith(b"\xef\xbb\xbf")
        report["checks"]["visible_csv"] = True
        window = MainWindow(league)
        from PySide6.QtCore import QSettings
        window.enable_session(QSettings(str(output / 'settings.ini'), QSettings.Format.IniFormat), output / 'recovery')
        original_name = window.league.name
        window.league.name = '실행 취소 확인'
        window.mark_dirty()
        window.undo_work(True)
        assert window.league.name == original_name
        report['checks']['undo_workflow'] = True
        first = next(iter(window.row_widgets.values()))
        first[1].setValue(2)
        assert window.write_recovery()
        data, recovered_league = window.recovery.read(window.recovery.path)
        assert data['draft'] and recovered_league.name == original_name
        window.render_results()
        window.write_recovery()
        report['checks']['recovery_snapshot'] = True
        window.show()
        app.processEvents()
        window.grab().save(str(output / "ui.png"))
        updates = UpdateDialog(window)
        updates.show()
        app.processEvents()
        updates.grab().save(str(output / "updates.png"))
        assert not updates.download.isEnabled()
        report["checks"]["update_manifest_url"] = default_manifest_url()
        updates.reject()
        window.close()
        report["checks"]["qt_widgets"] = True
        recognizer = TextRecognizer()
        report["checks"]["onnx_cpu"] = True
        if screenshots:
            rows = [row for shot in screenshots for row in recognize_screenshot(shot, recognizer)]
            assert rows
            report["checks"]["ocr_rows"] = [{"position": r.position, "name": r.name, "status": r.status, "lap": r.best_lap_text} for r in rows]
        report["ok"] = True
    except Exception:
        report["ok"] = False
        report["error"] = traceback.format_exc()
    report["output"] = str(output)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["ok"] else 1
