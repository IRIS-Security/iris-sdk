(function () {
  var sidebar = document.getElementById('docs-sidebar-inner');
  if (!sidebar) return;
  fetch('assets/docs-nav.html')
    .then(function (r) { return r.text(); })
    .then(function (html) {
      sidebar.innerHTML = html;
      var page = document.body.getAttribute('data-page');
      if (page) {
        var link = sidebar.querySelector('[data-page="' + page + '"]');
        if (link) link.classList.add('active');
      }
    })
    .catch(function () {
      sidebar.innerHTML = '<p style="padding:1rem;font-size:12px;color:#666">Nav failed to load.</p>';
    });
})();
