import { RouteObject } from 'react-router-dom'
import MainLayout from './layout/MainLayout'

// Page imports
import Dashboard from '../pages/Dashboard'
import DataStatus from '../pages/DataStatus'
import StockPool from '../pages/StockPool'
import SemiTheme from '../pages/SemiTheme'
import FactorLab from '../pages/FactorLab'
import BacktestLab from '../pages/BacktestLab'
import Portfolio from '../pages/Portfolio'
import QMTSpot from '../pages/QMTSpot'
import PaperDashboard from '../pages/PaperDashboard'
import LiveGate from '../pages/LiveGate'
import Reports from '../pages/Reports'
import Events from '../pages/Events'

// System pages (accessible via AgentOpsDrawer)
import AgentConsole from '../pages/AgentConsole'
import Roadmap from '../pages/Roadmap'
import OpsCenter from '../pages/OpsCenter'
import TaskCenter from '../pages/TaskCenter'
import SessionHistory from '../pages/SessionHistory'
import Feedback from '../pages/Feedback'
import Backup from '../pages/Backup'
import Settings from '../pages/Settings'

// Legacy / hidden pages (kept for URL compatibility)
import RiskDashboard from '../pages/RiskDashboard'

const routes: RouteObject[] = [
  {
    path: '/',
    element: <MainLayout />,
    children: [
      // Research navigation
      { index: true, element: <Dashboard /> },
      { path: 'data', element: <DataStatus /> },
      { path: 'stocks', element: <StockPool /> },
      { path: 'semi', element: <SemiTheme /> },
      { path: 'factors', element: <FactorLab /> },
      { path: 'backtest', element: <BacktestLab /> },
      { path: 'portfolio', element: <Portfolio /> },
      { path: 'qmt', element: <QMTSpot /> },
      { path: 'paper', element: <PaperDashboard /> },
      { path: 'livegate', element: <LiveGate /> },
      { path: 'reports', element: <Reports /> },
      { path: 'events', element: <Events /> },

      // System pages (AgentOpsDrawer)
      { path: 'console', element: <AgentConsole /> },
      { path: 'roadmap', element: <Roadmap /> },
      { path: 'ops', element: <OpsCenter /> },
      { path: 'tasks', element: <TaskCenter /> },
      { path: 'history', element: <SessionHistory /> },
      { path: 'feedback', element: <Feedback /> },
      { path: 'backup', element: <Backup /> },
      { path: 'settings', element: <Settings /> },

      // Legacy routes
      { path: 'risk', element: <RiskDashboard /> },
    ],
  },
]

export default routes
