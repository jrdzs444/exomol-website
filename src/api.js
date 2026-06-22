const basePath =
  import.meta.env.BASE_URL === "/"
    ? ""
    : import.meta.env.BASE_URL.replace(/\/$/, "");
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? basePath;

async function request(path, options = {}) {
  let response;

  try {
    response = await fetch(`${API_BASE_URL}${path}`, options);
  } catch {
    throw new Error(
      "Unable to connect to the backend. Please check that the API server is running and that the port/CORS configuration is correct."
    );
  }

  let data = null;
  try {
    data = await response.json();
  } catch {
    data = null;
  }

  if (!response.ok) {
    throw new Error(data?.detail || data?.message || "Request failed.");
  }

  return data;
}

export function getOptions() {
  return request("/api/options");
}

export function getRuntime() {
  return request("/api/runtime");
}

export function getOpacityCatalog() {
  return request("/api/opacities/catalog");
}

export function getOpacityDatasets(molecule) {
  const query = new URLSearchParams({ molecule });
  return request(`/api/opacities/datasets?${query}`);
}

export function getOpacityOptions({ molecule, datasetKey }) {
  const query = new URLSearchParams({ molecule, datasetKey });
  return request(`/api/opacities/options?${query}`);
}

export function getOpacitySpectrum({
  molecule,
  datasetKey,
  temperature,
  pressure,
  maxPoints,
}) {
  const query = new URLSearchParams({
    molecule,
    datasetKey,
    temperature: String(temperature),
    pressure: String(pressure),
    maxPoints: String(maxPoints),
  });
  return request(`/api/opacities/spectrum?${query}`);
}

export function submitJob(payload) {
  return request("/api/submit", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
}

export function getJob(jobId) {
  return request(`/api/jobs/${encodeURIComponent(jobId)}`);
}

export function getJobSpectrum(jobId, maxPoints = 2000) {
  const query = new URLSearchParams({ maxPoints: String(maxPoints) });
  return request(`/api/jobs/${encodeURIComponent(jobId)}/spectrum?${query}`);
}

export { API_BASE_URL };
