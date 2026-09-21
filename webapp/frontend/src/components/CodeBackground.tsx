import { useEffect, useRef } from 'react';
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';

gsap.registerPlugin(ScrollTrigger);

const CODE_SNIPPET = `// Planner Agent
export async function orchestrateTask(userRequest: string) {
  const plan = await planner.invoke({ input: userRequest });
  
  for (const step of plan.steps) {
    if (step.type === 'db_migration') {
      await dbAgent.execute(step);
    } else if (step.type === 'code_gen') {
      const context = await ragAgent.retrieve(step.contextQuery);
      const code = await codegenAgent.generate(step.prompt, context);
      const passed = await reviewerAgent.review(code);
      if (!passed) throw new Error('Review failed');
    }
  }
}

// RAG Agent
function retrieveContext(query: string) {
  const vectorStore = Chroma.fromExistingCollection(embeddings);
  return vectorStore.similaritySearch(query, 4);
}

// Reviewer Agent
const reviewCode = async (code: string) => {
  const linterResult = runLinter(code);
  const astResult = analyzeAST(code);
  return linterResult.valid && astResult.secure;
};
`;

export default function CodeBackground() {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    
    const ctx = gsap.context(() => {
      gsap.to(containerRef.current, {
        y: '-10%',
        ease: 'none',
        scrollTrigger: {
          trigger: document.body,
          start: 'top top',
          end: 'bottom bottom',
          scrub: 1
        }
      });
    }, containerRef);
    
    return () => ctx.revert();
  }, []);

  return (
    <div className="code-background-overlay" ref={containerRef}>
      <style>{`
        .code-background-overlay {
          position: fixed;
          top: 0;
          left: 0;
          width: 100vw;
          height: 120vh;
          z-index: 0;
          pointer-events: none;
          opacity: 0.08;
          overflow: hidden;
          font-family: 'Consolas', 'Courier New', monospace;
          font-size: 16px;
          line-height: 1.8;
          color: #0066b1;
          padding: 48px;
          white-space: pre-wrap;
          mask-image: linear-gradient(to bottom, black 10%, transparent 90%);
          -webkit-mask-image: linear-gradient(to bottom, black 10%, transparent 90%);
        }
      `}</style>
      {CODE_SNIPPET.repeat(8)}
    </div>
  );
}
