import { create } from 'zustand'

export type ThemePreference = 'system' | 'light' | 'dark'
export type ResolvedTheme = 'light' | 'dark'

const STORAGE_KEY = 'capeigen_theme'

type ThemeState = {
  preference: ThemePreference
  resolved: ResolvedTheme
  /** Apply preference, persist (except default system), and sync DOM. */
  setPreference: (preference: ThemePreference) => void
  /** Flip between light and dark (leaves system mode). */
  toggle: () => void
  init: () => () => void
}

function readStoredPreference(): ThemePreference {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw === 'light' || raw === 'dark' || raw === 'system') return raw
  } catch {
    /* ignore */
  }
  return 'system'
}

function getSystemTheme(): ResolvedTheme {
  if (typeof window === 'undefined') return 'light'
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function resolveTheme(preference: ThemePreference): ResolvedTheme {
  return preference === 'system' ? getSystemTheme() : preference
}

function applyToDocument(resolved: ResolvedTheme): void {
  const root = document.documentElement
  root.classList.toggle('dark', resolved === 'dark')
  root.style.colorScheme = resolved
}

function persistPreference(preference: ThemePreference): void {
  try {
    if (preference === 'system') localStorage.removeItem(STORAGE_KEY)
    else localStorage.setItem(STORAGE_KEY, preference)
  } catch {
    /* ignore */
  }
}

export const useThemeStore = create<ThemeState>((set, get) => ({
  preference: 'system',
  resolved: 'light',
  setPreference: (preference) => {
    const resolved = resolveTheme(preference)
    persistPreference(preference)
    applyToDocument(resolved)
    set({ preference, resolved })
  },
  toggle: () => {
    const next: ThemePreference = get().resolved === 'dark' ? 'light' : 'dark'
    get().setPreference(next)
  },
  init: () => {
    const preference = readStoredPreference()
    const resolved = resolveTheme(preference)
    applyToDocument(resolved)
    set({ preference, resolved })

    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const onSystemChange = () => {
      if (get().preference !== 'system') return
      const next = resolveTheme('system')
      applyToDocument(next)
      set({ resolved: next })
    }
    mq.addEventListener('change', onSystemChange)
    return () => mq.removeEventListener('change', onSystemChange)
  },
}))
