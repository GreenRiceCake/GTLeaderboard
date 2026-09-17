from hashlib import sha256
import json
from pathlib import Path
import shutil
import stat
import unittest
from uuid import uuid4
from zipfile import ZipFile, ZipInfo

from gtleaderboard.domain import ValidationError
from gtleaderboard.releases import MANIFEST, inspect_package, prepare_update, safe_payload_name, version_tuple
from gtleaderboard.update_ui import UpdateDialog
from test_ui import APP


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1] / "artifacts/tests"
        self.directory = self.root / uuid4().hex
        self.directory.mkdir(parents=True)
        self.models = self.directory / "old/models"
        self.models.mkdir(parents=True)
        (self.models / "test.onnx").write_bytes(b"model")
        self.old = self.directory / "old/league.png"
        self.old.write_bytes(b"user league")
        self.zip = self.directory / "update.zip"

    def tearDown(self):
        if self.directory.resolve().parent != self.root.resolve():
            raise RuntimeError("Test cleanup escaped workspace")
        shutil.rmtree(self.directory)

    def write_package(self, kind="update", extra=None, mutate=None):
        files = {"GTLeaderboard.exe": b"fake EXE"}
        if kind == "full":
            files["models/test.onnx"] = b"model"
        files.update(extra or {})
        manifest = {"format": "GTLeaderboardRelease", "schemaVersion": 1, "version": "0.7.0", "platform": "windows-x64", "kind": kind, "leagueSchema": {"min": 1, "max": 3}, "model": {"file": "models/test.onnx", "sha256": sha256(b"model").hexdigest()}, "files": {name: {"size": len(data), "sha256": sha256(data).hexdigest()} for name, data in files.items()}}
        if mutate:
            mutate(manifest)
        with ZipFile(self.zip, "w") as archive:
            for name, data in files.items():
                archive.writestr(name, data)
            archive.writestr(MANIFEST, json.dumps(manifest))
        return self.zip

    def test_update_reuses_model_and_preserves_existing_files(self):
        self.write_package()
        target = prepare_update(self.zip, self.directory, self.models, "0.6.0")
        self.assertEqual((target / "models/test.onnx").read_bytes(), b"model")
        self.assertEqual((target / "GTLeaderboard.exe").read_bytes(), b"fake EXE")
        self.assertEqual(self.old.read_bytes(), b"user league")
        self.assertFalse((target / "league.png").exists())

    def test_full_package_does_not_need_existing_model(self):
        self.write_package("full")
        target = prepare_update(self.zip, self.directory, self.directory / "missing", "0.6.0")
        self.assertEqual((target / "models/test.onnx").read_bytes(), b"model")

    def test_model_mismatch_rolls_back_only_staging_folder(self):
        self.write_package()
        (self.models / "test.onnx").write_bytes(b"wrong")
        with self.assertRaisesRegex(ValidationError, "전체 패키지"):
            prepare_update(self.zip, self.directory, self.models, "0.6.0")
        self.assertFalse((self.directory / "GTLeaderboard-0.7.0").exists())
        self.assertFalse(list(self.directory.glob(".gtleaderboard-stage-*")))
        self.assertEqual(self.old.read_bytes(), b"user league")

    def test_same_older_version_and_existing_destination_rejected(self):
        self.write_package()
        for version in ("0.7.0", "1.0.0"):
            with self.assertRaises(ValidationError):
                prepare_update(self.zip, self.directory, self.models, version)
        existing = self.directory / "GTLeaderboard-0.7.0"
        existing.mkdir()
        (existing / "keep.txt").write_text("keep")
        with self.assertRaises(ValidationError):
            prepare_update(self.zip, self.directory, self.models, "0.6.0")
        self.assertEqual((existing / "keep.txt").read_text(), "keep")

    def test_checksum_mismatch_rejected(self):
        self.write_package(mutate=lambda m: m["files"]["GTLeaderboard.exe"].update(sha256="0" * 64))
        with self.assertRaisesRegex(ValidationError, "손상"):
            inspect_package(self.zip)

    def test_unknown_personal_files_and_unsafe_paths_rejected(self):
        for name in ("../GTLeaderboard.exe", "/GTLeaderboard.exe", "models/../../x.onnx", "models\\x.onnx", "models/a:b.onnx", "models/CON.onnx", "licenses/x.txt.", "league.gtlb"):
            with self.subTest(name=name), self.assertRaises(ValidationError):
                safe_payload_name(name)
        self.write_package(extra={"league.gtlb": b"private"})
        with self.assertRaises(ValidationError):
            inspect_package(self.zip)

    def test_case_duplicate_and_symlink_rejected(self):
        self.write_package(extra={"gtleaderboard.exe": b"other"})
        with self.assertRaises(ValidationError):
            inspect_package(self.zip)
        self.write_package()
        with ZipFile(self.zip, "a") as archive:
            info = ZipInfo("licenses/link.txt")
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, "../../outside")
        with self.assertRaises(ValidationError):
            inspect_package(self.zip)

    def test_platform_schema_and_missing_full_model_rejected(self):
        for mutation in (lambda m: m.update(platform="linux"), lambda m: m.update(kind="full"), lambda m: m.update(leagueSchema={"min": 4, "max": 5})):
            self.write_package(mutate=mutation)
            with self.assertRaises(ValidationError):
                inspect_package(self.zip)

    def test_invalid_zip_is_readable_error(self):
        self.zip.write_bytes(b"not zip")
        with self.assertRaises(ValidationError):
            inspect_package(self.zip)

    def test_version_comparison_is_numeric(self):
        self.assertGreater(version_tuple("0.10.0"), version_tuple("0.9.0"))
        for bad in ("v0.6.0", "0.6", "../0.6.0", "0.06.0"):
            with self.assertRaises(ValidationError):
                version_tuple(bad)

    def test_update_dialog_only_arms_after_valid_new_version(self):
        dialog = UpdateDialog()
        self.assertFalse(dialog.prepare.isEnabled())
        self.write_package(mutate=lambda m: m.update(version="9.0.0"))
        dialog.inspected(inspect_package(self.zip))
        dialog.refresh_buttons()
        self.assertTrue(dialog.prepare.isEnabled())
        dialog.close()
