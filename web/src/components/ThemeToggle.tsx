import { Moon, Sun } from 'lucide-react'
import { clsx } from 'clsx'
import { useThemeStore } from '../lib/theme'

type ThemeToggleProps = {
  className?: string
}

/** Toggles light/dark. Default preference follows the OS until the user chooses. */
export function ThemeToggle({ className }: ThemeToggleProps) {
  const resolved = useThemeStore((s) => s.resolved)
  const toggle = useThemeStore((s) => s.toggle)
  const isDark = resolved === 'dark'

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
      title={isDark ? 'Light mode' : 'Dark mode'}
      className={clsx(
        'inline-flex size-9 items-center justify-center rounded-lg border border-border text-text/80 transition',
        'hover:bg-surface hover:text-text',
        className,
      )}
    >
      {isDark ? <Sun size={18} aria-hidden /> : <Moon size={18} aria-hidden />}
    </button>
  )
}
