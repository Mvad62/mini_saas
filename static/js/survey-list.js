document.querySelectorAll("[data-copy-url]").forEach((button) => {
  button.addEventListener("click", async () => {
    const status = button.parentElement.querySelector("[data-copy-status]");
    try {
      await navigator.clipboard.writeText(button.dataset.copyUrl);
      status.textContent = "Ссылка скопирована.";
    } catch (error) {
      status.textContent = "Не удалось скопировать ссылку. Выделите её и скопируйте вручную.";
      console.error("Could not copy the survey link.", error);
    }
  });
});
