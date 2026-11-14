// Form pieces that go with lib/useForm: a labelled control with its hint and error, a group for button scales,
// the form-level error line, the submit button and the summary of a long form.
// Errors are plain text in the "act" colour under the field. No boxes, no icons.
import type { ReactNode } from 'react'
import type { FormApi } from '../lib/useForm'

interface ControlProps {
  type?: string; inputMode?: 'numeric' | 'decimal' | 'text'; placeholder?: string; maxLength?: number; rows?: number
  min?: number | string; max?: number | string; step?: number | string; autoFocus?: boolean; autoComplete?: string
  disabled?: boolean; className?: string; list?: string; 'aria-label'?: string
}

interface FieldProps extends ControlProps {
  form: FormApi
  name: string
  label: string
  /** Unit and accepted range, shown under the control until it is wrong, e.g. "25–250 bpm". */
  hint?: string
  optional?: boolean
  as?: 'input' | 'select' | 'textarea'
  /** Keep the label for screen readers only (a one-line input such as the question box). */
  hideLabel?: boolean
  /** Turns what was typed into the stored value (for example digits only). */
  map?: (typed: string) => unknown
  children?: ReactNode
}

export function Field({ form, name, label, hint, optional, as: Tag = 'input', hideLabel, map, children, ...control }: FieldProps) {
  const p = form.bind(name, { map })
  const err = form.error(name)
  return (
    <div className="field">
      <label className={hideLabel ? 'lbl sr-only' : 'lbl'} htmlFor={p.id}>{label}{optional && <span className="dim"> (optional)</span>}</label>
      <Tag {...control} {...p}>{children}</Tag>
      {err ? <span className="err" id={`${p.id}-err`}>{err}</span> : hint ? <span className="hint" id={`${p.id}-hint`}>{hint}</span> : null}
    </div>
  )
}

/** A question answered with buttons (a 1 to 5 scale, a list of options). The wrapper takes the focus when it is missing. */
export function FieldGroup({ form, name, label, hint, children }: { form: FormApi; name: string; label: ReactNode; hint?: string; children: ReactNode }) {
  const id = form.idOf(name)
  const err = form.error(name)
  return (
    <div className="field group" id={id} role="group" aria-labelledby={`${id}-lbl`} aria-invalid={err ? true : undefined} aria-describedby={`${id}-err ${id}-hint`} tabIndex={-1}>
      <span className="lbl" id={`${id}-lbl`}>{label}</span>
      {children}
      {err ? <span className="err" id={`${id}-err`}>{err}</span> : hint ? <span className="hint" id={`${id}-hint`}>{hint}</span> : null}
    </div>
  )
}

/** The error that belongs to the whole form, right above the submit button. */
export function FormError({ form }: { form: Pick<FormApi, 'formError'> }) {
  return form.formError ? <p className="form-err" role="alert">{form.formError}</p> : null
}

/** Submit button: not disabled for invalid input (pressing it is how the errors show), only while saving. */
export function SubmitButton({ form, children, busyLabel = 'Saving…', className = 'btn pri' }: { form: Pick<FormApi, 'busy'>; children: ReactNode; busyLabel?: string; className?: string }) {
  return <button type="submit" className={className} disabled={form.busy}>{form.busy ? busyLabel : children}</button>
}

/** A short list of what is wrong in a long form. Each item takes the person to its field. */
export function FormSummary({ form, describe }: { form: FormApi; describe?: (key: string) => string }) {
  if (!form.visible.length) return null
  return (
    <div className="form-summary" role="alert">
      <b>{form.visible.length === 1 ? '1 thing to fix' : `${form.visible.length} things to fix`}</b>
      <ul>
        {form.visible.map(i => (
          <li key={i.key}><button type="button" onClick={() => form.focus(i.key)}>{describe ? `${describe(i.key)} · ` : ''}{i.message}</button></li>
        ))}
      </ul>
    </div>
  )
}

/** The error of a useAction, next to its button. */
export function ActionError({ error }: { error: string | null }) {
  return error ? <p className="form-err" role="alert">{error}</p> : null
}
