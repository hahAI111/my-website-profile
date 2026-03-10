// ── Click Tracking ─────────────────────────────────────
document.addEventListener('click', (e) => {
  const tracked = e.target.closest('[data-track]');
  if (!tracked) return;

  const element = tracked.getAttribute('data-track');
  fetch('/api/track', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ element, page: window.location.pathname })
  }).catch(() => {});
});

// ── Contact Form ──────────────────────────────────────
const contactForm = document.getElementById('contactForm');
if (contactForm) {
  contactForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const status = document.getElementById('contactStatus');
    const btn = contactForm.querySelector('button');
    const message = document.getElementById('message').value.trim();

    if (!message) return;

    btn.disabled = true;
    btn.textContent = 'Sending...';
    status.textContent = '';
    status.className = 'status-msg';

    try {
      const res = await fetch('/api/contact', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message })
      });
      const data = await res.json();

      if (data.success) {
        status.textContent = 'Message sent! Thank you for your interest.';
        status.className = 'status-msg success';
        contactForm.reset();
      } else {
        status.textContent = data.error || 'Something went wrong.';
        status.className = 'status-msg error';
      }
    } catch {
      status.textContent = 'Network error. Please try again.';
      status.className = 'status-msg error';
    } finally {
      btn.disabled = false;
      btn.textContent = 'Send Message';
    }
  });
}

// ── Scroll Reveal ─────────────────────────────────────
const observer = new IntersectionObserver(
  (entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) entry.target.classList.add('visible');
    });
  },
  { threshold: 0.15 }
);

document.querySelectorAll('.skill-card, .about-text, .contact form, .stat').forEach((el) => {
  el.classList.add('fade-in');
  observer.observe(el);
});
