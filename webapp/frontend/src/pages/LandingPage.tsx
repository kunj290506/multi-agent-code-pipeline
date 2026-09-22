import React, { useEffect, useRef, Suspense } from 'react'
import gsap from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import { Link } from 'react-router-dom'

import SmoothScroll from '../components/SmoothScroll'
import NoiseOverlay from '../components/NoiseOverlay'
import Navigation from '../components/Navigation'
import SplitText from '../components/SplitText'
import ScrambleText from '../components/ScrambleText'
import CodeBackground from '../components/CodeBackground'
import CinematicIntro from '../components/CinematicIntro'
import { useCardTilt, useScrollReveal, useParallaxBackground } from '../hooks/useLandingEffects'

gsap.registerPlugin(ScrollTrigger)

const HeroShaderBackground = React.lazy(() => import('../components/HeroShaderBackground'))

export default function LandingPage() {
  const heroRef = useRef<HTMLElement>(null)
  const heroTextRef = useRef<HTMLDivElement>(null)

  useCardTilt()
  useScrollReveal()
  useParallaxBackground()

  useEffect(() => {
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (reducedMotion) return

    const ctx = gsap.context(() => {
      // Intro Sequence
      const tl = gsap.timeline()
      tl.fromTo(heroTextRef.current, 
        { opacity: 0, scale: 0.95, y: 100 },
        { opacity: 1, scale: 1, y: 0, duration: 1.5, ease: 'power4.out', delay: 0.2 }
      )

      // Scroll Out Transition (Parallax + Fade)
      ScrollTrigger.create({
        trigger: heroRef.current,
        start: 'top top',
        end: 'bottom top',
        scrub: 1,
        animation: gsap.to(heroTextRef.current, {
          y: 200,
          opacity: 0,
          scale: 0.9,
          ease: 'none'
        })
      })
    }, heroRef)

    return () => ctx.revert()
  }, [])

  return (
    <SmoothScroll>
      <div className="landing-page">
        <CodeBackground />
        <NoiseOverlay />
        <Navigation />
        
        <style>{`
          .landing-page {
            background: #000000;
            color: #bbbbbb;
            font-family: 'Inter', system-ui, -apple-system, sans-serif;
            display: flex;
            flex-direction: column;
            line-height: 1.6;
            overflow-x: hidden;
          }
          
          /* Typography */
          .landing-page h1, .landing-page h2, .landing-page h3, .landing-page h4 {
            color: #ffffff;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: -2px;
            margin: 0;
            line-height: 0.9;
          }
          
          /* Cinematic Viewport Typography */
          .landing-page h1 { font-size: max(8vw, 64px); letter-spacing: -4px; margin-bottom: 24px; }
          .landing-page h2 { font-size: max(5vw, 48px); margin-bottom: 48px; }
          .landing-page h3 { font-size: 24px; letter-spacing: -1px; margin-bottom: 16px; }
          
          .landing-page p {
            font-weight: 300;
            margin: 0;
            font-size: 24px;
            max-width: none; /* Removed 600px cap */
          }
          
          /* Flexbox Section Spacing */
          .section {
            padding: 240px 48px;
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            gap: 64px;
            position: relative;
            z-index: 1;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
          }
          
          .section-left {
            flex: 0 0 40%;
          }
          
          .section-right {
            flex: 0 0 50%;
            padding-top: 12px;
          }
          
          .hero-section {
            height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            text-align: center;
            padding: 0 48px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
          }
          
          /* Horizontal Native Scroll Area for Agents */
          .agents-horizontal-scroll {
            padding: 120px 0;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
            position: relative;
          }
          
          .agents-horizontal-wrapper {
            display: flex;
            gap: 48px;
            padding: 0 48px 48px 48px; /* Extra bottom padding for scrollbar */
            overflow-x: auto;
            align-items: stretch;
            scroll-snap-type: x mandatory;
            scrollbar-width: thin;
            scrollbar-color: #3c3c3c transparent;
            perspective: 1200px;
          }
          
          .agents-horizontal-wrapper::-webkit-scrollbar {
            height: 8px;
          }
          .agents-horizontal-wrapper::-webkit-scrollbar-track {
            background: transparent;
          }
          .agents-horizontal-wrapper::-webkit-scrollbar-thumb {
            background-color: #3c3c3c;
            border-radius: 4px;
          }
          
          .agent-card {
            width: 400px;
            height: 500px;
            flex-shrink: 0;
            scroll-snap-align: start;
            background: rgba(10, 10, 10, 0.8);
            backdrop-filter: blur(20px);
            border: 1px solid #333;
            padding: 48px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            transform-style: preserve-3d;
            transition: border-color 0.3s ease, background 0.3s ease;
            position: relative;
            z-index: 10;
            --mouseX: 50%;
            --mouseY: 50%;
          }
          
          .agent-card::before {
            content: '';
            position: absolute;
            top: 0; left: 0; right: 0; bottom: 0;
            background: radial-gradient(600px circle at var(--mouseX) var(--mouseY), rgba(255,255,255,0.08), transparent 40%);
            opacity: 0;
            transition: opacity 0.3s;
            pointer-events: none;
            z-index: 0;
          }
          
          .agent-card:hover::before {
            opacity: 1;
          }
          
          .agent-card:hover, .agent-card.active {
            background: rgba(20, 20, 20, 0.9);
            border-color: #555;
          }
          
          .agent-card.planner { border-top: 4px solid #0066b1; }
          .agent-card.rag { border-top: 4px solid #e22718; }
          .agent-card.codegen { border-top: 4px solid #0066b1; }
          .agent-card.reviewer { border-top: 4px solid #e22718; }
          .agent-card.db { border-top: 4px solid #0066b1; }
          
          .agent-card h3, .agent-card p, .agent-card .agent-num {
            position: relative;
            z-index: 1;
          }
          
          .agent-card .agent-num {
            font-size: 80px;
            font-weight: 700;
            color: rgba(255, 255, 255, 0.1);
            line-height: 0.8;
            transform: translateZ(10px);
          }
          
          .agent-card h3 {
            font-size: 32px;
            transform: translateZ(40px);
            margin-bottom: 24px;
          }
          
          .agent-card p {
            font-size: 16px;
            transform: translateZ(20px);
          }
          
          .constraints-list {
            list-style-type: none;
            padding: 0;
            margin: 0;
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 32px;
          }
          
          .constraints-list li {
            margin-top: 48px;
          }
          
          .tech-chip {
            background: transparent;
            border: 1px solid #555;
            padding: 16px 32px;
            color: #ffffff;
            font-weight: 700;
            font-size: 16px;
            text-transform: uppercase;
            letter-spacing: 2px;
            transition: all 0.3s ease;
          }
          
          .tech-chip:hover {
            background: #ffffff;
            color: #000000;
          }
          
          footer {
            border-top: 1px solid rgba(255, 255, 255, 0.1);
            padding: 64px 48px;
            display: flex;
            justify-content: space-between;
            color: #555;
            font-size: 14px;
            font-weight: 300;
            text-transform: uppercase;
            letter-spacing: 2px;
          }
          
          .reveal-on-scroll {
            will-change: opacity, transform;
          }

          .tech-marquee-wrapper {
            width: 100%;
            overflow: hidden;
            white-space: nowrap;
            position: relative;
            mask-image: linear-gradient(to right, transparent, black 10%, black 90%, transparent);
            -webkit-mask-image: linear-gradient(to right, transparent, black 10%, black 90%, transparent);
          }
          
          .tech-marquee {
            display: inline-flex;
            gap: 64px;
            animation: marquee 20s linear infinite;
          }
          
          .tech-marquee span {
            font-size: 8vw;
            font-weight: 700;
            color: transparent;
            -webkit-text-stroke: 1px rgba(255, 255, 255, 0.2);
            text-transform: uppercase;
            letter-spacing: 2px;
          }
          
          @keyframes marquee {
            0% { transform: translateX(0); }
            100% { transform: translateX(-50%); }
          }
          
          @media (max-width: 768px) {
            .section { flex-direction: column; padding: 120px 24px; }
            .section-left, .section-right { flex: 0 0 100%; width: 100%; }
            .agents-horizontal-scroll { padding: 120px 0; }
            .agents-horizontal-wrapper { padding: 0 24px 24px 24px; }
            .agent-card { width: 85vw; height: auto; min-height: 300px; }
            .constraints-list { grid-template-columns: 1fr; }
            .tech-marquee span { font-size: 12vw; }
          }
        `}</style>

        <main>
          <section className="hero-section" id="hero" ref={heroRef}>
            <Suspense fallback={null}>
              <HeroShaderBackground />
            </Suspense>
            
            <div ref={heroTextRef} style={{ position: 'relative', zIndex: 10, width: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
              <h1>
                <SplitText>Multi-Agent Code</SplitText><br />
                <SplitText>Pipeline Orchestrator</SplitText>
              </h1>
              <p style={{ margin: '0 auto 40px auto', fontSize: 'max(1.5vw, 18px)' }}>
                <SplitText>A multi-agent pipeline that takes a natural-language request and produces real, reviewed code using five strictly coordinated AI agents.</SplitText>
              </p>
              <Link to="/ide" style={{
                display: 'inline-block',
                padding: '16px 40px',
                background: 'var(--text-white)',
                color: 'var(--canvas)',
                textDecoration: 'none',
                fontWeight: 700,
                textTransform: 'uppercase',
                letterSpacing: '2px',
                transition: 'transform 0.3s ease'
              }} onMouseEnter={(e) => e.currentTarget.style.transform = 'scale(1.05)'} onMouseLeave={(e) => e.currentTarget.style.transform = 'scale(1)'}>
                Get Started
              </Link>
            </div>
          </section>

          <CinematicIntro />

          <section className="section" id="how-it-works" style={{ position: 'relative', overflow: 'hidden' }}>
            <img src="/wireframe_globe.jpg" alt="" style={{ position: 'absolute', top: '-20%', left: 0, width: '100%', height: '140%', objectFit: 'cover', opacity: 0.15, pointerEvents: 'none' }} className="parallax-bg" />
            <div className="section-left reveal-on-scroll" style={{ position: 'relative', zIndex: 1 }}>
              <h2><SplitText>What It</SplitText><br /><SplitText>Actually Does</SplitText></h2>
            </div>
            <div className="section-right reveal-on-scroll" style={{ position: 'relative', zIndex: 1 }}>
              <p style={{ fontSize: '24px', lineHeight: '1.5' }}>
                When a natural language request is received, the Planner orchestrates the task and breaks it down into actionable subtasks. Specialized agents (CodeGen, DB, RAG) handle their respective steps, and the Reviewer gates the output for quality before it is finalized into the target workspace. The result is either a code change or a runnable project you can open and test.
              </p>
            </div>
          </section>

          <section className="agents-horizontal-scroll" id="agents">
            <div style={{ padding: '0 48px', marginBottom: '48px', position: 'relative', zIndex: 10 }}>
              <h2 className="reveal-on-scroll"><SplitText>The Architecture</SplitText></h2>
            </div>

            <div className="agents-horizontal-wrapper">
              {[
                { id: 'planner', num: '01', title: 'Planner Agent', desc: 'Orchestrates task flow, breaks user intent into subtasks, and delegates to other agents.' },
                { id: 'rag', num: '02', title: 'RAG Agent', desc: 'Retrieves relevant documentation snippets from the Chroma vector database.' },
                { id: 'codegen', num: '03', title: 'Code-Gen Agent', desc: 'Generates REST API endpoints and React components from specifications.' },
                { id: 'reviewer', num: '04', title: 'Reviewer Agent', desc: 'Reviews generated code for bugs, style, and security issues.' },
                { id: 'db', num: '05', title: 'DB Agent', desc: 'Handles database migrations and SQL query generation.' },
              ].map((agent) => (
                <div 
                  key={agent.id} 
                  className={`agent-card ${agent.id}`}
                  onMouseEnter={(e) => {
                    const rect = e.currentTarget.getBoundingClientRect()
                    e.currentTarget.style.setProperty('--mouseX', `${e.clientX - rect.left}px`)
                    e.currentTarget.style.setProperty('--mouseY', `${e.clientY - rect.top}px`)
                  }}
                  onMouseMove={(e) => {
                    const rect = e.currentTarget.getBoundingClientRect()
                    e.currentTarget.style.setProperty('--mouseX', `${e.clientX - rect.left}px`)
                    e.currentTarget.style.setProperty('--mouseY', `${e.clientY - rect.top}px`)
                  }}
                >
                  <div className="agent-num">{agent.num}</div>
                  <div>
                    <h3>{agent.title}</h3>
                    <p>{agent.desc}</p>
                  </div>
                </div>
              ))}
            </div>
          </section>

          <section className="section" style={{ position: 'relative', overflow: 'hidden' }}>
            <img src="/wireframe_cube.jpg" alt="" style={{ position: 'absolute', top: '-20%', left: 0, width: '100%', height: '140%', objectFit: 'cover', opacity: 0.15, pointerEvents: 'none' }} className="parallax-bg" />
            <div className="section-left reveal-on-scroll" style={{ position: 'relative', zIndex: 1 }}>
              <h2><SplitText>Why Built</SplitText><br /><SplitText>This Way</SplitText></h2>
            </div>
            <div className="section-right reveal-on-scroll" style={{ position: 'relative', zIndex: 1 }}>
              <p style={{ fontSize: '24px' }}>
                General-purpose AI coding tools typically use a single, broad model call to plan, generate, and validate at once, leading to inconsistent results and hallucinations. This project treats code generation as an orchestration and specialization problem: narrow agents, each with one job, strictly coordinated and reviewed.
              </p>
            </div>
          </section>

          <section className="section" id="constraints" style={{ display: 'block' }}>
            <h2 className="reveal-on-scroll" style={{ marginBottom: '96px' }}><SplitText>Non-Negotiable Constraints</SplitText></h2>
            <ul className="constraints-list">
              <li className="reveal-on-scroll">
                <strong><ScrambleText>Free & Self-Hosted</ScrambleText></strong>
                <p>No paid API required for the core demo. Runs locally via Ollama and n8n.</p>
              </li>
              <li className="reveal-on-scroll">
                <strong><ScrambleText>Sandboxed DB</ScrambleText></strong>
                <p>The DB Agent only ever executes against a local, sandboxed database.</p>
              </li>
              <li className="reveal-on-scroll">
                <strong><ScrambleText>Schema-Validated</ScrambleText></strong>
                <p>Every hand-off between agents is strictly schema-validated and visible. Nothing is a black box.</p>
              </li>
              <li className="reveal-on-scroll">
                <strong><ScrambleText>Bounded Retry</ScrambleText></strong>
                <p>Strict bounds on retries when an agent's output does not pass the Reviewer. No infinite loops, no silent failures.</p>
              </li>
            </ul>
          </section>

          <section className="section" style={{ display: 'block', paddingBottom: '120px', overflow: 'hidden' }}>
            <h2 className="reveal-on-scroll" style={{ marginBottom: '96px' }}><SplitText>The Tech Stack</SplitText></h2>
            <div className="tech-marquee-wrapper reveal-on-scroll">
              <div className="tech-marquee">
                {['N8N', 'OLLAMA', 'LANGCHAIN', 'CHROMA', 'DOCKER', 'REACT', 'GSAP', 'N8N', 'OLLAMA', 'LANGCHAIN', 'CHROMA'].map((tech, i) => (
                  <span key={i}>{tech}</span>
                ))}
              </div>
            </div>
          </section>
        </main>

        <footer>
          <div>Multi-Agent Code Pipeline</div>
          <div>&copy; {new Date().getFullYear()}</div>
        </footer>
      </div>
    </SmoothScroll>
  )
}
