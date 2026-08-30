import { cx } from '../../lib/utils'
import { Glow } from './Glow'

export type WorldRole = 'student' | 'institution' | 'verifier' | 'admin' | 'landing'

/**
 * The one reusable ambient background system for the whole app: deep
 * midnight base + faint grid + a couple of role-tinted glow blobs. Every
 * authenticated page (via AppShell) and every auth "world" (Login/SignUp)
 * renders this same component with a different `role`, so the product
 * reads as one universe with role-specific lighting rather than unrelated
 * per-page backgrounds.
 *
 * student    -> cyan / indigo   (personal, academic)
 * institution -> indigo / emerald (trust, authority)
 * verifier   -> violet / magenta (innovation, recruitment)
 * admin      -> no glow branch — falls through to the neutral base grid/vignette only,
 *               appropriate for a small utility surface with no "world" of its own
 * landing    -> indigo / violet / cyan (unified marketing identity)
 */
export function RoleBackground({ role, className }: { role: WorldRole; className?: string }) {
  return (
    <div aria-hidden className={cx('pointer-events-none absolute inset-0 overflow-hidden bg-canvas', className)}>
      {/* faint grid, slow pan */}
      <div
        className="absolute inset-0 opacity-[0.06] motion-safe:animate-[gridPan_40s_linear_infinite]"
        style={{
          backgroundImage:
            'linear-gradient(to right, #ffffff 1px, transparent 1px), linear-gradient(to bottom, #ffffff 1px, transparent 1px)',
          backgroundSize: '48px 48px',
        }}
      />
      {/* dot pattern, subtler layer on top for depth */}
      <div
        className="absolute inset-0 opacity-[0.05]"
        style={{ backgroundImage: 'radial-gradient(#ffffff 1px, transparent 1px)', backgroundSize: '22px 22px' }}
      />

      {role === 'student' && (
        <>
          <Glow color="cyan" size={560} className="-left-40 -top-32 motion-safe:animate-[driftSlow_16s_ease-in-out_infinite]" />
          <Glow color="primary" size={480} className="-bottom-32 -right-20 motion-safe:animate-[driftSlow_20s_ease-in-out_infinite_reverse]" />
        </>
      )}
      {role === 'institution' && (
        <>
          <Glow color="primary" size={560} className="-left-32 -top-24 motion-safe:animate-[driftSlow_18s_ease-in-out_infinite]" />
          <Glow color="good" size={420} className="-bottom-28 -right-24 motion-safe:animate-[driftSlow_22s_ease-in-out_infinite_reverse]" />
        </>
      )}
      {role === 'verifier' && (
        <>
          <Glow color="ai" size={560} className="-left-32 -top-28 motion-safe:animate-[driftSlow_17s_ease-in-out_infinite]" />
          <Glow color="magenta" size={440} className="-bottom-24 -right-24 motion-safe:animate-[driftSlow_21s_ease-in-out_infinite_reverse]" />
        </>
      )}
      {role === 'landing' && (
        <>
          <Glow color="primary" size={620} className="-left-40 -top-40 motion-safe:animate-[driftSlow_19s_ease-in-out_infinite]" />
          <Glow color="ai" size={520} className="right-[-10%] top-[10%] motion-safe:animate-[driftSlow_23s_ease-in-out_infinite_reverse]" />
          <Glow color="cyan" size={480} className="-bottom-36 left-[20%] motion-safe:animate-[driftSlow_26s_ease-in-out_infinite]" />
        </>
      )}

      {/* vignette so content near the edges stays legible against the glow */}
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,transparent_40%,var(--color-canvas)_100%)]" />
    </div>
  )
}
