import { useEffect, useMemo, useState } from "react";
import { API_BASE_URL, getOptions, submitJob } from "./api";

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

export default function App() {
  const [catalog, setCatalog] = useState([]);
  const [databaseVersion, setDatabaseVersion] = useState("");
  const [selectedMolecule, setSelectedMolecule] = useState("");
  const [selectedIsotopologue, setSelectedIsotopologue] = useState("");
  const [selectedLineList, setSelectedLineList] = useState("");
  const [form, setForm] = useState(buildDefaultForm());
  const [loadingOptions, setLoadingOptions] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [result, setResult] = useState(null);

  useEffect(() => {
    async function loadOptions() {
      try {
        setLoadingOptions(true);
        setErrorMessage("");

        const data = await getOptions();
        const molecules = data.molecules || [];

        setCatalog(molecules);
        setDatabaseVersion(data.databaseVersion || "");

        if (molecules.length === 0) {
          setErrorMessage("Backend connected, but no molecules were found. Please check EXOMOL.master.");
          return;
        }

        const firstMolecule = molecules[0] || null;
        const firstIso = firstMolecule?.isotopologues?.[0] || null;
        const firstLineList = firstIso?.lineLists?.[0] || null;

        setSelectedMolecule(firstMolecule?.key || "");
        setSelectedIsotopologue(firstIso?.key || "");
        setSelectedLineList(firstLineList?.key || "");
        setForm(buildDefaultForm(firstLineList?.massDa || ""));
      } catch (error) {
        setErrorMessage(error.message || "Failed to load molecule data.");
      } finally {
        setLoadingOptions(false);
      }
    }

    loadOptions();
  }, []);

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

    if (moleculeEntry && isotopologueOptions.length === 0) {
      setSelectedIsotopologue("");
      setSelectedLineList("");
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

    if (isotopologueEntry && lineListOptions.length === 0) {
      setSelectedLineList("");
    }
  }, [isotopologueEntry, lineListOptions, selectedLineList]);

  useEffect(() => {
    if (!lineListEntry) return;

    setForm((prev) => {
      const nextMass = lineListEntry.massDa ? String(lineListEntry.massDa) : prev.mass;
      if (prev.mass === nextMass) return prev;
      return { ...prev, mass: nextMass };
    });
  }, [lineListEntry]);

  function updateField(name, value) {
    setForm((prev) => ({ ...prev, [name]: value }));
  }

  function resetExampleValues() {
    setForm(buildDefaultForm(lineListEntry?.massDa || ""));
    setResult(null);
    setErrorMessage("");
  }

  async function handleSubmit(event) {
    event.preventDefault();
    setSubmitting(true);
    setErrorMessage("");
    setResult(null);

    try {
      const payload = {
        molecule: selectedMolecule,
        isotopologue: selectedIsotopologue,
        lineList: selectedLineList,
        temperature: Number(form.temperature),
        rangeMin: Number(form.rangeMin),
        rangeMax: Number(form.rangeMax),
        npoints: Number(form.npoints),
        profile: form.profile,
        mass: Number(form.mass),
      };

      const response = await submitJob(payload);
      setResult(response);
    } catch (error) {
      setErrorMessage(error.message || "Job submission failed.");
    } finally {
      setSubmitting(false);
    }
  }

  const resolvedFiles = result?.resolvedFiles || lineListEntry?.files || null;
  const missingFiles = result?.missingFiles || [];
  const preparedFiles = result?.preparedFiles || {};
  const remoteFiles = result?.remoteFiles || {};

  return (
    <div className="page">
      <div className="container">
        <header className="hero">
          <div>
            <div className="eyebrow">ExoMol / ExoCross prototype</div>
            <h1>ExoMol Opacity App</h1>
            <p className="hero-text">
              Select a molecule, isotopologue, and line list to prepare an ExoCross opacity request.
            </p>
          </div>

          <div className="hero-meta">
            <div className="meta-card">
              <div className="meta-label">Database version</div>
              <div className="meta-value">{databaseVersion || "-"}</div>
            </div>
            <div className="meta-card">
              <div className="meta-label">Molecule count</div>
              <div className="meta-value">{catalog.length || 0}</div>
            </div>
          </div>
        </header>

        {errorMessage && <div className="alert alert-error">{errorMessage}</div>}

        <div className="layout">
          <section className="panel">
            <div className="panel-header">
              <h2>Opacity request</h2>
              <p>Core physical inputs for generating an ExoCross job.</p>
            </div>

            <form className="form" onSubmit={handleSubmit}>
              <div className="form-grid">
                <Field label="Molecule">
                  <select
                    className="field"
                    value={selectedMolecule}
                    onChange={(event) => setSelectedMolecule(event.target.value)}
                    disabled={loadingOptions}
                  >
                    {catalog.length === 0 ? (
                      <option value="">
                        {loadingOptions ? "Loading..." : "No molecules loaded"}
                      </option>
                    ) : (
                      catalog.map((item) => (
                        <option key={item.key} value={item.key}>
                          {item.label}
                        </option>
                      ))
                    )}
                  </select>
                </Field>

                <Field label="Isotopologue">
                  <select
                    className="field"
                    value={selectedIsotopologue}
                    onChange={(event) => setSelectedIsotopologue(event.target.value)}
                    disabled={loadingOptions || isotopologueOptions.length === 0}
                  >
                    {isotopologueOptions.length === 0 ? (
                      <option value="">
                        {selectedMolecule ? "No isotopologues" : "Select molecule first"}
                      </option>
                    ) : (
                      isotopologueOptions.map((item) => (
                        <option key={item.key} value={item.key}>
                          {item.label}
                        </option>
                      ))
                    )}
                  </select>
                </Field>

                <Field label="Line list">
                  <select
                    className="field"
                    value={selectedLineList}
                    onChange={(event) => setSelectedLineList(event.target.value)}
                    disabled={loadingOptions || lineListOptions.length === 0}
                  >
                    {lineListOptions.length === 0 ? (
                      <option value="">
                        {selectedIsotopologue ? "No line lists" : "Select isotopologue first"}
                      </option>
                    ) : (
                      lineListOptions.map((item) => (
                        <option key={item.key} value={item.key}>
                          {item.label}{item.version ? ` (${item.version})` : ""}
                        </option>
                      ))
                    )}
                  </select>
                </Field>

                <Field label="Profile">
                  <select
                    className="field"
                    value={form.profile}
                    onChange={(event) => updateField("profile", event.target.value)}
                  >
                    <option value="Doppler">Doppler</option>
                  </select>
                </Field>

                <Field label="Temperature (K)">
                  <input
                    className="field"
                    value={form.temperature}
                    onChange={(event) => updateField("temperature", event.target.value)}
                  />
                </Field>

                <Field label="Mass (Da)">
                  <input
                    className="field"
                    value={form.mass}
                    onChange={(event) => updateField("mass", event.target.value)}
                  />
                </Field>

                <Field label="Range min (cm^-1)">
                  <input
                    className="field"
                    value={form.rangeMin}
                    onChange={(event) => updateField("rangeMin", event.target.value)}
                  />
                </Field>

                <Field label="Range max (cm^-1)">
                  <input
                    className="field"
                    value={form.rangeMax}
                    onChange={(event) => updateField("rangeMax", event.target.value)}
                  />
                </Field>

                <Field label="Npoints">
                  <input
                    className="field"
                    value={form.npoints}
                    onChange={(event) => updateField("npoints", event.target.value)}
                  />
                </Field>
              </div>

              <div className="resolved-box">
                <div className="resolved-title">Resolved ExoCross file names</div>

                <div className="resolved-row">
                  <span>States</span>
                  <code>{resolvedFiles?.states || "-"}</code>
                </div>

                <div className="resolved-row">
                  <span>Transitions</span>
                  <code>{resolvedFiles?.transitions || "-"}</code>
                </div>

                <div className="resolved-row">
                  <span>Partition function</span>
                  <code>{resolvedFiles?.pf || "-"}</code>
                </div>
              </div>

              <div className="button-row">
                <button
                  className="button button-primary"
                  type="submit"
                  disabled={
                    submitting ||
                    loadingOptions ||
                    !selectedMolecule ||
                    !selectedIsotopologue ||
                    !selectedLineList
                  }
                >
                  {submitting ? "Running..." : "Submit job"}
                </button>

                <button className="button" type="button" onClick={resetExampleValues}>
                  Reset example values
                </button>
              </div>
            </form>
          </section>

          <aside className="panel">
            <div className="panel-header">
              <h2>Current selection</h2>
              <p>Current request details and job status.</p>
            </div>

            <div className="summary-list">
              <SummaryRow label="Molecule" value={selectedMolecule || "-"} />
              <SummaryRow label="Isotopologue" value={selectedIsotopologue || "-"} />
              <SummaryRow label="Line list" value={selectedLineList || "-"} />
              <SummaryRow label="Temperature" value={`${form.temperature || "-"} K`} />
              <SummaryRow
                label="Range"
                value={`${form.rangeMin || "-"} to ${form.rangeMax || "-"} cm^-1`}
              />
              <SummaryRow label="Npoints" value={form.npoints || "-"} />
              <SummaryRow label="Mass" value={form.mass || "-"} />
            </div>

            <div className="result-box">
              <div className="result-title">Result</div>

              <div className="result-item">
                <span>Status</span>
                <strong>{result?.status || (loadingOptions ? "loading_options" : "ready")}</strong>
              </div>

              <div className="result-item">
                <span>Message</span>
                <strong>{result?.message || "No job submitted yet."}</strong>
              </div>

              <div className="result-item">
                <span>Job ID</span>
                <strong>{result?.jobId || "Not created yet"}</strong>
              </div>

              <div className="result-item">
                <span>Input file</span>
                <strong>{result?.inputFileName || "Not created yet"}</strong>
              </div>

              <div className="result-item">
                <span>Output file</span>
                <strong>{result?.outputFileName || "Not available yet"}</strong>
              </div>

              <div className="result-item">
                <span>Run attempted</span>
                <strong>{result?.runAttempted ? "Yes" : "No"}</strong>
              </div>

              <div className="button-row" style={{ marginTop: "16px" }}>
                {result ? (
                  <a
                    className="button"
                    href={`${API_BASE_URL}${result.downloadUrl}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Download input
                  </a>
                ) : (
                  <button className="button button-disabled" disabled>
                    Download input
                  </button>
                )}

                {result?.outputDownloadUrl ? (
                  <a
                    className="button"
                    href={`${API_BASE_URL}${result.outputDownloadUrl}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Download output
                  </a>
                ) : (
                  <button className="button button-disabled" disabled>
                    Download output
                  </button>
                )}
              </div>

              {result?.datasetPageUrl && (
                <div className="preview-box">
                  <div className="preview-title">Dataset page</div>
                  <pre>{result.datasetPageUrl}</pre>
                </div>
              )}

              {missingFiles.length > 0 && (
                <div className="preview-box">
                  <div className="preview-title">Missing files / stages</div>
                  <pre>{missingFiles.join("\n")}</pre>
                </div>
              )}

              {Object.keys(remoteFiles).length > 0 && (
                <div className="preview-box">
                  <div className="preview-title">Remote files</div>
                  <pre>{JSON.stringify(remoteFiles, null, 2)}</pre>
                </div>
              )}

              {Object.keys(preparedFiles).length > 0 && (
                <div className="preview-box">
                  <div className="preview-title">Prepared local files</div>
                  <pre>{JSON.stringify(preparedFiles, null, 2)}</pre>
                </div>
              )}

              {result?.stdoutDownloadUrl && (
                <div className="button-row" style={{ marginTop: "16px" }}>
                  <a
                    className="button"
                    href={`${API_BASE_URL}${result.stdoutDownloadUrl}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Download stdout
                  </a>
                  <a
                    className="button"
                    href={`${API_BASE_URL}${result.stderrDownloadUrl}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Download stderr
                  </a>
                </div>
              )}

              <div className="preview-box">
                <div className="preview-title">Input preview</div>
                <pre>{result?.inputContent || "Submit a job to preview the generated ExoCross input file."}</pre>
              </div>
            </div>
          </aside>
        </div>
      </div>
    </div>
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

function SummaryRow({ label, value }) {
  return (
    <div className="summary-row">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
