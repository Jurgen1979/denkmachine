/* denkmachine – client-side helpers */

document.addEventListener('DOMContentLoaded', function () {
  // globale laad-indicator: elke form-submit blokkeert de knop en toont een spinner
  document.addEventListener('submit', function (event) {
    var form = event.target;

    // zoek de submit-knop die nog niet uitgeschakeld is
    var knop = form.querySelector('button[type="submit"]:not([disabled])');
    if (!knop) knop = form.querySelector('button:not([type]):not([disabled])');
    if (!knop) return;

    var origTekst = knop.textContent.trim();
    knop.disabled = true;
    knop.style.display = 'inline-flex';
    knop.style.alignItems = 'center';
    knop.style.gap = '0.45rem';
    knop.innerHTML = '<span class="spinner-knop"></span>' + origTekst + '\u2026';
  });
});
