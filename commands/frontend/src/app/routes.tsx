/* oxlint-disable react/only-export-components -- route modules intentionally own lazy page factories */
import { lazy, Suspense, type ComponentType, type LazyExoticComponent } from 'react'
import type { RouteObject } from 'react-router-dom'
import MainLayout from './layout/MainLayout'
import LoadingState from '../components/common/LoadingState'

const Dashboard = lazy(() => import('../pages/Dashboard'))
const DataStatus = lazy(() => import('../pages/DataStatus'))
const StockPool = lazy(() => import('../pages/StockPool'))
const SemiTheme = lazy(() => import('../pages/SemiTheme'))
const FactorLab = lazy(() => import('../pages/FactorLab'))
const BacktestLab = lazy(() => import('../pages/BacktestLab'))
const Portfolio = lazy(() => import('../pages/Portfolio'))
const QMTSpot = lazy(() => import('../pages/QMTSpot'))
const PaperDashboard = lazy(() => import('../pages/PaperDashboard'))
const LiveGate = lazy(() => import('../pages/LiveGate'))
const Reports = lazy(() => import('../pages/Reports'))
const Events = lazy(() => import('../pages/Events'))
const DecisionCenter = lazy(() => import('../pages/DecisionCenter'))
const OpsCenter = lazy(() => import('../pages/OpsCenter'))
const CodeAudit = lazy(() => import('../pages/CodeAudit'))
const RiskDashboard = lazy(() => import('../pages/RiskDashboard'))

function namedPage(name: string) {
  return lazy(async () => {
    const pages = await import('../pages/vnext')
    return { default: pages[name as keyof typeof pages] as ComponentType }
  })
}

const VNextHome = namedPage('VNextHome')
const VNextRegime = namedPage('VNextRegime')
const VNextSemi = namedPage('VNextSemi')
const VNextCandidates = namedPage('VNextCandidates')
const VNextPortfolio = namedPage('VNextPortfolio')
const VNextML = namedPage('VNextML')
const VNextBacktests = namedPage('VNextBacktests')
const VNextTrading = namedPage('VNextTrading')
const VNextApprovals = namedPage('VNextApprovals')
const VNextExecution = namedPage('VNextExecution')
const VNextReview = namedPage('VNextReview')
const VNextDataHealth = namedPage('VNextDataHealth')

function page(Component: LazyExoticComponent<ComponentType>) {
  return <Suspense fallback={<LoadingState tip="正在按需加载页面" />}><Component /></Suspense>
}

const routes: RouteObject[] = [
  {
    path: '/',
    element: <MainLayout />,
    children: [
      { index: true, element: page(VNextHome) },
      { path: 'vnext/regime', element: page(VNextRegime) },
      { path: 'vnext/semi', element: page(VNextSemi) },
      { path: 'vnext/candidates', element: page(VNextCandidates) },
      { path: 'vnext/portfolio', element: page(VNextPortfolio) },
      { path: 'vnext/ml', element: page(VNextML) },
      { path: 'vnext/backtests', element: page(VNextBacktests) },
      { path: 'vnext/trading', element: page(VNextTrading) },
      { path: 'vnext/approvals', element: page(VNextApprovals) },
      { path: 'vnext/execution', element: page(VNextExecution) },
      { path: 'vnext/review', element: page(VNextReview) },
      { path: 'vnext/data-health', element: page(VNextDataHealth) },
      { path: 'decision-loop', element: page(DecisionCenter) },
      { path: 'legacy-dashboard', element: page(Dashboard) },
      { path: 'data', element: page(DataStatus) },
      { path: 'stocks', element: page(StockPool) },
      { path: 'semi', element: page(SemiTheme) },
      { path: 'factors', element: page(FactorLab) },
      { path: 'backtest', element: page(BacktestLab) },
      { path: 'portfolio', element: page(Portfolio) },
      { path: 'qmt', element: page(QMTSpot) },
      { path: 'paper', element: page(PaperDashboard) },
      { path: 'livegate', element: page(LiveGate) },
      { path: 'reports', element: page(Reports) },
      { path: 'events', element: page(Events) },
      { path: 'ops', element: page(OpsCenter) },
      { path: 'code-audit', element: page(CodeAudit) },
      { path: 'risk', element: page(RiskDashboard) },
    ],
  },
]

export default routes
