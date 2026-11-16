/* Select-all / Clear helpers for the Export checkbox groups. */
(function () {
  function setGroup(name, checked) {
    document
      .querySelectorAll('input[type="checkbox"][name="' + name + '"]')
      .forEach(function (box) {
        box.checked = checked;
      });
  }

  document.querySelectorAll("[data-select-all]").forEach(function (button) {
    button.addEventListener("click", function () {
      setGroup(button.dataset.selectAll, true);
    });
  });
  document.querySelectorAll("[data-clear]").forEach(function (button) {
    button.addEventListener("click", function () {
      setGroup(button.dataset.clear, false);
    });
  });
})();
