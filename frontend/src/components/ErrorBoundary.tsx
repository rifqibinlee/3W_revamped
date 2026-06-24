import { Component, type ErrorInfo, type ReactNode } from 'react'
import { GlassPanel } from './GlassPanel'

interface Props {
  children: ReactNode
}

interface State {
  error: Error | null
}

// Without this, a single component throwing (e.g. unexpected API
// response shape) unmounts the whole React tree and leaves a blank
// page with nothing but a console warning — confirmed the hard way
// when a <DataTable> error did exactly that during development.
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Unhandled error in component tree:', error, info.componentStack)
  }

  render() {
    if (this.state.error) {
      return (
        <div className="flex min-h-screen items-center justify-center p-6">
          <GlassPanel className="w-full max-w-md">
            <p className="mb-2 font-display text-lg font-semibold text-red-300">Something went wrong</p>
            <p className="mb-4 text-sm text-white/70">
              This page hit an unexpected error. Try reloading — if it keeps happening, the backend
              response may not match what this page expects.
            </p>
            <p className="mb-4 rounded-xl bg-black/30 p-3 font-mono text-xs text-white/50">
              {this.state.error.message}
            </p>
            <button
              onClick={() => window.location.reload()}
              className="rounded-xl bg-gradient-to-r from-accent-400 to-accent-500 px-4 py-2 text-sm font-semibold text-ink-900"
            >
              Reload
            </button>
          </GlassPanel>
        </div>
      )
    }
    return this.props.children
  }
}
