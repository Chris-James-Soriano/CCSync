console.log("CCSynq loaded");

document.addEventListener("DOMContentLoaded", () => {
  const modal = document.getElementById("confirm-modal");
  if (!modal) return;

  const titleEl = document.getElementById("confirm-modal-title");
  const messageEl = document.getElementById("confirm-modal-message");
  const acceptBtn = document.getElementById("confirm-modal-accept");
  const cancelButtons = modal.querySelectorAll("[data-confirm-cancel]");
  let pendingTrigger = null;
  let lastFocused = null;

  const openModal = (trigger) => {
    lastFocused = document.activeElement;
    pendingTrigger = trigger;
    titleEl.textContent = trigger.getAttribute("data-confirm-title") || "Please confirm";
    messageEl.textContent = trigger.getAttribute("data-confirm") || "Are you sure?";
    acceptBtn.textContent = trigger.getAttribute("data-confirm-label") || "Confirm";
    modal.hidden = false;
    acceptBtn.focus();
  };

  const closeModal = () => {
    modal.hidden = true;
    pendingTrigger = null;
    if (lastFocused) lastFocused.focus();
  };

  document.addEventListener("click", (event) => {
    const trigger = event.target.closest("[data-confirm]");
    if (!trigger) return;
    event.preventDefault();
    openModal(trigger);
  });

  acceptBtn.addEventListener("click", () => {
    const trigger = pendingTrigger;
    closeModal();
    if (!trigger) return;
    if (trigger.tagName === "FORM") {
      trigger.submit();
    } else if (trigger.tagName === "A" && trigger.href) {
      window.location.assign(trigger.href);
    } else if (trigger.form) {
      trigger.form.submit();
    }
  });

  cancelButtons.forEach((button) => button.addEventListener("click", closeModal));

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !modal.hidden) closeModal();
  });
});
