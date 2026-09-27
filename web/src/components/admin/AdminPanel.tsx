import { useState } from 'react'
import type { User } from '../../lib/types'
import AdminUsers from './AdminUsers'
import AdminData from './AdminData'
import AdminUsage from './AdminUsage'

const TABS = [
  { id: 'users', label: 'Users' },
  { id: 'data', label: 'Data' },
  { id: 'usage', label: 'Usage' },
] as const

type TabId = (typeof TABS)[number]['id']

export default function AdminPanel({ me }: { me: User }) {
  const [tab, setTab] = useState<TabId>('users')
  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 gap-1 border-b border-zinc-800 px-4 pt-1">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm transition ${
              tab === t.id
                ? 'border-emerald-600 font-medium text-zinc-100'
                : 'border-transparent text-zinc-500 hover:text-zinc-300'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {tab === 'users' && <AdminUsers me={me.username} />}
        {tab === 'data' && <AdminData />}
        {tab === 'usage' && <AdminUsage />}
      </div>
    </div>
  )
}
