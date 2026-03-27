import React, { useState } from 'react'

export interface Column<T> {
  key: string
  label: string
  render?: (row: T) => React.ReactNode
  sortable?: boolean
  align?: 'left' | 'right' | 'center'
}

interface Props<T> {
  columns: Column<T>[]
  rows: T[]
  rowKey: (row: T, index?: number) => string | number
  onRowClick?: (row: T) => void
}

export default function DataTable<T>({ columns, rows, rowKey, onRowClick }: Props<T>) {
  const [sortKey, setSortKey] = useState<string | null>(null)
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')

  function handleSort(key: string) {
    if (sortKey === key) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortKey(key); setSortDir('desc') }
  }

  const sorted = sortKey
    ? [...rows].sort((a: any, b: any) => {
        const av = a[sortKey], bv = b[sortKey]
        if (av == null) return 1
        if (bv == null) return -1
        const cmp = av < bv ? -1 : av > bv ? 1 : 0
        return sortDir === 'asc' ? cmp : -cmp
      })
    : rows

  return (
    <div style={{ overflowX: 'auto', borderRadius: 8, border: '1px solid var(--border-subtle)' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
        <thead>
          <tr style={{ background: 'var(--bg-elevated)', borderBottom: '1px solid var(--border-subtle)' }}>
            {columns.map(col => (
              <th
                key={col.key}
                onClick={() => col.sortable !== false && handleSort(col.key)}
                style={{
                  padding: '10px 14px',
                  textAlign: col.align ?? 'left',
                  color: 'var(--text-muted)',
                  fontWeight: 500,
                  fontSize: 11,
                  textTransform: 'uppercase',
                  letterSpacing: '0.5px',
                  cursor: col.sortable !== false ? 'pointer' : 'default',
                  whiteSpace: 'nowrap',
                  userSelect: 'none',
                }}
              >
                {col.label} {sortKey === col.key && (sortDir === 'asc' ? '↑' : '↓')}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row, i) => (
            <tr
              key={rowKey(row, i)}
              onClick={() => onRowClick?.(row)}
              style={{
                borderBottom: i < sorted.length - 1 ? '1px solid var(--border-subtle)' : undefined,
                background: 'var(--bg-surface)',
                cursor: onRowClick ? 'pointer' : 'default',
                transition: 'background 0.1s',
              }}
              onMouseEnter={e => { if (onRowClick) (e.currentTarget as HTMLElement).style.background = 'var(--bg-elevated)' }}
              onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'var(--bg-surface)' }}
            >
              {columns.map(col => (
                <td
                  key={col.key}
                  style={{
                    padding: '10px 14px',
                    color: 'var(--text-primary)',
                    textAlign: col.align ?? 'left',
                  }}
                >
                  {col.render ? col.render(row) : (row as any)[col.key] ?? '—'}
                </td>
              ))}
            </tr>
          ))}
          {sorted.length === 0 && (
            <tr>
              <td colSpan={columns.length} style={{ padding: 32, textAlign: 'center', color: 'var(--text-muted)' }}>
                No data
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}
