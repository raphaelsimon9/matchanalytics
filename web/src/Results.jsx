import { useEffect, useState } from "react";

const API = import.meta.env.VITE_API_URL || "http://localhost:8000";
const pct = (x) => (x == null ? "–" : `${(x * 100).toFixed(0)}%`);
const num = (x, d = 3) => (x == null ? "–" : x.toFixed(d));

function Row({ label, s, strong }) {
  return (
    <tr className={strong ? "strong" : ""}>
      <td>{label}</td><td>{s.n}</td><td>{pct(s.hit_rate)}</td><td>{pct(s.avg_prob)}</td>
      <td>{num(s.brier)}</td>
      <td className={s.roi == null ? "" : s.roi >= 0 ? "pos" : "neg"}>
        {s.roi == null ? "–" : `${(s.roi * 100).toFixed(1)}%`}{s.priced ? ` (${s.priced})` : ""}
      </td>
    </tr>
  );
}

export default function Results() {
  const [d, setD] = useState(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    fetch(`${API}/api/performance`)
      .then(async (r) => { if (!r.ok) throw new Error((await r.json()).detail || r.statusText); return r.json(); })
      .then(setD).catch((e) => setErr(String(e.message || e)));
  }, []);

  if (err) return <p className="err">{err}</p>;
  if (!d) return <p className="muted">Loading results…</p>;
  const settled = d.markets.reduce((a, m) => a + m.n, 0);

  return (
    <section className="results">
      <p className="muted">
        Every prediction is saved before kickoff and graded after full time. Pending picks: {d.pending}.
        Open the Predictions tab regularly so new matches get logged.
      </p>
      <div className="tablewrap">
        <table>
          <thead>
            <tr><th>Market</th><th>Settled</th><th>Hit rate</th><th>Model avg</th><th>Brier</th><th>ROI (flat, priced)</th></tr>
          </thead>
          <tbody>
            {d.markets.map((m) => <Row key={m.key} label={m.pick} s={m} strong={m.key === "over15" || m.key === "over25"} />)}
            <Row label="Recommended picks" s={d.recommended} strong />
          </tbody>
        </table>
      </div>
      <p className="muted small">
        Hit rate vs Model avg: if the model says 75% on average, the hit rate should be near 75%.
        Brier: lower is better (0.25 is what constant 50% guessing scores). ROI: profit per 1 unit staked,
        only on picks that had real odds (count in brackets). Do not trust any number until a market has 100+ settled picks
        {settled < 100 ? ` – you have ${settled} settled in total so far.` : "."}
      </p>
      <h3>Recent logged picks</h3>
      <div className="tablewrap">
        <table>
          <thead><tr><th>Kickoff</th><th>Match</th><th>Pick</th><th>Model</th><th>Odds</th><th>Result</th></tr></thead>
          <tbody>
            {d.recent.map((r) => (
              <tr key={`${r.match_id}-${r.key}`}>
                <td>{new Date(r.kickoff).toLocaleDateString()}</td>
                <td>{r.home} v {r.away}{r.result != null && ` (${r.hg}-${r.ag})`}</td>
                <td>{r.pick}{r.recommended ? " ★" : ""}</td>
                <td>{pct(r.prob)}</td><td>{r.odds ?? "–"}</td>
                <td className={r.result == null ? "" : r.result ? "pos" : "neg"}>{r.result == null ? "pending" : r.result ? "won" : "lost"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
