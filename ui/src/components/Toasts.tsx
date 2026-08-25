export interface Toast {
  id: number
  message: string
  variant?: 'error' | 'success'
}

export default function Toasts({ toasts }: { toasts: Toast[] }) {
  return (
    <div className="toasts" aria-live="polite" aria-atomic="false">
      {toasts.map((toast) => (
        <div key={toast.id} className={`toast toast--${toast.variant ?? 'error'}`} role="status">
          {toast.message}
        </div>
      ))}
    </div>
  )
}