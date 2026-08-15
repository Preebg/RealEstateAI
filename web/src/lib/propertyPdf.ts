import { jsPDF } from 'jspdf'
import type { FinanceMetrics } from './finance'

const PAGE_W = 612
const PAGE_H = 792
const MARGIN = 40
const INDIGO: [number, number, number] = [79, 70, 229]
const INDIGO_DARK: [number, number, number] = [49, 46, 129]
const SURFACE: [number, number, number] = [238, 242, 255]
const TEXT: [number, number, number] = [26, 26, 46]
const MUTED: [number, number, number] = [100, 116, 139]
const WHITE: [number, number, number] = [255, 255, 255]
const GREEN: [number, number, number] = [5, 150, 105]
const ROSE: [number, number, number] = [225, 29, 72]
const BORDER: [number, number, number] = [224, 228, 239]
const PAGE_BG: [number, number, number] = [248, 250, 252]

const TAGLINE = 'AI rental underwriting with QAOA portfolio alignment.'

export type PdfBreakdownRow = {
  label: string
  amount: string
  value: number
  emphasize?: boolean
}

export type PropertyPdfInput = {
  address: string
  summary?: string
  locationScore: number
  strategy?: string
  yearBuilt?: number
  price: number
  assumptions: {
    down_payment_pct: number
    interest_rate: number
    loan_term: number
    closing_costs_pct: number
    monthly_rent: number
  }
  finance: FinanceMetrics
  breakdown: PdfBreakdownRow[]
  quantum?: Record<string, number>
  forecastValues?: number[]
}

export function pdfDownloadFilename(address: string): string {
  const cleaned = address
    .replace(/[<>:"/\\|?*\u0000-\u001f]+/g, '')
    .replace(/\s+/g, ' ')
    .replace(/^[.\s]+|[.\s]+$/g, '')
  const slug = (cleaned || 'property').slice(0, 80)
  return `CapEigen - ${slug}.pdf`
}

function money(n: number): string {
  const abs = Math.abs(n).toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  })
  return n < 0 ? `-$${abs}` : `$${abs}`
}

function moneyExact(n: number): string {
  const abs = Math.abs(n).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
  return n < 0 ? `-$${abs}` : `$${abs}`
}

function drawChrome(doc: jsPDF): void {
  doc.setFillColor(...PAGE_BG)
  doc.rect(0, 0, PAGE_W, PAGE_H, 'F')

  doc.setFillColor(...INDIGO)
  doc.rect(0, 0, PAGE_W, 28, 'F')
  doc.setFillColor(...WHITE)
  doc.roundedRect(MARGIN, 8, 12, 12, 2, 2, 'F')
  doc.setTextColor(...INDIGO)
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(9)
  doc.text('C', MARGIN + 6, 17, { align: 'center' })
  doc.setTextColor(...WHITE)
  doc.setFontSize(11)
  doc.text('CapEigen', MARGIN + 18, 18)
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(8)
  doc.text('Confidential analysis', PAGE_W - MARGIN, 18, { align: 'right' })

  doc.setFillColor(...INDIGO)
  doc.rect(0, PAGE_H - 22, PAGE_W, 22, 'F')
  doc.setTextColor(...WHITE)
  doc.setFontSize(8)
  doc.text('Prepared by CapEigen', MARGIN, PAGE_H - 9)
  doc.text(`Page ${doc.getNumberOfPages()}`, PAGE_W - MARGIN, PAGE_H - 9, {
    align: 'right',
  })
}

function ensureSpace(doc: jsPDF, y: number, needed: number): number {
  if (y + needed < PAGE_H - 36) return y
  doc.addPage()
  drawChrome(doc)
  return 44
}

function sectionTitle(doc: jsPDF, title: string, y: number): number {
  y = ensureSpace(doc, y, 22)
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(12)
  doc.setTextColor(...INDIGO_DARK)
  doc.text(title, MARGIN, y)
  return y + 14
}

function kpiCards(
  doc: jsPDF,
  items: Array<[string, string]>,
  y: number,
): number {
  const gap = 8
  const width = (PAGE_W - MARGIN * 2 - gap * (items.length - 1)) / items.length
  const accents: Array<[number, number, number]> = [
    INDIGO,
    [13, 148, 136],
    [124, 58, 237],
    [217, 119, 6],
  ]
  y = ensureSpace(doc, y, 52)
  items.forEach(([label, value], i) => {
    const x = MARGIN + i * (width + gap)
    doc.setFillColor(...SURFACE)
    doc.roundedRect(x, y, width, 48, 4, 4, 'F')
    doc.setFillColor(...accents[i % accents.length])
    doc.rect(x, y, width, 3, 'F')
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(7)
    doc.setTextColor(...MUTED)
    doc.text(label.toUpperCase(), x + 8, y + 16)
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(11)
    doc.setTextColor(...INDIGO_DARK)
    const lines = doc.splitTextToSize(value, width - 16)
    doc.text(lines, x + 8, y + 32)
  })
  return y + 60
}

function drawCashFlowChart(doc: jsPDF, rows: PdfBreakdownRow[], y: number): number {
  const chartRows = rows.filter((r) => !/total/i.test(r.label))
  if (chartRows.length < 2) return y
  const canvas = document.createElement('canvas')
  const rowH = 28
  canvas.width = 1100
  canvas.height = 70 + chartRows.length * rowH
  const ctx = canvas.getContext('2d')
  if (!ctx) return y

  ctx.fillStyle = '#ffffff'
  ctx.fillRect(0, 0, canvas.width, canvas.height)
  ctx.font = '600 18px Inter, system-ui, sans-serif'
  ctx.fillStyle = '#312e81'
  ctx.fillText('Monthly cash flow mix', 8, 28)

  const values = chartRows.map((r) => r.value)
  const maxAbs = Math.max(...values.map((v) => Math.abs(v)), 1)
  const plotLeft = 280
  const plotWidth = canvas.width - plotLeft - 120
  const zeroX = plotLeft + (maxAbs / (maxAbs * 2)) * plotWidth

  ctx.strokeStyle = '#94a3b8'
  ctx.lineWidth = 1
  ctx.beginPath()
  ctx.moveTo(zeroX, 46)
  ctx.lineTo(zeroX, canvas.height - 12)
  ctx.stroke()

  chartRows.forEach((row, i) => {
    const top = 52 + i * rowH
    const barW = (Math.abs(row.value) / (maxAbs * 2)) * plotWidth
    const x = row.value >= 0 ? zeroX : zeroX - barW
    const low = row.label.toLowerCase()
    if (low.includes('cash flow')) ctx.fillStyle = row.value >= 0 ? '#059669' : '#e11d48'
    else if (low.includes('rent')) ctx.fillStyle = '#4f46e5'
    else ctx.fillStyle = '#fb7185'
    ctx.fillRect(x, top, Math.max(barW, 2), 18)
    ctx.fillStyle = '#1a1a2e'
    ctx.font = '15px Inter, system-ui, sans-serif'
    ctx.textAlign = 'right'
    ctx.fillText(row.label.replace(' (P&I)', '').replace(' (CapEx)', ''), plotLeft - 12, top + 14)
    ctx.textAlign = 'left'
    ctx.fillText(row.amount, plotLeft + plotWidth + 8, top + 14)
  })

  const imgH = Math.min(210, 28 + chartRows.length * 16)
  y = ensureSpace(doc, y, imgH + 8)
  doc.addImage(canvas.toDataURL('image/png'), 'PNG', MARGIN, y, PAGE_W - MARGIN * 2, imgH)
  return y + imgH + 10
}

function drawForecastChart(doc: jsPDF, values: number[], y: number): number {
  const nums = values.filter((v) => Number.isFinite(v))
  if (nums.length < 2) return y
  const canvas = document.createElement('canvas')
  canvas.width = 1100
  canvas.height = 360
  const ctx = canvas.getContext('2d')
  if (!ctx) return y
  ctx.fillStyle = '#ffffff'
  ctx.fillRect(0, 0, canvas.width, canvas.height)
  ctx.font = '600 18px Inter, system-ui, sans-serif'
  ctx.fillStyle = '#312e81'
  ctx.fillText('10-year value path', 8, 28)

  const min = Math.min(...nums) * 0.96
  const max = Math.max(...nums) * 1.04
  const left = 70
  const top = 50
  const width = canvas.width - 90
  const height = 270
  ctx.strokeStyle = '#e0e4ef'
  ctx.lineWidth = 1
  for (let i = 0; i <= 4; i += 1) {
    const gy = top + (height * i) / 4
    ctx.beginPath()
    ctx.moveTo(left, gy)
    ctx.lineTo(left + width, gy)
    ctx.stroke()
  }
  ctx.beginPath()
  ctx.strokeStyle = '#4f46e5'
  ctx.lineWidth = 3
  nums.forEach((v, i) => {
    const x = left + (i / Math.max(nums.length - 1, 1)) * width
    const py = top + height - ((v - min) / Math.max(max - min, 1)) * height
    if (i === 0) ctx.moveTo(x, py)
    else ctx.lineTo(x, py)
  })
  ctx.stroke()
  nums.forEach((v, i) => {
    const x = left + (i / Math.max(nums.length - 1, 1)) * width
    const py = top + height - ((v - min) / Math.max(max - min, 1)) * height
    ctx.fillStyle = '#4f46e5'
    ctx.beginPath()
    ctx.arc(x, py, 4, 0, Math.PI * 2)
    ctx.fill()
  })

  y = ensureSpace(doc, y, 150)
  doc.addImage(canvas.toDataURL('image/png'), 'PNG', MARGIN, y, PAGE_W - MARGIN * 2, 140)
  return y + 150
}

export function buildPropertyPdfBlob(input: PropertyPdfInput): Blob {
  const doc = new jsPDF({ unit: 'pt', format: 'letter' })
  doc.setProperties({
    title: `CapEigen — ${input.address}`,
    author: 'CapEigen',
    creator: 'CapEigen Property Analysis',
    subject: `CapEigen investment analysis for ${input.address}`,
  })
  drawChrome(doc)

  let y = 40
  doc.setFillColor(...INDIGO_DARK)
  doc.roundedRect(MARGIN, y, PAGE_W - MARGIN * 2, 78, 6, 6, 'F')
  doc.setTextColor(...WHITE)
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(13)
  doc.text('CapEigen', MARGIN + 14, y + 22)
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(8)
  doc.setTextColor(199, 210, 254)
  doc.text(TAGLINE, MARGIN + 14, y + 36)
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(16)
  doc.setTextColor(...WHITE)
  const addrLines = doc.splitTextToSize(input.address || 'Address unavailable', PAGE_W - MARGIN * 2 - 28)
  doc.text(addrLines, MARGIN + 14, y + 56)
  y += 94

  y = kpiCards(
    doc,
    [
      ['Cap rate', `${input.finance.cap_rate.toFixed(2)}%`],
      ['Cash on cash', `${input.finance.cash_on_cash.toFixed(2)}%`],
      ['Cash flow / mo', moneyExact(input.finance.monthly_net_cash_flow)],
      ['Location score', `${input.locationScore.toFixed(1)}/10`],
    ],
    y,
  )

  y = sectionTitle(doc, 'Underwriting assumptions', y)
  const params: Array<[string, string]> = [
    ['Offer amount', money(input.price)],
    ['Year built', input.yearBuilt != null && input.yearBuilt >= 1800 ? String(input.yearBuilt) : '—'],
    ['Down payment', `${input.assumptions.down_payment_pct}%`],
    ['Interest rate', `${input.assumptions.interest_rate}%`],
    ['Loan term', `${input.assumptions.loan_term} years`],
    ['Closing costs', `${input.assumptions.closing_costs_pct}%`],
    ['Monthly rent', moneyExact(input.assumptions.monthly_rent)],
    ['Total cash required', moneyExact(input.finance.total_investment)],
    ['Strategy', input.strategy || '—'],
  ]
  const colW = (PAGE_W - MARGIN * 2) / 4
  const paramRows = Math.ceil(params.length / 4)
  y = ensureSpace(doc, y, paramRows * 36)
  params.forEach((pair, i) => {
    const col = i % 4
    const row = Math.floor(i / 4)
    const x = MARGIN + col * colW
    const boxY = y + row * 36
    doc.setFillColor(...WHITE)
    doc.setDrawColor(...BORDER)
    doc.roundedRect(x + 2, boxY, colW - 6, 30, 3, 3, 'FD')
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(7)
    doc.setTextColor(...MUTED)
    doc.text(pair[0], x + 8, boxY + 11)
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(9)
    doc.setTextColor(...TEXT)
    doc.text(doc.splitTextToSize(pair[1], colW - 16)[0], x + 8, boxY + 23)
  })
  y += paramRows * 36 + 8

  y = sectionTitle(doc, 'Property summary', y)
  const summary = input.summary?.trim() || 'No summary available.'
  const summaryLines = doc.splitTextToSize(summary, PAGE_W - MARGIN * 2 - 20)
  const summaryH = Math.min(120, 16 + summaryLines.length * 12)
  y = ensureSpace(doc, y, summaryH)
  doc.setFillColor(...WHITE)
  doc.setDrawColor(...BORDER)
  doc.roundedRect(MARGIN, y, PAGE_W - MARGIN * 2, summaryH, 4, 4, 'FD')
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(9)
  doc.setTextColor(...TEXT)
  doc.text(summaryLines.slice(0, 8), MARGIN + 10, y + 14)
  y += summaryH + 10

  y = sectionTitle(doc, 'Monthly cash flow', y)
  y = drawCashFlowChart(doc, input.breakdown, y)

  const rowH = 16
  y = ensureSpace(doc, y, 20 + input.breakdown.length * rowH)
  doc.setFillColor(...INDIGO)
  doc.rect(MARGIN, y, PAGE_W - MARGIN * 2, 18, 'F')
  doc.setTextColor(...WHITE)
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(8)
  doc.text('Description', MARGIN + 8, y + 12)
  doc.text('Monthly amount', PAGE_W - MARGIN - 8, y + 12, { align: 'right' })
  y += 18
  input.breakdown.forEach((row, i) => {
    y = ensureSpace(doc, y, rowH)
    if (row.emphasize) doc.setFillColor(...SURFACE)
    else if (i % 2 === 1) doc.setFillColor(248, 250, 252)
    else doc.setFillColor(...WHITE)
    doc.rect(MARGIN, y, PAGE_W - MARGIN * 2, rowH, 'F')
    doc.setFont('helvetica', row.emphasize ? 'bold' : 'normal')
    doc.setFontSize(8)
    doc.setTextColor(...TEXT)
    doc.text(row.label, MARGIN + 8, y + 11)
    const low = row.label.toLowerCase()
    if (low.includes('cash flow') && row.value >= 0) doc.setTextColor(...GREEN)
    else if (row.value < 0 || row.amount.startsWith('-')) doc.setTextColor(...ROSE)
    else if (low.includes('rent')) doc.setTextColor(...INDIGO)
    doc.text(row.amount, PAGE_W - MARGIN - 8, y + 11, { align: 'right' })
    y += rowH
  })
  y += 12

  if (input.forecastValues && input.forecastValues.length > 1) {
    y = sectionTitle(doc, '10-year appreciation forecast', y)
    y = drawForecastChart(doc, input.forecastValues, y)
  }

  if (input.quantum) {
    y = sectionTitle(doc, 'QAOA alignment', y)
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(8)
    doc.setTextColor(...MUTED)
    y = ensureSpace(doc, y, 20)
    doc.text(
      'Educational simulation of cash-flow, appreciation, and combined wealth alignment. Not a market prediction.',
      MARGIN,
      y,
    )
    y += 10
    y = kpiCards(
      doc,
      [
        ['Cash flow', `${Number(input.quantum.cashflow_success_pct ?? 0).toFixed(0)}%`],
        ['Appreciation', `${Number(input.quantum.appreciation_success_pct ?? 0).toFixed(0)}%`],
        ['Combined', `${Number(input.quantum.combined_wealth_success_pct ?? 0).toFixed(0)}%`],
        ['Overall', `${Number(input.quantum.overall_success_pct ?? 0).toFixed(0)}%`],
      ],
      y,
    )
  }

  y = ensureSpace(doc, y, 28)
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(7.5)
  doc.setTextColor(...MUTED)
  const stamp = new Date().toISOString().slice(0, 16).replace('T', ' ')
  doc.text(
    `Prepared by CapEigen. Report generated ${stamp}. Comps and forecasts are AI-assisted estimates.`,
    PAGE_W / 2,
    y,
    { align: 'center', maxWidth: PAGE_W - MARGIN * 2 },
  )

  return doc.output('blob')
}
