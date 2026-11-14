// Space weather (NASA DONKI + Curiosity RAD) and the Link to Earth, as two pages.
import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { CountUp, Icon, LineChart, Loading } from '../components/ui'
import { useApi, useSession } from '../state/session'

export function SpaceWeather() {
  const { data: sw } = useApi(() => api.spaceWeather(), [])
  const { data: rad } = useApi(() => api.rad(), [])
  if (!sw || !rad) return <Loading what="space weather" />
  const t0 = sw.kp.length ? Date.parse(sw.kp[0][0]) : 0
  const kp = sw.kp.map(([t, v]) => [(Date.parse(t) - t0) / 36e5, v] as [number, number])
  return (
    <div className="page">
      <div className="head rise"><div><span className="eyebrow">NASA open data</span><h1 style={{ marginTop: 6 }}>{sw.active ? sw.headline : 'Space weather is calm'}</h1>
        <p className="sub">The storms Canary replays really happened. These are NASA's records.</p></div></div>

      <div className="stats">
        {([['Strongest Kp, May 2024', sw.kp_max, ''], ['Solar particle events', sw.sep_events, ''], ['Storm peak on Mars', rad.peak, 'µGy/day'], ['Times the quiet dose', rad.ratio, '×']] as [string, number, string][]).map(([k, v, u], i) => (
          <div key={k} className="stat rise" style={{ ['--d' as string]: i }}><div className="k">{k}</div><b className="num"><CountUp value={v} dp={v % 1 ? 1 : 0} /><small>{u}</small></b></div>))}
      </div>

      <section className="detail-card rise" style={{ ['--d' as string]: 2 }}>
        <div className="section-head"><h2>Geomagnetic storm, 10 to 16 May 2024</h2><span className="sub">Kp index · NASA DONKI</span></div>
        <LineChart series={[{ pts: kp, color: 'var(--watch)' }]} refY={5} refLabel="storm level (Kp 5)" xLabels={['10 May', '12 May', '14 May', '16 May']} />
        <p className="small dim" style={{ marginTop: 10 }}>The strongest storm in two decades. Demo step 4 puts a crew on the way to Mars inside it.{sw.live ? ` Live DONKI, ${sw.live.window}: Kp max ${sw.live.kp_max}.` : ''}</p>
      </section>

      <section className="detail-card rise" style={{ ['--d' as string]: 3 }}>
        <div className="section-head"><h2>Radiation at Gale crater, Mars</h2><span className="sub">Curiosity RAD · grey 9 May 2024, red 20 May 2024</span></div>
        <LineChart series={[{ pts: rad.quiet, color: 'var(--muted)' }, { pts: rad.storm, color: 'var(--act)' }]} xLabels={['00:00', '06:00', '12:00', '18:00', '24:00']} />
        <p className="small dim" style={{ marginTop: 10 }}>At 06:15 the dose rate reached {rad.peak.toLocaleString('en-US')} µGy/day, {rad.ratio} times the quiet day. Demo step 6 keeps the crew inside that day.</p>
      </section>
    </div>
  )
}

export function LinkToEarth() {
  const { me, mission, bump } = useSession()
  const { data } = useApi(() => api.messages(me ?? undefined), [me])
  const [text, setText] = useState('')
  const [, tick] = useState(0)
  useEffect(() => { const t = setInterval(() => tick(x => x + 1), 1000); return () => clearInterval(t) }, [])
  return (
    <div className="page">
      <div className="head rise"><div><span className="eyebrow">Link to Earth</span><h1 style={{ marginTop: 6 }}>Earth replies {mission?.place.reply === 'Live' ? 'live' : `in ${mission?.place.reply}`}</h1>
        <p className="sub">Messages, briefings and emergency reports wait for the real delay from {mission?.place.name}. 20 times faster in the demo.</p></div></div>
      <div className="grid" style={{ gridTemplateColumns: 'minmax(0, 1fr) 360px', gap: 24, alignItems: 'start' }}>
        <section className="detail-card rise">
          <div className="list">{(data ?? []).map(m => {
            const eta = Math.max(0, Math.round(m.deliver_at - Date.now() / 1000))
            return (
              <div key={m.id} className={`item s${eta ? 1 : 0}`} style={{ alignItems: 'flex-start' }}>
                <span className="dot" style={{ marginTop: 8 }} />
                <div className="grow"><b>{m.sender} → {m.recipient}</b> <span className="tag">{m.kind}</span><div className="small muted" style={{ whiteSpace: 'pre-line', marginTop: 2 }}>{m.text.slice(0, 260)}</div></div>
                <span className="v small">{eta ? `arrives in ${eta}s` : 'delivered'}</span>
              </div>)
          })}{!data?.length && <p className="muted">Nothing sent yet. Write below, or approve a briefing in the medical console.</p>}</div>
        </section>
        <form className="detail-card col rise" style={{ ['--d' as string]: 1 }} onSubmit={async e => { e.preventDefault(); if (!me) return; await api.send(me, 'earth', text); setText(''); bump() }}>
          <h3>Write to Earth</h3>
          <textarea className="in" required rows={5} value={text} onChange={e => setText(e.target.value)} />
          <button className="btn pri" disabled={!text.trim()}><Icon name="send" />Send</button>
        </form>
      </div>
    </div>
  )
}
