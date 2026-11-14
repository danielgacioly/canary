import { api } from '../api/client'
import { LineChart, Loading, Pill } from '../components/ui'
import { useApi, useSession } from '../state/session'

export default function Mission() {
  const { catalog, mission, setLocation, toast } = useSession()
  const { data: sw } = useApi(() => api.spaceWeather(), [])
  const { data: rad } = useApi(() => api.rad(), [])
  if (!catalog || !mission || !sw || !rad) return <Loading what="mission data" />
  const t0 = sw.kp.length ? Date.parse(sw.kp[0][0]) : 0
  const kp = sw.kp.map(([t, v]) => [(Date.parse(t) - t0) / 36e5, v] as [number, number])
  return (
    <div className="page">
      <div className="hello">
        <div className="col" style={{ gap: 8 }}><span className="lbl">{mission.day_label}</span><h1>Where you are changes everything.</h1></div>
        <div className="right"><Pill level={sw.active ? 2 : 0}>{sw.headline}</Pill></div>
      </div>

      <section className="card">
        <div className="head"><h2>Place</h2><span className="small muted">Gravity, distance and radiation reshape goals, alerts and Guided Response</span></div>
        <div className="places">
          {Object.entries(catalog.locations).map(([k, p]) => (
            <button key={k} className={`place ${mission.location === k ? 'on' : ''}`} onClick={async () => { await setLocation(k); toast(`Now at: ${p.name}`) }}>
              <span className="lbl">{p.sub}</span><b style={{ fontSize: 17 }}>{p.name}</b>
              <dl><dt>Gravity</dt><dd>{p.gravity}</dd><dt>Earth replies</dt><dd>{p.reply}</dd><dt>Hospital</dt><dd>{p.hospital}</dd><dt>Radiation</dt><dd>{p.dose_rate} mSv/day</dd></dl>
              <span className="small muted">{p.what}</span>
            </button>))}
        </div>
      </section>

      <div className="grid g2">
        <section className="card">
          <div className="head"><div><span className="lbl">NASA DONKI · {sw.window}</span><h2 style={{ marginTop: 4 }}>Geomagnetic storm, Kp index</h2></div></div>
          <LineChart series={[{ pts: kp, color: '#ffb547' }]} refY={5} refLabel="storm level (Kp 5)" xLabels={['5 May', '8 May', '11 May', '14 May', '16 May']} yLabel="Kp" />
          <div className="row wrap" style={{ gap: 22, marginTop: 12 }}>
            <div className="kpi"><span className="lbl">Kp max</span><b className="num">{sw.kp_max}</b></div>
            <div className="kpi"><span className="lbl">Solar particle events</span><b className="num">{sw.sep_events}</b></div>
            <div className="kpi"><span className="lbl">CMEs ≥ 900 km/s</span><b className="num">{sw.fast_cmes}</b></div>
            <div className="kpi"><span className="lbl">Linked flares</span><b className="num">{sw.flares}</b></div>
          </div>
          {sw.live && <p className="small muted" style={{ marginTop: 10 }}>Live DONKI, {sw.live.window}: {sw.live.sep_events} particle events, Kp max {sw.live.kp_max}.</p>}
          <p className="small dim" style={{ marginTop: 10 }}>The 10 to 11 May 2024 storm reached Kp 9, the strongest in two decades. Story step 4 replays it on a Mars transit.</p>
        </section>
        <section className="card">
          <div className="head"><div><span className="lbl">Curiosity RAD level 2 · Gale crater</span><h2 style={{ marginTop: 4 }}>Dose rate on Mars, quiet day vs storm</h2></div></div>
          <LineChart series={[{ pts: rad.quiet, color: '#5ef2ff' }, { pts: rad.storm, color: '#ff4d5e' }]} xLabels={['00:00', '06:00', '12:00', '18:00', '24:00']} refY={rad.quietMean} refLabel={`quiet mean ${rad.quietMean}`} yLabel="µGy/day" />
          <div className="row wrap" style={{ gap: 22, marginTop: 12 }}>
            <div className="kpi"><span className="lbl">Quiet day mean</span><b className="num">{rad.quietMean}<small>µGy/day</small></b></div>
            <div className="kpi"><span className="lbl">Storm peak, 20 May 2024</span><b className="num" style={{ color: 'var(--act)' }}>{rad.peak.toLocaleString()}<small>µGy/day</small></b></div>
            <div className="kpi"><span className="lbl">Ratio</span><b className="num">{rad.ratio}×</b></div>
          </div>
          <p className="small dim" style={{ marginTop: 10 }}>Blue: 9 May 2024. Red: 20 May 2024. Story step 6 puts the crew on Mars that day.</p>
        </section>
      </div>

      <section className="card">
        <div className="head"><h2>Communication delay</h2></div>
        <div className="grid g3">
          {(['iss', 'moon', 'mars'] as const).map(k => {
            const p = catalog.locations[k]
            return <div key={k} className="kpi"><span className="lbl">{p.name}</span><b className="num">{p.reply}</b><span className="small muted">Hospital: {p.hospital}</span></div>
          })}
        </div>
        <p className="muted" style={{ marginTop: 12 }}>At Mars a question to the flight surgeon can take up to 24 minutes to arrive and as long to come back. Canary stays on board for that gap: it watches, guides the first response and sends a short report so Earth catches up when the message lands. In the demo, delays run 20 times faster.</p>
      </section>
    </div>
  )
}
