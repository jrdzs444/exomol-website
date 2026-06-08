import { useState } from "react";
import JobBuilder from "./JobBuilder";
import OpacityVisualizer from "./OpacityVisualizer";

export default function App() {
  const [activeView, setActiveView] = useState("visualizer");

  return (
    <main className="page">
      <div className="container">
        <nav className="app-tabs" aria-label="Application sections">
          <button
            className={activeView === "visualizer" ? "app-tab active" : "app-tab"}
            type="button"
            onClick={() => setActiveView("visualizer")}
          >
            Opacity visualizer
          </button>
          <button
            className={activeView === "job-builder" ? "app-tab active" : "app-tab"}
            type="button"
            onClick={() => setActiveView("job-builder")}
          >
            ExoCross job builder
          </button>
        </nav>

        <header className="hero">
          <div className="hero-copy">
            <div className="eyebrow">ExoMol opacity app</div>
            <h1>
              {activeView === "visualizer"
                ? "Explore molecular cross-sections"
                : "Prepare an ExoCross calculation"}
            </h1>
            <p>
              {activeView === "visualizer"
                ? "Select any published ExoMolOP TauREx dataset, then inspect its pre-calculated opacity across the available temperature and pressure grid."
                : "Use the original calculation workflow to select line-list data, generate an input file, and prepare an ExoCross job."}
            </p>
          </div>
        </header>

        {activeView === "job-builder" ? (
          <JobBuilder />
        ) : (
          <OpacityVisualizer />
        )}
      </div>
    </main>
  );
}
