import { useEffect, useRef, useState } from 'react';

export default function InteractiveCursor() {
  const dotRef = useRef<HTMLDivElement>(null);
  const ringRef = useRef<HTMLDivElement>(null);
  const glowRef = useRef<HTMLDivElement>(null);
  const requestRef = useRef<number>(0);
  const mouse = useRef({ x: 0, y: 0 });
  const ring = useRef({ x: 0, y: 0 });
  const isHovering = useRef(false);
  const [shouldRender, setShouldRender] = useState(true);

  useEffect(() => {
    // Disable on reduced motion or coarse pointer
    if (
      window.matchMedia('(prefers-reduced-motion: reduce)').matches ||
      window.matchMedia('(pointer: coarse)').matches
    ) {
      setShouldRender(false);
      return;
    }

    const onMouseMove = (e: MouseEvent) => {
      mouse.current.x = e.clientX;
      mouse.current.y = e.clientY;

      if (dotRef.current) {
        dotRef.current.style.transform = `translate3d(${e.clientX}px, ${e.clientY}px, 0)`;
      }
      if (glowRef.current) {
        glowRef.current.style.background = `radial-gradient(600px circle at ${e.clientX}px ${e.clientY}px, rgba(28, 105, 212, 0.08), transparent 40%)`;
      }
    };

    const animate = () => {
      // Lerp ring
      ring.current.x += (mouse.current.x - ring.current.x) * 0.2;
      ring.current.y += (mouse.current.y - ring.current.y) * 0.2;

      if (ringRef.current) {
        const scale = isHovering.current ? 'scale(1.5)' : 'scale(1)';
        ringRef.current.style.transform = `translate3d(${ring.current.x}px, ${ring.current.y}px, 0) ${scale}`;
      }

      requestRef.current = requestAnimationFrame(animate);
    };

    const handleMouseOver = (e: MouseEvent) => {
      const target = e.target as HTMLElement;
      if (target.closest('button, a, .agent-card')) {
        isHovering.current = true;
        if (dotRef.current) dotRef.current.style.opacity = '0';
        if (ringRef.current) {
          ringRef.current.classList.add('hovering');
        }
      } else {
        isHovering.current = false;
        if (dotRef.current) dotRef.current.style.opacity = '1';
        if (ringRef.current) {
          ringRef.current.classList.remove('hovering');
        }
      }
    };

    window.addEventListener('mousemove', onMouseMove, { passive: true });
    window.addEventListener('mouseover', handleMouseOver, { passive: true });
    requestRef.current = requestAnimationFrame(animate);

    document.body.style.cursor = 'none';

    return () => {
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseover', handleMouseOver);
      cancelAnimationFrame(requestRef.current);
      document.body.style.cursor = '';
    };
  }, []);

  if (!shouldRender) return null;

  return (
    <>
      <style>{`
        body {
          cursor: none;
        }
        .custom-cursor-dot {
          position: fixed;
          top: 0;
          left: 0;
          width: 8px;
          height: 8px;
          background-color: white;
          border-radius: 50%;
          pointer-events: none;
          z-index: 99999;
          transform: translate(-50%, -50%);
          mix-blend-mode: difference;
        }
        .custom-cursor-ring {
          position: fixed;
          top: 0;
          left: 0;
          width: 40px;
          height: 40px;
          border: 1px solid rgba(255, 255, 255, 0.4);
          border-radius: 50%;
          pointer-events: none;
          z-index: 99998;
          transform: translate(-50%, -50%);
          transition: width 0.3s, height 0.3s, border-color 0.3s, background-color 0.3s;
          mix-blend-mode: difference;
        }
        .custom-cursor-ring.hovering {
          width: 60px;
          height: 60px;
          background: rgba(255, 255, 255, 1);
          border-color: transparent;
          mix-blend-mode: difference;
        }
      `}</style>
      <div
        ref={glowRef}
        style={{
          position: 'fixed',
          top: 0,
          left: 0,
          width: '100vw',
          height: '100vh',
          pointerEvents: 'none',
          zIndex: 0,
          willChange: 'background',
        }}
      />
      <div ref={ringRef} className="custom-cursor-ring" />
      <div
        ref={dotRef}
        className="custom-cursor-dot"
        style={{
          position: 'fixed',
          top: 0,
          left: 0,
          width: '8px',
          height: '8px',
          margin: '-4px 0 0 -4px',
          background: '#ffffff',
          borderRadius: '50%',
          pointerEvents: 'none',
          zIndex: 10000,
          willChange: 'transform',
          transition: 'opacity 0.2s ease',
        }}
      />
    </>
  );
}
