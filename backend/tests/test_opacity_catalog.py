from __future__ import annotations

import unittest

from backend.opacity_catalog import (
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


if __name__ == "__main__":
    unittest.main()
