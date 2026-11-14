// One way to run every form: values, errors, touched fields, a busy state and server errors.
//
// - A field shows its error after it was left (blur) or after the first submit, and the error goes away
//   the moment the value is valid again.
// - Submitting with errors does not call the server: the first wrong field takes the focus.
// - While the request runs the button reads "Saving…" and a second submit is ignored.
// - A 400/422 answer that names fields (`[{field, message}]`) lands on those fields; anything else becomes one
//   line above the submit button (`formError`).
import { useCallback, useId, useRef, useState, type ChangeEvent, type FormEvent } from 'react'
import { ApiError, errorText } from '../api/client'

export type Errors = Record<string, string | null | undefined>

export interface BindProps {
  id: string
  name: string
  value: string
  onChange: (e: ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => void
  onBlur: () => void
  'aria-invalid': true | undefined
  'aria-describedby': string
}

/** What the form components (Field, FormError, SubmitButton) need from useForm. */
export interface FormApi {
  values: Record<string, unknown>
  busy: boolean
  formError: string | null
  /** The error to show under a field right now, or null. */
  error(key: string): string | null
  /** Every error showing right now, in field order (for the summary of a long form). */
  visible: { key: string; message: string }[]
  bind(key: string, o?: { map?: (typed: string) => unknown }): BindProps
  /** The DOM id of a field, for a label or a group wrapper. */
  idOf(key: string): string
  set(key: string, value: unknown): void
  touch(key: string): void
  focus(key: string): void
  submit(e?: FormEvent): Promise<boolean>
}

export interface Form<T extends Record<string, unknown>> extends FormApi {
  values: T
  set<K extends keyof T & string>(key: K, value: T[K]): void
  setValues(patch: Partial<T> | ((v: T) => T)): void
  reset(v?: T): void
  setFormError(m: string | null): void
}

interface Options<T> {
  initial: T
  /** Every current error by field name. A `form` key is a message that belongs to no field. */
  validate: (v: T) => Errors
  submit: (v: T) => Promise<unknown> | unknown
  /** Called with a field that is not on screen (a closed panel) before it is focused. */
  reveal?: (key: string) => void
  /** Maps a field name from the server onto a form key. Default: the same name. */
  mapField?: (serverField: string) => string | undefined
}

export function useForm<T extends Record<string, unknown>>(opts: Options<T>): Form<T> {
  const uid = useId()
  const [values, setVals] = useState<T>(opts.initial)
  const [touched, setTouched] = useState<Record<string, boolean>>({})
  const [submitted, setSubmitted] = useState(false)
  const [server, setServer] = useState<Record<string, string>>({})
  const [formError, setFormError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const busyRef = useRef(false)

  const all: Errors = opts.validate(values)
  const latest = useRef({ values, all, opts })
  latest.current = { values, all, opts }

  const idOf = useCallback((key: string) => `${uid}-${key}`, [uid])
  const wrong = Object.keys(all).filter(k => all[k])
  const error = (key: string): string | null => server[key] ?? (touched[key] || submitted ? all[key] ?? null : null)
  const visible = [...new Set([...wrong, ...Object.keys(server)])].filter(k => k !== 'form' && error(k)).map(k => ({ key: k, message: error(k) as string }))

  const set = useCallback((key: string, value: unknown) => {
    setVals(v => ({ ...v, [key]: value }))
    setServer(s => { if (!(key in s)) return s; const n = { ...s }; delete n[key]; return n })
    setFormError(null)
  }, [])
  const touch = useCallback((key: string) => setTouched(t => (t[key] ? t : { ...t, [key]: true })), [])

  const focus = useCallback((key: string) => {
    const go = (tries: number) => {
      const el = document.getElementById(idOf(key))
      if (!el) {
        if (tries === 0) latest.current.opts.reveal?.(key)
        if (tries < 4) requestAnimationFrame(() => go(tries + 1))
        return
      }
      const target = el.matches('input,select,textarea,button') ? el : el.querySelector<HTMLElement>('button,input,select,textarea') ?? el
      target.focus()
      target.scrollIntoView?.({ block: 'center', behavior: 'smooth' })
    }
    go(0)
  }, [idOf])

  const bind = (key: string, o?: { map?: (typed: string) => unknown }): BindProps => ({
    id: idOf(key), name: key, value: values[key] === null || values[key] === undefined ? '' : String(values[key]),
    onChange: e => set(key, o?.map ? o.map(e.target.value) : e.target.value),
    onBlur: () => touch(key),
    'aria-invalid': error(key) ? true : undefined,
    'aria-describedby': `${idOf(key)}-err ${idOf(key)}-hint`,
  })

  const submit = async (e?: FormEvent): Promise<boolean> => {
    e?.preventDefault()
    if (busyRef.current) return false
    setSubmitted(true)
    const { all: errs, values: vals, opts: o } = latest.current
    const bad = Object.keys(errs).filter(k => errs[k])
    if (bad.length) {
      const first = bad.find(k => k !== 'form')
      if (first) focus(first)
      return false
    }
    busyRef.current = true; setBusy(true); setFormError(null)
    try {
      await o.submit(vals)
      return true
    } catch (err) {
      const mapped: Record<string, string> = {}, rest: string[] = []
      if (err instanceof ApiError && err.issues.length) {
        for (const i of err.issues) {
          const k = o.mapField ? o.mapField(i.field) : i.field
          if (k && k !== 'form' && k in vals) mapped[k] = mapped[k] ? `${mapped[k]}. ${i.message}` : i.message
          else rest.push(i.message)
        }
      } else rest.push(errorText(err))
      setServer(mapped); setFormError(rest.length ? rest.join('. ') : null)
      const first = Object.keys(mapped)[0]
      if (first) focus(first)
      return false
    } finally {
      busyRef.current = false; setBusy(false)
    }
  }

  const reset = (v?: T) => { setVals(v ?? opts.initial); setTouched({}); setSubmitted(false); setServer({}); setFormError(null) }
  const setValues = (patch: Partial<T> | ((v: T) => T)) => setVals(v => (typeof patch === 'function' ? patch(v) : { ...v, ...patch }))

  return { values, busy, formError: formError ?? (submitted && all.form ? all.form : null), error, visible, bind, idOf, set: set as Form<T>['set'], setValues, touch, focus, submit, reset, setFormError }
}
