const header = document.querySelector('[data-header]')
const menuToggle = document.querySelector('.menu-toggle')
const nav = document.querySelector('.site-nav')
const blueprint = document.querySelector('[data-blueprint]')
const compareRange = document.querySelector('.compare-range')
const runtimePanel = document.querySelector('[data-runtime-panel] code')
const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches

const runtimeExamples = {
  web: `拖入 drawing.dwg
目标语言  Russian
回填模式  Replace
状态      Ready to process_`,
  cli: `$ cad-translate pipeline extract -i drawing.dxf
$ cad-translate pipeline translate-excel \\
    -i texts.xlsx --target-language ru
$ cad-translate pipeline apply \\
    -i drawing.dxf -e texts_translated.xlsx_`,
  exe: `CAD Translation System.exe
本地运行时   Embedded
外部 Python  Not required
任务模式     Local
状态         Ready_`,
}

function updateHeader() {
  header?.classList.toggle('is-scrolled', window.scrollY > 24)
}

function closeMenu() {
  menuToggle?.setAttribute('aria-expanded', 'false')
  nav?.classList.remove('is-open')
  document.body.style.removeProperty('overflow')
}

menuToggle?.addEventListener('click', () => {
  const open = menuToggle.getAttribute('aria-expanded') !== 'true'
  menuToggle.setAttribute('aria-expanded', String(open))
  nav?.classList.toggle('is-open', open)
  document.body.style.overflow = open ? 'hidden' : ''
})

nav?.querySelectorAll('a').forEach((link) => link.addEventListener('click', closeMenu))
window.addEventListener('scroll', updateHeader, { passive: true })
updateHeader()

if (compareRange && blueprint) {
  const updateCompare = () => {
    const value = `${compareRange.value}%`
    blueprint.querySelector('.drawing-stage')?.style.setProperty('--compare', value)
  }

  compareRange.addEventListener('input', updateCompare)
  updateCompare()
}

if (blueprint && !prefersReducedMotion && window.matchMedia('(pointer: fine)').matches) {
  blueprint.addEventListener('pointermove', (event) => {
    const bounds = blueprint.getBoundingClientRect()
    const x = (event.clientX - bounds.left) / bounds.width - 0.5
    const y = (event.clientY - bounds.top) / bounds.height - 0.5
    blueprint.style.transform = `perspective(1200px) rotateY(${x * 3 - 2}deg) rotateX(${-y * 2 + 1}deg)`
    const coordinates = blueprint.querySelector('.drawing-coordinates')
    if (coordinates) {
      coordinates.textContent = `X ${String(Math.round((x + 0.5) * 760)).padStart(3, '0')}.00  Y ${String(Math.round((y + 0.5) * 560)).padStart(3, '0')}.00`
    }
  })

  blueprint.addEventListener('pointerleave', () => {
    blueprint.style.transform = ''
  })
}

document.querySelectorAll('[data-runtime]').forEach((button) => {
  button.addEventListener('click', () => {
    const runtime = button.dataset.runtime
    if (!runtime || !runtimePanel || !(runtime in runtimeExamples)) return

    document.querySelectorAll('[data-runtime]').forEach((item) => {
      const active = item === button
      item.classList.toggle('is-active', active)
      item.setAttribute('aria-selected', String(active))
    })
    runtimePanel.textContent = runtimeExamples[runtime]
  })
})

document.querySelectorAll('[data-copy-target]').forEach((button) => {
  button.addEventListener('click', async () => {
    const target = document.getElementById(button.dataset.copyTarget)
    if (!target) return

    const text = target.innerText.replace(/^PS>\s?/gm, '').replace(/^#.*$/gm, '').trim()
    try {
      await navigator.clipboard.writeText(text)
      const originalLabel = button.textContent
      button.textContent = '已复制'
      button.classList.add('is-copied')
      window.setTimeout(() => {
        button.textContent = originalLabel
        button.classList.remove('is-copied')
      }, 1800)
    } catch {
      button.textContent = '请手动复制'
    }
  })
})

const revealItems = document.querySelectorAll('[data-reveal]')
if (prefersReducedMotion || !('IntersectionObserver' in window)) {
  revealItems.forEach((item) => item.classList.add('is-visible'))
} else {
  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return
        entry.target.classList.add('is-visible')
        observer.unobserve(entry.target)
      })
    },
    { threshold: 0.12, rootMargin: '0px 0px -5% 0px' },
  )
  revealItems.forEach((item) => observer.observe(item))
}

document.querySelectorAll('[data-year]').forEach((item) => {
  item.textContent = String(new Date().getFullYear())
})
