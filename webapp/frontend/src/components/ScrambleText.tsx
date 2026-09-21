import { useEffect, useRef } from 'react';
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';

gsap.registerPlugin(ScrollTrigger);

interface ScrambleTextProps {
  children: string;
  className?: string;
}

const CHARS = '!<>-_\\/[]{}—=+*^?#________';

export default function ScrambleText({ children, className = '' }: ScrambleTextProps) {
  const textRef = useRef<HTMLSpanElement>(null);
  
  useEffect(() => {
    if (!textRef.current || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    
    const originalText = children;
    const length = originalText.length;
    
    // Store tweening state object
    const state = { progress: 0 };
    
    const st = ScrollTrigger.create({
      trigger: textRef.current,
      start: 'top 85%',
      animation: gsap.to(state, {
        progress: 1,
        duration: 1.5,
        ease: 'power3.out',
        onUpdate: () => {
          if (!textRef.current) return;
          const progress = state.progress;
          const revealedChars = Math.floor(length * progress);
          
          let newText = originalText.substring(0, revealedChars);
          
          for (let i = revealedChars; i < length; i++) {
            // Only scramble non-space characters
            if (originalText[i] === ' ') {
              newText += ' ';
            } else {
              newText += CHARS[Math.floor(Math.random() * CHARS.length)];
            }
          }
          
          textRef.current.innerText = newText;
        },
        onComplete: () => {
          if (textRef.current) textRef.current.innerText = originalText;
        }
      })
    });

    // Initial state before animation starts
    textRef.current.innerText = originalText.replace(/[^ ]/g, '_');

    return () => {
      st.kill();
    };
  }, [children]);

  return (
    <span ref={textRef} className={className} style={{ display: 'inline-block', minWidth: '1em' }}>
      {children}
    </span>
  );
}
