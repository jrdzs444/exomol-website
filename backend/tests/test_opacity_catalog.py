from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import h5py
import numpy as np

import backend.opacity_catalog as opacity_catalog
from backend.opacity_catalog import (
    build_link_file_dataset_record,
    discover_link_file_opacity_molecules,
    discover_link_file_taurex_datasets,
    discover_local_opacity_molecules,
    discover_local_taurex_datasets,
    parse_immediate_children,
    parse_taurex_files,
)


class OpacityCatalogTests(unittest.TestCase):
    def write_taurex_file(self, path: Path, molecule: bytes, key_iso_ll: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with h5py.File(path, "w") as handle:
            handle.create_dataset("mol_name", data=[molecule])
            handle.create_dataset("key_iso_ll", data=[key_iso_ll])
            handle.create_dataset("t", data=np.array([300.0]))
            handle.create_dataset("p", data=np.array([1.0]))
            handle.create_dataset("bin_edges", data=np.arange(2))
            handle.create_dataset("xsecarr", data=np.zeros((1, 1, 2)))

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
            self.write_taurex_file(path, b"NaH", b"23Na-1H__Rivlin")

            molecules = discover_local_opacity_molecules(root)
            datasets = discover_local_taurex_datasets("NaH", root)

            self.assertEqual(molecules, [{"key": "NaH", "label": "NaH"}])
            self.assertEqual(len(datasets), 1)
            self.assertEqual(datasets[0]["sourceType"], "local")
            self.assertEqual(datasets[0]["localPath"], str(path))

    def test_catalog_cache_refreshes_from_local_data_dir(self) -> None:
        previous_data_dir = opacity_catalog.EXOMOL_OPACITY_DATA_DIR
        previous_links_file = opacity_catalog.EXOMOL_OPACITY_LINKS_FILE
        previous_cache_file = opacity_catalog.EXOMOL_OPACITY_CATALOG_CACHE_FILE
        previous_cache_enabled = opacity_catalog.EXOMOL_OPACITY_CATALOG_CACHE_ENABLED
        previous_ttl = opacity_catalog.EXOMOL_OPACITY_CATALOG_CACHE_TTL_SECONDS

        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                local_data = root / "exomol3_data"
                cache_file = root / "cache" / "opacity_catalog.json"
                first_file = (
                    local_data
                    / "NaH"
                    / "23Na-1H"
                    / "Rivlin"
                    / "23Na-1H__Rivlin.R15000_0.3-50mu.xsec.TauREx.h5"
                )
                second_file = (
                    local_data
                    / "HCN"
                    / "1H-12C-14N"
                    / "Harris"
                    / "1H-12C-14N__Harris.R15000_0.3-50mu.xsec.TauREx.h5"
                )
                self.write_taurex_file(first_file, b"NaH", b"23Na-1H__Rivlin")

                opacity_catalog.EXOMOL_OPACITY_DATA_DIR = local_data
                opacity_catalog.EXOMOL_OPACITY_LINKS_FILE = None
                opacity_catalog.EXOMOL_OPACITY_CATALOG_CACHE_FILE = cache_file
                opacity_catalog.EXOMOL_OPACITY_CATALOG_CACHE_ENABLED = True
                opacity_catalog.EXOMOL_OPACITY_CATALOG_CACHE_TTL_SECONDS = 24 * 60 * 60
                opacity_catalog.clear_catalog_memory_caches()

                molecules = opacity_catalog.discover_opacity_molecules()

                self.assertEqual(molecules, [{"key": "NaH", "label": "NaH"}])
                self.assertTrue(cache_file.is_file())

                self.write_taurex_file(second_file, b"HCN", b"1H-12C-14N__Harris")
                opacity_catalog.refresh_opacity_catalog()
                molecules = opacity_catalog.discover_opacity_molecules()

                self.assertEqual(
                    molecules,
                    [
                        {"key": "HCN", "label": "HCN"},
                        {"key": "NaH", "label": "NaH"},
                    ],
                )
        finally:
            opacity_catalog.EXOMOL_OPACITY_DATA_DIR = previous_data_dir
            opacity_catalog.EXOMOL_OPACITY_LINKS_FILE = previous_links_file
            opacity_catalog.EXOMOL_OPACITY_CATALOG_CACHE_FILE = previous_cache_file
            opacity_catalog.EXOMOL_OPACITY_CATALOG_CACHE_ENABLED = previous_cache_enabled
            opacity_catalog.EXOMOL_OPACITY_CATALOG_CACHE_TTL_SECONDS = previous_ttl
            opacity_catalog.clear_catalog_memory_caches()

    def test_local_scan_excludes_invalid_hdf5_files(self) -> None:
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
            path.write_bytes(b"not an hdf5 file")

            self.assertEqual(discover_local_opacity_molecules(root), [])
            self.assertEqual(discover_local_taurex_datasets("NaH", root), [])

    def test_link_file_parser_filters_taurex_cross_sections(self) -> None:
        record = build_link_file_dataset_record(
            "/db/H2O/1H2-16O/POKAZATEL/"
            "1H2-16O__POKAZATEL.R15000_0.3-50mu.xsec.TauREx.h5"
        )
        ignored = build_link_file_dataset_record(
            "/db/H2O/1H2-16O/POKAZATEL/"
            "1H2-16O__POKAZATEL.R1000_0.3-50mu.ktable.NEMESIS.kta"
        )

        self.assertIsNone(ignored)
        self.assertIsNotNone(record)
        self.assertEqual(record["molecule"], "H2O")
        self.assertEqual(record["isotopologue"], "1H2-16O")
        self.assertEqual(record["lineList"], "POKAZATEL")
        self.assertEqual(record["configuration"], "R15000_0.3-50mu")
        self.assertEqual(record["sourceType"], "remote")
        self.assertEqual(
            record["url"],
            (
                "https://exomol.com/db/H2O/1H2-16O/POKAZATEL/"
                "1H2-16O__POKAZATEL.R15000_0.3-50mu.xsec.TauREx.h5"
            ),
        )

    def test_link_file_catalog_can_map_to_local_data_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            links_file = root / "opacity-links.txt"
            local_data = root / "exomol3_data"
            local_h5 = (
                local_data
                / "HCN"
                / "1H-12C-14N"
                / "Harris"
                / "1H-12C-14N__Harris.R15000_0.3-50mu.xsec.TauREx.h5"
            )
            local_h5.parent.mkdir(parents=True)
            local_h5.write_bytes(b"placeholder")

            links_file.write_text(
                "\n".join(
                    [
                        "/db/HCN/1H-12C-14N/Harris/"
                        "1H-12C-14N__Harris.R1000_0.3-50mu.ktable.ARCiS.fits.gz",
                        "/db/HCN/1H-12C-14N/Harris/"
                        "1H-12C-14N__Harris.R15000_0.3-50mu.xsec.TauREx.h5",
                    ]
                ),
                encoding="utf-8",
            )

            molecules = discover_link_file_opacity_molecules(links_file, local_data)
            datasets = discover_link_file_taurex_datasets(
                "HCN",
                links_file,
                local_data,
            )

            self.assertEqual(molecules, [{"key": "HCN", "label": "HCN"}])
            self.assertEqual(len(datasets), 1)
            self.assertEqual(datasets[0]["sourceType"], "local")
            self.assertEqual(datasets[0]["localPath"], str(local_h5))


if __name__ == "__main__":
    unittest.main()
