import OpacityVisualizer from "./OpacityVisualizer";

export default function App() {
  return (
    <main className="page">
      <div className="container">
        <header className="hero">
          <div className="hero-copy">
            <div className="eyebrow">ExoMol opacity app</div>
            <h1>Explore molecular cross-sections</h1>
            <p>
              Select any published ExoMolOP TauREx dataset, then inspect its
              pre-calculated opacity across the available temperature and
              pressure grid.
            </p>
          </div>
        </header>

        <OpacityVisualizer />
      </div>
    </main>
  );
}
