import { useEffect, useRef } from 'react';
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';

gsap.registerPlugin(ScrollTrigger);

interface SplitTextProps {
  children: string;
  className?: string;
}

export default function SplitText({ children, className = '' }: SplitTextProps) {
  const containerRef = useRef<HTMLSpanElement>(null);
  const words = children.split(' ');

  useEffect(() => {
    if (!containerRef.current) return;
    
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      gsap.set(containerRef.current.querySelectorAll('.split-char'), { y: '0%' });
      return;
    }

    const ctx = gsap.context(() => {
      const chars = containerRef.current!.querySelectorAll('.split-char');
      ScrollTrigger.create({
        trigger: containerRef.current,
        start: 'top 90%',
        animation: gsap.to(chars, {
          y: '0%',
          duration: 0.8,
          stagger: 0.02,
          ease: 'power3.out',
        })
      });
    }, containerRef);

    return () => ctx.revert();
  }, []);

  return (
    <span ref={containerRef} className={className} style={{ display: 'inline-block', overflow: 'hidden' }}>
      {words.map((word, wordIndex) => (
        <span key={wordIndex} className="split-word" style={{ display: 'inline-block', overflow: 'hidden', whiteSpace: 'nowrap' }}>
          {word.split('').map((char, charIndex) => (
            <span
              key={charIndex}
              className="split-char"
              style={{ display: 'inline-block', transform: 'translateY(100%)', willChange: 'transform' }}
            >
              {char}
            </span>
          ))}
          {wordIndex < words.length - 1 && <span style={{ display: 'inline-block', width: '0.25em' }}>&nbsp;</span>}
        </span>
      ))}
    </span>
  );
}
