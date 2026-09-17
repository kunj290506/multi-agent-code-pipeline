import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

type Tab = 'login' | 'signup'

const font = 'Inter, system-ui, -apple-system, sans-serif'

const page: React.CSSProperties = {
  minHeight: '100vh',
  background: '#000000',
  display: 'flex',
  flexDirection: 'column',
  fontFamily: font,
}

const accentStripe: React.CSSProperties = {
  width: '100%',
  height: '4px',
  display: 'flex',
  flexShrink: 0,
}

const centerWrap: React.CSSProperties = {
  flex: 1,
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  padding: '40px 24px',
}

const card: React.CSSProperties = {
  width: '100%',
  maxWidth: '400px',
  background: '#1a1a1a',
  border: '1px solid #3c3c3c',
  borderRadius: '0px',
  padding: '40px',
}

const tabBar: React.CSSProperties = {
  display: 'flex',
  gap: '0px',
  borderBottom: '1px solid #3c3c3c',
  marginBottom: '32px',
}

function tabStyle(active: boolean): React.CSSProperties {
  return {
    fontFamily: font,
    fontWeight: 700,
    fontSize: '14px',
    letterSpacing: '1.5px',
    textTransform: 'uppercase',
    color: active ? '#ffffff' : '#7e7e7e',
    background: 'transparent',
    border: 'none',
    borderBottom: active ? '4px solid #1c69d4' : '4px solid transparent',
    padding: '8px 20px',
    cursor: 'pointer',
    marginBottom: '-1px',
  }
}

const fieldWrap: React.CSSProperties = { display: 'flex', flexDirection: 'column', gap: '16px', marginBottom: '24px' }

const inputStyle: React.CSSProperties = {
  background: '#000000',
  border: '1px solid #3c3c3c',
  borderRadius: '0px',
  color: '#ffffff',
  fontFamily: font,
  fontWeight: 300,
  fontSize: '14px',
  padding: '10px 14px',
  outline: 'none',
  width: '100%',
}

const submitBtn: React.CSSProperties = {
  fontFamily: font,
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
  width: '100%',
  transition: 'border-color 0.15s',
}

const errorStyle: React.CSSProperties = {
  color: '#e22718',
  fontSize: '13px',
  fontWeight: 300,
  marginTop: '16px',
  lineHeight: 1.5,
}

export default function LoginPage() {
  const { user, loading, login, signup } = useAuth()
  const navigate = useNavigate()
  const [tab, setTab] = useState<Tab>('login')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  // Redirect already-authenticated users
  useEffect(() => {
    if (!loading && user) navigate('/ide', { replace: true })
  }, [user, loading, navigate])

  async function handleLogin(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setError(null)
    const fd = new FormData(e.currentTarget)
    const username = fd.get('username') as string
    const password = fd.get('password') as string
    setSubmitting(true)
    try {
      await login(username, password)
      navigate('/ide', { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed')
    } finally {
      setSubmitting(false)
    }
  }

  async function handleSignup(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setError(null)
    const fd = new FormData(e.currentTarget)
    const username = fd.get('username') as string
    const email = fd.get('email') as string
    const password = fd.get('password') as string
    setSubmitting(true)
    try {
      await signup(username, email, password)
      navigate('/ide', { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign up failed')
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) return null

  return (
    <div style={page}>
      {/* Tricolor accent stripe */}
      <div style={accentStripe}>
        <div style={{ flex: 1, background: '#0066b1' }} />
        <div style={{ flex: 1, background: '#1c69d4' }} />
        <div style={{ flex: 1, background: '#e22718' }} />
      </div>

      <div style={centerWrap}>
        <div style={card}>
          {/* Tab bar */}
          <div style={tabBar}>
            <button style={tabStyle(tab === 'login')} onClick={() => { setTab('login'); setError(null) }}>
              Login
            </button>
            <button style={tabStyle(tab === 'signup')} onClick={() => { setTab('signup'); setError(null) }}>
              Sign Up
            </button>
          </div>

          {tab === 'login' ? (
            <form onSubmit={handleLogin} noValidate>
              <div style={fieldWrap}>
                <FocusInput name="username" placeholder="Username" autoComplete="username" required />
                <FocusInput name="password" placeholder="Password" type="password" autoComplete="current-password" required />
              </div>
              <SubmitButton label="Log In" disabled={submitting} />
              {error && <p style={errorStyle}>{error}</p>}
            </form>
          ) : (
            <form onSubmit={handleSignup} noValidate>
              <div style={fieldWrap}>
                <FocusInput name="username" placeholder="Username" autoComplete="username" required />
                <FocusInput name="email" placeholder="Email" type="email" autoComplete="email" required />
                <FocusInput name="password" placeholder="Password" type="password" autoComplete="new-password" required />
              </div>
              <SubmitButton label="Create Account" disabled={submitting} />
              {error && <p style={errorStyle}>{error}</p>}
            </form>
          )}
        </div>
      </div>
    </div>
  )
}

function FocusInput(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      style={inputStyle}
      onFocus={e => (e.currentTarget.style.borderColor = '#1c69d4')}
      onBlur={e => (e.currentTarget.style.borderColor = '#3c3c3c')}
    />
  )
}

function SubmitButton({ label, disabled }: { label: string; disabled: boolean }) {
  return (
    <button
      type="submit"
      disabled={disabled}
      style={{ ...submitBtn, opacity: disabled ? 0.6 : 1 }}
      onMouseEnter={e => { if (!disabled) (e.currentTarget as HTMLButtonElement).style.borderColor = '#1c69d4' }}
      onMouseLeave={e => (e.currentTarget as HTMLButtonElement).style.borderColor = '#3c3c3c'}
    >
      {label}
    </button>
  )
}
