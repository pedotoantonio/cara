import { Component, type ReactNode, type ErrorInfo } from 'react';

interface Props {
  children: ReactNode;
  fallback?: (err: Error, reset: () => void) => ReactNode;
}

interface State {
  error: Error | null;
}

/**
 * Global error boundary — evita "schermata bianca silenziosa" se un render
 * crasha. Sappiamo cosa è successo + permettiamo all'utente di provare a
 * ricaricare senza dover refresh tutto.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[cara] uncaught render error', error, info);
  }

  reset = () => {
    this.setState({ error: null });
  };

  render() {
    if (this.state.error) {
      if (this.props.fallback) return this.props.fallback(this.state.error, this.reset);
      return (
        <main className="min-h-[100dvh] grid place-items-center p-6 bg-bg-base">
          <div className="max-w-sm w-full text-center">
            <h1 className="font-display text-3xl text-text-primary mb-2">Mi sono persa</h1>
            <p className="text-text-secondary mb-4">
              Qualcosa è andato storto mentre disegnavo la pagina. Riprova, o ricarica.
            </p>
            <pre className="text-xs text-text-muted bg-bg-surface border border-border-soft rounded-md p-3 text-left overflow-auto max-h-48 mb-4">
              {this.state.error.message}
            </pre>
            <div className="flex flex-col gap-2">
              <button
                onClick={this.reset}
                className="h-11 px-5 rounded-md bg-accent-coral text-white font-medium"
              >
                Riprova
              </button>
              <button
                onClick={() => window.location.reload()}
                className="h-9 px-3 rounded-sm text-text-secondary hover:bg-bg-surface"
              >
                Ricarica la pagina
              </button>
            </div>
          </div>
        </main>
      );
    }
    return this.props.children;
  }
}
