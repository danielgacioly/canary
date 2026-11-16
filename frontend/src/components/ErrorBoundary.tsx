// One page that fails to render shows a short note instead of blanking the whole app: the sidebar, the top bar and the
// emergency button stay usable. The Shell keys it by the path, so moving to another page tries again.
import { Component, type ErrorInfo, type ReactNode } from 'react'
import { Link } from 'react-router-dom'

export default class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Page failed to render', error, info.componentStack)
  }

  render() {
    if (!this.state.failed) return this.props.children
    return (
      <div className="page" role="alert">
        <h1>This page could not be shown</h1>
        <p className="muted">Something on this page went wrong. The rest of Canary still works.</p>
        <Link to="/crew" className="link">Back to the crew</Link>
      </div>
    )
  }
}
