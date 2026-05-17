// ── Nav scroll shadow ──────────────────────────────────────────────
const nav = document.querySelector('nav');
window.addEventListener('scroll', () => {
    nav.classList.toggle('scrolled', window.scrollY > 50);
});

// ── Back to top ────────────────────────────────────────────────────
const backToTop = document.getElementById('back-to-top');
window.addEventListener('scroll', () => {
    backToTop.classList.toggle('visible', window.scrollY > 300);
});
backToTop.addEventListener('click', () => {
    window.scrollTo({ top: 0, behavior: 'smooth' });
});

// ── Scroll restore after form submit / remove ──────────────────────
if (document.querySelector('.products-grid')) {
    window.addEventListener('DOMContentLoaded', () => {
        const scrollY = sessionStorage.getItem('scrollY');
        if (scrollY !== null) {
            window.scrollTo({ top: parseInt(scrollY), behavior: 'instant' });
            sessionStorage.removeItem('scrollY');
        }
    });
    document.addEventListener('submit', () => {
        sessionStorage.setItem('scrollY', window.scrollY);
    });
    document.querySelectorAll('a[href*="remove_from_cart"]').forEach(link => {
        link.addEventListener('click', () => {
            sessionStorage.setItem('scrollY', window.scrollY);
        });
    });
}

// ── Overlay + panel helpers ────────────────────────────────────────
const overlay = document.getElementById('mainOverlay');

// Hide every panel, show only the requested one, open the overlay
function showPanel(name) {
    document.querySelectorAll('.overlay-panel').forEach(p => p.style.display = 'none');
    const panel = document.getElementById('panel-' + name);
    if (panel) panel.style.display = 'block';
    overlay.style.display = 'flex';
    document.body.style.overflow = 'hidden';
}

// Hide overlay and unlock scroll — only called from the Continue button after login
function dismissOverlay() {
    overlay.style.display = 'none';
    document.body.style.overflow = '';
}

// Aliases so HTML onclick attrs work
function switchToRegister() { showPanel('register'); }
function switchToLogin()     { showPanel('login'); }

// ── Boot logic ────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', function () {
    const isLoggedIn     = document.body.dataset.loggedIn === 'true';
    const reopenAuth     = document.body.dataset.reopenAuth; // 'login' | 'register' | ''
    const justLoggedIn   = sessionStorage.getItem('justLoggedIn');
    const justRegistered = sessionStorage.getItem('justRegistered');

    if (justLoggedIn) {
        // Just logged in → welcome panel, Continue button dismisses it
        sessionStorage.removeItem('justLoggedIn');
        showPanel('loggedin');

    } else if (reopenAuth) {
        // Form error → reopen correct panel so error message is visible
        showPanel(reopenAuth);

    } else if (!isLoggedIn) {
        // Logged out (fresh visit or just hit logout) → force login panel
        // No way to dismiss without logging in
        showPanel('login');

    } else if (justRegistered) {
        sessionStorage.removeItem('justRegistered');
        showPanel('login');
    }
    // Logged in, no special flag → overlay stays hidden, browse freely
});