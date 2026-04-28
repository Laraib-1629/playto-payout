import { useState, useEffect, useCallback } from 'react'
import { apiClient } from './api/client'

// ── Helpers ───────────────────────────────────────────────────
const fmtINR = (paise) => {
  const rupees = Math.abs(paise) / 100
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    minimumFractionDigits: 2,
  }).format(rupees)
}

const fmtDate = (dt) =>
  new Date(dt).toLocaleString('en-IN', {
    day: '2-digit', month: 'short',
    hour: '2-digit', minute: '2-digit',
  })

// ── Status Badge ──────────────────────────────────────────────
function StatusBadge({ status }) {
  const map = {
    PENDING:    { bg: '#F3F4F6', color: '#374151', dot: '#9CA3AF' },
    PROCESSING: { bg: '#FFFBEB', color: '#B45309', dot: '#F59E0B' },
    COMPLETED:  { bg: '#F0FDF4', color: '#00875A', dot: '#00875A' },
    FAILED:     { bg: '#FEF2F2', color: '#DE3730', dot: '#DE3730' },
  }
  const s = map[status] || map.PENDING

  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 6,
      background: s.bg, color: s.color,
      padding: '3px 10px', borderRadius: 4,
      fontSize: 11, fontWeight: 600,
      fontFamily: 'IBM Plex Mono, monospace',
      letterSpacing: '0.05em',
    }}>
      <span style={{
        width: 6, height: 6, borderRadius: '50%',
        background: s.dot,
        ...(status === 'PROCESSING' ? { animation: 'pulse-dot 1.5s ease infinite' } : {})
      }} />
      {status}
    </span>
  )
}

// ── Balance Card ──────────────────────────────────────────────
function BalanceCard({ label, amount, color, delay }) {
  return (
    <div style={{
      background: 'var(--white)',
      border: '1px solid var(--border)',
      padding: '24px 28px',
      animation: `fadeIn 0.4s ease ${delay}s both`,
    }}>
      <p style={{
        fontSize: 11, fontWeight: 600,
        letterSpacing: '0.1em', textTransform: 'uppercase',
        color: 'var(--text-muted)', marginBottom: 12,
      }}>
        {label}
      </p>
      <p style={{
        fontFamily: 'DM Serif Display, serif',
        fontSize: 36, lineHeight: 1,
        color: color || 'var(--text)',
      }}>
        {fmtINR(amount)}
      </p>
    </div>
  )
}

// ── Payout Form ───────────────────────────────────────────────
function PayoutForm({ api, bankAccounts, onPayoutCreated }) {
  const [amount, setAmount] = useState('')
  const [bankId, setBankId] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [success, setSuccess] = useState(null)

  const handleSubmit = async () => {
    setError(null)
    setSuccess(null)
    const paise = Math.round(parseFloat(amount) * 100)
    if (!paise || paise < 100) return setError('Minimum payout is ₹1')
    if (!bankId) return setError('Select a bank account')

    setLoading(true)
    try {
      const payout = await api.post(
        '/payouts/',
        { amount_paise: paise, bank_account_id: parseInt(bankId) },
        crypto.randomUUID()
      )
      setSuccess(`Payout #${payout.id} created — ₹${amount}`)
      setAmount('')
      onPayoutCreated()
    } catch (err) {
      setError(err.error || err.amount_paise?.[0] || 'Failed to create payout')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{
      background: 'var(--white)',
      border: '1px solid var(--border)',
      padding: '24px 28px',
      marginTop: 1,
    }}>
      <p style={{
        fontSize: 11, fontWeight: 600, letterSpacing: '0.1em',
        textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 16,
      }}>
        Request Payout
      </p>

      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        <input
          type="number"
          placeholder="Amount in ₹"
          value={amount}
          onChange={e => setAmount(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleSubmit()}
          style={{
            flex: 1, minWidth: 160,
            border: '1px solid var(--border)',
            padding: '10px 14px',
            fontSize: 14,
            fontFamily: 'IBM Plex Mono, monospace',
            outline: 'none',
            background: 'var(--bg)',
          }}
        />
        <select
          value={bankId}
          onChange={e => setBankId(e.target.value)}
          style={{
            flex: 2, minWidth: 200,
            border: '1px solid var(--border)',
            padding: '10px 14px',
            fontSize: 13,
            fontFamily: 'IBM Plex Sans, sans-serif',
            outline: 'none',
            background: 'var(--bg)',
            cursor: 'pointer',
          }}
        >
          <option value="">Select bank account</option>
          {bankAccounts.map(acc => (
            <option key={acc.id} value={acc.id}>
              {acc.account_holder_name} — ••••{acc.account_number.slice(-4)} ({acc.ifsc_code})
            </option>
          ))}
        </select>
        <button
          onClick={handleSubmit}
          disabled={loading}
          style={{
            background: loading ? '#6B6B6B' : 'var(--text)',
            color: 'var(--white)',
            border: 'none',
            padding: '10px 24px',
            fontSize: 13, fontWeight: 600,
            cursor: loading ? 'not-allowed' : 'pointer',
            fontFamily: 'IBM Plex Sans, sans-serif',
            letterSpacing: '0.03em',
            transition: 'background 0.15s',
          }}
        >
          {loading ? 'Processing...' : 'Submit Payout'}
        </button>
      </div>

      {error && (
        <p style={{ marginTop: 12, fontSize: 13, color: 'var(--red)', fontFamily: 'IBM Plex Mono, monospace' }}>
          ✕ {error}
        </p>
      )}
      {success && (
        <p style={{ marginTop: 12, fontSize: 13, color: 'var(--green)', fontFamily: 'IBM Plex Mono, monospace' }}>
          ✓ {success}
        </p>
      )}
    </div>
  )
}

// ── Payout History ────────────────────────────────────────────
function PayoutHistory({ payouts }) {
  if (payouts.length === 0) return (
    <div style={{
      background: 'var(--white)',
      border: '1px solid var(--border)',
      padding: '40px 28px',
      marginTop: 1,
      textAlign: 'center',
      color: 'var(--text-muted)',
      fontSize: 13,
    }}>
      No payouts yet. Submit your first payout above.
    </div>
  )

  return (
    <div style={{
      background: 'var(--white)',
      border: '1px solid var(--border)',
      marginTop: 1,
    }}>
      <div style={{
        padding: '16px 28px',
        borderBottom: '1px solid var(--border)',
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      }}>
        <p style={{
          fontSize: 11, fontWeight: 600, letterSpacing: '0.1em',
          textTransform: 'uppercase', color: 'var(--text-muted)',
        }}>
          Payout History
        </p>
        <span style={{
          fontSize: 11, color: 'var(--text-muted)',
          fontFamily: 'IBM Plex Mono, monospace',
          display: 'flex', alignItems: 'center', gap: 6,
        }}>
          <span className="pulse-dot" style={{
            width: 6, height: 6, borderRadius: '50%',
            background: 'var(--green)', display: 'inline-block',
          }} />
          Live · updates every 5s
        </span>
      </div>

      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr style={{ borderBottom: '1px solid var(--border)' }}>
            {['ID', 'Amount', 'Status', 'Attempts', 'Created'].map(h => (
              <th key={h} style={{
                padding: '10px 28px',
                textAlign: 'left',
                fontSize: 10, fontWeight: 600,
                letterSpacing: '0.1em', textTransform: 'uppercase',
                color: 'var(--text-muted)',
              }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {payouts.map((p, i) => (
            <tr key={p.id} style={{
              borderBottom: '1px solid var(--border)',
              animation: `fadeIn 0.3s ease ${i * 0.05}s both`,
            }}>
              <td style={{ padding: '14px 28px', fontFamily: 'IBM Plex Mono, monospace', fontSize: 13, color: 'var(--text-muted)' }}>
                #{p.id}
              </td>
              <td style={{ padding: '14px 28px', fontFamily: 'IBM Plex Mono, monospace', fontSize: 14, fontWeight: 500 }}>
                {fmtINR(p.amount_paise)}
              </td>
              <td style={{ padding: '14px 28px' }}>
                <StatusBadge status={p.status} />
              </td>
              <td style={{ padding: '14px 28px', fontFamily: 'IBM Plex Mono, monospace', fontSize: 13, color: 'var(--text-muted)' }}>
                {p.attempts}
              </td>
              <td style={{ padding: '14px 28px', fontSize: 12, color: 'var(--text-muted)' }}>
                {fmtDate(p.created_at)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── Ledger ────────────────────────────────────────────────────
function LedgerView({ ledger }) {
  const eventLabel = {
    CREDIT_RECEIVED: 'Credit Received',
    PAYOUT_INITIATED: 'Payout Initiated',
    PAYOUT_REVERSED: 'Payout Reversed',
  }

  return (
    <div style={{
      background: 'var(--white)',
      border: '1px solid var(--border)',
      marginTop: 1,
    }}>
      <div style={{ padding: '16px 28px', borderBottom: '1px solid var(--border)' }}>
        <p style={{
          fontSize: 11, fontWeight: 600, letterSpacing: '0.1em',
          textTransform: 'uppercase', color: 'var(--text-muted)',
        }}>
          Ledger Events
        </p>
      </div>
      <div style={{ maxHeight: 280, overflowY: 'auto' }}>
        {ledger.map((e, i) => (
          <div key={e.id} style={{
            display: 'flex', justifyContent: 'space-between',
            alignItems: 'center',
            padding: '12px 28px',
            borderBottom: '1px solid var(--border)',
            animation: `fadeIn 0.3s ease ${i * 0.03}s both`,
          }}>
            <div>
              <p style={{ fontSize: 13, fontWeight: 500, marginBottom: 2 }}>
                {eventLabel[e.event_type] || e.event_type}
              </p>
              <p style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'IBM Plex Mono, monospace' }}>
                {e.description}
              </p>
            </div>
            <div style={{ textAlign: 'right' }}>
              <p style={{
                fontFamily: 'DM Serif Display, serif',
                fontSize: 20,
                color: e.amount_paise > 0 ? 'var(--green)' : 'var(--red)',
              }}>
                {e.amount_paise > 0 ? '+' : ''}{fmtINR(e.amount_paise)}
              </p>
              <p style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
                {fmtDate(e.created_at)}
              </p>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Sidebar ───────────────────────────────────────────────────
function Sidebar({ merchantName, onLogout }) {
  return (
    <div style={{
      width: 220, minHeight: '100vh',
      background: 'var(--sidebar)',
      padding: '32px 24px',
      display: 'flex', flexDirection: 'column',
      position: 'fixed', top: 0, left: 0,
    }}>
      <div style={{ marginBottom: 48 }}>
        <p style={{
          fontFamily: 'DM Serif Display, serif',
          fontSize: 20, color: '#FFFFFF',
          letterSpacing: '-0.02em',
        }}>
          Playto Pay
        </p>
        <p style={{ fontSize: 11, color: '#6B7280', marginTop: 4, fontFamily: 'IBM Plex Mono, monospace' }}>
          Payout Engine
        </p>
      </div>

      <div style={{
        background: '#1C2030',
        padding: '12px 16px',
        marginBottom: 32,
      }}>
        <p style={{ fontSize: 10, color: '#6B7280', marginBottom: 4, letterSpacing: '0.1em', textTransform: 'uppercase' }}>
          Merchant
        </p>
        <p style={{ fontSize: 13, color: '#E5E7EB', fontWeight: 500 }}>
          {merchantName || '—'}
        </p>
      </div>

      <nav style={{ flex: 1 }}>
        {['Dashboard'].map(item => (
          <div key={item} style={{
            padding: '10px 14px',
            fontSize: 13, color: '#FFFFFF',
            fontWeight: 500,
            background: '#1C2030',
            marginBottom: 4,
            cursor: 'pointer',
            borderLeft: '2px solid #FFFFFF',
          }}>
            {item}
          </div>
        ))}
      </nav>

      <button
        onClick={onLogout}
        style={{
          background: 'transparent',
          border: '1px solid #374151',
          color: '#6B7280',
          padding: '8px 14px',
          fontSize: 12,
          cursor: 'pointer',
          fontFamily: 'IBM Plex Sans, sans-serif',
          textAlign: 'left',
          transition: 'color 0.15s',
        }}
        onMouseEnter={e => e.target.style.color = '#E5E7EB'}
        onMouseLeave={e => e.target.style.color = '#6B7280'}
      >
        Sign out →
      </button>
    </div>
  )
}

// ── Login ─────────────────────────────────────────────────────
function Login({ onLogin }) {
  const [token, setToken] = useState('')

  const SEED_TOKENS = [
    { name: 'Rahul Design Studio', token: '' },
  ]

  return (
    <div style={{
      minHeight: '100vh',
      background: 'var(--sidebar)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}>
      <div style={{
        background: 'var(--white)',
        padding: '48px',
        width: '100%', maxWidth: 420,
        animation: 'fadeIn 0.5s ease both',
      }}>
        <p style={{
          fontFamily: 'DM Serif Display, serif',
          fontSize: 32, marginBottom: 8, color: 'var(--text)',
        }}>
          Playto Pay
        </p>
        <p style={{
          fontSize: 13, color: 'var(--text-muted)',
          marginBottom: 32, fontFamily: 'IBM Plex Mono, monospace',
        }}>
          Merchant Payout Dashboard
        </p>

        <label style={{
          fontSize: 10, fontWeight: 600,
          letterSpacing: '0.1em', textTransform: 'uppercase',
          color: 'var(--text-muted)', display: 'block', marginBottom: 8,
        }}>
          Auth Token
        </label>
        <input
          type="text"
          placeholder="Paste your merchant token"
          value={token}
          onChange={e => setToken(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && token && onLogin(token)}
          style={{
            width: '100%',
            border: '1px solid var(--border)',
            padding: '12px 14px',
            fontSize: 13,
            fontFamily: 'IBM Plex Mono, monospace',
            outline: 'none',
            background: 'var(--bg)',
            marginBottom: 16,
          }}
        />
        <button
          onClick={() => token && onLogin(token)}
          style={{
            width: '100%',
            background: 'var(--text)',
            color: 'var(--white)',
            border: 'none',
            padding: '13px',
            fontSize: 13, fontWeight: 600,
            cursor: 'pointer',
            fontFamily: 'IBM Plex Sans, sans-serif',
            letterSpacing: '0.05em',
          }}
        >
          SIGN IN
        </button>

        <div style={{
          marginTop: 32,
          padding: '16px',
          background: 'var(--bg)',
          borderLeft: '3px solid var(--border)',
        }}>
          <p style={{
            fontSize: 10, fontWeight: 600,
            letterSpacing: '0.1em', textTransform: 'uppercase',
            color: 'var(--text-muted)', marginBottom: 8,
          }}>
            Test Tokens (from seed)
          </p>
          <p style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>
            Run <code style={{ background: '#E5E7EB', padding: '1px 4px', fontFamily: 'IBM Plex Mono, monospace' }}>
              python manage.py seed
            </code> to get fresh tokens
          </p>
        </div>
      </div>
    </div>
  )
}

// ── App ───────────────────────────────────────────────────────
export default function App() {
  const [token, setToken] = useState(localStorage.getItem('playto_token') || '')
  const [balance, setBalance] = useState(null)
  const [payouts, setPayouts] = useState([])
  const [bankAccounts, setBankAccounts] = useState([])
  const [ledger, setLedger] = useState([])
  const [merchantName, setMerchantName] = useState('')
  const [error, setError] = useState(null)

  const api = apiClient(token)

  const fetchAll = useCallback(async () => {
    try {
      const [bal, pays, banks, led] = await Promise.all([
        api.get('/balance/'),
        api.get('/payouts/'),
        api.get('/bank-accounts/'),
        api.get('/ledger/'),
      ])
      setBalance(bal)
      setPayouts(pays)
      setBankAccounts(banks)
      setLedger(led)
      if (banks.length > 0) setMerchantName(banks[0].account_holder_name)
      setError(null)
    } catch (err) {
      // If 401 — token is invalid, log out
      if (err.detail === 'Invalid token.') {
        handleLogout()
        return
      }
      setError('Failed to load data. Check your token.')
    }
  }, [token])
  useEffect(() => {
    if (!token) return
    fetchAll()
    const interval = setInterval(fetchAll, 5000)
    return () => clearInterval(interval)
  }, [token, fetchAll])

  const handleLogin = (t) => {
    localStorage.setItem('playto_token', t)
    setToken(t)
  }

  const handleLogout = () => {
    localStorage.removeItem('playto_token')
    setToken('')
    setBalance(null)
    setPayouts([])
    setBankAccounts([])
    setLedger([])
  }

  if (!token) return <Login onLogin={handleLogin} />

  return (
    <div style={{ display: 'flex' }}>
      <Sidebar merchantName={merchantName} onLogout={handleLogout} />

      <div style={{ marginLeft: 220, flex: 1, padding: '40px 48px', minHeight: '100vh' }}>

        {/* Page header */}
        <div style={{ marginBottom: 32 }}>
          <p style={{
            fontSize: 11, fontWeight: 600,
            letterSpacing: '0.1em', textTransform: 'uppercase',
            color: 'var(--text-muted)', marginBottom: 6,
          }}>
            Overview
          </p>
          <h1 style={{
            fontFamily: 'DM Serif Display, serif',
            fontSize: 28, color: 'var(--text)',
            letterSpacing: '-0.02em',
          }}>
            Merchant Dashboard
          </h1>
        </div>

        {error && (
          <div style={{
            background: '#FEF2F2',
            border: '1px solid #FCA5A5',
            padding: '12px 16px',
            marginBottom: 24,
            fontSize: 13, color: 'var(--red)',
            fontFamily: 'IBM Plex Mono, monospace',
          }}>
            ✕ {error}
          </div>
        )}

        {/* Balance cards */}
        {balance && (
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(3, 1fr)',
            gap: 1,
            marginBottom: 1,
            background: 'var(--border)',
          }}>
            <BalanceCard
              label="Available Balance"
              amount={balance.available_balance_paise}
              color="var(--green)"
              delay={0}
            />
            <BalanceCard
              label="Held in Payouts"
              amount={balance.held_balance_paise}
              color="var(--amber)"
              delay={0.1}
            />
            <BalanceCard
              label="Total Credited"
              amount={balance.total_balance_paise}
              color="var(--text)"
              delay={0.2}
            />
          </div>
        )}

        <PayoutForm
          api={api}
          bankAccounts={bankAccounts}
          onPayoutCreated={fetchAll}
        />

        <PayoutHistory payouts={payouts} />

        {ledger.length > 0 && <LedgerView ledger={ledger} />}

      </div>
    </div>
  )
}