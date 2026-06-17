from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import h5py
import numpy as np

from backend.opacity_catalog import (
    discover_local_opacity_molecules,
    discover_local_taurex_datasets,
    parse_immediate_children,
    parse_taurex_files,
)


class OpacityCatalogTests(unittest.TestCase):
    def test_immediate_children_ignore_navigation_and_deeper_links(self) -> None:
        html = """
        <a href="/data/data-types/opacity/">Opacity home</a>
        <a href="NaH/">NaH</a>
        <a href="/data/data-types/opacity/H2O/">H2O</a>
        <a href="/data/data-types/opacity/NaH/23Na-1H/">Too deep</a>
        <a href="https://example.com/data/data-types/opacity/CO/">External</a>
        """

        result = parse_immediate_children(
            html,
            "https://exomol.com/data/data-types/opacity/",
        )

        self.assertEqual(result, ["H2O", "NaH"])

    def test_taurex_parser_only_returns_cross_section_hdf5_files(self) -> None:
        html = """
        <a href="/db/NaH/23Na-1H/Rivlin/example.ktable.petitRADTRANS.h5">
          petitRADTRANS
        </a>
        <a href="/db/NaH/23Na-1H/Rivlin/23Na-1H__Rivlin.R15000_0.3-50mu.xsec.TauREx.h5">
          TauREx
        </a>
        """

        result = parse_taurex_files(
            html,
            "https://exomol.com/data/data-types/opacity/NaH/23Na-1H/Rivlin/",
            molecule="NaH",
            isotopologue="23Na-1H",
            line_list="Rivlin",
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["dataset"], "23Na-1H__Rivlin")
        self.assertEqual(result[0]["configuration"], "R15000_0.3-50mu")
        self.assertEqual(
            result[0]["label"],
            (
                "23Na-1H / Rivlin / "
                "23Na-1H__Rivlin.R15000_0.3-50mu.xsec.TauREx.h5"
            ),
        )

    def test_local_catalog_discovers_hdf5_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = (
                root
                / "NaH"
                / "23Na-1H"
                / "Rivlin"
                / "23Na-1H__Rivlin.R15000_0.3-50mu.xsec.TauREx.h5"
            )
            path.parent.mkdir(parents=True)
            with h5py.File(path, "w") as handle:
                handle.create_dataset("mol_name", data=[b"NaH"])
                handle.create_dataset("key_iso_ll", data=[b"23Na-1H__Rivlin"])
                handle.create_dataset("t", data=np.array([300.0]))
                handle.create_dataset("p", data=np.array([1.0]))
                handle.create_dataset("bin_edges", data=np.arange(2))
                handle.create_dataset("xsecarr", data=np.zeros((1, 1, 2)))

            molecules = discover_local_opacity_molecules(root)
            datasets = discover_local_taurex_datasets("NaH", root)

            self.assertEqual(molecules, [{"key": "NaH", "label": "NaH"}])
            self.assertEqual(len(datasets), 1)
            self.assertEqual(datasets[0]["sourceType"], "local")
            self.assertEqual(datasets[0]["localPath"], str(path))


if __name__ == "__main__":
    unittest.main()
