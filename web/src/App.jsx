import { useEffect, useMemo, useState } from "react";
import Results from "./Results.jsx";

const APP_NAME = "Stat90"; // change your brand name here

const API = import.meta.env.VITE_API_URL || "http://localhost:8000";
const pct = (x) => `${Math.round(x * 100)}%`;

function Bar({ label, p }) {
  return (
    <div className="bar">
      <span>{label}</span>
      <div className="track"><div className="fill" style={{ width: pct(p) }} /></div>
      <b>{pct(p)}</b>
    </div>
  );
}

function Form({ f }) {
  return (
    <span className="form">
      {f.last5.split("").map((c, i) => <i key={i} className={`f${c}`}>{c}</i>)}
    </span>
  );
}

function OddsStatus({ data }) {
  const ps = data.odds_providers || [];
  if (ps.length === 0)
    return <p className="warn">No odds provider configured, so you only see model favourites. Add an odds key on the server to get value picks.</p>;
  return (
    <div className="oddsbar">
      {ps.map((p) => (
        <span key={p.provider} className={p.ok ? "pos" : "neg"}>
          {p.provider}: {p.ok ? `${p.matched} matches priced` : p.error}
          {p.quota_left != null && ` · ${p.quota_left} left`}
        </span>
      ))}
    </div>
  );
}

function MatchCard({ m, onAdd, inSlip }) {
  const r = m.recommendation;
  const label = `${m.home} v ${m.away}`;
  return (
    <article className="card">
      <header>
        <div>
          <h3>{m.home} <small>vs</small> {m.away}</h3>
          <small>{new Date(m.kickoff).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}</small>
        </div>
      </header>
      <div className="bars">
        <Bar label="Home" p={m.model.home} />
        <Bar label="Draw" p={m.model.draw} />
        <Bar label="Away" p={m.model.away} />
      </div>
      <div className="meta">
        <span>xG {m.model.xg_home} – {m.model.xg_away}</span>
        <span>O1.5 {pct(m.model.over15)}</span>
        <span>O2.5 {pct(m.model.over25)}</span>
        <span>BTTS {pct(m.model.btts_yes)}</span>
      </div>
      <div className="meta">
        <span>{m.home.split(" ")[0]} <Form f={m.form_home} /></span>
        <span>{m.away.split(" ")[0]} <Form f={m.form_away} /></span>
      </div>
      <div className="meta">
        <span>Likely scores: {m.model.top_scores.map((t) => `${t.score} (${pct(t.p)})`).join(" · ")}</span>
      </div>
      <div className="goals">
        {m.candidates.filter((c) => c.key === "over15" || c.key === "over25").map((c) => (
          <div key={c.key} className="goal">
            <span><b>{c.pick}</b> {pct(c.prob)} · {c.odds ? `odds ${c.odds}` : `fair ${c.fair_odds}`}</span>
            {c.odds && (
              <button className="ghost" disabled={inSlip(label, c.pick)}
                onClick={() => onAdd({ match: label, market: c.market, pick: c.pick, odds: c.odds })}>
                {inSlip(label, c.pick) ? "Added" : "Add"}
              </button>
            )}
          </div>
        ))}
      </div>
      {r ? (
        <div className={`rec ${r.confidence}`}>
          <div>
            <b>{r.pick}</b> <small>({r.market})</small>
            <div className="sub">
              Model {pct(r.prob)}
              {r.odds ? ` · odds ${r.odds} (${r.bookmaker}${r.preferred === false ? ", not your bookmaker" : ""}) · edge ${(r.edge * 100).toFixed(1)}%` : ` · fair odds ${r.fair_odds} · no market odds`}
              {` · ${r.confidence} confidence`}
              {r.stake_pct > 0 && ` · suggested ≤ ${(r.stake_pct * 100).toFixed(1)}% of bankroll`}
            </div>
          </div>
          {r.odds && (
            <button disabled={inSlip(label, r.pick)} onClick={() => onAdd({ match: label, market: r.market, pick: r.pick, odds: r.odds })}>
              {inSlip(label, r.pick) ? "Added" : "Add"}
            </button>
          )}
        </div>
      ) : (
        <div className="rec none">{m.sample_ok ? "No edge found – skip this one." : "Not enough data for these teams – skipped."}</div>
      )}
    </article>
  );
}

function Slip({ slip, setSlip, bankroll }) {
  const [stake, setStake] = useState(1000);
  const [res, setRes] = useState(null);
  const [err, setErr] = useState("");
  useEffect(() => { setRes(null); }, [slip]);

  async function calc() {
    setErr("");
    try {
      const r = await fetch(`${API}/api/slip`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ selections: slip, stake: Number(stake), bankroll: bankroll ? Number(bankroll) : null }),
      });
      if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
      setRes(await r.json());
    } catch (e) { setErr(String(e.message || e)); }
  }

  return (
    <aside className="slip">
      <h2>Bet slip ({slip.length})</h2>
      {slip.length === 0 && <p className="muted">Add recommended picks to build a slip.</p>}
      {slip.map((s, i) => (
        <div key={i} className="sel">
          <div><b>{s.pick}</b> @ {s.odds}<br /><small>{s.match}</small></div>
          <button className="ghost" onClick={() => setSlip(slip.filter((_, j) => j !== i))}>✕</button>
        </div>
      ))}
      {slip.length > 0 && (
        <>
          <label>Stake <input type="number" min="1" value={stake} onChange={(e) => setStake(e.target.value)} /></label>
          <button onClick={calc}>Review slip</button>
        </>
      )}
      {err && <p className="err">{err}</p>}
      {res && (
        <div className="result">
          <p>Combined odds <b>{res.combined_odds}</b> · Potential return <b>{res.potential_return}</b></p>
          {res.warnings.map((w, i) => <p key={i} className="warn">⚠ {w}</p>)}
          <button className="ghost" onClick={() => navigator.clipboard.writeText(res.text)}>Copy slip</button>
          <p className="muted">Open your bookmaker, add these selections, review and confirm there:</p>
          <div className="links">
            {res.handoff.map((h) => <a key={h.bookmaker} href={h.url} target="_blank" rel="noreferrer">{h.bookmaker} ↗</a>)}
          </div>
        </div>
      )}
    </aside>
  );
}

export default function App() {
  const [comps, setComps] = useState({ PL: "Premier League" });
  const [comp, setComp] = useState("PL");
  const [days, setDays] = useState(7);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [slip, setSlip] = useState([]);
  const [view, setView] = useState("predictions");
  const [bankroll, setBankroll] = useState(() => localStorage.getItem("bankroll") || "");
  const [onlyPicks, setOnlyPicks] = useState(true);

  useEffect(() => { fetch(`${API}/api/competitions`).then((r) => r.json()).then(setComps).catch(() => {}); }, []);
  useEffect(() => { localStorage.setItem("bankroll", bankroll); }, [bankroll]);
  useEffect(() => {
    setLoading(true); setError(""); setData(null);
    fetch(`${API}/api/predictions?competition=${comp}&days=${days}`)
      .then(async (r) => { if (!r.ok) throw new Error((await r.json()).detail || r.statusText); return r.json(); })
      .then(setData).catch((e) => setError(String(e.message || e))).finally(() => setLoading(false));
  }, [comp, days]);

  const shown = useMemo(() => (data?.matches || []).filter((m) => !onlyPicks || m.recommendation), [data, onlyPicks]);
  const inSlip = (match, pick) => slip.some((s) => s.match === match && s.pick === pick);

  return (
    <div className="app">
      <div className="banner">18+ only. Predictions are probabilities, not guarantees – most bettors lose money over time. Never stake what you cannot afford to lose.</div>
      <header className="top">
        <h1>{APP_NAME}</h1>
        <nav className="tabs">
          <button className={view === "predictions" ? "" : "ghost"} onClick={() => setView("predictions")}>Predictions</button>
          <button className={view === "results" ? "" : "ghost"} onClick={() => setView("results")}>Results log</button>
        </nav>
        <div className="controls" style={{ display: view === "predictions" ? undefined : "none" }}>
          <select value={comp} onChange={(e) => setComp(e.target.value)}>
            {Object.entries(comps).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
            {[3, 7, 14].map((d) => <option key={d} value={d}>Next {d} days</option>)}
          </select>
          <input className="bank" type="number" placeholder="Bankroll" value={bankroll} onChange={(e) => setBankroll(e.target.value)} />
          <label className="chk"><input type="checkbox" checked={onlyPicks} onChange={(e) => setOnlyPicks(e.target.checked)} /> Picks only</label>
        </div>
      </header>
      {view === "results" ? <Results /> : (
      <main className="layout">
        <section>
          {loading && <p className="muted">Crunching numbers…</p>}
          {error && <p className="err">{error}</p>}
          {data && <OddsStatus data={data} />}
          {data && shown.length === 0 && !loading && <p className="muted">No qualifying picks in this window. Skipping is a valid strategy.</p>}
          {shown.map((m) => <MatchCard key={m.id} m={m} inSlip={inSlip} onAdd={(s) => setSlip([...slip, s])} />)}
        </section>
        <Slip slip={slip} setSlip={setSlip} bankroll={bankroll} />
      </main>
      )}
    </div>
  );
}
