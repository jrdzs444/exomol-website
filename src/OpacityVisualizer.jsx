import { useEffect, useMemo, useState } from "react";
import createPlotlyComponentModule from "react-plotly.js/factory";
import Plotly from "plotly.js-basic-dist-min";
import {
  getOpacityCatalog,
  getOpacityDatasets,
  getOpacityOptions,
  getOpacitySpectrum,
} from "./api";

const DEFAULT_TEMPERATURE = 300;
const DEFAULT_PRESSURE = 1;
const createPlotlyComponent =
  createPlotlyComponentModule.default || createPlotlyComponentModule;
const Plot = createPlotlyComponent(Plotly);

function nearestValue(values, target) {
  if (!values.length) return "";
  return values.reduce((nearest, value) =>
    Math.abs(value - target) < Math.abs(nearest - target) ? value : nearest
  );
}

function formatPressure(value) {
  if (!Number.isFinite(value)) return "-";
  if (value < 0.01 || value >= 1000) return value.toExponential(2);
  return value.toLocaleString(undefined, { maximumSignificantDigits: 5 });
}

function formatNumber(value) {
  if (!Number.isFinite(value)) return "-";
  return value.toLocaleString();
}

export default function OpacityVisualizer() {
  const [molecules, setMolecules] = useState([]);
  const [datasets, setDatasets] = useState([]);
  const [selectedMolecule, setSelectedMolecule] = useState("");
  const [selectedIsotopologue, setSelectedIsotopologue] = useState("");
  const [selectedDataset, setSelectedDataset] = useState("");
  const [options, setOptions] = useState(null);
  const [selectedTemperature, setSelectedTemperature] = useState("");
  const [selectedPressure, setSelectedPressure] = useState("");
  const [maxPoints, setMaxPoints] = useState("2000");
  const [spectrum, setSpectrum] = useState(null);
  const [loadingCatalog, setLoadingCatalog] = useState(true);
  const [loadingDatasets, setLoadingDatasets] = useState(false);
  const [loadingOptions, setLoadingOptions] = useState(false);
  const [loadingSpectrum, setLoadingSpectrum] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

  useEffect(() => {
    let active = true;

    async function loadCatalog() {
      try {
        setLoadingCatalog(true);
        setErrorMessage("");
        const data = await getOpacityCatalog();
        if (!active) return;

        const availableMolecules = data.molecules || [];
        const preferred =
          availableMolecules.find((item) => item.key === "NaH") ||
          availableMolecules[0];
        setMolecules(availableMolecules);
        setSelectedMolecule(preferred?.key || "");
      } catch (error) {
        if (active) {
          setErrorMessage(error.message || "Failed to load opacity molecules.");
        }
      } finally {
        if (active) setLoadingCatalog(false);
      }
    }

    loadCatalog();
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!selectedMolecule) return undefined;
    let active = true;

    async function loadDatasets() {
      try {
        setLoadingDatasets(true);
        setErrorMessage("");
        setDatasets([]);
        setSelectedIsotopologue("");
        setSelectedDataset("");
        setOptions(null);
        setSpectrum(null);
        setSelectedTemperature("");
        setSelectedPressure("");

        const data = await getOpacityDatasets(selectedMolecule);
        if (!active) return;

        const availableDatasets = data.datasets || [];
        const preferred =
          availableDatasets.find((item) => item.lineList === "Rivlin") ||
          availableDatasets[0];
        setDatasets(availableDatasets);
        setSelectedIsotopologue(preferred?.isotopologue || "");
        setSelectedDataset(preferred?.key || "");
        if (!preferred) {
          setErrorMessage(
            `No TauREx cross-section HDF5 file is published for ${selectedMolecule}.`
          );
        }
      } catch (error) {
        if (active) {
          setErrorMessage(error.message || "Failed to load opacity datasets.");
        }
      } finally {
        if (active) setLoadingDatasets(false);
      }
    }

    loadDatasets();
    return () => {
      active = false;
    };
  }, [selectedMolecule]);

  function handleIsotopologueChange(value) {
    const nextDataset = datasets.find((item) => item.isotopologue === value);
    setSelectedIsotopologue(value);
    setSelectedDataset(nextDataset?.key || "");
  }

  useEffect(() => {
    if (!selectedMolecule || !selectedDataset) return undefined;
    let active = true;

    async function loadOptions() {
      try {
        setLoadingOptions(true);
        setErrorMessage("");
        setOptions(null);
        setSpectrum(null);
        const data = await getOpacityOptions({
          molecule: selectedMolecule,
          datasetKey: selectedDataset,
        });
        if (!active) return;

        const temperatures = data.temperatures || [];
        const pressures = data.pressures || [];
        setOptions(data);
        setSelectedTemperature(
          String(nearestValue(temperatures, DEFAULT_TEMPERATURE))
        );
        setSelectedPressure(
          String(nearestValue(pressures, DEFAULT_PRESSURE))
        );
      } catch (error) {
        if (active) {
          setErrorMessage(error.message || "Failed to prepare opacity data.");
        }
      } finally {
        if (active) setLoadingOptions(false);
      }
    }

    loadOptions();
    return () => {
      active = false;
    };
  }, [selectedMolecule, selectedDataset]);

  useEffect(() => {
    if (
      !options ||
      !selectedMolecule ||
      !selectedDataset ||
      !selectedTemperature ||
      !selectedPressure
    ) {
      return undefined;
    }

    let active = true;

    async function loadSpectrum() {
      try {
        setLoadingSpectrum(true);
        setErrorMessage("");
        const data = await getOpacitySpectrum({
          molecule: selectedMolecule,
          datasetKey: selectedDataset,
          temperature: Number(selectedTemperature),
          pressure: Number(selectedPressure),
          maxPoints: Number(maxPoints),
        });
        if (active) setSpectrum(data);
      } catch (error) {
        if (active) {
          setSpectrum(null);
          setErrorMessage(error.message || "Failed to load opacity spectrum.");
        }
      } finally {
        if (active) setLoadingSpectrum(false);
      }
    }

    loadSpectrum();
    return () => {
      active = false;
    };
  }, [
    options,
    selectedMolecule,
    selectedDataset,
    selectedTemperature,
    selectedPressure,
    maxPoints,
  ]);

  const selectedDatasetEntry = useMemo(
    () => datasets.find((item) => item.key === selectedDataset) || null,
    [datasets, selectedDataset]
  );

  const isotopologues = useMemo(() => {
    const labels = new Map();
    datasets.forEach((item) => {
      if (item.isotopologue) {
        labels.set(item.isotopologue, item.isotopologue);
      }
    });
    return Array.from(labels, ([key, label]) => ({ key, label })).sort((a, b) =>
      a.label.localeCompare(b.label)
    );
  }, [datasets]);

  const visibleDatasets = useMemo(
    () =>
      datasets.filter(
        (item) =>
          !selectedIsotopologue || item.isotopologue === selectedIsotopologue
      ),
    [datasets, selectedIsotopologue]
  );

  const plotSeries = useMemo(() => {
    if (!spectrum) return { x: [], y: [] };

    const x = [];
    const y = [];
    for (let index = 0; index < spectrum.wavenumbers.length; index += 1) {
      const crossSection = spectrum.crossSections[index];
      if (Number.isFinite(crossSection) && crossSection > 0) {
        x.push(spectrum.wavenumbers[index]);
        y.push(crossSection);
      }
    }
    return { x, y };
  }, [spectrum]);

  const matchedSelection =
    spectrum &&
    (spectrum.temperature !== spectrum.requestedTemperature ||
      spectrum.pressure !== spectrum.requestedPressure);
  const busy =
    loadingCatalog || loadingDatasets || loadingOptions || loadingSpectrum;

  return (
    <>
      <div className="visualizer-status">
        <span className={options ? "status-dot online" : "status-dot"} />
        {loadingCatalog
          ? "Loading ExoMolOP catalogue"
          : loadingDatasets
            ? "Finding published datasets"
            : loadingOptions
              ? "Preparing selected HDF5 file"
              : options
                ? "Dataset ready"
                : "Select an available dataset"}
      </div>

      {errorMessage && (
        <div className="alert alert-error" role="alert">
          <strong>Unable to load the visualizer.</strong>
          <span>{errorMessage}</span>
        </div>
      )}

      <section className="dataset-strip" aria-label="Dataset selection">
        <MetricSelect label="Molecule">
          <select
            className="metric-field"
            value={selectedMolecule}
            onChange={(event) => setSelectedMolecule(event.target.value)}
            disabled={loadingCatalog || !molecules.length}
          >
            {molecules.map((item) => (
              <option key={item.key} value={item.key}>
                {item.label}
              </option>
            ))}
          </select>
        </MetricSelect>

        <MetricSelect label="Isotopologue">
          <select
            className="metric-field"
            value={selectedIsotopologue}
            onChange={(event) => handleIsotopologueChange(event.target.value)}
            disabled={loadingDatasets || !isotopologues.length}
          >
            {isotopologues.map((item) => (
              <option key={item.key} value={item.key}>
                {item.label}
              </option>
            ))}
          </select>
        </MetricSelect>

        <MetricSelect label="Dataset">
          <select
            className="metric-field"
            value={selectedDataset}
            onChange={(event) => setSelectedDataset(event.target.value)}
            disabled={loadingDatasets || !visibleDatasets.length}
            title={selectedDatasetEntry?.label || ""}
          >
            {visibleDatasets.map((item) => (
              <option key={item.key} value={item.key}>
                {item.lineList} ({item.configuration})
              </option>
            ))}
          </select>
        </MetricSelect>

        <MetricSelect label="Temperature grid">
          <select
            className="metric-field"
            value={selectedTemperature}
            onChange={(event) => setSelectedTemperature(event.target.value)}
            disabled={loadingOptions || !options}
          >
            {(options?.temperatures || []).map((temperature) => (
              <option key={temperature} value={temperature}>
                {temperature.toLocaleString()} K
              </option>
            ))}
          </select>
        </MetricSelect>

        <MetricSelect label="Pressure grid">
          <select
            className="metric-field"
            value={selectedPressure}
            onChange={(event) => setSelectedPressure(event.target.value)}
            disabled={loadingOptions || !options}
          >
            {(options?.pressures || []).map((pressure) => (
              <option key={pressure} value={pressure}>
                {formatPressure(pressure)} bar
              </option>
            ))}
          </select>
        </MetricSelect>

        <Metric
          label="Native spectrum"
          value={options ? `${formatNumber(options.spectralPointCount)} points` : "-"}
        />
      </section>

      <div className="workspace">
        <aside className="controls-card">
          <div className="section-heading">
            <span className="section-kicker">Display</span>
            <h2>Plot settings</h2>
            <p>
              Molecule, dataset, temperature, and pressure are selected above.
            </p>
          </div>

          <div className="control-stack">
            <Field label="Display resolution">
              <select
                className="field"
                value={maxPoints}
                onChange={(event) => setMaxPoints(event.target.value)}
                disabled={loadingOptions || !options}
              >
                <option value="1000">Fast - 1,000 points</option>
                <option value="1500">Balanced - 1,500 points</option>
                <option value="2000">Desktop max - 2,000 points</option>
              </select>
            </Field>
          </div>

          <div className="selection-summary">
            <SummaryRow
              label="Molecule"
              value={options?.molecule || selectedMolecule || "-"}
            />
            <SummaryRow
              label="Isotopologue"
              value={selectedDatasetEntry?.isotopologue || selectedIsotopologue || "-"}
            />
            <SummaryRow
              label="Dataset"
              value={options?.dataset || selectedDatasetEntry?.dataset || "-"}
            />
            <SummaryRow
              label="Selected temperature"
              value={spectrum ? `${formatNumber(spectrum.temperature)} K` : "-"}
            />
            <SummaryRow
              label="Selected pressure"
              value={spectrum ? `${formatPressure(spectrum.pressure)} bar` : "-"}
            />
            <SummaryRow
              label="Displayed points"
              value={spectrum ? formatNumber(spectrum.pointCount) : "-"}
            />
            <SummaryRow
              label="Wavenumber range"
              value={
                options
                  ? `${Math.round(options.wavenumberMin).toLocaleString()} - ${Math.round(
                      options.wavenumberMax
                    ).toLocaleString()} cm^-1`
                  : "-"
              }
            />
          </div>

          {matchedSelection && (
            <div className="info-note">
              The request was matched to the nearest available temperature and
              pressure.
            </div>
          )}

          <div className="file-note">
            <span>Source file</span>
            <code>{options?.fileName || "Waiting for dataset selection"}</code>
          </div>
        </aside>

        <section className="chart-card">
          <div className="chart-header">
            <div>
              <span className="section-kicker">Cross-section spectrum</span>
              <h2>{spectrum?.dataset || options?.dataset || "TauREx opacity data"}</h2>
              <p>
                Logarithmic cross-section scale. Drag to zoom, scroll to zoom,
                and hover for exact values.
              </p>
            </div>

            <div className="chart-selection">
              <strong>{spectrum ? `${spectrum.temperature} K` : "-"}</strong>
              <span>{spectrum ? `${formatPressure(spectrum.pressure)} bar` : "-"}</span>
            </div>
          </div>

          <div className="chart-shell">
            {busy && (
              <div className="chart-overlay" role="status">
                <span className="spinner" />
                {loadingOptions
                  ? "Downloading or opening selected dataset"
                  : "Reading spectrum"}
              </div>
            )}

            {!spectrum && !busy ? (
              <div className="empty-state">
                <strong>No spectrum available</strong>
                <span>Select a published TauREx opacity dataset above.</span>
              </div>
            ) : (
              <Plot
                data={[
                  {
                    x: plotSeries.x,
                    y: plotSeries.y,
                    type: "scatter",
                    mode: "lines",
                    line: { color: "#176b87", width: 1.2 },
                    hovertemplate:
                      "Wavenumber: %{x:.5g} cm<sup>-1</sup><br>" +
                      "Cross-section: %{y:.4e} cm<sup>2</sup>/molecule<extra></extra>",
                  },
                ]}
                layout={{
                  autosize: true,
                  margin: { l: 82, r: 28, t: 24, b: 70 },
                  paper_bgcolor: "#ffffff",
                  plot_bgcolor: "#fbfcfd",
                  hovermode: "closest",
                  dragmode: "zoom",
                  font: {
                    family: "Arial, Helvetica, sans-serif",
                    color: "#334155",
                    size: 12,
                  },
                  xaxis: {
                    title: { text: "Wavenumber (cm<sup>-1</sup>)", standoff: 18 },
                    showgrid: true,
                    gridcolor: "#e7edf1",
                    zeroline: false,
                    showline: true,
                    linecolor: "#cbd5dc",
                    mirror: true,
                    fixedrange: false,
                  },
                  yaxis: {
                    title: {
                      text: "Cross-section (cm<sup>2</sup>/molecule)",
                      standoff: 12,
                    },
                    type: "log",
                    showgrid: true,
                    gridcolor: "#e7edf1",
                    zeroline: false,
                    showline: true,
                    linecolor: "#cbd5dc",
                    mirror: true,
                    fixedrange: false,
                  },
                }}
                config={{
                  responsive: true,
                  scrollZoom: true,
                  displaylogo: false,
                  modeBarButtonsToRemove: ["select2d", "lasso2d"],
                  toImageButtonOptions: {
                    format: "png",
                    filename: `${spectrum?.dataset || "opacity"}_${spectrum?.temperature || ""}K`,
                    height: 700,
                    width: 1200,
                    scale: 2,
                  },
                }}
                useResizeHandler
                className="spectrum-plot"
              />
            )}
          </div>

          <div className="chart-footer">
            <span>
              Values are read from one pressure-temperature slice of the selected
              HDF5 cube.
            </span>
            <span>Units: {spectrum?.crossSectionUnits || "cm^2/molecule"}</span>
          </div>
        </section>
      </div>
    </>
  );
}

function Field({ label, children }) {
  return (
    <label className="field-group">
      <span className="field-label">{label}</span>
      {children}
    </label>
  );
}

function MetricSelect({ label, children }) {
  return (
    <label className="metric metric-select">
      <span>{label}</span>
      {children}
    </label>
  );
}

function Metric({ label, value }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function SummaryRow({ label, value }) {
  return (
    <div className="summary-row">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
