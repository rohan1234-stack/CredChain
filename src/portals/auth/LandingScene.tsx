import { useEffect, useMemo, useRef, useState } from 'react'
import type { MutableRefObject, PointerEvent as ReactPointerEvent } from 'react'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import type { ThreeEvent } from '@react-three/fiber'
import { Grid, RoundedBox, Sparkles, Text } from '@react-three/drei'
import * as THREE from 'three'
import './Landing.css'

type Vec3 = [number, number, number]
type Density = 'desktop' | 'tablet' | 'mobile'
type HoverState = { hovered: string | null }
type IconKind = 'university' | 'student' | 'employer' | 'verified'

type NodeInfo = {
  label: string
  position: Vec3
  flyFrom: Vec3
  rotation: Vec3
  color: string
  phase: number
  spin: number
  icon: IconKind
  pulseStart: number
  direction: 'in' | 'out'
  delay: number
}

const PULSE_PERIOD = 6.2
const PULSE_START_DELAY = 2.5
const NODE_PULSE_DURATION = 0.85
const VAULT_PULSE_START = 0.35
const VAULT_PULSE_DURATION = 1.3
const RING_PULSE_DURATION = 1.1
const SCAN_PERIOD = 5
const SCAN_DURATION = 1.6
const VAULT_REST_Y = 0.35

// Asymmetric, depth-staggered placement -- deliberately NOT a flat rectangle around the vault.
const NODES: NodeInfo[] = [
  { label: 'UNIVERSITY', position: [-2.0, 1.35, -0.85], flyFrom: [-1.0, 1.9, -1.9], rotation: [0.1, 0.4, -0.08], color: '#a78bfa', phase: 0.2, spin: 0.05, icon: 'university', pulseStart: 0.15, direction: 'in', delay: 0 },
  { label: 'STUDENT', position: [-1.85, -1.3, 0.75], flyFrom: [-0.9, -1.9, 1.8], rotation: [-0.08, 0.3, 0.07], color: '#4cd7f6', phase: 1.7, spin: -0.04, icon: 'student', pulseStart: 0.95, direction: 'in', delay: 0.16 },
  { label: 'EMPLOYER', position: [2.0, 1.25, 0.65], flyFrom: [1.0, 1.85, 1.75], rotation: [0.09, -0.35, 0.1], color: '#5b9cff', phase: 2.5, spin: 0.045, icon: 'employer', pulseStart: 1.75, direction: 'out', delay: 0.32 },
  { label: 'VERIFIED', position: [0.1, -1.3, 1.65], flyFrom: [0.05, -1.85, 0.6], rotation: [-0.1, -0.15, -0.05], color: '#4edea3', phase: 3.6, spin: -0.05, icon: 'verified', pulseStart: 2.55, direction: 'out', delay: 0.48 },
]

function clamp01(x: number) {
  return Math.min(1, Math.max(0, x))
}

function smoothstep(edge0: number, edge1: number, x: number) {
  const t = clamp01((x - edge0) / (edge1 - edge0))
  return t * t * (3 - 2 * t)
}

/** Triangular ease-in/ease-out bump used for the periodic verification pulse. */
function pulseBump(cycle: number, start: number, duration: number) {
  const local = cycle - start
  if (local < 0 || local > duration) return 0
  return Math.sin((local / duration) * Math.PI)
}

function usePrefersReducedMotionRef() {
  const ref = useRef(false)
  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)')
    ref.current = mq.matches
    const handler = () => { ref.current = mq.matches }
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }, [])
  return ref
}

function densityFromWidth(width: number): Density {
  if (width < 640) return 'mobile'
  if (width < 1024) return 'tablet'
  return 'desktop'
}

function useDensity(): Density {
  const [density, setDensity] = useState<Density>(() => (typeof window === 'undefined' ? 'desktop' : densityFromWidth(window.innerWidth)))
  useEffect(() => {
    function handleResize() {
      setDensity(densityFromWidth(window.innerWidth))
    }
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [])
  return density
}

function useScrollRef() {
  const ref = useRef(0)
  useEffect(() => {
    function handleScroll() {
      ref.current = clamp01(window.scrollY / 900)
    }
    handleScroll()
    window.addEventListener('scroll', handleScroll, { passive: true })
    return () => window.removeEventListener('scroll', handleScroll)
  }, [])
  return ref
}

function createGlowTexture() {
  const size = 128
  const canvas = document.createElement('canvas')
  canvas.width = size
  canvas.height = size
  const ctx = canvas.getContext('2d')
  if (!ctx) return null
  const gradient = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2)
  gradient.addColorStop(0, 'rgba(255,255,255,0.9)')
  gradient.addColorStop(0.45, 'rgba(255,255,255,0.22)')
  gradient.addColorStop(1, 'rgba(255,255,255,0)')
  ctx.fillStyle = gradient
  ctx.fillRect(0, 0, size, size)
  const texture = new THREE.CanvasTexture(canvas)
  texture.needsUpdate = true
  return texture
}

const glowTexture = typeof document === 'undefined' ? null : createGlowTexture()

function useShieldGeometry() {
  return useMemo(() => {
    const shape = new THREE.Shape()
    shape.moveTo(-0.5, 0.62)
    shape.lineTo(0.5, 0.62)
    shape.lineTo(0.5, -0.08)
    shape.quadraticCurveTo(0.5, -0.56, 0, -0.74)
    shape.quadraticCurveTo(-0.5, -0.56, -0.5, -0.08)
    shape.closePath()
    return new THREE.ExtrudeGeometry(shape, { depth: 0.16, bevelEnabled: true, bevelSize: 0.03, bevelThickness: 0.03, bevelSegments: 2, curveSegments: 8 })
  }, [])
}

function ShieldEmblem({ scale = 1, color = '#4cd7f6' }: { scale?: number; color?: string }) {
  const geometry = useShieldGeometry()
  return (
    <group scale={scale}>
      <mesh geometry={geometry} position={[0, 0, -0.08]}>
        <meshStandardMaterial color="#0e1830" metalness={0.6} roughness={0.25} emissive={color} emissiveIntensity={0.45} />
      </mesh>
      <lineSegments position={[0, 0, -0.08]}>
        <edgesGeometry args={[geometry]} />
        <lineBasicMaterial color={color} toneMapped={false} />
      </lineSegments>
      <mesh position={[-0.16, 0, 0.09]} rotation={[0, 0, Math.PI / 4]}>
        <boxGeometry args={[0.13, 0.32, 0.06]} />
        <meshBasicMaterial color="#eafcff" toneMapped={false} />
      </mesh>
      <mesh position={[0.1, 0.14, 0.09]} rotation={[0, 0, -Math.PI / 4]}>
        <boxGeometry args={[0.13, 0.58, 0.06]} />
        <meshBasicMaterial color="#eafcff" toneMapped={false} />
      </mesh>
    </group>
  )
}

function UniversityIcon({ color }: { color: string }) {
  return (
    <group>
      <mesh position={[0, -0.05, 0]}>
        <boxGeometry args={[0.34, 0.34, 0.12]} />
        <meshStandardMaterial color="#0e1830" metalness={0.5} roughness={0.3} emissive={color} emissiveIntensity={0.35} />
      </mesh>
      <mesh position={[0, 0.19, 0]}>
        <coneGeometry args={[0.24, 0.18, 4]} />
        <meshStandardMaterial color="#0e1830" metalness={0.5} roughness={0.3} emissive={color} emissiveIntensity={0.45} />
      </mesh>
      <mesh position={[-0.08, -0.05, 0.065]}>
        <planeGeometry args={[0.06, 0.08]} />
        <meshBasicMaterial color={color} toneMapped={false} />
      </mesh>
      <mesh position={[0.08, -0.05, 0.065]}>
        <planeGeometry args={[0.06, 0.08]} />
        <meshBasicMaterial color={color} toneMapped={false} />
      </mesh>
    </group>
  )
}

function StudentIcon({ color }: { color: string }) {
  return (
    <group rotation={[0.35, Math.PI / 4, 0]}>
      <mesh>
        <boxGeometry args={[0.42, 0.04, 0.42]} />
        <meshStandardMaterial color="#0e1830" metalness={0.5} roughness={0.25} emissive={color} emissiveIntensity={0.5} />
      </mesh>
      <mesh position={[0, -0.09, 0]}>
        <coneGeometry args={[0.15, 0.16, 20]} />
        <meshStandardMaterial color="#0e1830" metalness={0.4} roughness={0.35} emissive={color} emissiveIntensity={0.3} />
      </mesh>
      <mesh position={[0.18, -0.05, 0.18]}>
        <cylinderGeometry args={[0.008, 0.008, 0.18, 6]} />
        <meshBasicMaterial color={color} toneMapped={false} />
      </mesh>
      <mesh position={[0.18, -0.15, 0.18]}>
        <sphereGeometry args={[0.025, 8, 8]} />
        <meshBasicMaterial color={color} toneMapped={false} />
      </mesh>
    </group>
  )
}

function EmployerIcon({ color }: { color: string }) {
  return (
    <group>
      <mesh>
        <boxGeometry args={[0.38, 0.28, 0.12]} />
        <meshStandardMaterial color="#0e1830" metalness={0.55} roughness={0.28} emissive={color} emissiveIntensity={0.35} />
      </mesh>
      <mesh position={[0, 0.05, 0.065]}>
        <planeGeometry args={[0.38, 0.025]} />
        <meshBasicMaterial color={color} toneMapped={false} />
      </mesh>
      <mesh position={[0, 0.18, 0]} rotation={[Math.PI / 2, 0, 0]}>
        <torusGeometry args={[0.08, 0.018, 8, 16, Math.PI]} />
        <meshStandardMaterial color="#0e1830" metalness={0.5} roughness={0.3} emissive={color} emissiveIntensity={0.5} />
      </mesh>
    </group>
  )
}

function CameraRig({ reducedMotion, scrollRef }: { reducedMotion: MutableRefObject<boolean>; scrollRef: MutableRefObject<number> }) {
  const { camera, pointer } = useThree()
  const base = useMemo(() => ({ x: 0, y: 0.5, z: 7.1 }), [])
  useFrame((state) => {
    const t = state.clock.elapsedTime
    const reduced = reducedMotion.current
    const orbit = reduced ? 0 : Math.sin(t * 0.06) * 0.65
    const dolly = reduced ? 0 : Math.sin(t * 0.09) * 0.4
    // Deliberately large parallax: the vault's side/top faces should swing into view as the mouse moves.
    // Bounded enough that University/Student/Employer/Verified stay inside frame at rest.
    const parallaxX = reduced ? 0 : pointer.x * 1.2
    const parallaxY = reduced ? 0 : pointer.y * 0.7
    const scroll = scrollRef.current
    const targetX = base.x + orbit + parallaxX
    const targetY = base.y + parallaxY - scroll * 0.5
    const targetZ = base.z + dolly + scroll * 1.1
    // Three.js camera objects are mutable scene nodes; damped lerp each frame creates the cinematic drift.
    // oxlint-disable-next-line react/immutability
    camera.position.x = THREE.MathUtils.lerp(camera.position.x, targetX, 0.05)
    camera.position.y = THREE.MathUtils.lerp(camera.position.y, targetY, 0.05)
    camera.position.z = THREE.MathUtils.lerp(camera.position.z, targetZ, 0.035)
    camera.lookAt(0, VAULT_REST_Y, 0)
  })
  return null
}

function MovingLights({ reducedMotion }: { reducedMotion: MutableRefObject<boolean> }) {
  const cyanLight = useRef<THREE.PointLight>(null)
  const violetLight = useRef<THREE.PointLight>(null)
  const verifyLight = useRef<THREE.PointLight>(null)
  const sweepLight = useRef<THREE.PointLight>(null)
  const flashLight = useRef<THREE.PointLight>(null)
  const sweepColor = useMemo(() => new THREE.Color(), [])

  useFrame((state) => {
    const t = state.clock.elapsedTime
    const reduced = reducedMotion.current
    if (cyanLight.current) {
      cyanLight.current.position.x = reduced ? -4.5 : Math.sin(t * 0.22) * 5.5
      cyanLight.current.position.z = reduced ? 2.5 : 2.5 + Math.cos(t * 0.22) * 2
    }
    if (violetLight.current) {
      violetLight.current.position.x = reduced ? 4.5 : Math.cos(t * 0.16 + 2) * 5.5
      violetLight.current.position.z = reduced ? -2.5 : -2.5 + Math.sin(t * 0.16 + 2) * 2
    }
    // A dedicated raking light that sweeps across the vault's front/side faces, making brightness
    // visibly change per-face instead of the scene reading as flat, uniform illumination.
    if (sweepLight.current) {
      const sweep = reduced ? 0 : Math.sin(t * 0.32)
      sweepLight.current.position.set(sweep * 3.4, 1.1 + Math.sin(t * 0.5) * 0.3, 2.6)
      sweepColor.setHSL(0.56 + sweep * 0.14, 0.85, 0.6)
      sweepLight.current.color.copy(sweepColor)
      sweepLight.current.intensity = reduced ? 22 : 30 + Math.abs(sweep) * 20
    }

    const cycle = t < PULSE_START_DELAY ? -1 : (t - PULSE_START_DELAY) % PULSE_PERIOD
    const verifyPulse = reduced || cycle < 0 ? 0 : pulseBump(cycle, 2.05, 1.05)
    if (verifyLight.current) verifyLight.current.intensity = 8 + verifyPulse * 38
    // Scene-wide emerald wash during the verification event, centered near the vault.
    if (flashLight.current) flashLight.current.intensity = verifyPulse * 60
  })

  return (
    <>
      <pointLight ref={cyanLight} position={[4.5, 3, 3.5]} intensity={30} distance={9} color="#32d8f4" />
      <pointLight ref={violetLight} position={[-4.5, 0, 2.5]} intensity={26} distance={8} color="#766dff" />
      <pointLight ref={verifyLight} position={[3.2, -2.05, 0.4]} intensity={8} distance={7} color="#4edea3" />
      <pointLight ref={sweepLight} position={[0, 1.1, 2.6]} intensity={28} distance={6} color="#4cd7f6" />
      <pointLight ref={flashLight} position={[0, VAULT_REST_Y + 0.2, 0.6]} intensity={0} distance={11} color="#4edea3" />
    </>
  )
}

function Vault({ reducedMotion, interaction, density }: { reducedMotion: MutableRefObject<boolean>; interaction: MutableRefObject<HoverState>; density: Density }) {
  const introGroup = useRef<THREE.Group>(null)
  const idleGroup = useRef<THREE.Group>(null)
  const edgeMaterial = useRef<THREE.LineBasicMaterial>(null)
  const coreMaterial = useRef<THREE.MeshBasicMaterial>(null)
  const coreMesh = useRef<THREE.Mesh>(null)
  const checkGroup = useRef<THREE.Group>(null)
  const glowMaterial = useRef<THREE.MeshBasicMaterial>(null)
  const edgesGeo = useMemo(() => new THREE.EdgesGeometry(new THREE.BoxGeometry(2.83, 2.83, 2.83)), [])

  useFrame((state, delta) => {
    const t = state.clock.elapsedTime
    const reduced = reducedMotion.current

    const introScale = reduced ? 1 : smoothstep(0.7, 1.35, t)
    const riseT = reduced ? 1 : smoothstep(0.65, 1.4, t)
    if (introGroup.current) {
      const s = THREE.MathUtils.lerp(introGroup.current.scale.x, introScale, reduced ? 1 : 0.15)
      introGroup.current.scale.setScalar(s)
      // "Vault rises from platform": interpolate the resting height up from the platform level.
      introGroup.current.position.y = THREE.MathUtils.lerp(-1.7, VAULT_REST_Y, riseT)
    }

    const cycle = t < PULSE_START_DELAY ? -1 : (t - PULSE_START_DELAY) % PULSE_PERIOD
    const vaultPulse = reduced || cycle < 0 ? 0 : pulseBump(cycle, VAULT_PULSE_START, VAULT_PULSE_DURATION)
    const hoverBoost = interaction.current.hovered ? 0.35 : 0

    if (idleGroup.current && !reduced) {
      // Continuous slow revolution -- over time every face (front/side/top) cycles into clear view.
      idleGroup.current.rotation.y += delta * 0.11
      idleGroup.current.rotation.x = THREE.MathUtils.lerp(idleGroup.current.rotation.x, 0.32 + Math.sin(t * 0.4) * 0.05, 0.04)
      idleGroup.current.position.y = Math.sin(t * 0.6) * 0.09
    }

    const edgeIntro = smoothstep(1.15, 1.7, t)
    if (edgeMaterial.current) edgeMaterial.current.opacity = THREE.MathUtils.lerp(0.6, 1, vaultPulse + hoverBoost) * edgeIntro

    if (coreMaterial.current) {
      const breathing = reduced ? 0.5 : 0.5 + Math.sin(t * 0.9) * 0.18
      coreMaterial.current.opacity = Math.min(1, breathing + vaultPulse * 0.6 + hoverBoost * 0.3)
    }
    if (coreMesh.current && !reduced) {
      coreMesh.current.rotation.y -= delta * 0.2
      coreMesh.current.rotation.x += delta * 0.13
      coreMesh.current.scale.setScalar(1 + vaultPulse * 0.35)
    }

    if (glowMaterial.current) glowMaterial.current.opacity = 0.34 + vaultPulse * 0.6 + hoverBoost * 0.2

    const checkScale = reduced ? 1 : smoothstep(2.3, 2.7, t)
    if (checkGroup.current) checkGroup.current.scale.setScalar(THREE.MathUtils.lerp(checkGroup.current.scale.x, checkScale, 0.2))
  })

  return (
    <group ref={introGroup} scale={0} position={[0, -1.7, 0]}>
      <group ref={idleGroup} rotation={[0.32, -0.55, 0]}>
        <RoundedBox args={[2.8, 2.8, 2.8]} radius={0.26} smoothness={5} castShadow={density === 'desktop'} receiveShadow={density === 'desktop'}>
          <meshStandardMaterial color="#10182d" metalness={0.92} roughness={0.22} />
        </RoundedBox>
        <RoundedBox args={[2.98, 2.98, 2.98]} radius={0.29} smoothness={4}>
          <meshStandardMaterial color="#3d5a95" transparent opacity={0.1} roughness={0.12} metalness={0.15} emissive="#1c2c52" emissiveIntensity={0.18} />
        </RoundedBox>
        <mesh ref={coreMesh}>
          <icosahedronGeometry args={[0.56, 1]} />
          <meshBasicMaterial ref={coreMaterial} color="#83e7ff" transparent opacity={0.5} toneMapped={false} wireframe />
        </mesh>
        <mesh position={[0, 0, 1.42]}>
          <planeGeometry args={[2.13, 2.13]} />
          <meshStandardMaterial color="#091323" metalness={0.68} roughness={0.18} emissive="#101e38" emissiveIntensity={0.55} />
        </mesh>
        <mesh position={[0, 0, 1.46]}>
          <torusGeometry args={[0.82, 0.032, 10, 64]} />
          <meshBasicMaterial color="#4cd7f6" toneMapped={false} />
        </mesh>
        <mesh position={[0, 0, 1.48]} rotation={[0, 0, Math.PI / 4]}>
          <ringGeometry args={[0.55, 0.63, 4]} />
          <meshBasicMaterial color="#a78bfa" toneMapped={false} />
        </mesh>
        <group ref={checkGroup} position={[0, 0.06, 1.52]} scale={0}>
          <ShieldEmblem scale={0.56} color="#4cd7f6" />
        </group>
        <Text position={[0, -0.88, 1.5]} fontSize={0.17} color="#4cd7f6" anchorX="center" anchorY="middle" letterSpacing={0.13}>
          CREDCHAIN VAULT
        </Text>
        <mesh position={[1.42, 0, 0]} rotation={[0, Math.PI / 2, 0]}>
          <planeGeometry args={[2.14, 2.14]} />
          <meshStandardMaterial color="#070d1c" metalness={0.95} roughness={0.3} emissive="#17103a" emissiveIntensity={0.4} />
        </mesh>
        <mesh position={[0, 1.42, 0]} rotation={[Math.PI / 2, 0, 0]}>
          <planeGeometry args={[2.15, 2.15]} />
          <meshStandardMaterial color="#263253" metalness={0.8} roughness={0.24} emissive="#17254a" emissiveIntensity={0.55} />
        </mesh>
        <lineSegments geometry={edgesGeo}>
          <lineBasicMaterial ref={edgeMaterial} color="#6c63ff" toneMapped={false} transparent opacity={0.6} />
        </lineSegments>
      </group>
      {glowTexture && (
        <mesh position={[0, 0, -1.5]}>
          <planeGeometry args={[4.6, 4.6]} />
          <meshBasicMaterial ref={glowMaterial} map={glowTexture} color="#6c63ff" transparent opacity={0.34} depthWrite={false} blending={THREE.AdditiveBlending} toneMapped={false} />
        </mesh>
      )}
    </group>
  )
}

/**
 * Three large orbital rings, deliberately offset in Z rather than only rotated: one sits behind the
 * vault (the vault occludes it), one sits in front (it occludes the vault), so the depth read is
 * unambiguous regardless of camera angle. A third large "halo" ring weaves through both as it spins.
 */
function OrbitalSystem({ reducedMotion, interaction }: { reducedMotion: MutableRefObject<boolean>; interaction: MutableRefObject<HoverState> }) {
  const introGroup = useRef<THREE.Group>(null)
  const ringBehind = useRef<THREE.Mesh>(null)
  const ringFront = useRef<THREE.Mesh>(null)
  const ringHalo = useRef<THREE.Mesh>(null)
  const matBehind = useRef<THREE.MeshBasicMaterial>(null)
  const matFront = useRef<THREE.MeshBasicMaterial>(null)
  const matHalo = useRef<THREE.MeshBasicMaterial>(null)

  useFrame((state, delta) => {
    const t = state.clock.elapsedTime
    const reduced = reducedMotion.current

    const introScale = reduced ? 1 : smoothstep(1.5, 2.1, t)
    if (introGroup.current) introGroup.current.scale.setScalar(THREE.MathUtils.lerp(introGroup.current.scale.x, introScale, 0.15))

    const cycle = t < PULSE_START_DELAY ? -1 : (t - PULSE_START_DELAY) % PULSE_PERIOD
    const ringPulse = reduced || cycle < 0 ? 0 : pulseBump(cycle, 0, RING_PULSE_DURATION)
    const hoverBoost = interaction.current.hovered ? 0.25 : 0

    if (!reduced) {
      if (ringBehind.current) ringBehind.current.rotation.z += delta * 0.12
      if (ringFront.current) ringFront.current.rotation.z -= delta * 0.09
      if (ringHalo.current) {
        ringHalo.current.rotation.x += delta * 0.07
        ringHalo.current.rotation.y += delta * 0.05
      }
    }

    const pulseScale = 1 + ringPulse * 0.5
    if (ringBehind.current) ringBehind.current.scale.setScalar(1 + ringPulse * 0.3)
    if (ringFront.current) ringFront.current.scale.setScalar(1 + ringPulse * 0.35)
    if (ringHalo.current) ringHalo.current.scale.setScalar(pulseScale)

    if (matBehind.current) matBehind.current.opacity = 0.5 + ringPulse * 0.4 + hoverBoost
    if (matFront.current) matFront.current.opacity = 0.55 + ringPulse * 0.4 + hoverBoost
    if (matHalo.current) matHalo.current.opacity = 0.3 + ringPulse * 0.5 + hoverBoost
  })

  return (
    <group ref={introGroup} scale={0} position={[0, VAULT_REST_Y, 0]}>
      <mesh ref={ringBehind} position={[0, 0, -1.3]} rotation={[Math.PI / 2 - 0.3, 0.3, 0]}>
        <torusGeometry args={[2.5, 0.026, 10, 72]} />
        <meshBasicMaterial ref={matBehind} color="#a78bfa" transparent opacity={0.5} toneMapped={false} />
      </mesh>
      <mesh ref={ringFront} position={[0, 0, 1.3]} rotation={[Math.PI / 2 + 0.22, -0.28, 0]}>
        <torusGeometry args={[2.35, 0.022, 10, 72]} />
        <meshBasicMaterial ref={matFront} color="#4cd7f6" transparent opacity={0.55} toneMapped={false} />
      </mesh>
      <mesh ref={ringHalo} rotation={[Math.PI / 2.3, 0.15, 0]}>
        <torusGeometry args={[3.35, 0.03, 10, 96]} />
        <meshBasicMaterial ref={matHalo} color="#5b9cff" transparent opacity={0.3} toneMapped={false} />
      </mesh>
    </group>
  )
}

function Platform({ reducedMotion, density }: { reducedMotion: MutableRefObject<boolean>; density: Density }) {
  const introGroup = useRef<THREE.Group>(null)
  const group = useRef<THREE.Group>(null)
  const ringOuter = useRef<THREE.Mesh>(null)
  const ringInner = useRef<THREE.Mesh>(null)
  const glowMat = useRef<THREE.MeshBasicMaterial>(null)

  useFrame((state, delta) => {
    const t = state.clock.elapsedTime
    const reduced = reducedMotion.current

    const introScale = reduced ? 1 : smoothstep(0.5, 1.0, t)
    if (introGroup.current) introGroup.current.scale.setScalar(THREE.MathUtils.lerp(introGroup.current.scale.x, introScale, 0.16))

    if (!reduced) {
      if (group.current) group.current.rotation.z += delta * 0.03
      if (ringOuter.current) ringOuter.current.rotation.z += delta * 0.045
      if (ringInner.current) ringInner.current.rotation.z -= delta * 0.075
    }
    if (glowMat.current) glowMat.current.opacity = 0.36 + (reduced ? 0 : Math.sin(t * 0.6) * 0.1)
  })

  return (
    <group ref={introGroup} scale={0}>
      <group ref={group} position={[0, -1.95, 0]}>
        <mesh rotation={[-Math.PI / 2, 0, 0]} receiveShadow={density === 'desktop'}>
          <cylinderGeometry args={[2.7, 3.05, 0.3, density === 'mobile' ? 40 : 72]} />
          <meshStandardMaterial color="#0a1121" metalness={0.95} roughness={0.2} />
        </mesh>
        <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.16, 0]}>
          <cylinderGeometry args={[2.2, 2.2, 0.05, density === 'mobile' ? 40 : 72]} />
          <meshStandardMaterial color="#16213f" metalness={0.5} roughness={0.15} transparent opacity={0.5} />
        </mesh>
        <mesh ref={ringOuter} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.19, 0]}>
          <torusGeometry args={[2.34, 0.045, 10, 72]} />
          <meshBasicMaterial color="#4cd7f6" toneMapped={false} />
        </mesh>
        <mesh ref={ringInner} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.2, 0]}>
          <torusGeometry args={[1.75, 0.028, 10, 72]} />
          <meshBasicMaterial color="#a78bfa" toneMapped={false} />
        </mesh>
        <mesh position={[0, 0.22, 0]} rotation={[-Math.PI / 2, 0, 0]}>
          <circleGeometry args={[1.82, 56]} />
          <meshBasicMaterial color="#172548" transparent opacity={0.42} />
        </mesh>
        {glowTexture && (
          <mesh position={[0, 0.07, 0]} rotation={[-Math.PI / 2, 0, 0]}>
            <planeGeometry args={[6.2, 6.2]} />
            <meshBasicMaterial ref={glowMat} map={glowTexture} color="#6c63ff" transparent opacity={0.36} depthWrite={false} blending={THREE.AdditiveBlending} toneMapped={false} />
          </mesh>
        )}
      </group>
    </group>
  )
}

function NetworkLine({ from, to, color, label, interaction, reducedMotion, speed, phase, direction, pulseStart }: {
  from: Vec3
  to: Vec3
  color: string
  label: string
  interaction: MutableRefObject<HoverState>
  reducedMotion: MutableRefObject<boolean>
  speed: number
  phase: number
  direction: 'in' | 'out'
  pulseStart: number
}) {
  const packetRef = useRef<THREE.Mesh>(null)
  const packetMaterial = useRef<THREE.MeshBasicMaterial>(null)
  // `<line>` collides with React's SVG intrinsic element, so the connector is built as a plain
  // three.js Line object and mounted via `primitive` instead of the JSX `line`/`lineBasicMaterial` tags.
  const lineObject = useMemo(() => {
    const lineGeometry = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(...from), new THREE.Vector3(...to)])
    const lineMaterial = new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.22, toneMapped: false })
    return new THREE.Line(lineGeometry, lineMaterial)
  }, [from, to, color])
  const start = direction === 'in' ? from : to
  const end = direction === 'in' ? to : from

  useFrame((state) => {
    const t = state.clock.elapsedTime
    const reduced = reducedMotion.current
    const active = interaction.current.hovered === label
    const cycle = t < PULSE_START_DELAY ? -1 : (t - PULSE_START_DELAY) % PULSE_PERIOD
    // The line lights up on its own during the verification event, sequenced by the node's pulseStart,
    // not only on hover -- this is what makes the network read as "sequentially illuminating."
    const pulse = reduced || cycle < 0 ? 0 : pulseBump(cycle, pulseStart, NODE_PULSE_DURATION)
    const targetOpacity = 0.22 + (active ? 0.5 : 0) + pulse * 0.55
    const material = lineObject.material as THREE.LineBasicMaterial
    // The line object is a plain three.js instance held in a ref-like memo; mutating its material each frame is the standard R3F animation pattern.
    // oxlint-disable-next-line react/immutability
    material.opacity = THREE.MathUtils.lerp(material.opacity, targetOpacity, 0.1)

    if (packetRef.current) {
      if (reduced) {
        packetRef.current.visible = false
      } else {
        packetRef.current.visible = true
        const localT = (t * speed + phase) % 1
        packetRef.current.position.set(
          THREE.MathUtils.lerp(start[0], end[0], localT),
          THREE.MathUtils.lerp(start[1], end[1], localT),
          THREE.MathUtils.lerp(start[2], end[2], localT),
        )
        const boost = 1 + pulse * 1.4
        packetRef.current.scale.setScalar(boost)
        if (packetMaterial.current) packetMaterial.current.opacity = Math.sin(localT * Math.PI) * (0.55 + (active ? 0.45 : 0) + pulse * 0.4)
      }
    }
  })

  return (
    <group>
      <primitive object={lineObject} />
      <mesh ref={packetRef}>
        <sphereGeometry args={[0.06, 10, 10]} />
        <meshBasicMaterial ref={packetMaterial} color={color} transparent opacity={0.8} toneMapped={false} />
      </mesh>
    </group>
  )
}

function GlassNode({ node, reducedMotion, interaction }: { node: NodeInfo; reducedMotion: MutableRefObject<boolean>; interaction: MutableRefObject<HoverState> }) {
  const introGroup = useRef<THREE.Group>(null)
  const idleGroup = useRef<THREE.Group>(null)
  const boxMaterial = useRef<THREE.MeshPhysicalMaterial>(null)
  const pointLightRef = useRef<THREE.PointLight>(null)
  const hoverAmount = useRef(0)
  const isHovered = useRef(false)

  useFrame((state) => {
    const t = state.clock.elapsedTime
    const reduced = reducedMotion.current

    const introT = reduced ? 1 : smoothstep(1.75 + node.delay, 2.35 + node.delay, t)
    if (introGroup.current) {
      const s = THREE.MathUtils.lerp(introGroup.current.scale.x, introT, 0.2)
      introGroup.current.scale.setScalar(s)
      // "Fly gently into position": start scattered further from the vault, converge on the final spot.
      introGroup.current.position.set(
        THREE.MathUtils.lerp(node.flyFrom[0], node.position[0], introT),
        THREE.MathUtils.lerp(node.flyFrom[1], node.position[1], introT),
        THREE.MathUtils.lerp(node.flyFrom[2], node.position[2], introT),
      )
    }

    const cycle = t < PULSE_START_DELAY ? -1 : (t - PULSE_START_DELAY) % PULSE_PERIOD
    const pulse = reduced || cycle < 0 ? 0 : pulseBump(cycle, node.pulseStart, NODE_PULSE_DURATION)

    hoverAmount.current = THREE.MathUtils.lerp(hoverAmount.current, isHovered.current ? 1 : 0, 0.12)

    if (idleGroup.current && !reduced) {
      idleGroup.current.position.y = Math.sin(t * 0.75 + node.phase) * 0.14
      idleGroup.current.rotation.z = node.rotation[2] + Math.sin(t * 0.5 + node.phase) * 0.03
      idleGroup.current.rotation.y = node.rotation[1] + Math.sin(t * node.spin * 4 + node.phase) * 0.5
    }
    if (idleGroup.current) idleGroup.current.position.z = THREE.MathUtils.lerp(idleGroup.current.position.z, hoverAmount.current * 0.28, 0.15)

    const glow = Math.min(1, pulse * 0.85 + hoverAmount.current * 0.6)
    if (boxMaterial.current) boxMaterial.current.emissiveIntensity = 0.14 + glow * 0.6
    if (pointLightRef.current) pointLightRef.current.intensity = 0.6 + glow * 2.4
  })

  function handlePointerOver(event: ThreeEvent<PointerEvent>) {
    event.stopPropagation()
    isHovered.current = true
    // `interaction` is a shared mutable ref (not React state) so hover changes don't re-render the whole scene tree.
    // oxlint-disable-next-line react/immutability
    interaction.current.hovered = node.label
    document.body.style.cursor = 'pointer'
  }
  function handlePointerOut(event: ThreeEvent<PointerEvent>) {
    event.stopPropagation()
    isHovered.current = false
    // oxlint-disable-next-line react/immutability
    if (interaction.current.hovered === node.label) interaction.current.hovered = null
    document.body.style.cursor = 'auto'
  }

  const IconComponent = node.icon === 'university' ? UniversityIcon : node.icon === 'student' ? StudentIcon : node.icon === 'employer' ? EmployerIcon : null
  const edgesGeo = useMemo(() => new THREE.EdgesGeometry(new THREE.BoxGeometry(1.62, 0.72, 0.26)), [])

  return (
    <group ref={introGroup} scale={0}>
      <group ref={idleGroup} rotation={node.rotation} onPointerOver={handlePointerOver} onPointerOut={handlePointerOut}>
        <RoundedBox args={[1.6, 0.7, 0.24]} radius={0.13} smoothness={4}>
          <meshPhysicalMaterial ref={boxMaterial} color="#14213a" metalness={0.42} roughness={0.14} transmission={0.14} transparent opacity={0.96} emissive={node.color} emissiveIntensity={0.14} />
        </RoundedBox>
        <lineSegments geometry={edgesGeo}>
          <lineBasicMaterial color={node.color} toneMapped={false} transparent opacity={0.7} />
        </lineSegments>
        <mesh position={[0, 0, 0.13]}>
          <planeGeometry args={[1.38, 0.5]} />
          <meshStandardMaterial color="#0b1529" metalness={0.3} roughness={0.22} transparent opacity={0.9} />
        </mesh>
        <group position={[-0.52, 0, 0.22]} scale={0.7}>
          {node.icon === 'verified' ? <ShieldEmblem scale={0.34} color={node.color} /> : IconComponent ? <IconComponent color={node.color} /> : null}
        </group>
        <Text position={[0.21, 0, 0.18]} fontSize={0.13} color="#f4f6fb" anchorX="center" anchorY="middle" letterSpacing={0.03}>{node.label}</Text>
        <pointLight ref={pointLightRef} position={[0, 0, 0.5]} color={node.color} intensity={0.6} distance={1.8} />
      </group>
    </group>
  )
}

function Transcript({ reducedMotion }: { reducedMotion: MutableRefObject<boolean> }) {
  const introGroup = useRef<THREE.Group>(null)
  const idleGroup = useRef<THREE.Group>(null)
  const scanRef = useRef<THREE.Mesh>(null)
  const verifiedRef = useRef<THREE.Group>(null)
  const finalPos: Vec3 = [1.5, -0.05, 2.3]
  const startPos: Vec3 = [0.4, -0.1, 0.4]

  useFrame((state) => {
    const t = state.clock.elapsedTime
    const reduced = reducedMotion.current

    const introT = reduced ? 1 : smoothstep(2.0, 2.6, t)
    if (introGroup.current) {
      const s = THREE.MathUtils.lerp(introGroup.current.scale.x, introT, 0.18)
      introGroup.current.scale.setScalar(s)
      // Floats forward out from near the vault into the foreground, rather than just fading in place.
      introGroup.current.position.set(
        THREE.MathUtils.lerp(startPos[0], finalPos[0], introT),
        THREE.MathUtils.lerp(startPos[1], finalPos[1], introT),
        THREE.MathUtils.lerp(startPos[2], finalPos[2], introT),
      )
    }

    if (idleGroup.current && !reduced) {
      idleGroup.current.position.y = Math.sin(t * 0.6 + 1.5) * 0.13
      idleGroup.current.rotation.y = -0.32 + Math.sin(t * 0.4) * 0.04
      idleGroup.current.rotation.z = -0.16 + Math.sin(t * 0.5 + 1) * 0.025
    }

    if (t > 2.7 && !reduced) {
      const localT = (t - 2.7) % SCAN_PERIOD
      const scanning = localT < SCAN_DURATION
      if (scanRef.current) {
        scanRef.current.visible = scanning
        if (scanning) scanRef.current.position.y = THREE.MathUtils.lerp(0.65, -0.65, smoothstep(0, 1, localT / SCAN_DURATION))
      }
      const flash = pulseBump(localT, SCAN_DURATION, 0.7)
      if (verifiedRef.current) {
        verifiedRef.current.visible = flash > 0.02
        verifiedRef.current.scale.setScalar(0.8 + flash * 0.3)
      }
    } else if (scanRef.current) {
      scanRef.current.visible = false
    }
  })

  return (
    <group ref={introGroup} scale={0}>
      <group ref={idleGroup} rotation={[0.1, -0.32, -0.16]}>
        <RoundedBox args={[2.0, 1.4, 0.24]} radius={0.11} smoothness={4} castShadow>
          <meshPhysicalMaterial color="#14243c" metalness={0.34} roughness={0.16} transmission={0.1} transparent opacity={0.97} />
        </RoundedBox>
        <lineSegments>
          <edgesGeometry args={[new THREE.BoxGeometry(2.0, 1.4, 0.24)]} />
          <lineBasicMaterial color="#4cd7f6" toneMapped={false} transparent opacity={0.8} />
        </lineSegments>
        <mesh position={[0.98, 0, 0]} rotation={[0, Math.PI / 2, 0]}>
          <planeGeometry args={[0.24, 1.38]} />
          <meshStandardMaterial color="#0a1830" metalness={0.6} roughness={0.2} emissive="#0e2a44" emissiveIntensity={0.6} />
        </mesh>
        <mesh position={[0, 0, 0.13]}>
          <planeGeometry args={[1.78, 1.18]} />
          <meshStandardMaterial color="#0d1b31" roughness={0.28} emissive="#07152a" emissiveIntensity={0.75} />
        </mesh>
        <Text position={[-0.75, 0.42, 0.22]} fontSize={0.12} color="#4cd7f6" anchorX="left" anchorY="middle" letterSpacing={0.025}>ACADEMIC TRANSCRIPT</Text>
        <Text position={[-0.75, 0.1, 0.22]} fontSize={0.17} color="#f4f6fb" anchorX="left" anchorY="middle">Degree</Text>
        <Text position={[-0.75, -0.18, 0.22]} fontSize={0.11} color="#aab4c8" anchorX="left" anchorY="middle">CGPA      8.72</Text>
        <Text position={[-0.75, -0.4, 0.22]} fontSize={0.1} color="#aab4c8" anchorX="left" anchorY="middle">Graduation Year  2026</Text>
        <mesh position={[0.58, -0.12, 0.22]}>
          <planeGeometry args={[0.34, 0.34]} />
          <meshBasicMaterial color="#d9faff" />
        </mesh>
        <mesh position={[0.58, -0.12, 0.23]}>
          <planeGeometry args={[0.28, 0.28]} />
          <meshBasicMaterial color="#132541" wireframe />
        </mesh>
        <mesh ref={scanRef} position={[0, 0.65, 0.24]} visible={false}>
          <planeGeometry args={[1.78, 0.035]} />
          <meshBasicMaterial color="#4cd7f6" transparent opacity={0.85} toneMapped={false} />
        </mesh>
        <group ref={verifiedRef} position={[0, -0.52, 0.24]} visible={false}>
          <Text fontSize={0.15} color="#4edea3" anchorX="center" anchorY="middle" letterSpacing={0.08}>VERIFIED</Text>
        </group>
      </group>
    </group>
  )
}

/** A handful of small sparks drifting slowly toward the vault, reinforcing the "credential flowing
 * into the vault" idea beyond the ambient Sparkles fields. */
function IncomingSparks({ reducedMotion, density }: { reducedMotion: MutableRefObject<boolean>; density: Density }) {
  const seeds = useMemo(() => {
    const starts: Vec3[] = [
      [-5.5, 2.2, -3],
      [5.2, -1.8, -2.4],
      [-4.6, -2.6, 2.6],
      [4.8, 2.6, 2.2],
    ]
    return starts.map((start, i) => ({ start, phase: i * 0.27, speed: 0.05 + i * 0.006 }))
  }, [])
  if (density === 'mobile') return null
  return (
    <>
      {seeds.map((seed, i) => (
        <IncomingSpark key={i} start={seed.start} phase={seed.phase} speed={seed.speed} reducedMotion={reducedMotion} />
      ))}
    </>
  )
}

function IncomingSpark({ start, phase, speed, reducedMotion }: { start: Vec3; phase: number; speed: number; reducedMotion: MutableRefObject<boolean> }) {
  const ref = useRef<THREE.Mesh>(null)
  const materialRef = useRef<THREE.MeshBasicMaterial>(null)
  const end: Vec3 = [0, VAULT_REST_Y, 0]
  useFrame((state) => {
    if (!ref.current) return
    if (reducedMotion.current) {
      ref.current.visible = false
      return
    }
    ref.current.visible = true
    const t = state.clock.elapsedTime
    const localT = (t * speed + phase) % 1
    ref.current.position.set(
      THREE.MathUtils.lerp(start[0], end[0], localT),
      THREE.MathUtils.lerp(start[1], end[1], localT),
      THREE.MathUtils.lerp(start[2], end[2], localT),
    )
    if (materialRef.current) materialRef.current.opacity = Math.sin(localT * Math.PI) * 0.85
  })
  return (
    <mesh ref={ref}>
      <sphereGeometry args={[0.045, 8, 8]} />
      <meshBasicMaterial ref={materialRef} color="#bfeeff" transparent opacity={0} toneMapped={false} />
    </mesh>
  )
}

function AtmosphereBeams() {
  if (!glowTexture) return null
  return (
    <>
      <mesh position={[-2.4, 0.6, -3.4]} rotation={[0, 0, 0.14]}>
        <planeGeometry args={[1.5, 7.5]} />
        <meshBasicMaterial map={glowTexture} color="#6c63ff" transparent opacity={0.14} depthWrite={false} blending={THREE.AdditiveBlending} toneMapped={false} />
      </mesh>
      <mesh position={[2.5, 0.4, -3.6]} rotation={[0, 0, -0.16]}>
        <planeGeometry args={[1.5, 7.5]} />
        <meshBasicMaterial map={glowTexture} color="#4cd7f6" transparent opacity={0.13} depthWrite={false} blending={THREE.AdditiveBlending} toneMapped={false} />
      </mesh>
    </>
  )
}

function SceneContent({ density, scrollRef }: { density: Density; scrollRef: MutableRefObject<number> }) {
  const reducedMotion = usePrefersReducedMotionRef()
  const interaction = useRef<HoverState>({ hovered: null })
  const nearCount = density === 'mobile' ? 0 : density === 'tablet' ? 8 : 14
  const midCount = density === 'mobile' ? 16 : density === 'tablet' ? 28 : 40
  const farCount = density === 'mobile' ? 0 : density === 'tablet' ? 10 : 20
  const vaultCenter: Vec3 = [0, VAULT_REST_Y, 0]

  return (
    <>
      <color attach="background" args={['#05070d']} />
      <fog attach="fog" args={['#05070d', 8, 16]} />
      <ambientLight intensity={0.24} />
      <directionalLight position={[-4, 5, 5]} intensity={4.2} color="#d9e5ff" castShadow={density === 'desktop'} shadow-mapSize={[512, 512]} />
      <MovingLights reducedMotion={reducedMotion} />

      {/* Foreground depth layer */}
      {nearCount > 0 && <Sparkles count={nearCount} scale={[4, 3, 3]} position={[0, 0.4, 3.4]} size={2.4} speed={0.22} color="#bfeeff" noise={1} />}
      <IncomingSparks reducedMotion={reducedMotion} density={density} />

      {/* Midground */}
      <Sparkles count={midCount} scale={[9, 6, 6]} size={1.3} speed={0.16} color="#83e7ff" noise={1.2} />

      {/* Background depth layer */}
      {farCount > 0 && <Sparkles count={farCount} scale={[13, 8, 8]} position={[0, 0.2, -4.6]} size={0.75} speed={0.08} color="#5b9cff" noise={1.6} />}
      {density !== 'mobile' && <AtmosphereBeams />}
      {density !== 'mobile' && (
        <Grid position={[0, -1.9, 0]} args={[14, 14]} cellSize={0.7} cellThickness={0.4} cellColor="#1b2c52" sectionSize={3.5} sectionThickness={0.8} sectionColor="#3450a8" fadeDistance={8} fadeStrength={1.6} />
      )}

      <CameraRig reducedMotion={reducedMotion} scrollRef={scrollRef} />
      {NODES.map((node) => (
        <NetworkLine key={node.label} from={node.position} to={vaultCenter} color={node.color} label={node.label} interaction={interaction} reducedMotion={reducedMotion} speed={0.18} phase={node.phase} direction={node.direction} pulseStart={node.pulseStart} />
      ))}
      <Platform reducedMotion={reducedMotion} density={density} />
      <OrbitalSystem reducedMotion={reducedMotion} interaction={interaction} />
      <Vault reducedMotion={reducedMotion} interaction={interaction} density={density} />
      {NODES.map((node) => <GlassNode key={node.label} node={node} reducedMotion={reducedMotion} interaction={interaction} />)}
      <Transcript reducedMotion={reducedMotion} />
    </>
  )
}

function supportsWebGL() {
  try {
    const canvas = document.createElement('canvas')
    return Boolean(canvas.getContext('webgl2') || canvas.getContext('webgl'))
  } catch {
    return false
  }
}

function FallbackScene() {
  function handlePointerMove(event: ReactPointerEvent<HTMLDivElement>) {
    const bounds = event.currentTarget.getBoundingClientRect()
    const x = ((event.clientX - bounds.left) / bounds.width - 0.5) * 2
    const y = ((event.clientY - bounds.top) / bounds.height - 0.5) * 2
    event.currentTarget.style.setProperty('--parallax-x', `${x * 9}deg`)
    event.currentTarget.style.setProperty('--parallax-y', `${y * -7}deg`)
  }

  return (
    <div className="landing-scene-fallback landing-scene-fallback-3d" aria-label="Credential verification flow" onPointerMove={handlePointerMove} onPointerLeave={(event) => { event.currentTarget.style.setProperty('--parallax-x', '0deg'); event.currentTarget.style.setProperty('--parallax-y', '0deg') }}>
      <div className="fallback-platform" />
      <div className="fallback-connection fallback-connection-tl" />
      <div className="fallback-connection fallback-connection-bl" />
      <div className="fallback-connection fallback-connection-tr" />
      <div className="fallback-connection fallback-connection-br" />
      <div className="fallback-node fallback-node-university"><b>U</b> UNIVERSITY</div>
      <div className="fallback-node fallback-node-student"><b>S</b> STUDENT</div>
      <div className="fallback-node fallback-node-employer"><b>E</b> EMPLOYER</div>
      <div className="fallback-node fallback-node-verified"><b>✓</b> VERIFIED</div>
      <div className="fallback-vault"><div className="fallback-vault-front"><span>✓</span><small>CREDCHAIN<br />VAULT</small></div><div className="fallback-vault-side" /><div className="fallback-vault-top" /></div>
      <div className="fallback-transcript"><strong>ACADEMIC TRANSCRIPT</strong><span>Degree</span><small>CGPA&nbsp;&nbsp; 8.72<br />Graduation Year&nbsp;&nbsp; 2026</small><i>▦</i></div>
    </div>
  )
}

const MAX_CANVAS_REMOUNTS = 3

export function LandingScene() {
  const [renderable, setRenderable] = useState(supportsWebGL)
  const [canvasKey, setCanvasKey] = useState(0)
  const remountsRef = useRef(0)
  const density = useDensity()
  const scrollRef = useScrollRef()
  if (!renderable) return <FallbackScene />
  return (
    <div className="landing-scene" aria-label="Interactive CredChain credential verification visualization">
      <Canvas
        key={canvasKey}
        shadows={density === 'desktop'}
        dpr={density === 'mobile' ? [1, 1] : [1, 1.25]}
        camera={{ position: [0, 0.5, 7.1], fov: 40, near: 0.1, far: 40 }}
        gl={{ alpha: false, antialias: true, powerPreference: 'high-performance' }}
        onCreated={({ gl }) => {
          const canvas = gl.domElement
          const handleContextLost = (event: Event) => {
            // Ask the browser to attempt automatic recovery instead of abandoning the context outright.
            event.preventDefault()
            window.setTimeout(() => {
              if (!canvas.isConnected) return
              const context = gl.getContext()
              if (!context.isContextLost()) return
              // In dev, React StrictMode double-mounts the Canvas and disposes the first WebGL
              // context; on some GPU drivers that disposal also poisons the second (live) context
              // even though the browser never truly restores it. A raw context restore wouldn't be
              // enough anyway -- three.js needs a fresh WebGLRenderer -- so force a full remount
              // (new canvas element, new context) a few times before giving up to the CSS fallback.
              if (remountsRef.current < MAX_CANVAS_REMOUNTS) {
                remountsRef.current += 1
                setCanvasKey((k) => k + 1)
              } else {
                setRenderable(false)
              }
            }, 900)
          }
          canvas.addEventListener('webglcontextlost', handleContextLost)
        }}
      >
        <SceneContent density={density} scrollRef={scrollRef} />
      </Canvas>
    </div>
  )
}
