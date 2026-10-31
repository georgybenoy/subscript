/**
 * Subscript Client Interaction Layer
 * Sidebar toggling, HTMX indicators, keyboard shortcuts, and UI helpers
 */

document.addEventListener('DOMContentLoaded', function () {
  // 1. Mobile Sidebar Toggle
  const sidebar = document.getElementById('appSidebar');
  const sidebarToggle = document.getElementById('sidebarToggle');
  const sidebarOverlay = document.getElementById('sidebarOverlay');

  if (sidebarToggle && sidebar && sidebarOverlay) {
    sidebarToggle.addEventListener('click', function () {
      sidebar.classList.toggle('show');
      sidebarOverlay.classList.toggle('show');
    });

    sidebarOverlay.addEventListener('click', function () {
      sidebar.classList.remove('show');
      sidebarOverlay.classList.remove('show');
    });
  }

  // 2. Global Keyboard Shortcut: Ctrl+K / Cmd+K to focus search
  const searchInput = document.getElementById('globalSearchInput');
  document.addEventListener('keydown', function (e) {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      if (searchInput) {
        searchInput.focus();
        searchInput.select();
      }
    }
  });

  // 3. HTMX Loading Indicators
  document.body.addEventListener('htmx:beforeRequest', function (event) {
    const target = event.detail.target;
    if (target && !target.classList.contains('no-htmx-spinner')) {
      target.style.opacity = '0.6';
      target.style.pointerEvents = 'none';
    }
  });

  document.body.addEventListener('htmx:afterOnLoad', function (event) {
    const target = event.detail.target;
    if (target) {
      target.style.opacity = '1';
      target.style.pointerEvents = 'auto';
    }
  });

  // 4. Form Submit Loading Feedback
  const subscriptForms = document.querySelectorAll('form[data-loading-indicator]');
  subscriptForms.forEach(function (form) {
    form.addEventListener('submit', function () {
      const btn = form.querySelector('button[type="submit"]');
      if (btn) {
        const originalText = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span> Processing...';
        setTimeout(function () {
          btn.disabled = false;
          btn.innerHTML = originalText;
        }, 8000); // safety fallback
      }
    });
  });
});
