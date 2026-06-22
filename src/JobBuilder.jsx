import { useEffect, useMemo, useState } from "react";
import createPlotlyComponentModule from "react-plotly.js/factory";
import Plotly from "plotly.js-basic-dist-min";
import {
  API_BASE_URL,
  getJob,
  getJobSpectrum,
  getOptions,
  getRuntime,
  submitJob,
} from "./api";

const POLLABLE_STATUSES = new Set(["queued", "running", "waiting_for_exocross"]);
const createPlotlyComponent =
  createPlotlyComponentModule.default || createPlotlyComponentModule;
const Plot = createPlotlyComponent(Plotly);

function buildDefaultForm(mass = "") {
  return {
    temperature: "296",
    rangeMin: "0",
    rangeMax: "10000",
    npoints: "10000",
    profile: "Doppler",
    mass: mass ? String(mass) : "",
  };
}

export default function JobBuilder() {
  const [catalog, setCatalog] = useState([]);
  const [databaseVersion, setDatabaseVersion] = useState("");
  const [selectedMolecule, setSelectedMolecule] = useState("");
  const [selectedIsotopologue, setSelectedIsotopologue] = useState("");
  const [selectedLineList, setSelectedLineList] = useState("");
  const [form, setForm] = useState(buildDefaultForm());
  const [runtime, setRuntime] = useState(null);
  const [loadingRuntime, setLoadingRuntime] = useState(true);
  const [loadingOptions, setLoadingOptions] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [result, setResult] = useState(null);
  const [outputSpectrum, setOutputSpectrum] = useState(null);
  const [loadingOutputSpectrum, setLoadingOutputSpectrum] = useState(false);

  const jobBuilderEnabled = Boolean(runtime?.jobBuilderEnabled);

  useEffect(() => {
    let active = true;

    async function loadRuntime() {
      try {
        setLoadingRuntime(true);
        const data = await getRuntime();
        if (active) setRuntime(data);
      } catch (error) {
        if (active) {
          setRuntime({ jobBuilderEnabled: false });
          setErrorMessage(error.message || "Failed to load runtime configuration.");
        }
      } finally {
        if (active) setLoadingRuntime(false);
      }
    }

    loadRuntime();
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    let active = true;

    async function loadOptions() {
      if (!jobBuilderEnabled) {
        setLoadingOptions(false);
        setErrorMessage("");
        return;
      }

      try {
        setLoadingOptions(true);
        setErrorMessage("");
        const data = await getOptions();
        if (!active) return;

        const molecules = data.molecules || [];
        const firstMolecule = molecules[0] || null;
        const firstIso = firstMolecule?.isotopologues?.[0] || null;
        const firstLineList = firstIso?.lineLists?.[0] || null;

        setCatalog(molecules);
        setDatabaseVersion(data.databaseVersion || "");
        setSelectedMolecule(firstMolecule?.key || "");
        setSelectedIsotopologue(firstIso?.key || "");
        setSelectedLineList(firstLineList?.key || "");
        setForm(buildDefaultForm(firstLineList?.massDa || ""));
      } catch (error) {
        if (active) {
          setErrorMessage(error.message || "Failed to load molecule data.");
        }
      } finally {
        if (active) setLoadingOptions(false);
      }
    }

    loadOptions();
    return () => {
      active = false;
    };
  }, [jobBuilderEnabled]);

  useEffect(() => {
    if (!result?.jobId || !POLLABLE_STATUSES.has(result.status)) return undefined;

    let active = true;
    const timer = window.setInterval(async () => {
      try {
        const next = await getJob(result.jobId);
        if (active) setResult(next);
      } catch (error) {
        if (active) {
          setErrorMessage(error.message || "Failed to refresh job status.");
        }
      }
    }, 5000);

    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [result?.jobId, result?.status]);

  useEffect(() => {
    let active = true;

    async function loadOutputSpectrum() {
      if (!result?.jobId || !result.outputSpectrumUrl) {
        setOutputSpectrum(null);
        return;
      }

      try {
        setLoadingOutputSpectrum(true);
        const data = await getJobSpectrum(result.jobId, 2000);
        if (active) setOutputSpectrum(data);
      } catch {
        if (active) setOutputSpectrum(null);
      } finally {
        if (active) setLoadingOutputSpectrum(false);
      }
    }

    loadOutputSpectrum();
    return () => {
      active = false;
    };
  }, [result?.jobId, result?.outputSpectrumUrl]);

  const moleculeEntry = useMemo(
    () => catalog.find((item) => item.key === selectedMolecule) || null,
    [catalog, selectedMolecule]
  );
  const isotopologueOptions = useMemo(
    () => moleculeEntry?.isotopologues || [],
    [moleculeEntry]
  );
  const isotopologueEntry = useMemo(
    () =>
      isotopologueOptions.find((item) => item.key === selectedIsotopologue) ||
      isotopologueOptions[0] ||
      null,
    [isotopologueOptions, selectedIsotopologue]
  );
  const lineListOptions = useMemo(
    () => isotopologueEntry?.lineLists || [],
    [isotopologueEntry]
  );
  const lineListEntry = useMemo(
    () =>
      lineListOptions.find((item) => item.key === selectedLineList) ||
      lineListOptions[0] ||
      null,
    [lineListOptions, selectedLineList]
  );

  useEffect(() => {
    if (!moleculeEntry && catalog.length > 0) {
      setSelectedMolecule(catalog[0].key);
      return;
    }

    if (
      moleculeEntry &&
      isotopologueOptions.length > 0 &&
      !isotopologueOptions.some((item) => item.key === selectedIsotopologue)
    ) {
      setSelectedIsotopologue(isotopologueOptions[0].key);
    }
  }, [catalog, moleculeEntry, isotopologueOptions, selectedIsotopologue]);

  useEffect(() => {
    if (
      isotopologueEntry &&
      lineListOptions.length > 0 &&
      !lineListOptions.some((item) => item.key === selectedLineList)
    ) {
      setSelectedLineList(lineListOptions[0].key);
    }
  }, [isotopologueEntry, lineListOptions, selectedLineList]);

  useEffect(() => {
    if (!lineListEntry) return;
    setForm((previous) => ({
      ...previous,
      mass: lineListEntry.massDa ? String(lineListEntry.massDa) : previous.mass,
    }));
  }, [lineListEntry]);

  function updateField(name, value) {
    setForm((previous) => ({ ...previous, [name]: value }));
  }

  async function handleSubmit(event) {
    event.preventDefault();
    if (!jobBuilderEnabled) {
      setErrorMessage(
        runtime?.disabledReason ||
          "ExoCross/HPC job submission is not enabled on this server."
      );
      return;
    }

    setSubmitting(true);
    setErrorMessage("");
    setResult(null);
    setOutputSpectrum(null);

    try {
      const response = await submitJob({
        molecule: selectedMolecule,
        isotopologue: selectedIsotopologue,
        lineList: selectedLineList,
        temperature: Number(form.temperature),
        rangeMin: Number(form.rangeMin),
        rangeMax: Number(form.rangeMax),
        npoints: Number(form.npoints),
        profile: form.profile,
        mass: Number(form.mass),
      });
      setResult(response);
    } catch (error) {
      setErrorMessage(error.message || "Job submission failed.");
    } finally {
      setSubmitting(false);
    }
  }

  const resolvedFiles = result?.resolvedFiles || lineListEntry?.files || {};

  return (
    <section className="job-page">
      <div className="job-intro">
        <div>
          <span className="section-kicker">ExoCross workflow</span>
          <h2>Prepare an opacity calculation</h2>
          <p>
            Select a molecule, isotopologue, line list, and calculation range.
            When the server has a configured ExoCross runner, this form prepares
            the input files and submits the calculation.
          </p>
        </div>
        <div className="job-database">
          <span>EXOMOL.master</span>
          <strong>
            {databaseVersion || (loadingRuntime || loadingOptions ? "Loading" : "-")}
          </strong>
          <small>{catalog.length} molecules</small>
        </div>
      </div>

      {errorMessage && (
        <div className="alert alert-error" role="alert">
          <strong>Job builder error.</strong>
          <span>{errorMessage}</span>
        </div>
      )}

      {!jobBuilderEnabled && (
        <div className="alert alert-warning" role="note">
          <strong>Task 2 is not active on this server.</strong>
          <span>
            {runtime?.disabledReason ||
              "The UI is ready, but a real ExoCross executable or HPC submission script has not been configured."}
          </span>
        </div>
      )}

      {jobBuilderEnabled && !runtime?.canRunExocross && (
        <div className="alert alert-warning" role="note">
          <strong>Prepare-only mode.</strong>
          <span>
            Jobs can create input and resolve dataset files, but this deployment
            is not configured to run ExoCross automatically.
          </span>
        </div>
      )}

      <div className="job-layout">
        <form className="job-form-card" onSubmit={handleSubmit}>
          <div className="job-card-header">
            <h3>Calculation parameters</h3>
            <p>These values are written into the generated ExoCross input file.</p>
          </div>

          <div className="job-form-grid">
            <JobField label="Molecule">
              <select
                className="field"
                value={selectedMolecule}
                onChange={(event) => setSelectedMolecule(event.target.value)}
                disabled={!jobBuilderEnabled || loadingOptions}
              >
                {catalog.map((item) => (
                  <option key={item.key} value={item.key}>
                    {item.label}
                  </option>
                ))}
              </select>
            </JobField>

            <JobField label="Isotopologue">
              <select
                className="field"
                value={selectedIsotopologue}
                onChange={(event) => setSelectedIsotopologue(event.target.value)}
                disabled={!jobBuilderEnabled || !isotopologueOptions.length}
              >
                {isotopologueOptions.map((item) => (
                  <option key={item.key} value={item.key}>
                    {item.label}
                  </option>
                ))}
              </select>
            </JobField>

            <JobField label="Line list">
              <select
                className="field"
                value={selectedLineList}
                onChange={(event) => setSelectedLineList(event.target.value)}
                disabled={!jobBuilderEnabled || !lineListOptions.length}
              >
                {lineListOptions.map((item) => (
                  <option key={item.key} value={item.key}>
                    {item.label}
                    {item.version ? ` (${item.version})` : ""}
                  </option>
                ))}
              </select>
            </JobField>

            <JobField label="Profile">
              <select
                className="field"
                value={form.profile}
                onChange={(event) => updateField("profile", event.target.value)}
                disabled={!jobBuilderEnabled}
              >
                <option value="Doppler">Doppler</option>
              </select>
            </JobField>

            <JobField label="Temperature (K)">
              <input
                className="field"
                type="number"
                min="1"
                value={form.temperature}
                onChange={(event) => updateField("temperature", event.target.value)}
                disabled={!jobBuilderEnabled}
              />
            </JobField>

            <JobField label="Mass (Da)">
              <input
                className="field"
                type="number"
                min="0.000001"
                step="any"
                value={form.mass}
                onChange={(event) => updateField("mass", event.target.value)}
                disabled={!jobBuilderEnabled}
              />
            </JobField>

            <JobField label="Range minimum (cm^-1)">
              <input
                className="field"
                type="number"
                min="0"
                step="any"
                value={form.rangeMin}
                onChange={(event) => updateField("rangeMin", event.target.value)}
                disabled={!jobBuilderEnabled}
              />
            </JobField>

            <JobField label="Range maximum (cm^-1)">
              <input
                className="field"
                type="number"
                min="0"
                step="any"
                value={form.rangeMax}
                onChange={(event) => updateField("rangeMax", event.target.value)}
                disabled={!jobBuilderEnabled}
              />
            </JobField>

            <JobField label="Number of points">
              <input
                className="field"
                type="number"
                min="2"
                value={form.npoints}
                onChange={(event) => updateField("npoints", event.target.value)}
                disabled={!jobBuilderEnabled}
              />
            </JobField>
          </div>

          <div className="job-files">
            <h4>Resolved dataset files</h4>
            <FileRow label="States" value={resolvedFiles.states} />
            <FileRow label="Transitions" value={resolvedFiles.transitions} />
            <FileRow label="Partition function" value={resolvedFiles.pf} />
          </div>

          <div className="job-actions">
            <button
              className="primary-action"
              type="submit"
              disabled={
                submitting ||
                !jobBuilderEnabled ||
                loadingOptions ||
                !selectedMolecule ||
                !selectedIsotopologue ||
                !selectedLineList
              }
            >
              {!jobBuilderEnabled
                ? "Submission not configured"
                : submitting
                  ? "Preparing calculation..."
                  : runtime?.canRunExocross
                    ? "Submit ExoCross job"
                    : "Prepare ExoCross input"}
            </button>
            <button
              className="secondary-action"
              type="button"
              onClick={() => {
                setForm(buildDefaultForm(lineListEntry?.massDa || ""));
                setResult(null);
                setOutputSpectrum(null);
                setErrorMessage("");
              }}
              disabled={!jobBuilderEnabled}
            >
              Reset values
            </button>
          </div>
        </form>

        <aside className="job-result-card">
          <div className="job-card-header">
            <h3>Job result</h3>
            <p>Generated files and execution state appear here.</p>
          </div>

          <div className={`job-status job-status-${result?.status || "idle"}`}>
            <span>Status</span>
            <strong>
              {result?.status ||
                (jobBuilderEnabled ? "Ready" : "Not configured")}
            </strong>
            <p>
              {result?.message ||
                (jobBuilderEnabled
                  ? "Submit a calculation to create job files and, when configured, run ExoCross."
                  : runtime?.disabledReason ||
                    "A real ExoCross runner or HPC submission script is required before this can run.")}
            </p>
          </div>

          <div className="job-result-list">
            <ResultRow label="Job ID" value={result?.jobId || "-"} />
            <ResultRow label="Input file" value={result?.inputFileName || "-"} />
            <ResultRow label="Output file" value={result?.outputFileName || "-"} />
            <ResultRow
              label="Run attempted"
              value={result ? (result.runAttempted ? "Yes" : "No") : "-"}
            />
          </div>

          <div className="job-downloads">
            {result ? (
              <a
                className="secondary-action"
                href={`${API_BASE_URL}${result.downloadUrl}`}
                target="_blank"
                rel="noreferrer"
              >
                Download input
              </a>
            ) : (
              <button className="secondary-action" type="button" disabled>
                Download input
              </button>
            )}
            {result?.outputDownloadUrl ? (
              <a
                className="secondary-action"
                href={`${API_BASE_URL}${result.outputDownloadUrl}`}
                target="_blank"
                rel="noreferrer"
              >
                Download output
              </a>
            ) : (
              <button className="secondary-action" type="button" disabled>
                Download output
              </button>
            )}
            {result?.stdoutDownloadUrl && (
              <a
                className="secondary-action"
                href={`${API_BASE_URL}${result.stdoutDownloadUrl}`}
                target="_blank"
                rel="noreferrer"
              >
                Download stdout
              </a>
            )}
            {result?.stderrDownloadUrl && (
              <a
                className="secondary-action"
                href={`${API_BASE_URL}${result.stderrDownloadUrl}`}
                target="_blank"
                rel="noreferrer"
              >
                Download stderr
              </a>
            )}
          </div>

          <div className="job-preview">
            <span>Input preview</span>
            <pre>
              {result?.inputContent ||
                "The generated ExoCross input file will be shown here."}
            </pre>
          </div>

          {(loadingOutputSpectrum || outputSpectrum) && (
            <div className="job-output-plot">
              <span>Output spectrum</span>
              {loadingOutputSpectrum && !outputSpectrum ? (
                <p>Reading output spectrum...</p>
              ) : (
                <Plot
                  data={[
                    {
                      x: outputSpectrum.wavenumber,
                      y: outputSpectrum.crossSection,
                      type: "scatter",
                      mode: "lines",
                      line: { color: "#0f6f8f", width: 1.4 },
                    },
                  ]}
                  layout={{
                    autosize: true,
                    margin: { l: 64, r: 20, t: 24, b: 56 },
                    paper_bgcolor: "rgba(0,0,0,0)",
                    plot_bgcolor: "rgba(248,251,252,0.72)",
                    xaxis: {
                      title: { text: "Wavenumber (cm^-1)" },
                      zeroline: false,
                    },
                    yaxis: {
                      title: { text: "Cross-section" },
                      type: "log",
                      zeroline: false,
                    },
                    showlegend: false,
                  }}
                  config={{ responsive: true, displaylogo: false }}
                  useResizeHandler
                  className="plotly-chart"
                />
              )}
            </div>
          )}

          {result?.missingFiles?.length > 0 && (
            <div className="job-warning">
              Missing stages: {result.missingFiles.join(", ")}
            </div>
          )}
        </aside>
      </div>
    </section>
  );
}

function JobField({ label, children }) {
  return (
    <label className="field-group">
      <span className="field-label">{label}</span>
      {children}
    </label>
  );
}

function FileRow({ label, value }) {
  return (
    <div className="job-file-row">
      <span>{label}</span>
      <code>{value || "-"}</code>
    </div>
  );
}

function ResultRow({ label, value }) {
  return (
    <div className="job-result-row">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
