// Keep what was typed in a form while the user goes to add a new
// department/person, and fill it back in when they return.
(function () {
  var SKIP = { csrfmiddlewaretoken: 1, current_holder: 1, to_holder: 1 };

  function keyFor(form) {
    return "draft:" + (form.getAttribute("action") || location.pathname);
  }

  document.addEventListener("click", function (e) {
    var link = e.target.closest && e.target.closest("[data-keep-draft]");
    if (!link) return;
    var form = link.closest("form");
    if (!form) return;
    var data = {};
    Array.prototype.forEach.call(form.elements, function (el) {
      if (!el.name || SKIP[el.name] || el.type === "submit") return;
      data[el.name] = el.type === "checkbox" ? el.checked : el.value;
    });
    try { sessionStorage.setItem(keyFor(form), JSON.stringify(data)); } catch (err) { /* storage off */ }
  }, true);

  function restore() {
    // Only when coming back with a newly added department/person selected.
    if (!/[?&](holder|contact)=\d+/.test(location.search)) return;
    document.querySelectorAll("form").forEach(function (form) {
      var key = keyFor(form), raw = null;
      try { raw = sessionStorage.getItem(key); } catch (err) { return; }
      if (!raw) return;
      var data = JSON.parse(raw);
      Object.keys(data).forEach(function (name) {
        var el = form.elements[name];
        if (!el || el.length > 1 && !el.tagName) return;
        if (el.type === "checkbox") el.checked = data[name]; else el.value = data[name];
      });
      try { sessionStorage.removeItem(key); } catch (err) { /* ignore */ }
    });
  }

  document.addEventListener("DOMContentLoaded", restore);
  document.addEventListener("htmx:afterSettle", restore);
})();

// Adding a Person: the Department choice appears only for type Person, and
// Role / Main contact only once a department is picked.
(function () {
  function sync() {
    document.querySelectorAll('select[name="kind"]').forEach(function (kind) {
      var form = kind.form;
      var dept = form && form.querySelector('[data-field="department"]');
      if (!dept) return;
      var isPerson = kind.value === "person";
      dept.hidden = !isPerson;
      var deptSelect = dept.querySelector("select");
      var inDept = isPerson && deptSelect && deptSelect.value !== "";
      ["role", "is_primary"].forEach(function (name) {
        var f = form.querySelector('[data-field="' + name + '"]');
        if (f) f.hidden = !inDept;
      });
    });
  }
  document.addEventListener("change", function (e) {
    if (e.target.matches && e.target.matches('select[name="kind"], select[name="department"]')) sync();
  });
  document.addEventListener("DOMContentLoaded", sync);
  document.addEventListener("htmx:afterSwap", sync);
  document.addEventListener("htmx:afterSettle", sync);
})();

// Events: "My topic" and speaking time only matter when I'm presenting.
(function () {
  var PRESENTING = ["host", "speaker", "panelist", "moderator", "trainer"];
  function sync() {
    document.querySelectorAll('form.eventform select[name="my_role"]').forEach(function (select) {
      var presenting = PRESENTING.indexOf(select.value) !== -1;
      ["my_topic", "duration_minutes"].forEach(function (name) {
        var f = select.form.querySelector('[data-field="' + name + '"]');
        if (f) f.hidden = !presenting;
      });
    });
  }
  document.addEventListener("change", function (e) {
    if (e.target.matches && e.target.matches('form.eventform select[name="my_role"]')) sync();
  });
  document.addEventListener("DOMContentLoaded", sync);
  document.addEventListener("htmx:afterSwap", sync);
  document.addEventListener("htmx:afterSettle", sync);
})();

// "I'm doing it" means the task is on my own desk: hide "Currently with".
(function () {
  function sync() {
    document.querySelectorAll('select[name="my_role"]').forEach(function (select) {
      var field = select.form && select.form.querySelector('[data-field="current_holder"]');
      if (field) field.hidden = select.value === "executing";
    });
  }
  document.addEventListener("change", function (e) {
    if (e.target.matches && e.target.matches('select[name="my_role"]')) sync();
  });
  document.addEventListener("DOMContentLoaded", sync);
  document.addEventListener("htmx:afterSwap", sync);
  document.addEventListener("htmx:afterSettle", sync);
})();

// One-click copy for phone numbers and email addresses.
(function () {
  function fallbackCopy(text) {
    var ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    var ok = false;
    try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
    document.body.removeChild(ta);
    return ok ? Promise.resolve() : Promise.reject();
  }

  document.addEventListener("click", function (e) {
    var btn = e.target.closest && e.target.closest(".copybtn");
    if (!btn) return;
    e.preventDefault();
    var text = btn.getAttribute("data-copy") || "";
    var copy = navigator.clipboard && window.isSecureContext
      ? navigator.clipboard.writeText(text).catch(function () { return fallbackCopy(text); })
      : fallbackCopy(text);
    copy.then(function () {
      btn.classList.add("copied");
      clearTimeout(btn._copiedTimer);
      btn._copiedTimer = setTimeout(function () { btn.classList.remove("copied"); }, 1500);
    }, function () {
      window.prompt("Copy this:", text);
    });
  });
})();
