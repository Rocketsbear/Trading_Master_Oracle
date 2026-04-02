import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import './index.css'

class ErrorBoundary extends React.Component {
  constructor(props) { super(props); this.state = { error: null, errorInfo: null } }
  componentDidCatch(error, errorInfo) { this.setState({ error, errorInfo }) }
  render() {
    if (this.state.error) {
      return (
        <div style={{ padding: 40, color: '#ff4757', background: '#0a0a0a', fontFamily: 'monospace', minHeight: '100vh' }}>
          <h1 style={{ color: '#ff6b81' }}>⚠️ React Runtime Error</h1>
          <pre style={{ color: '#ffa502', whiteSpace: 'pre-wrap', fontSize: 14 }}>{this.state.error.toString()}</pre>
          <pre style={{ color: '#747d8c', whiteSpace: 'pre-wrap', fontSize: 11, marginTop: 20 }}>{this.state.errorInfo?.componentStack}</pre>
        </div>
      )
    }
    return this.props.children
  }
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>
)
