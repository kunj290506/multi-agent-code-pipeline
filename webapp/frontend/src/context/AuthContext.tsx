import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { authLogin, authLogout, authMe, authSignup, type AuthUser } from '../api'

interface AuthContextValue {
  user: AuthUser | null
  loading: boolean
  login(username: string, password: string): Promise<void>
  signup(username: string, email: string, password: string): Promise<void>
  logout(): Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    authMe()
      .then(setUser)
      .finally(() => setLoading(false))
  }, [])

  async function login(username: string, password: string): Promise<void> {
    const u = await authLogin(username, password)
    setUser(u)
  }

  async function signup(username: string, email: string, password: string): Promise<void> {
    const u = await authSignup(username, email, password)
    setUser(u)
  }

  async function logout(): Promise<void> {
    await authLogout()
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, signup, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}
