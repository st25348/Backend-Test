// scroll header
const nav = document.querySelector('nav');
window.addEventListener('scroll', () => {
    nav.classList.toggle('scrolled', window.scrollY > 50);
});

// back to top
const backToTop = document.getElementById('back-to-top');
window.addEventListener('scroll', () => {
    backToTop.classList.toggle('visible', window.scrollY > 300);
});
backToTop.addEventListener('click', () => {
    window.scrollTo({ top: 0, behavior: 'smooth' });
});

// Scroll restore
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

// Switch to register form
function switchToRegister() {
    document.getElementById('loginForm').classList.remove('active');
    document.getElementById('registerForm').classList.add('active');
}

// Switch to login form
function switchToLogin() {
    document.getElementById('registerForm').classList.remove('active');
    document.getElementById('loginForm').classList.add('active');
}