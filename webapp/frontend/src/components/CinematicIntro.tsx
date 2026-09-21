import { useEffect, useRef } from 'react';
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import ScrambleText from './ScrambleText';

gsap.registerPlugin(ScrollTrigger);

export default function CinematicIntro() {
  const containerRef = useRef<HTMLDivElement>(null);
  const imageRef = useRef<HTMLImageElement>(null);
  const bubblesRef = useRef<(HTMLDivElement | null)[]>([]);

  useEffect(() => {
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reducedMotion) return;

    const ctx = gsap.context(() => {
      // Pin the container
      const tl = gsap.timeline({
        scrollTrigger: {
          trigger: containerRef.current,
          start: 'top top',
          end: '+=4000', // 4000px of scrolling for the story
          pin: true,
          scrub: 1,
        }
      });

      // Initial state
      gsap.set(bubblesRef.current, { opacity: 0, scale: 0.8, y: 20 });
      gsap.set(imageRef.current, { scale: 1.1, opacity: 0.2 });

      // Image fade in & slow scale
      tl.to(imageRef.current, { opacity: 1, scale: 1, duration: 1 }, 0);

      const staggerDuration = 1.5;

      // Bubble 1: Planner
      tl.to(bubblesRef.current[0], { opacity: 1, scale: 1, y: 0, duration: 0.5 }, 1);
      tl.to(bubblesRef.current[0], { opacity: 0.5, duration: 0.5 }, 1 + staggerDuration);

      // Bubble 2: CodeGen
      tl.to(bubblesRef.current[1], { opacity: 1, scale: 1, y: 0, duration: 0.5 }, 2);
      tl.to(bubblesRef.current[1], { opacity: 0.5, duration: 0.5 }, 2 + staggerDuration);

      // Bubble 3: RAG
      tl.to(bubblesRef.current[2], { opacity: 1, scale: 1, y: 0, duration: 0.5 }, 3);
      tl.to(bubblesRef.current[2], { opacity: 0.5, duration: 0.5 }, 3 + staggerDuration);

      // Bubble 4: DB
      tl.to(bubblesRef.current[3], { opacity: 1, scale: 1, y: 0, duration: 0.5 }, 4);
      tl.to(bubblesRef.current[3], { opacity: 0.5, duration: 0.5 }, 4 + staggerDuration);

      // Bubble 5: Reviewer
      tl.to(bubblesRef.current[4], { opacity: 1, scale: 1, y: 0, duration: 0.5 }, 5);
      tl.to(bubblesRef.current[0], { opacity: 0, duration: 0.5 }, 6);
      tl.to(bubblesRef.current[1], { opacity: 0, duration: 0.5 }, 6);
      tl.to(bubblesRef.current[2], { opacity: 0, duration: 0.5 }, 6);
      tl.to(bubblesRef.current[3], { opacity: 0, duration: 0.5 }, 6);
      tl.to(bubblesRef.current[4], { opacity: 0, duration: 0.5 }, 6);
      
      // Fade out image at the very end
      tl.to(imageRef.current, { opacity: 0.2, filter: 'blur(10px)', duration: 1 }, 6.5);

    }, containerRef);

    return () => ctx.revert();
  }, []);

  return (
    <div ref={containerRef} className="cinematic-container">
      <style>{`
        .cinematic-container {
          height: 100vh;
          width: 100vw;
          background: #000000;
          position: relative;
          overflow: hidden;
          display: flex;
          align-items: center;
          justify-content: center;
          border-bottom: 1px solid rgba(255, 255, 255, 0.1);
        }
        
        .cinematic-bg {
          position: absolute;
          width: 100%;
          height: 100%;
          object-fit: cover;
          z-index: 0;
        }

        .chat-overlay {
          position: absolute;
          top: 0; left: 0; width: 100%; height: 100%;
          z-index: 10;
          pointer-events: none;
        }

        .chat-bubble {
          position: absolute;
          background: rgba(10, 10, 10, 0.9);
          border: 1px solid #333;
          padding: 24px 32px;
          backdrop-filter: blur(10px);
          max-width: 320px;
          color: #fff;
          font-family: 'JetBrains Mono', 'Fira Code', monospace;
          font-size: 14px;
          line-height: 1.5;
        }

        .chat-bubble.planner { border-top: 4px solid #0066b1; top: 20%; left: 10%; }
        .chat-bubble.codegen { border-top: 4px solid #e22718; top: 50%; left: 25%; }
        .chat-bubble.rag { border-top: 4px solid #1c69d4; top: 30%; left: 50%; transform: translateX(-50%); }
        .chat-bubble.db { border-top: 4px solid #0066b1; top: 60%; right: 25%; }
        .chat-bubble.reviewer { border-top: 4px solid #e22718; top: 20%; right: 10%; }

        .chat-speaker {
          font-size: 12px;
          font-weight: 700;
          text-transform: uppercase;
          letter-spacing: 2px;
          margin-bottom: 12px;
          opacity: 0.6;
        }

        .chat-bubble.planner .chat-speaker { color: #0066b1; }
        .chat-bubble.codegen .chat-speaker { color: #e22718; }
        .chat-bubble.rag .chat-speaker { color: #1c69d4; }
        .chat-bubble.db .chat-speaker { color: #0066b1; }
        .chat-bubble.reviewer .chat-speaker { color: #e22718; }
      `}</style>

      <img 
        ref={imageRef} 
        src="/agents_at_table.jpg" 
        alt="Agents discussing" 
        className="cinematic-bg"
      />

      <div className="chat-overlay">
        <div ref={el => { bubblesRef.current[0] = el; }} className="chat-bubble planner">
          <div className="chat-speaker">Planner</div>
          <div><ScrambleText>User wants a secure login system. Breaking it down into 4 subtasks. CodeGen, you're up.</ScrambleText></div>
        </div>

        <div ref={el => { bubblesRef.current[1] = el; }} className="chat-bubble codegen">
          <div className="chat-speaker">CodeGen</div>
          <div><ScrambleText>Writing Next.js components. I need the latest Auth.js context.</ScrambleText></div>
        </div>

        <div ref={el => { bubblesRef.current[2] = el; }} className="chat-bubble rag">
          <div className="chat-speaker">RAG</div>
          <div><ScrambleText>Querying vector database. Injecting v5 documentation into your context window.</ScrambleText></div>
        </div>

        <div ref={el => { bubblesRef.current[3] = el; }} className="chat-bubble db">
          <div className="chat-speaker">DB</div>
          <div><ScrambleText>Provisioning users table and session schemas in Postgres. Migrations ready.</ScrambleText></div>
        </div>

        <div ref={el => { bubblesRef.current[4] = el; }} className="chat-bubble reviewer">
          <div className="chat-speaker">Reviewer</div>
          <div><ScrambleText>Static analysis complete. 0 vulnerabilities found. Approved for deployment.</ScrambleText></div>
        </div>
      </div>
    </div>
  );
}
