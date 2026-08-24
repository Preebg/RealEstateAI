import { StrictMode, useEffect, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import './index.css'
import App from './App.tsx'
import { useThemeStore } from './lib/theme'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false },
  },
})

function ThemeRoot({ children }: { children: ReactNode }) {
  const init = useThemeStore((s) => s.init)
  useEffect(() => init(), [init])
  return children
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <ThemeRoot>
          <App />
        </ThemeRoot>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
