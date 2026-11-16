// The one modal shell: a labelled, modal dialog over a scrim. Focus and Escape come from useDialog.
// Put <ModalTitle> inside: it is the element the dialog is labelled by.
import { createContext, useContext, useId, type ReactNode } from 'react'
import { useDialog } from '../lib/useDialog'

const TitleId = createContext<string | undefined>(undefined)

export function Modal({ onClose, wide, dismissable = true, className = '', children }: {
  onClose: () => void; wide?: boolean; dismissable?: boolean; className?: string; children: ReactNode
}) {
  const titleId = useId()
  const ref = useDialog<HTMLDivElement>(onClose, dismissable)
  return (
    <div className="scrim" onClick={dismissable ? onClose : undefined}>
      <div ref={ref} className={`modal${wide ? ' wide' : ''}${className ? ` ${className}` : ''}`} role="dialog" aria-modal="true"
        aria-labelledby={titleId} onClick={e => e.stopPropagation()}>
        <TitleId.Provider value={titleId}>{children}</TitleId.Provider>
      </div>
    </div>
  )
}

/** The heading that names its enclosing Modal. Pass `className` to keep a layout (for example a row). */
export function ModalTitle({ className, children }: { className?: string; children: ReactNode }) {
  return <h2 id={useContext(TitleId)} className={className}>{children}</h2>
}
