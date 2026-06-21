import { useState } from "react";
import JobBuilder from "./JobBuilder";
import OpacityVisualizer from "./OpacityVisualizer";

export default function App() {
  const [activeTab, setActiveTab] = useState("visualizer");

  return (
    <main className="page">
      <div className="container">
        <div className="app-tabs" role="tablist" aria-label="ExoMol app modes">
          <button
            className={`app-tab ${activeTab === "visualizer" ? "active" : ""}`}
            type="button"
            role="tab"
            aria-selected={activeTab === "visualizer"}
            onClick={() => setActiveTab("visualizer")}
          >
            Existing opacity visualizer
          </button>
          <button
            className={`app-tab ${activeTab === "job-builder" ? "active" : ""}`}
            type="button"
            role="tab"
            aria-selected={activeTab === "job-builder"}
            onClick={() => setActiveTab("job-builder")}
          >
            ExoCross job builder
          </button>
        </div>

        <header className="hero">
          <div className="hero-copy">
            <div className="eyebrow">ExoMol opacity app</div>
            <h1>
              {activeTab === "visualizer"
                ? "Explore molecular cross-sections"
                : "Prepare future ExoCross workflows"}
            </h1>
            <p>
              {activeTab === "visualizer"
                ? "Select any published ExoMolOP TauREx dataset, then inspect its pre-calculated opacity across the available temperature and pressure grid."
                : "Review the earlier calculation builder prototype. Public HPC submission is disabled until authentication, quota control, and queue integration are agreed."}
            </p>
          </div>
        </header>

        {activeTab === "visualizer" ? <OpacityVisualizer /> : <JobBuilder />}
      </div>
    </main>
  );
}
