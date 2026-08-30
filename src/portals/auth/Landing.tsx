import { lazy, Suspense } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, Check, GraduationCap, LockKeyhole, ScanSearch, Share2, ShieldCheck, UserRound, WalletCards } from 'lucide-react'
import { Button, RoleBackground } from '../../components/ui'

const LandingScene = lazy(() => import('./LandingScene').then(({ LandingScene }) => ({ default: LandingScene })))

const CAPABILITIES = [
  { icon: LockKeyhole, label: 'Cryptographically signed', detail: 'Every issued credential carries a verifiable signature.' },
  { icon: UserRound, label: 'Student-owned', detail: 'Students control access to their academic record.' },
  { icon: ScanSearch, label: 'Instant verification', detail: 'Check authenticity and status in seconds.' },
]

const STATS = [
  ['4', 'credential flow stages'],
  ['1', 'student-controlled record'],
  ['0', 'paper handoffs required'],
]

const JOURNEY = [
  { icon: GraduationCap, title: 'Issue', description: 'Institutions cryptographically sign verified credentials directly into the student wallet.', accent: 'text-primary' },
  { icon: WalletCards, title: 'Own', description: 'Students hold the real, signed proof and decide what gets shared.', accent: 'text-cyan' },
  { icon: Share2, title: 'Share', description: 'Share exactly which credential is needed, with whom, and for how long.', accent: 'text-ai' },
  { icon: ScanSearch, title: 'Verify', description: 'Employers check authenticity and status, not just appearance.', accent: 'text-good' },
]

function SceneLoading() {
  return <div className="landing-scene-fallback" aria-hidden="true"><span className="landing-loading-orbit" /><span>Opening credential vault</span></div>
}

export function Landing() {
  return (
    <div className="relative min-h-screen overflow-x-clip bg-canvas text-body">
      <RoleBackground role="landing" className="fixed" />
      <div aria-hidden className="pointer-events-none fixed inset-0 -z-10 bg-[radial-gradient(ellipse_at_top,rgba(79,70,229,0.16),transparent_46%),radial-gradient(ellipse_at_bottom_right,rgba(76,215,246,0.08),transparent_40%)]" />

      <header className="fixed top-0 z-50 w-full border-b border-white/10 bg-[#05070d]/75 backdrop-blur-xl">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-5 py-4 md:px-8">
          <Link to="/" className="flex items-center gap-3" aria-label="CredChain home">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl border border-cyan/40 bg-cyan/10 text-cyan shadow-[0_0_24px_-8px_var(--color-cyan)]"><ShieldCheck className="h-5 w-5" strokeWidth={2.25} /></span>
            <span className="font-[family-name:var(--font-display)] text-xl font-bold tracking-tight text-white">CredChain</span>
          </Link>
          <nav className="flex items-center gap-2" aria-label="Landing navigation">
            <a href="#how-it-works" className="hidden px-3 py-2 text-sm font-medium text-muted transition-colors hover:text-ink sm:block">How it works</a>
            <Link to="/sign-in"><Button variant="ghost" size="sm">Sign In</Button></Link>
            <Link to="/sign-up"><Button variant="solid" size="sm">Create Account</Button></Link>
          </nav>
        </div>
      </header>

      <main className="relative z-10">
        <section className="mx-auto grid min-h-[760px] max-w-7xl items-center gap-8 px-5 pb-16 pt-32 md:grid-cols-[.8fr_1.2fr] md:px-8 md:pt-36">
          <div className="max-w-xl">
            <div className="mb-7 inline-flex items-center gap-3 rounded-full border border-cyan/25 bg-cyan/5 px-4 py-2 font-[family-name:var(--font-mono)] text-[10px] uppercase tracking-[.16em] text-cyan"><span className="h-1.5 w-1.5 animate-pulse rounded-full bg-cyan" />Trust infrastructure for academic identity</div>
            <h1 className="font-[family-name:var(--font-display)] text-[42px] font-bold leading-[1.07] tracking-tight text-white md:text-[68px]">Instant academic verification,<br /><span className="bg-gradient-to-r from-primary via-cyan to-good bg-clip-text text-transparent">owned by the student.</span></h1>
            <p className="mt-7 max-w-lg text-base leading-relaxed text-body md:text-lg">Universities issue cryptographically signed transcripts, degrees and migration certificates. Students own and selectively share them. Employers and institutions verify authenticity in seconds.</p>
            <div className="mt-9 flex flex-col gap-3 sm:flex-row"><Link to="/sign-up"><Button variant="solid" className="w-full rounded-xl px-7 py-3.5 sm:w-auto" icon={<ArrowRight className="h-4 w-4" strokeWidth={2.5} />}>Get Started</Button></Link><a href="#how-it-works" className="w-full sm:w-auto"><Button variant="outline" className="w-full rounded-xl px-7 py-3.5 sm:w-auto">See How It Works</Button></a></div>
            <div className="mt-8 flex flex-wrap gap-x-5 gap-y-2 font-[family-name:var(--font-mono)] text-[10px] uppercase tracking-[.12em] text-faint"><span className="flex items-center gap-2"><Check className="h-3.5 w-3.5 text-good" />Signed credentials</span><span className="flex items-center gap-2"><Check className="h-3.5 w-3.5 text-good" />Selective sharing</span></div>
          </div>
          <Suspense fallback={<SceneLoading />}><LandingScene /></Suspense>
        </section>

        <section className="border-y border-white/10 bg-white/[.025]" aria-label="Product capabilities"><div className="mx-auto grid max-w-7xl gap-0 md:grid-cols-3 md:px-8">{CAPABILITIES.map(({ icon: Icon, label, detail }) => <div key={label} className="flex gap-4 border-b border-white/10 px-5 py-6 last:border-0 md:border-b-0 md:border-r md:px-6 md:last:border-r-0"><Icon className="mt-1 h-5 w-5 shrink-0 text-cyan" strokeWidth={1.8} /><div><h2 className="text-sm font-semibold text-ink">{label}</h2><p className="mt-1 text-xs leading-relaxed text-muted">{detail}</p></div></div>)}</div></section>

        <section className="mx-auto grid max-w-7xl gap-10 px-5 py-20 md:grid-cols-[.7fr_1.3fr] md:px-8 md:py-28"><div><p className="font-[family-name:var(--font-mono)] text-[10px] uppercase tracking-[.18em] text-cyan">The system at a glance</p><h2 className="mt-4 max-w-sm font-[family-name:var(--font-display)] text-3xl font-semibold text-white md:text-4xl">Proof that moves at the speed of trust.</h2></div><div className="grid gap-4 sm:grid-cols-3">{STATS.map(([value, label]) => <div key={label} className="border-l border-primary/50 pl-5"><p className="font-[family-name:var(--font-display)] text-4xl font-bold text-white">{value}</p><p className="mt-2 text-sm leading-relaxed text-muted">{label}</p></div>)}</div></section>

        <section id="how-it-works" className="border-y border-white/10 bg-[#070a12]/80"><div className="mx-auto max-w-7xl px-5 py-20 md:px-8 md:py-28"><div className="max-w-xl"><p className="font-[family-name:var(--font-mono)] text-[10px] uppercase tracking-[.18em] text-cyan">How it works</p><h2 className="mt-4 font-[family-name:var(--font-display)] text-3xl font-semibold text-white md:text-4xl">One credential. A clearer chain of trust.</h2></div><div className="mt-14 grid gap-4 md:grid-cols-4">{JOURNEY.map(({ icon: Icon, title, description, accent }, index) => <article key={title} className="relative border border-white/10 bg-white/[.035] p-6 backdrop-blur-md"><span className="font-[family-name:var(--font-mono)] text-[10px] text-faint">0{index + 1}</span><Icon className={`mt-8 h-7 w-7 ${accent}`} strokeWidth={1.7} /><h3 className="mt-5 font-[family-name:var(--font-display)] text-lg font-semibold text-white">{title}</h3><p className="mt-2 text-sm leading-relaxed text-muted">{description}</p></article>)}</div></div></section>

        <section className="mx-auto max-w-7xl px-5 py-20 text-center md:px-8 md:py-28"><ShieldCheck className="mx-auto h-8 w-8 text-good" strokeWidth={1.7} /><h2 className="mx-auto mt-5 max-w-2xl font-[family-name:var(--font-display)] text-3xl font-semibold text-white md:text-5xl">Make every academic achievement verifiable.</h2><p className="mx-auto mt-5 max-w-xl text-base leading-relaxed text-muted">Give students a portable proof of their work and give verifiers a faster way to know it is real.</p><Link to="/sign-up" className="mt-8 inline-block"><Button variant="solid" className="rounded-xl px-7 py-3.5" icon={<ArrowRight className="h-4 w-4" strokeWidth={2.5} />}>Create your account</Button></Link></section>
      </main>
    </div>
  )
}
