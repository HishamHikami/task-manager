// Show the "Main contact" fields only when the holder type is a group
// (department, committee or outside party), not a single person.
(function () {
  var GROUP_KINDS = ["department", "committee", "external"];
  var PAIRS = [
    ["new_holder_kind", "new_holder_contact_person"],
    ["new_holder_kind", "new_holder_contact_role"],
  ];

  function sync(root) {
    PAIRS.forEach(function (pair) {
      (root || document).querySelectorAll('select[name="' + pair[0] + '"]').forEach(function (select) {
        var form = select.form;
        var target = form && form.querySelector('[data-field="' + pair[1] + '"]');
        if (target) target.hidden = GROUP_KINDS.indexOf(select.value) === -1;
      });
    });
  }

  document.addEventListener("change", function (e) {
    if (e.target.matches && e.target.matches('select[name="kind"], select[name="new_holder_kind"]')) sync(e.target.form);
  });
  document.addEventListener("DOMContentLoaded", function () { sync(); });
  // hx-boost swaps the page body; re-check after every swap and history restore.
  ["htmx:afterSettle", "htmx:historyRestore"].forEach(function (ev) {
    document.addEventListener(ev, function () { sync(); });
  });
})();
