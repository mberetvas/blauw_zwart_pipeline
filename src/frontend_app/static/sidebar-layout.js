(function () {
  "use strict";

  var LS_SIDEBAR = "cb_chat_sidebar_collapsed";

  function updateSidebarToggleUi() {
    var shellEl = document.getElementById("shell");
    var sidebarToggle = document.getElementById("sidebar-toggle");
    var sidebarToggleIcon = document.getElementById("sidebar-toggle-icon");
    var sidebarEl = document.getElementById("app-sidebar");
    var collapsed = shellEl && shellEl.getAttribute("data-sidebar") === "collapsed";
    if (sidebarToggle) {
      sidebarToggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
      sidebarToggle.setAttribute(
        "aria-label",
        collapsed ? "Expand navigation sidebar" : "Collapse navigation sidebar"
      );
    }
    if (sidebarToggleIcon) {
      sidebarToggleIcon.textContent = collapsed ? "chevron_right" : "chevron_left";
    }
    if (sidebarEl) {
      var desktop = window.matchMedia("(min-width:768px)").matches;
      if (!desktop) {
        sidebarEl.setAttribute("aria-hidden", "true");
      } else {
        sidebarEl.setAttribute("aria-hidden", collapsed ? "true" : "false");
      }
    }
  }

  function initSidebarLayout() {
    var shellEl = document.getElementById("shell");
    var sidebarToggle = document.getElementById("sidebar-toggle");
    if (!shellEl) {
      return;
    }
    updateSidebarToggleUi();
    if (sidebarToggle) {
      sidebarToggle.addEventListener("click", function () {
        var collapsed = shellEl.getAttribute("data-sidebar") === "collapsed";
        var next = !collapsed;
        shellEl.setAttribute("data-sidebar", next ? "collapsed" : "expanded");
        try {
          localStorage.setItem(LS_SIDEBAR, next ? "1" : "0");
        } catch (_) {}
        updateSidebarToggleUi();
      });
    }
    window.matchMedia("(min-width:768px)").addEventListener("change", updateSidebarToggleUi);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initSidebarLayout);
  } else {
    initSidebarLayout();
  }
})();
