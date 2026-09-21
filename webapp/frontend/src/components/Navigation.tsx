import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import gsap from 'gsap';
import Magnetic from './Magnetic';

export default function Navigation() {
  const [isOpen, setIsOpen] = useState(false);
  const overlayRef = useRef<HTMLDivElement>(null);
  const linksRef = useRef<(HTMLAnchorElement | null)[]>([]);
  const timelineRef = useRef<gsap.core.Timeline | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    if (!overlayRef.current) return;

    gsap.set(overlayRef.current, { clipPath: 'circle(0% at 100% 0%)' });

    timelineRef.current = gsap.timeline({ paused: true })
      .to(overlayRef.current, {
        clipPath: 'circle(150% at 100% 0%)',
        duration: 0.8,
        ease: 'power3.inOut'
      })
      .fromTo(linksRef.current, 
        { y: 100, opacity: 0 },
        { y: 0, opacity: 1, duration: 0.6, stagger: 0.1, ease: 'power3.out' },
        '-=0.4'
      );

    return () => {
      timelineRef.current?.kill();
    };
  }, []);

  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      if (isOpen) {
        gsap.set(overlayRef.current, { clipPath: 'circle(150% at 100% 0%)' });
        gsap.set(linksRef.current, { y: 0, opacity: 1 });
      } else {
        gsap.set(overlayRef.current, { clipPath: 'circle(0% at 100% 0%)' });
      }
      return;
    }

    if (isOpen) {
      timelineRef.current?.play();
      document.body.style.overflow = 'hidden';
    } else {
      timelineRef.current?.reverse();
      document.body.style.overflow = '';
    }
  }, [isOpen]);

  // Focus trap
  useEffect(() => {
    if (!isOpen) return;
    
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setIsOpen(false);
      }
      if (e.key === 'Tab') {
        const focusableElements = overlayRef.current?.querySelectorAll('a, button');
        if (!focusableElements || focusableElements.length === 0) return;
        const firstElement = focusableElements[0] as HTMLElement;
        const lastElement = focusableElements[focusableElements.length - 1] as HTMLElement;

        if (e.shiftKey) {
          if (document.activeElement === firstElement) {
            lastElement.focus();
            e.preventDefault();
          }
        } else {
          if (document.activeElement === lastElement) {
            firstElement.focus();
            e.preventDefault();
          }
        }
      }
    };
    
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen]);

  const handleLinkClick = (anchor: string) => {
    setIsOpen(false);
    setTimeout(() => {
      if (anchor === '/login') {
        navigate(anchor);
      } else {
        const el = document.querySelector(anchor);
        el?.scrollIntoView({ behavior: 'smooth' });
      }
    }, 800);
  };

  return (
    <>
      <style>{`
        .nav-header {
          position: fixed;
          top: 0;
          left: 0;
          width: 100%;
          padding: 24px 32px;
          display: flex;
          justify-content: space-between;
          align-items: center;
          z-index: 10000;
          pointer-events: none;
        }

        .nav-header > * {
          pointer-events: auto;
        }

        .nav-logo {
          font-weight: 700;
          font-size: 16px;
          text-transform: uppercase;
          letter-spacing: 1px;
          color: #ffffff;
        }

        .nav-toggle {
          background: none;
          border: none;
          color: #ffffff;
          font-family: 'Inter', sans-serif;
          font-weight: 700;
          font-size: 14px;
          cursor: pointer;
          text-transform: uppercase;
          z-index: 10001;
        }

        .nav-overlay {
          position: fixed;
          top: 0;
          left: 0;
          width: 100vw;
          height: 100vh;
          background: #000000;
          z-index: 9999;
          display: flex;
          flex-direction: column;
          justify-content: center;
          padding: 64px;
        }
        
        .nav-overlay-bg {
          position: absolute;
          top: 0;
          left: 0;
          width: 100%;
          height: 100%;
          background: radial-gradient(circle at 100% 0%, rgba(28, 105, 212, 0.1), transparent 50%);
          pointer-events: none;
        }

        .nav-link {
          font-size: 80px;
          font-weight: 700;
          color: #ffffff;
          text-transform: uppercase;
          text-decoration: none;
          line-height: 1;
          margin: 16px 0;
          display: inline-block;
          position: relative;
          cursor: pointer;
          letter-spacing: -2px;
        }

        .nav-link::after {
          content: '';
          position: absolute;
          bottom: 10px;
          left: 0;
          width: 100%;
          height: 8px;
          background: linear-gradient(90deg, #0066b1, #1c69d4, #e22718);
          transform: scaleX(0);
          transform-origin: left;
          transition: transform 0.4s cubic-bezier(0.19, 1, 0.22, 1);
        }

        .nav-link:hover::after {
          transform: scaleX(1);
        }
        
        @media (max-width: 768px) {
          .nav-link { font-size: 48px; }
        }
      `}</style>

      <header className="nav-header">
        <Magnetic strength={15}>
          <div className="nav-logo" style={{ pointerEvents: 'auto' }}>Pipeline</div>
        </Magnetic>
        <Magnetic strength={20}>
          <button className="nav-toggle" onClick={() => setIsOpen(!isOpen)}>
            {isOpen ? 'Close' : 'Menu'}
          </button>
        </Magnetic>
      </header>

      <div className="nav-overlay" ref={overlayRef}>
        <div className="nav-overlay-bg" />
        <nav style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start' }}>
          {[
            { label: 'Home', href: '#hero' },
            { label: 'How It Works', href: '#how-it-works' },
            { label: 'The Agents', href: '#agents' },
            { label: 'Constraints', href: '#constraints' },
            { label: 'Get Started', href: '/login' }
          ].map((item, i) => (
            <Magnetic key={item.label} strength={10}>
              <a
                className="nav-link"
                href={item.href}
                onClick={(e) => { e.preventDefault(); handleLinkClick(item.href); }}
                ref={el => { linksRef.current[i] = el; }}
              >
                {item.label}
              </a>
            </Magnetic>
          ))}
        </nav>
      </div>
    </>
  );
}
