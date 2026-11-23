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

// Quick capture review: show only the fields for the chosen action.
(function () {
  function sync() {
    document.querySelectorAll("form.reviewform").forEach(function (form) {
      var checked = form.querySelector('input[name="action"]:checked');
      var action = checked ? checked.value : "";
      form.querySelectorAll(".when").forEach(function (el) {
        el.hidden = !el.classList.contains("when-" + action);
      });
      form.querySelectorAll(".radiocard").forEach(function (card) {
        card.classList.toggle("on", card.querySelector("input").checked);
      });
    });
  }
  document.addEventListener("change", function (e) {
    if (e.target.name === "action" && e.target.closest("form.reviewform")) sync();
  });
  document.addEventListener("DOMContentLoaded", sync);
  document.addEventListener("htmx:afterSwap", sync);
  document.addEventListener("htmx:afterSettle", sync);
})();

// Buttons that call the AI: show that something is happening (it takes a few seconds).
document.addEventListener("submit", function (e) {
  var btn = e.submitter;
  if (btn && btn.dataset.busy) {
    // Keep the button's name/value in the submission, then disable it.
    var hidden = document.createElement("input");
    hidden.type = "hidden"; hidden.name = btn.name; hidden.value = btn.value;
    if (btn.name) e.target.appendChild(hidden);
    setTimeout(function () { btn.disabled = true; btn.textContent = btn.dataset.busy; }, 0);
  }
});

// Installable app: service worker + "Install app" button when Chrome offers it.
(function () {
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(function () { /* not critical */ });
    });
  }
  var deferred = null;
  function buttons() { return document.querySelectorAll("#install-btn, [data-install]"); }
  function show(on) { buttons().forEach(function (b) { b.hidden = !on; }); }
  window.addEventListener("beforeinstallprompt", function (e) {
    e.preventDefault();
    deferred = e;
    show(true);
  });
  window.addEventListener("appinstalled", function () { deferred = null; show(false); });
  document.addEventListener("click", function (e) {
    var b = e.target.closest && e.target.closest("#install-btn, [data-install]");
    if (!b || !deferred) return;
    deferred.prompt();
    deferred.userChoice.finally(function () { deferred = null; show(false); });
  });
  document.addEventListener("htmx:afterSettle", function () { show(!!deferred); });
})();

// Chat-style Quick capture.
(function () {
  function thread() { return document.getElementById("thread"); }
  function scrollToEnd() {
    var t = thread();
    if (!t) return;
    var last = t.lastElementChild;
    if (last) last.scrollIntoView({ behavior: "smooth", block: "start" });
  }
  function grow(ta) {
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, window.innerHeight * 0.4) + "px";
  }
  function syncAI() {
    var form = document.querySelector("form.composer");
    if (!form) return;
    var sel = form.querySelector('select[name="workspace"]');
    var box = form.querySelector('input[name="use_ai"]');
    var hint = document.getElementById("ai-hint");
    if (!sel || !box || box.dataset.noKey === "1") return;
    var opt = sel.options[sel.selectedIndex];
    var allowed = opt && opt.dataset.ai === "1";
    if (!allowed) { box.dataset.was = box.checked ? "1" : "0"; box.checked = false; }
    else if (box.disabled && box.dataset.was === "1") { box.checked = true; }
    box.disabled = !allowed;
    if (hint) hint.textContent = allowed ? "" : "AI is off for " + opt.text + " — it will be saved without AI.";
  }
  function init() {
    var ta = document.getElementById("composer-text");
    if (!ta) return;
    var box = document.querySelector('form.composer input[name="use_ai"]');
    if (box && box.disabled) box.dataset.noKey = "1";
    grow(ta);
    syncAI();
    if (ta.value) ta.focus();
  }

  document.addEventListener("input", function (e) { if (e.target.id === "composer-text") grow(e.target); });
  document.addEventListener("change", function (e) {
    if (e.target.closest && e.target.closest("form.composer") && e.target.name === "workspace") syncAI();
  });
  document.addEventListener("keydown", function (e) {
    if (e.target.id === "composer-text" && e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      e.target.form.requestSubmit();
    }
  });

  // Show my message right away, then replace it with the server's copy when the reply arrives.
  document.addEventListener("htmx:beforeRequest", function (e) {
    var form = e.detail.elt;
    if (!form.matches || !form.matches("form.composer")) return;
    var ta = form.querySelector("textarea");
    if (!ta.value.trim()) { e.preventDefault(); return; }
    var msg = document.createElement("div");
    msg.className = "msg me pending";
    var bubble = document.createElement("div");
    bubble.className = "bubble";
    var body = document.createElement("div");
    body.className = "prewrap";
    body.textContent = ta.value.length > 420 ? ta.value.slice(0, 420) + "…" : ta.value;
    bubble.appendChild(body);
    msg.appendChild(bubble);
    thread().appendChild(msg);
    scrollToEnd();
  });
  document.addEventListener("htmx:beforeSwap", function (e) {
    if (e.detail.target && e.detail.target.id === "thread") {
      document.querySelectorAll("#thread .msg.pending").forEach(function (m) { m.remove(); });
    }
  });
  document.addEventListener("htmx:afterRequest", function (e) {
    var form = e.detail.elt;
    if (!form.matches || !form.matches("form.composer")) return;
    if (e.detail.successful) {
      var ta = form.querySelector("textarea");
      ta.value = "";
      grow(ta);
    } else {
      document.querySelectorAll("#thread .msg.pending").forEach(function (m) { m.remove(); });
      alert("Couldn't send — check your connection and try again.");
    }
  });
  document.addEventListener("htmx:afterSettle", function (e) {
    if (e.detail.target && e.detail.target.id === "thread") scrollToEnd();
  });

  // Discard a suggestion (and the message it answered).
  document.addEventListener("click", function (e) {
    var btn = e.target.closest && e.target.closest("[data-dismiss-msg]");
    if (!btn) return;
    var reply = btn.closest(".msg");
    var mine = reply.previousElementSibling;
    if (mine && mine.classList.contains("me")) mine.remove();
    reply.remove();
  });

  document.addEventListener("DOMContentLoaded", init);
  document.addEventListener("htmx:afterSwap", function (e) { if (e.detail.target === document.body) init(); });
})();
