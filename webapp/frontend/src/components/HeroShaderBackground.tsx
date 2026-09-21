import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';

const fragmentShader = `
uniform float uTime;
uniform vec2 uMouse;
uniform vec2 uResolution;
varying vec2 vUv;

// Simple 2D noise
float hash(vec2 p) { return fract(1e4 * sin(17.0 * p.x + p.y * 0.1) * (0.1 + abs(sin(p.y * 13.0 + p.x)))); }
float noise(vec2 x) {
    vec2 i = floor(x);
    vec2 f = fract(x);
    float a = hash(i);
    float b = hash(i + vec2(1.0, 0.0));
    float c = hash(i + vec2(0.0, 1.0));
    float d = hash(i + vec2(1.0, 1.0));
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(a, b, u.x) + (c - a) * u.y * (1.0 - u.x) + (d - b) * u.x * u.y;
}

void main() {
    vec2 uv = gl_FragCoord.xy / uResolution.xy;
    
    // Parallax offset from mouse
    vec2 offset = uMouse * 0.05;
    uv += offset;
    
    // Smooth flowing field
    float n1 = noise(uv * 2.0 + uTime * 0.1);
    float n2 = noise(uv * 4.0 - uTime * 0.15);
    float n = (n1 + n2) * 0.5;
    
    // Colors
    vec3 c1 = vec3(0.0, 0.4, 0.69); // #0066b1
    vec3 c2 = vec3(0.11, 0.41, 0.83); // #1c69d4
    vec3 c3 = vec3(0.88, 0.15, 0.09); // #e22718
    
    vec3 color = mix(c1, c2, n);
    color = mix(color, c3, noise(uv * 3.0 + uTime * 0.2) * 0.5);
    
    // Mask to black
    float mask = smoothstep(0.2, 0.8, n);
    vec3 finalColor = mix(vec3(0.0), color, mask * 0.3); // Kept dark for text legibility
    
    gl_FragColor = vec4(finalColor, 1.0);
}
`;

const vertexShader = `
varying vec2 vUv;
void main() {
    vUv = uv;
    gl_Position = vec4(position, 1.0);
}
`;

export default function HeroShaderBackground() {
  const mountRef = useRef<HTMLDivElement>(null);
  const [useFallback, setUseFallback] = useState(false);

  useEffect(() => {
    // Check reduced motion or WebGL failure
    const canvas = document.createElement('canvas');
    const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
    if (!gl || window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setUseFallback(true);
      return;
    }

    if (!mountRef.current) return;

    const width = mountRef.current.clientWidth;
    const height = mountRef.current.clientHeight;

    const scene = new THREE.Scene();
    const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, 10);
    camera.position.z = 1;

    const renderer = new THREE.WebGLRenderer({ alpha: false, antialias: false });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    mountRef.current.appendChild(renderer.domElement);

    const uniforms = {
      uTime: { value: 0 },
      uMouse: { value: new THREE.Vector2(0, 0) },
      uResolution: { value: new THREE.Vector2(width, height) }
    };

    const material = new THREE.ShaderMaterial({
      vertexShader,
      fragmentShader,
      uniforms,
      depthWrite: false,
      depthTest: false
    });

    const plane = new THREE.PlaneGeometry(2, 2);
    const mesh = new THREE.Mesh(plane, material);
    scene.add(mesh);

    let reqId: number;
    let time = 0;
    
    const animate = () => {
      reqId = requestAnimationFrame(animate);
      time += 0.01;
      uniforms.uTime.value = time;
      renderer.render(scene, camera);
    };

    const handleMouseMove = (e: MouseEvent) => {
      // Normalized mouse coords (-1 to +1)
      const nx = (e.clientX / window.innerWidth) * 2 - 1;
      const ny = -(e.clientY / window.innerHeight) * 2 + 1;
      // Lerp mouse towards target to keep it smooth
      uniforms.uMouse.value.x += (nx - uniforms.uMouse.value.x) * 0.1;
      uniforms.uMouse.value.y += (ny - uniforms.uMouse.value.y) * 0.1;
    };

    const handleResize = () => {
      if (!mountRef.current) return;
      const w = window.innerWidth;
      const h = window.innerHeight;
      renderer.setSize(w, h);
      uniforms.uResolution.value.set(w, h);
    };

    window.addEventListener('resize', handleResize);
    window.addEventListener('mousemove', handleMouseMove);
    animate();

    return () => {
      cancelAnimationFrame(reqId);
      window.removeEventListener('resize', handleResize);
      window.removeEventListener('mousemove', handleMouseMove);
      if (mountRef.current && renderer.domElement) {
        mountRef.current.removeChild(renderer.domElement);
      }
      renderer.dispose();
      material.dispose();
      plane.dispose();
    };
  }, []);

  if (useFallback) {
    return (
      <div 
        style={{ 
          width: '100vw', 
          height: '100vh', 
          position: 'absolute', 
          top: 0, 
          left: 0, 
          zIndex: -1,
          background: 'radial-gradient(circle at 50% 50%, #0d0d0d 0%, #000000 100%)' 
        }} 
      />
    );
  }

  return (
    <div 
      ref={mountRef} 
      style={{ 
        width: '100vw', 
        height: '100vh', 
        position: 'absolute', 
        top: 0, 
        left: 0, 
        zIndex: -1,
        pointerEvents: 'none'
      }} 
    />
  );
}
