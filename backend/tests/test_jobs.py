from __future__ import annotations

import bz2
import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException

import backend.main as main


class JobWorkflowTests(unittest.TestCase):
    def test_zero_byte_exocross_placeholder_is_not_available(self) -> None:
        original_exe = main.EXOCROSS_EXE
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                exe = Path(temp_dir) / "exocross.exe"
                exe.write_bytes(b"")
                main.EXOCROSS_EXE = exe
                self.assertFalse(main.exocross_executable_available())
        finally:
            main.EXOCROSS_EXE = original_exe

    def test_local_dataset_discovery_uses_server_style_layout(self) -> None:
        original_dir = main.LINE_LIST_DATA_DIR
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                dataset_dir = root / "NaH" / "23Na-1H" / "Rivlin"
                dataset_dir.mkdir(parents=True)
                (dataset_dir / "23Na-1H__Rivlin.pf").write_text("pf", encoding="utf-8")
                with bz2.open(dataset_dir / "23Na-1H__Rivlin.states.bz2", "wb") as handle:
                    handle.write(b"states")
                with bz2.open(dataset_dir / "23Na-1H__Rivlin.trans.bz2", "wb") as handle:
                    handle.write(b"transitions")

                main.LINE_LIST_DATA_DIR = root
                result = main.discover_local_dataset_files(
                    molecule="NaH",
                    isotopologue="23Na-1H",
                    line_list="Rivlin",
                    range_min=0,
                    range_max=100,
                )

                self.assertIsNotNone(result)
                assert result is not None
                self.assertEqual(result["source"], "local")
                self.assertEqual(result["states"]["name"], "23Na-1H__Rivlin.states.bz2")
                self.assertEqual(result["pf"]["name"], "23Na-1H__Rivlin.pf")
                self.assertEqual(result["transitions"][0]["name"], "23Na-1H__Rivlin.trans.bz2")
        finally:
            main.LINE_LIST_DATA_DIR = original_dir

    def test_transition_count_limit_rejects_too_many_chunks(self) -> None:
        original_limit = main.EXOCROSS_MAX_TRANSITION_FILES
        try:
            main.EXOCROSS_MAX_TRANSITION_FILES = 1
            with self.assertRaises(HTTPException):
                main.validate_transition_count(
                    [
                        {"name": "file1.trans.bz2"},
                        {"name": "file2.trans.bz2"},
                    ]
                )
        finally:
            main.EXOCROSS_MAX_TRANSITION_FILES = original_limit

    def test_output_spectrum_parser_downsamples_two_column_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "opacity.out"
            output.write_text(
                "\n".join(
                    [
                        "# comment",
                        "100.0 1.0e-20",
                        "101.0 2.0e-20",
                        "102.0 3.0e-20",
                        "103.0 4.0e-20",
                    ]
                ),
                encoding="utf-8",
            )

            result = main.read_output_spectrum(output, max_points=2)

            self.assertEqual(result["nativePoints"], 4)
            self.assertEqual(result["wavenumber"], [100.0, 102.0, 103.0])
            self.assertEqual(result["crossSection"], [1.0e-20, 3.0e-20, 4.0e-20])


if __name__ == "__main__":
    unittest.main()
