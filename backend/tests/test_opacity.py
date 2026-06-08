from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import h5py
import numpy as np

from backend.opacity import get_opacity_options, get_opacity_spectrum


class OpacityReaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.opacity_path = Path(self.temp_dir.name) / "test-opacity.h5"

        with h5py.File(self.opacity_path, "w") as handle:
            handle.create_dataset("mol_name", data=[b"NaH"])
            handle.create_dataset("key_iso_ll", data=[b"23Na-1H__Rivlin"])
            temperatures = handle.create_dataset(
                "t",
                data=np.array([100.0, 300.0]),
            )
            pressures = handle.create_dataset(
                "p",
                data=np.array([0.1, 1.0]),
            )
            wavenumbers = handle.create_dataset(
                "bin_edges",
                data=np.arange(10, dtype=float),
            )
            cross_sections = handle.create_dataset(
                "xsecarr",
                data=np.arange(40, dtype=float).reshape(2, 2, 10),
            )

            temperatures.attrs["units"] = "kelvin"
            pressures.attrs["units"] = "bar"
            wavenumbers.attrs["units"] = "wavenumbers"
            cross_sections.attrs["units"] = "cm^2/molecule"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_options_describe_available_grid(self) -> None:
        result = get_opacity_options(self.opacity_path)

        self.assertEqual(result["molecule"], "NaH")
        self.assertEqual(result["dataset"], "23Na-1H__Rivlin")
        self.assertEqual(result["temperatures"], [100.0, 300.0])
        self.assertEqual(result["pressures"], [0.1, 1.0])
        self.assertEqual(result["spectralPointCount"], 10)

    def test_spectrum_selects_nearest_grid_values(self) -> None:
        result = get_opacity_spectrum(
            self.opacity_path,
            temperature=290.0,
            pressure=0.9,
            max_points=5,
        )

        self.assertEqual(result["temperature"], 300.0)
        self.assertEqual(result["pressure"], 1.0)
        self.assertEqual(result["pointCount"], 5)
        self.assertEqual(result["wavenumbers"], [0.0, 2.0, 4.0, 6.0, 9.0])
        self.assertEqual(
            result["crossSections"],
            [30.0, 32.0, 34.0, 36.0, 39.0],
        )

    def test_invalid_cross_section_shape_is_rejected(self) -> None:
        invalid_path = Path(self.temp_dir.name) / "invalid.h5"
        with h5py.File(invalid_path, "w") as handle:
            handle.create_dataset("t", data=np.array([100.0]))
            handle.create_dataset("p", data=np.array([1.0]))
            handle.create_dataset("bin_edges", data=np.arange(4))
            handle.create_dataset("xsecarr", data=np.zeros((1, 1, 3)))

        with self.assertRaisesRegex(ValueError, "Unexpected xsecarr shape"):
            get_opacity_options(invalid_path)


if __name__ == "__main__":
    unittest.main()
