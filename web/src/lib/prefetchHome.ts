import type { QueryClient } from '@tanstack/react-query'
import { fetchPortfolio } from './portfolio'

/** Warm the Home page JS chunk (Leaflet map + filters) before navigation. */
export function prefetchHomeChunk(): void {
  void import('../pages/HomePage')
}

/**
 * Start the portfolio fetch as soon as a session exists so Home mounts with
 * an in-flight (or completed) React Query request instead of a cold start.
 */
export function prefetchHomeData(queryClient: QueryClient): void {
  void queryClient.prefetchQuery({
    queryKey: ['portfolio'],
    queryFn: fetchPortfolio,
  })
}

/** Chunk + data when the user is clearly about to land on Home after auth. */
export function prefetchHome(queryClient?: QueryClient): void {
  prefetchHomeChunk()
  if (queryClient) prefetchHomeData(queryClient)
}
