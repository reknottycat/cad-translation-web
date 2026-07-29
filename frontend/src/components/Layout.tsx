import React from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import {
  FolderIcon,
  HistoryIcon,
  HomeIcon,
  NotificationIcon,
  SettingIcon,
  TranslateIcon,
  UserCircleIcon,
  ViewModuleIcon,
} from 'tdesign-icons-react'

interface LayoutProps {
  children: React.ReactNode
}

const navItems = [
  { to: '/', label: 'Dashboard', icon: <HomeIcon /> },
  { to: '/cad', label: 'CAD Workspace', icon: <ViewModuleIcon /> },
  { to: '/projects', label: 'Projects', icon: <HistoryIcon /> },
  { to: '/translation', label: 'Text Tools', icon: <TranslateIcon /> },
  { to: '/gateway', label: 'Model Config', icon: <SettingIcon /> },
]

const pageMeta: Record<string, { title: string; description: string; badge: string }> = {
  '/': {
    title: 'Dashboard',
    description: 'View runtime health, active work, and recent outputs.',
    badge: 'Workstation Overview',
  },
  '/cad': {
    title: 'CAD Workspace',
    description: 'Upload files, extract text, edit translations, and export results.',
    badge: 'Primary Toolchain',
  },
  '/projects': {
    title: 'Projects',
    description: 'Inspect task history, outputs, logs, and retry candidates.',
    badge: 'Task Ledger',
  },
  '/translation': {
    title: 'Text Tools',
    description: 'Translate text snippets or batch Excel files with the current model.',
    badge: 'Quick Utilities',
  },
  '/gateway': {
    title: 'Model Config',
    description: 'Configure provider, endpoint, credentials, and runtime tuning.',
    badge: 'Runtime Setup',
  },
}

const Layout: React.FC<LayoutProps> = ({ children }) => {
  const location = useLocation()
  const meta = pageMeta[location.pathname] || pageMeta['/']

  return (
    <div className="app-shell">
      <aside className="app-sidebar">
        <div className="sidebar-brand">
          <NavLink to="/" className="brand-lockup">
            <div className="brand-mark">CE</div>
            <div>
              <div className="brand-title">CAD Engine</div>
              <div className="brand-subtitle">Translation Workstation</div>
            </div>
          </NavLink>

          <div className="sidebar-hero">
            <div className="sidebar-hero-kicker">The Precision Engine</div>
            <p className="sidebar-hero-copy">
              Tool-first, dense, and focused on real CAD translation operations.
            </p>
          </div>
        </div>

        <nav className="sidebar-nav" aria-label="Primary">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) => `nav-item${isActive ? ' nav-item-active' : ''}`}
            >
              <span className="nav-item-icon">{item.icon}</span>
              <span className="nav-item-label">{item.label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="sidebar-summary">
          <div className="summary-row">
            <span className="summary-label">Status</span>
            <span className="pill pill-success">Online</span>
          </div>
          <div className="summary-row">
            <span className="summary-label">Mode</span>
            <strong>Local workstation</strong>
          </div>
          <div className="summary-row">
            <span className="summary-label">Data</span>
            <strong>DWG / DXF / XLSX</strong>
          </div>
          <div className="summary-row">
            <span className="summary-label">Flow</span>
            <strong>Extract → Translate → Apply</strong>
          </div>
        </div>
      </aside>

      <div className="app-stage">
        <header className="app-topbar">
          <div className="topbar-copy">
            <div className="topbar-kicker">{meta.badge}</div>
            <div className="topbar-title">{meta.title}</div>
            <div className="topbar-description">{meta.description}</div>
          </div>

          <div className="topbar-actions">
            <span className="status-chip status-chip-neutral">
              <span className="status-dot" />
              API Ready
            </span>
            <span className="status-chip status-chip-success">Runtime Stable</span>
            <button type="button" className="icon-button" aria-label="Notifications">
              <NotificationIcon />
            </button>
            <button type="button" className="icon-button" aria-label="Profile">
              <UserCircleIcon />
            </button>
          </div>
        </header>

        <main className="app-main">
          <div className="container-xl page-stack">{children}</div>
        </main>
      </div>
    </div>
  )
}

export default Layout
