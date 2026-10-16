/**
 * Multi-Agent Code Pipeline — Interactive Presentation Controller
 * Controls 16:9 Widescreen responsive scaling, animations, keyboard/touch navigation.
 */

document.addEventListener('DOMContentLoaded', () => {
  const slides = document.querySelectorAll('.slide');
  const totalSlides = slides.length;
  let currentSlideIndex = 0;
  let autoPlayInterval = null;
  const autoPlayDelay = 12000; // 12 seconds per slide in autoplay

  // DOM Elements
  const viewport = document.getElementById('presentation-viewport');
  const stage = document.getElementById('slide-stage');
  const btnPrev = document.getElementById('btn-prev');
  const btnNext = document.getElementById('btn-next');
  const btnFullscreen = document.getElementById('btn-fullscreen');
  const btnAutoplay = document.getElementById('btn-autoplay');
  const currentSlideNumEl = document.getElementById('current-slide-num');
  const totalSlidesNumEl = document.getElementById('total-slides-num');
  const dotsContainer = document.getElementById('slide-dots');
  const progressBar = document.getElementById('presentation-progress-bar');

  // Set total count
  totalSlidesNumEl.textContent = totalSlides < 10 ? `0${totalSlides}` : totalSlides;

  // -------------------------------------------------------------------------
  // 1. Dynamic 16:9 Widescreen Responsive Scaling
  // -------------------------------------------------------------------------
  function updateViewportScale() {
    const windowWidth = window.innerWidth;
    const windowHeight = window.innerHeight;

    // Canonical canvas size
    const baseWidth = 1920;
    const baseHeight = 1080;

    // Leave a small 20px margin around presentation if not in fullscreen
    const padding = document.fullscreenElement ? 0 : 20;
    const availWidth = windowWidth - padding;
    const availHeight = windowHeight - padding;

    const scaleX = availWidth / baseWidth;
    const scaleY = availHeight / baseHeight;
    const scale = Math.min(scaleX, scaleY);

    document.documentElement.style.setProperty('--scale-factor', scale.toString());
  }

  window.addEventListener('resize', updateViewportScale);
  updateViewportScale();

  // -------------------------------------------------------------------------
  // 2. Generate Slide Navigation Dots
  // -------------------------------------------------------------------------
  function renderDots() {
    dotsContainer.innerHTML = '';
    slides.forEach((slide, idx) => {
      const dot = document.createElement('div');
      dot.className = `slide-dot ${idx === currentSlideIndex ? 'active' : ''}`;
      dot.title = `Slide ${idx + 1}: ${slide.getAttribute('data-title') || ''}`;
      dot.addEventListener('click', () => goToSlide(idx));
      dotsContainer.appendChild(dot);
    });
  }
  renderDots();

  // -------------------------------------------------------------------------
  // 3. Slide Navigation Core Logic
  // -------------------------------------------------------------------------
  function goToSlide(newIndex) {
    if (newIndex < 0 || newIndex >= totalSlides) return;

    // Mark previous state for slide transition animations
    slides.forEach((s, idx) => {
      s.classList.remove('active', 'prev');
      if (idx < newIndex) {
        s.classList.add('prev');
      }
    });

    currentSlideIndex = newIndex;
    slides[currentSlideIndex].classList.add('active');

    // Update Indicators
    const num = currentSlideIndex + 1;
    currentSlideNumEl.textContent = num < 10 ? `0${num}` : num;

    // Update Dots
    const dots = dotsContainer.querySelectorAll('.slide-dot');
    dots.forEach((dot, idx) => {
      dot.classList.toggle('active', idx === currentSlideIndex);
    });

    // Update Top Progress Bar
    const progressPercent = ((currentSlideIndex + 1) / totalSlides) * 100;
    progressBar.style.width = `${progressPercent}%`;

    // Update URL hash
    window.location.hash = `slide-${currentSlideIndex + 1}`;
  }

  function nextSlide() {
    if (currentSlideIndex < totalSlides - 1) {
      goToSlide(currentSlideIndex + 1);
    } else if (autoPlayInterval) {
      // Loop back to start in autoplay mode
      goToSlide(0);
    }
  }

  function prevSlide() {
    if (currentSlideIndex > 0) {
      goToSlide(currentSlideIndex - 1);
    }
  }

  // Button Listeners
  btnNext.addEventListener('click', nextSlide);
  btnPrev.addEventListener('click', prevSlide);

  // -------------------------------------------------------------------------
  // 4. Keyboard Controls
  // -------------------------------------------------------------------------
  document.addEventListener('keydown', (e) => {
    // Avoid triggering when focused on inputs (if any)
    if (['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName)) return;

    switch (e.key) {
      case 'ArrowRight':
      case 'PageDown':
      case ' ': // Spacebar
      case 'l':
      case 'n':
        e.preventDefault();
        nextSlide();
        break;

      case 'ArrowLeft':
      case 'PageUp':
      case 'Backspace':
      case 'h':
      case 'p':
        e.preventDefault();
        prevSlide();
        break;

      case 'Home':
        e.preventDefault();
        goToSlide(0);
        break;

      case 'End':
        e.preventDefault();
        goToSlide(totalSlides - 1);
        break;

      case 'f':
      case 'F':
        e.preventDefault();
        toggleFullscreen();
        break;

      case 'a':
      case 'A':
        e.preventDefault();
        toggleAutoplay();
        break;
    }
  });

  // -------------------------------------------------------------------------
  // 5. Fullscreen Toggle
  // -------------------------------------------------------------------------
  function toggleFullscreen() {
    if (!document.fullscreenElement) {
      document.documentElement.requestFullscreen().catch(err => {
        console.warn(`Error attempting to enable fullscreen: ${err.message}`);
      });
      btnFullscreen.innerHTML = '<i class="fa-solid fa-compress"></i>';
    } else {
      document.exitFullscreen();
      btnFullscreen.innerHTML = '<i class="fa-solid fa-expand"></i>';
    }
    setTimeout(updateViewportScale, 100);
  }

  btnFullscreen.addEventListener('click', toggleFullscreen);

  document.addEventListener('fullscreenchange', () => {
    btnFullscreen.innerHTML = document.fullscreenElement
      ? '<i class="fa-solid fa-compress"></i>'
      : '<i class="fa-solid fa-expand"></i>';
    updateViewportScale();
  });

  // -------------------------------------------------------------------------
  // 6. Autoplay / Presentation Timer Mode
  // -------------------------------------------------------------------------
  function toggleAutoplay() {
    if (autoPlayInterval) {
      clearInterval(autoPlayInterval);
      autoPlayInterval = null;
      btnAutoplay.classList.remove('active');
      btnAutoplay.innerHTML = '<i class="fa-solid fa-play"></i> Auto';
    } else {
      autoPlayInterval = setInterval(nextSlide, autoPlayDelay);
      btnAutoplay.classList.add('active');
      btnAutoplay.innerHTML = '<i class="fa-solid fa-pause"></i> Auto (12s)';
    }
  }

  btnAutoplay.addEventListener('click', toggleAutoplay);

  // -------------------------------------------------------------------------
  // 7. Touch Swipe Support
  // -------------------------------------------------------------------------
  let touchStartX = 0;
  let touchEndX = 0;

  viewport.addEventListener('touchstart', (e) => {
    touchStartX = e.changedTouches[0].screenX;
  }, { passive: true });

  viewport.addEventListener('touchend', (e) => {
    touchEndX = e.changedTouches[0].screenX;
    handleSwipe();
  }, { passive: true });

  function handleSwipe() {
    const swipeThreshold = 50;
    if (touchEndX < touchStartX - swipeThreshold) {
      nextSlide(); // Swiped left -> next slide
    }
    if (touchEndX > touchStartX + swipeThreshold) {
      prevSlide(); // Swiped right -> prev slide
    }
  }

  // -------------------------------------------------------------------------
  // 8. Hash-based deep linking (e.g., #slide-3)
  // -------------------------------------------------------------------------
  function checkHash() {
    const hash = window.location.hash;
    if (hash && hash.startsWith('#slide-')) {
      const idx = parseInt(hash.replace('#slide-', ''), 10) - 1;
      if (!isNaN(idx) && idx >= 0 && idx < totalSlides) {
        goToSlide(idx);
      }
    }
  }
  checkHash();
});
