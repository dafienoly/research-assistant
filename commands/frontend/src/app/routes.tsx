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

// System pages
import OpsCenter from '../pages/OpsCenter'
import CodeAudit from '../pages/CodeAudit'

// Legacy / hidden pages (kept for URL compatibility)
import RiskDashboard from '../pages/RiskDashboard'
import {
  VNextApprovals,
  VNextBacktests,
  VNextCandidates,
  VNextDataHealth,
  VNextExecution,
  VNextHome,
  VNextML,
  VNextPortfolio,
  VNextRegime,
  VNextReview,
  VNextSemi,
  VNextTrading,
} from '../pages/vnext'

const routes: RouteObject[] = [
  {
    path: '/',
    element: <MainLayout />,
    children: [
      // Research navigation
      { index: true, element: <VNextHome /> },
      { path: 'vnext/regime', element: <VNextRegime /> },
      { path: 'vnext/semi', element: <VNextSemi /> },
      { path: 'vnext/candidates', element: <VNextCandidates /> },
      { path: 'vnext/portfolio', element: <VNextPortfolio /> },
      { path: 'vnext/ml', element: <VNextML /> },
      { path: 'vnext/backtests', element: <VNextBacktests /> },
      { path: 'vnext/trading', element: <VNextTrading /> },
      { path: 'vnext/approvals', element: <VNextApprovals /> },
      { path: 'vnext/execution', element: <VNextExecution /> },
      { path: 'vnext/review', element: <VNextReview /> },
      { path: 'vnext/data-health', element: <VNextDataHealth /> },

      // Legacy research pages remain URL-compatible.
      { path: 'legacy-dashboard', element: <Dashboard /> },
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

      // System pages
      { path: 'ops', element: <OpsCenter /> },
      { path: 'code-audit', element: <CodeAudit /> },

      // Legacy routes
      { path: 'risk', element: <RiskDashboard /> },
    ],
  },
]

export default routes
