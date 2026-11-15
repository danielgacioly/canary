// Protocols: the knowledge page. Every protocol in one place: the emergency ones (they start in Guided Response) and the
// operational ones (EVA, dose, space sickness...). "In force now" lists what applies to the crew today.
// Crew-wide, so it carries the place, the storm and the rules, never anyone's health.
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { InForce, ProtocolLibrary, ProtocolPage } from '../api/types'
import { Icon, Loading } from '../components/ui'
import { useApi, useSession } from '../state/session'

const OPS = { full: 'Fit for all duties', limited: 'Fit for duty, no EVA', rest: 'Off critical tasks' } as const

/** Where a protocol lives on the Protocols page. Every "Open ... protocol" button goes through here. */
export const protocolPath = (id: string) => `/protocols/${id}`

export default function Protocols() {
  const { id } = useParams()
  const { data, error } = useApi<ProtocolLibrary>(() => api.protocolLibrary(), [])
  if (error) return <div className="page"><p className="muted">Cannot reach the Canary API.</p></div>
  if (!data) return <Loading what="protocols" />
  const page = id ? [...data.emergency, ...data.operational].find(p => p.id === id) : null
  if (id && !page) return <div className="page"><Link className="back" to="/protocols"><Icon name="back" />Protocols</Link><p className="muted">There is no protocol called “{id}”.</p></div>
  return page ? <Page p={page} lib={data} /> : <Index lib={data} />
}

function Index({ lib }: { lib: ProtocolLibrary }) {
  const by = Object.fromEntries([...lib.emergency, ...lib.operational].map(p => [p.id, p]))
  return (
    <div className="page protocols">
      <div className="head rise">
        <div>
          <h1>Protocols</h1>
          <p className="sub">What to do, step by step, at {lib.place.name}. For the whole crew: nothing here is about one person.</p>
        </div>
      </div>

      <section className="rise" style={{ ['--d' as string]: 1 }}>
        <div className="section-head"><h2>In force now</h2></div>
        {lib.in_force.length === 0
          ? <p className="muted">Nothing special is in force. Canary is learning each person's normal.</p>
          : <ul className="plist">{lib.in_force.map(f => <ForceRow key={f.id} f={f} name={by[f.id]?.name ?? f.id} />)}</ul>}
      </section>

      <section className="rise" style={{ ['--d' as string]: 2 }}>
        <div className="section-head"><h2>Emergency</h2><span className="sub">Start any of them from Hold for emergency</span></div>
        <ul className="plist">{lib.emergency.map(p => <ListRow key={p.id} p={p} />)}</ul>
      </section>

      <section className="rise" style={{ ['--d' as string]: 3 }}>
        <div className="section-head"><h2>Operational</h2></div>
        <ul className="plist">{lib.operational.map(p => <ListRow key={p.id} p={p} />)}</ul>
      </section>

      <p className="small dim">{lib.note}</p>
    </div>
  )
}

function ForceRow({ f, name }: { f: InForce; name: string }) {
  return (
    <li className={`s${f.level}`}>
      <Link to={protocolPath(f.id)} className="prow">
        <span className="dot" />
        <span className="grow"><b>{name}</b><span className="muted">{f.reason}{f.audience && ` For the ${f.audience} only.`}</span></span>
        <Icon name="chev" size={16} />
      </Link>
    </li>
  )
}

function ListRow({ p }: { p: ProtocolPage }) {
  return (
    <li>
      <Link to={protocolPath(p.id)} className="prow">
        <span className="grow"><b>{p.name}</b><span className="muted">{p.sign ?? p.when[0]}</span></span>
        <Icon name="chev" size={16} />
      </Link>
    </li>
  )
}

function Page({ p, lib }: { p: ProtocolPage; lib: ProtocolLibrary }) {
  const { startProtocol } = useSession()
  const nav = useNavigate()
  const force = lib.in_force.find(f => f.id === p.id)
  const all = Object.fromEntries([...lib.emergency, ...lib.operational].map(x => [x.id, x]))
  return (
    <div className="page protocols">
      <div className="head rise">
        <div>
          <Link className="back" to="/protocols"><Icon name="back" />Protocols</Link>
          <h1 style={{ marginTop: 10 }}>{p.name}</h1>
          <p className="sub">{p.kind === 'emergency' ? 'Emergency protocol' : 'Operational protocol'}{p.audience !== 'everyone' && ` · for the ${p.audience}`}</p>
        </div>
        {p.guided && <button className="btn pri right" onClick={() => startProtocol(p.id)}>Start guided response</button>}
      </div>

      {force && <div className={`warning s${force.level} rise`}><span className="dot" /><div className="grow"><b>In force now.</b> <span className="muted">{force.reason}</span></div></div>}
      {p.live.length > 0 && <ul className="live rise">{p.live.map(l => <li key={l}>{l}</li>)}</ul>}

      <div className="pbody">
        <section className="rise" style={{ ['--d' as string]: 1 }}>
          <h2>When to use it</h2>
          <ul className="bul">{p.when.map(w => <li key={w}>{w}</li>)}</ul>
        </section>

        <section className="rise" style={{ ['--d' as string]: 2 }}>
          <h2>Steps</h2>
          <ol className="steps">
            {p.steps.map((s, i) => (
              <li key={i}><span>{s.t ?? s.q}{s.t && s.q && <span className="muted"> {s.q}</span>}{s.variant && <span className="muted"> Here: {s.variant}</span>}</span></li>
            ))}
          </ol>
          {p.kit.length > 0 && <p className="small muted" style={{ marginTop: 14 }}>Bring: {p.kit.join(', ')}.</p>}
        </section>

        <section className="rise" style={{ ['--d' as string]: 3 }}>
          <h2>What to watch</h2>
          <ul className="bul">{p.watch.map(w => <li key={w}>{w}</li>)}</ul>
          {p.kind === 'emergency' && p.window_days > 0 && <p className="small muted" style={{ marginTop: 12 }}>The patient is followed for {p.window_days} {p.window_days === 1 ? 'day' : 'days'}: {OPS[p.ops ?? 'full'].toLowerCase()}.</p>}
        </section>

        {p.id === 'care' && (
          <section className="rise" style={{ ['--d' as string]: 4 }}>
            <h2>Window by protocol</h2>
            <table className="ptable"><tbody>
              {lib.care_table.map(r => <tr key={r.id}><td><Link className="item" to={protocolPath(r.id)}>{r.name}</Link></td><td className="num">{r.window_days} {r.window_days === 1 ? 'day' : 'days'}</td><td className="muted">{OPS[r.ops]}</td></tr>)}
            </tbody></table>
          </section>
        )}

        {(p.standard || p.source) && (
          <section className="rise" style={{ ['--d' as string]: 5 }}>
            <h2>Source</h2>
            {p.standard
              ? <p className="muted">{p.standard.text} <a className="item" href={p.standard.url} target="_blank" rel="noreferrer">{p.standard.name}</a></p>
              : <p className="muted">No NASA standard checked for this one.</p>}
            {p.source && <p className="small dim" style={{ marginTop: 6 }}>{p.source}.</p>}
          </section>
        )}

        {p.links.length > 0 && (
          <section className="rise" style={{ ['--d' as string]: 6 }}>
            <h2>Related</h2>
            <p>{p.links.filter(l => all[l]).map((l, i) => <span key={l}>{i > 0 && ' · '}<button className="link" onClick={() => nav(protocolPath(l))}>{all[l].name}</button></span>)}</p>
          </section>
        )}
      </div>
    </div>
  )
}
