import { useNavigate } from 'react-router-dom'

const styles: Record<string, React.CSSProperties> = {
  page: {
    minHeight: '100vh',
    background: '#000000',
    display: 'flex',
    flexDirection: 'column',
    fontFamily: 'Inter, system-ui, -apple-system, sans-serif',
  },
  accentStripe: {
    width: '100%',
    height: '4px',
    display: 'flex',
    flexShrink: 0,
  },
  accentLeft: { flex: 1, background: '#0066b1' },
  accentMid: { flex: 1, background: '#1c69d4' },
  accentRight: { flex: 1, background: '#e22718' },
  main: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    justifyContent: 'center',
    alignItems: 'center',
    padding: '64px 24px',
    textAlign: 'center',
  },
  heading: {
    fontWeight: 700,
    fontSize: '36px',
    lineHeight: 1.15,
    letterSpacing: '-0.5px',
    textTransform: 'uppercase',
    color: '#ffffff',
    marginBottom: '24px',
    maxWidth: '760px',
  },
  description: {
    fontWeight: 300,
    fontSize: '16px',
    lineHeight: 1.7,
    color: '#bbbbbb',
    maxWidth: '580px',
    marginBottom: '40px',
  },
  footer: {
    borderTop: '1px solid #3c3c3c',
    padding: '16px 24px',
    textAlign: 'center',
    color: '#7e7e7e',
    fontSize: '12px',
    fontWeight: 300,
  },
}

export default function LandingPage() {
  const navigate = useNavigate()
  return (
    <div style={styles.page}>
      {/* Tricolor accent stripe */}
      <div style={styles.accentStripe}>
        <div style={styles.accentLeft} />
        <div style={styles.accentMid} />
        <div style={styles.accentRight} />
      </div>

      <main style={styles.main}>
        <h1 style={styles.heading}>Multi-Agent Code Pipeline</h1>
        <p style={styles.description}>
          An orchestrated AI pipeline where a Planner agent decomposes natural-language feature
          requests into subtasks, a CodeGen agent generates the implementation, and a Reviewer
          agent enforces quality rules. Each run is stored, versioned, and viewable in real
          time — agent reasoning, generated code, and review verdicts all in one place.
        </p>
        <GetStartedButton onClick={() => navigate('/login')} />
      </main>

      <footer style={styles.footer}>Multi-Agent Code Pipeline</footer>
    </div>
  )
}

function GetStartedButton({ onClick }: { onClick: () => void }) {
  const base: React.CSSProperties = {
    fontFamily: 'Inter, system-ui, -apple-system, sans-serif',
    fontWeight: 700,
    fontSize: '14px',
    letterSpacing: '1.5px',
    textTransform: 'uppercase',
    color: '#ffffff',
    background: '#1a1a1a',
    border: '1px solid #3c3c3c',
    borderRadius: '0px',
    padding: '12px 32px',
    cursor: 'pointer',
    transition: 'border-color 0.15s',
  }
  return (
    <button
      style={base}
      onClick={onClick}
      onMouseEnter={e => ((e.currentTarget as HTMLButtonElement).style.borderColor = '#1c69d4')}
      onMouseLeave={e => ((e.currentTarget as HTMLButtonElement).style.borderColor = '#3c3c3c')}
    >
      Get Started
    </button>
  )
}
