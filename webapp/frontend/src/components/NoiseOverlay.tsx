export default function NoiseOverlay() {
  return (
    <>
      <style>{`
        .noise-overlay {
          position: fixed;
          top: 0;
          left: 0;
          width: 100vw;
          height: 100vh;
          pointer-events: none;
          z-index: 9999;
          opacity: 0.04;
          background: url('data:image/svg+xml;utf8,%3Csvg viewBox="0 0 200 200" xmlns="http://www.w3.org/2000/svg"%3E%3Cfilter id="noiseFilter"%3E%3CfeTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves="3" stitchTiles="stitch"/%3E%3C/filter%3E%3Crect width="100%25" height="100%25" filter="url(%23noiseFilter)"/%3E%3C/svg%3E');
          animation: noise-shift 0.2s infinite;
        }

        @keyframes noise-shift {
          0% { transform: translate(0, 0); }
          10% { transform: translate(-1%, -1%); }
          20% { transform: translate(-2%, 1%); }
          30% { transform: translate(1%, -2%); }
          40% { transform: translate(-1%, 2%); }
          50% { transform: translate(-2%, -1%); }
          60% { transform: translate(2%, 1%); }
          70% { transform: translate(1%, -1%); }
          80% { transform: translate(-1%, -2%); }
          90% { transform: translate(2%, -1%); }
          100% { transform: translate(1%, 2%); }
        }
      `}</style>
      <div className="noise-overlay" />
    </>
  );
}
