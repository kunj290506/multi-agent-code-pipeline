import { useEffect } from 'react';
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';

gsap.registerPlugin(ScrollTrigger);

export function useCardTilt() {
  useEffect(() => {
    if (
      window.matchMedia('(prefers-reduced-motion: reduce)').matches ||
      window.matchMedia('(pointer: coarse)').matches
    ) {
      return;
    }

    const cards = document.querySelectorAll('.agent-card');
    
    cards.forEach((card) => {
      const el = card as HTMLElement;
      
      const handleMouseMove = (e: MouseEvent) => {
        const rect = el.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        
        const centerX = rect.width / 2;
        const centerY = rect.height / 2;
        
        const rotateX = ((y - centerY) / centerY) * -5; // max 5 degrees
        const rotateY = ((x - centerX) / centerX) * 5;
        
        el.style.setProperty('--mouseX', `${(x / rect.width) * 100}%`);
        el.style.setProperty('--mouseY', `${(y / rect.height) * 100}%`);
        
        el.style.transform = `perspective(1000px) rotateX(${rotateX}deg) rotateY(${rotateY}deg) scale3d(1.02, 1.02, 1.02)`;
        el.style.transition = 'none';
      };
      
      const handleMouseLeave = () => {
        el.style.transform = `perspective(1000px) rotateX(0deg) rotateY(0deg) scale3d(1, 1, 1)`;
        el.style.transition = 'transform 0.5s cubic-bezier(0.23, 1, 0.32, 1)';
        el.style.setProperty('--mouseX', '50%');
        el.style.setProperty('--mouseY', '50%');
      };
      
      el.addEventListener('mousemove', handleMouseMove);
      el.addEventListener('mouseleave', handleMouseLeave);
    });

    return () => {
      // Cleanups generally handled by page unmount since landing page is a full page
    };
  }, []);
}



export function useScrollReveal() {
  useEffect(() => {
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    
    if (reducedMotion) {
      document.querySelectorAll('.reveal-on-scroll').forEach(el => {
        el.classList.add('reveal-visible');
      });
      return;
    }

    const ctx = gsap.context(() => {
      const elements = document.querySelectorAll('.reveal-on-scroll');
      gsap.set(elements, { y: 30, opacity: 0 });

      ScrollTrigger.batch('.reveal-on-scroll', {
        onEnter: batch => gsap.to(batch, {
          opacity: 1, 
          y: 0, 
          stagger: 0.1, 
          duration: 0.8,
          ease: 'power3.out',
          overwrite: true
        }),
        onLeaveBack: batch => gsap.to(batch, {
          opacity: 0, 
          y: 30,
          duration: 0.4,
          overwrite: true
        }),
        start: "top 90%"
      });
    });

    return () => ctx.revert();
  }, []);
}

export function useHorizontalScroll() {
  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches || window.matchMedia('(pointer: coarse)').matches) {
      return;
    }

    const container = document.querySelector('.agents-horizontal-scroll') as HTMLElement;
    const wrapper = document.querySelector('.agents-horizontal-wrapper') as HTMLElement;
    if (!container || !wrapper) return;

    const ctx = gsap.context(() => {
      const getScrollAmount = () => {
        return -(wrapper.scrollWidth - window.innerWidth + 200); // 200px buffer
      };

      ScrollTrigger.create({
        trigger: container,
        start: 'top top',
        end: () => `+=${getScrollAmount() * -1}`,
        pin: true,
        animation: gsap.to(wrapper, {
          x: getScrollAmount,
          ease: 'none'
        }),
        scrub: 1,
        invalidateOnRefresh: true
      });
    });

    return () => ctx.revert();
  }, []);
}

export function useParallaxBackground() {
  useEffect(() => {
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reducedMotion) return;

    const ctx = gsap.context(() => {
      const bgs = document.querySelectorAll('.parallax-bg');
      bgs.forEach(bg => {
        gsap.to(bg, {
          yPercent: 30, // move it down as we scroll down
          ease: "none",
          scrollTrigger: {
            trigger: bg.parentElement,
            start: "top bottom",
            end: "bottom top",
            scrub: true
          }
        });
      });
    });

    return () => ctx.revert();
  }, []);
}
