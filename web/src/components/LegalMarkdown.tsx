import { useMemo, type ReactNode } from 'react'

export function formatLegalEffectiveDate(iso?: string | null): string | null {
  if (!iso) return null
  const d = new Date(`${iso}T00:00:00`)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  })
}

function renderInline(text: string): ReactNode[] {
  const parts: ReactNode[] = []
  const re = /\*\*(.+?)\*\*/g
  let last = 0
  let match: RegExpExecArray | null
  let key = 0
  while ((match = re.exec(text)) !== null) {
    if (match.index > last) {
      parts.push(text.slice(last, match.index))
    }
    parts.push(
      <strong key={key++} className="font-semibold text-text">
        {match[1]}
      </strong>,
    )
    last = match.index + match[0].length
  }
  if (last < text.length) parts.push(text.slice(last))
  return parts
}

export function stripDuplicateLegalTitle(markdown: string, title: string): string {
  const trimmed = markdown.trim()
  const escaped = title.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return trimmed
    .replace(new RegExp(`^#{1,6}\\s*${escaped}\\s*\\n+`, 'i'), '')
    .replace(new RegExp(`^\\*\\*Effective date:\\*\\*[^\\n]*\\n+`, 'i'), '')
    .trim()
}

/** Renders the same Markdown subset used on public `/legal/:doc` pages. */
export function LegalBody({ markdown }: { markdown: string }) {
  const blocks = useMemo(() => {
    const lines = markdown.replace(/\r\n/g, '\n').split('\n')
    const nodes: ReactNode[] = []
    let i = 0
    let key = 0

    while (i < lines.length) {
      const line = lines[i]
      const trimmed = line.trim()

      if (!trimmed) {
        i += 1
        continue
      }

      if (trimmed === '---') {
        nodes.push(<hr key={key++} className="my-8 border-border" />)
        i += 1
        continue
      }

      const heading = /^(#{1,6})\s+(.+)$/.exec(trimmed)
      if (heading) {
        const level = heading[1].length
        const content = renderInline(heading[2].trim())
        if (level <= 3) {
          nodes.push(
            <h2
              key={key++}
              className="mt-10 font-display text-xl font-semibold tracking-tight text-text first:mt-0"
            >
              {content}
            </h2>,
          )
        } else {
          nodes.push(
            <h3
              key={key++}
              className="mt-8 font-display text-base font-semibold tracking-tight text-text first:mt-0"
            >
              {content}
            </h3>,
          )
        }
        i += 1
        continue
      }

      if (trimmed.startsWith('- ')) {
        const items: string[] = []
        while (i < lines.length && lines[i].trim().startsWith('- ')) {
          items.push(lines[i].trim().slice(2))
          i += 1
        }
        nodes.push(
          <ul key={key++} className="mt-3 list-disc space-y-2 pl-5 text-[15px] leading-relaxed text-muted">
            {items.map((item, idx) => (
              <li key={idx}>{renderInline(item)}</li>
            ))}
          </ul>,
        )
        continue
      }

      const para: string[] = [trimmed]
      i += 1
      while (i < lines.length) {
        const next = lines[i].trim()
        if (!next || next === '---' || next.startsWith('#') || next.startsWith('- ')) {
          break
        }
        para.push(next)
        i += 1
      }
      nodes.push(
        <p key={key++} className="mt-3 text-[15px] leading-relaxed text-muted first:mt-0">
          {renderInline(para.join(' '))}
        </p>,
      )
    }

    return nodes
  }, [markdown])

  return <div className="legal-body">{blocks}</div>
}

/** Public legal article chrome: title, effective date, and body. */
export function LegalDocumentPreview({
  title,
  effectiveDate,
  body,
  className,
}: {
  title: string
  effectiveDate?: string | null
  body: string
  className?: string
}) {
  const effectiveLabel = formatLegalEffectiveDate(effectiveDate)
  const bodyMarkdown = useMemo(
    () => stripDuplicateLegalTitle(body || '', title),
    [body, title],
  )

  return (
    <article className={className}>
      <header>
        <h1 className="font-display text-3xl font-semibold tracking-tight sm:text-4xl">{title}</h1>
        {effectiveLabel && <p className="mt-3 text-sm text-muted">Effective {effectiveLabel}</p>}
      </header>
      <div className="mt-8">
        <LegalBody markdown={bodyMarkdown} />
      </div>
    </article>
  )
}
