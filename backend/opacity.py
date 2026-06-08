from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np


REQUIRED_DATASETS = ("bin_edges", "p", "t", "xsecarr")


def decode_scalar(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


def validate_opacity_file(handle: h5py.File) -> None:
    missing = [name for name in REQUIRED_DATASETS if name not in handle]
    if missing:
        raise ValueError(
            "Invalid TauREx opacity file. Missing datasets: "
            + ", ".join(missing)
        )

    pressures = handle["p"]
    temperatures = handle["t"]
    wavenumbers = handle["bin_edges"]
    cross_sections = handle["xsecarr"]
    expected_shape = (
        len(pressures),
        len(temperatures),
        len(wavenumbers),
    )

    if cross_sections.shape != expected_shape:
        raise ValueError(
            "Unexpected xsecarr shape. "
            f"Expected {expected_shape}, found {cross_sections.shape}."
        )


def read_text_dataset(handle: h5py.File, name: str) -> str | None:
    if name not in handle:
        return None

    value = handle[name][()]
    if isinstance(value, np.ndarray):
        if value.size == 0:
            return None
        value = value.flat[0]
    return decode_scalar(value)


def nearest_index(values: np.ndarray, target: float) -> int:
    return int(np.abs(values - target).argmin())


def evenly_spaced_indices(length: int, max_points: int) -> np.ndarray:
    if length <= max_points:
        return np.arange(length)
    return np.linspace(0, length - 1, max_points, dtype=int)


def get_opacity_options(path: Path) -> dict:
    with h5py.File(path, "r") as handle:
        validate_opacity_file(handle)
        temperatures = handle["t"][:]
        pressures = handle["p"][:]
        wavenumbers = handle["bin_edges"]

        return {
            "fileName": path.name,
            "molecule": read_text_dataset(handle, "mol_name"),
            "dataset": read_text_dataset(handle, "key_iso_ll"),
            "temperatures": temperatures.tolist(),
            "pressures": pressures.tolist(),
            "temperatureUnits": handle["t"].attrs.get("units", "kelvin"),
            "pressureUnits": handle["p"].attrs.get("units", "bar"),
            "wavenumberUnits": handle["bin_edges"].attrs.get(
                "units",
                "wavenumbers",
            ),
            "crossSectionUnits": handle["xsecarr"].attrs.get(
                "units",
                "cm^2/molecule",
            ),
            "spectralPointCount": len(wavenumbers),
            "wavenumberMin": float(wavenumbers[0]),
            "wavenumberMax": float(wavenumbers[-1]),
        }


def get_opacity_spectrum(
    path: Path,
    temperature: float,
    pressure: float,
    max_points: int,
) -> dict:
    with h5py.File(path, "r") as handle:
        validate_opacity_file(handle)
        temperatures = handle["t"][:]
        pressures = handle["p"][:]

        temperature_index = nearest_index(temperatures, temperature)
        pressure_index = nearest_index(pressures, pressure)
        point_indices = evenly_spaced_indices(
            len(handle["bin_edges"]),
            max_points,
        )

        # h5py requires increasing indices for efficient partial reads.
        wavenumbers = handle["bin_edges"][point_indices]
        cross_sections = handle["xsecarr"][
            pressure_index,
            temperature_index,
            point_indices,
        ]

        return {
            "molecule": read_text_dataset(handle, "mol_name"),
            "dataset": read_text_dataset(handle, "key_iso_ll"),
            "requestedTemperature": temperature,
            "requestedPressure": pressure,
            "temperature": float(temperatures[temperature_index]),
            "pressure": float(pressures[pressure_index]),
            "temperatureUnits": handle["t"].attrs.get("units", "kelvin"),
            "pressureUnits": handle["p"].attrs.get("units", "bar"),
            "wavenumberUnits": handle["bin_edges"].attrs.get(
                "units",
                "wavenumbers",
            ),
            "crossSectionUnits": handle["xsecarr"].attrs.get(
                "units",
                "cm^2/molecule",
            ),
            "originalPointCount": len(handle["bin_edges"]),
            "pointCount": len(point_indices),
            "wavenumbers": wavenumbers.tolist(),
            "crossSections": cross_sections.tolist(),
        }
