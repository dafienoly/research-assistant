import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useRoutes } from 'react-router-dom'
import ErrorBoundary from './components/common/ErrorBoundary'
import routes from './app/routes'

/** Base API URL — use relative paths via Vite proxy (dev) or same-origin (prod) */
const API = ''
export { API }

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 2,
      staleTime: 30_000,
      refetchOnWindowFocus: true,
    },
  },
})

export default function App() {
  const element = useRoutes(routes)
  return (
    <QueryClientProvider client={queryClient}>
      <ErrorBoundary>{element}</ErrorBoundary>
    </QueryClientProvider>
  )
}
