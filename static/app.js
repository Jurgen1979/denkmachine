/* denkmachine – client-side helpers */

document.addEventListener('DOMContentLoaded', function () {
  /* laad-indicator voor formulieren die een llm-call triggeren */
  var forms = [
    { formId: 'nieuw-form',   knapId: 'submit-knop',   indicatorId: 'laad-indicator'   },
    { formId: 'verfijn-form', knapId: 'verfijn-knop',  indicatorId: 'verfijn-indicator' },
  ];

  forms.forEach(function (cfg) {
    var form = document.getElementById(cfg.formId);
    if (!form) return;

    form.addEventListener('submit', function () {
      var knop = document.getElementById(cfg.knapId);
      var indicator = document.getElementById(cfg.indicatorId);
      if (knop) knop.disabled = true;
      if (indicator) indicator.classList.add('zichtbaar');
    });
  });
});
