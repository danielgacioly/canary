import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import { PlaceGrid } from '../components/Shell'
import { Icon, LineChart, Loading, Tabs } from '../components/ui'
import { useApi, useSession } from '../state/session'

type Tab = 'place' | 'weather' | 'mars' | 'link'

export default function Mission() {
  const { mission, setLocation, toast } = useSession()
  const [params, setParams] = useSearchParams()
  const tab = (params.get('tab') as Tab) || 'place'
  const { data: sw } = useApi(() => api.spaceWeather(), [])
  const { data: rad } = useApi(() => api.rad(), [])
  if (!mission || !sw || !rad) return <Loading what="mission" />
  const t0 = sw.kp.length ? Date.parse(sw.kp[0][0]) : 0
  const kp = sw.kp.map(([t, v]) => [(Date.parse(t) - t0) / 36e5, v] as [number, number])
  return (
    <div className="page">
      <div className="head"><div><h1>{mission.place.name}, {mission.day_label}</h1><p className="sub">{mission.place.what}</p></div></div>
      <Tabs value={tab} onChange={t => setParams(t === 'place' ? {} : { tab: t }, { replace: true })}
        options={[['place', 'Where you are'], ['weather', 'Space weather'], ['mars', 'Radiation on Mars'], ['link', 'Link to Earth']]} />

      {tab === 'place' && <PlaceGrid current={mission.location} onPick={async (k, n) => { await setLocation(k); toast(`Now at: ${n}`) }} />}

      {tab === 'weather' && (
        <div className="grid" style={{ gridTemplateColumns: 'minmax(0, 1fr) 280px', gap: 24, alignItems: 'start' }}>
          <section className="card">
            <h2>Geomagnetic storm, May 2024</h2>
            <p className="small muted" style={{ margin: '4px 0 16px' }}>Kp index from NASA DONKI. Kp 5 and above is a storm.</p>
            <LineChart series={[{ pts: kp, color: 'var(--watch)' }]} refY={5} refLabel="storm (Kp 5)" xLabels={['5 May', '8 May', '11 May', '14 May', '16 May']} />
          </section>
          <aside className="col" style={{ gap: 12 }}>
            {[['Strongest Kp', sw.kp_max], ['Solar particle events', sw.sep_events], ['CMEs at 900 km/s or more', sw.fast_cmes]].map(([k, v]) => (
              <div key={k} className="card pad-sm"><div className="lbl">{k}</div><div className="big-num num" style={{ marginTop: 4 }}>{v}</div></div>))}
            <p className="small dim">Demo step 4 replays this storm on the way to Mars.{sw.live ? ` Live DONKI, ${sw.live.window}: Kp max ${sw.live.kp_max}.` : ''}</p>
          </aside>
        </div>
      )}

      {tab === 'mars' && (
        <div className="grid" style={{ gridTemplateColumns: 'minmax(0, 1fr) 280px', gap: 24, alignItems: 'start' }}>
          <section className="card">
            <h2>Dose rate at Gale crater</h2>
            <p className="small muted" style={{ margin: '4px 0 16px' }}>NASA Curiosity RAD, µGy/day over the day. Grey: 9 May 2024. Red: 20 May 2024.</p>
            <LineChart series={[{ pts: rad.quiet, color: 'var(--muted)' }, { pts: rad.storm, color: 'var(--act)' }]} xLabels={['00:00', '06:00', '12:00', '18:00', '24:00']} />
          </section>
          <aside className="col" style={{ gap: 12 }}>
            <div className="card pad-sm"><div className="lbl">Quiet day</div><div className="big-num num" style={{ marginTop: 4 }}>{rad.quietMean}<small>µGy/day</small></div></div>
            <div className="card pad-sm"><div className="lbl">Storm peak</div><div className="big-num num" style={{ marginTop: 4, color: 'var(--act)' }}>{rad.peak.toLocaleString('en-US')}<small>µGy/day</small></div></div>
            <div className="card pad-sm"><div className="lbl">Times normal</div><div className="big-num num" style={{ marginTop: 4 }}>{rad.ratio}×</div></div>
          </aside>
        </div>
      )}

      {tab === 'link' && <LinkLog />}
    </div>
  )
}

function LinkLog() {
  const { me, mission, bump } = useSession()
  const { data } = useApi(() => api.messages(me ?? undefined), [me])
  const [text, setText] = useState('')
  const [, tick] = useState(0)
  useEffect(() => { const t = setInterval(() => tick(x => x + 1), 1000); return () => clearInterval(t) }, [])
  return (
    <div className="grid" style={{ gridTemplateColumns: 'minmax(0, 1fr) 340px', gap: 24, alignItems: 'start' }}>
      <section className="card">
        <h2>Messages, briefings and reports</h2>
        <p className="small muted" style={{ margin: '4px 0 12px' }}>Everything waits for the real delay from {mission?.place.name} ({mission?.place.reply}), 20 times faster in the demo.</p>
        <div className="list">{(data ?? []).map(m => {
          const eta = Math.max(0, Math.round(m.deliver_at - Date.now() / 1000))
          return (
            <div key={m.id} className={`item s${eta ? 1 : 0}`} style={{ alignItems: 'flex-start' }}>
              <span className="dot" style={{ marginTop: 8 }} />
              <div className="grow"><b>{m.sender} → {m.recipient}</b> <span className="tag">{m.kind}</span><div className="small muted" style={{ whiteSpace: 'pre-line', marginTop: 2 }}>{m.text.slice(0, 220)}</div></div>
              <span className="v small">{eta ? `arrives in ${eta}s` : 'delivered'}</span>
            </div>)
        })}{!data?.length && <p className="muted">Nothing sent yet.</p>}</div>
      </section>
      <form className="card col" onSubmit={async e => { e.preventDefault(); if (!me) return; await api.send(me, 'earth', text); setText(''); bump() }}>
        <h3>Write to Earth</h3>
        <textarea className="in" required rows={4} value={text} onChange={e => setText(e.target.value)} />
        <button className="btn pri" disabled={!text.trim()}><Icon name="send" />Send</button>
      </form>
    </div>
  )
}
