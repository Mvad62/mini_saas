const questionList = document.querySelector("[data-questions]");
const questionTemplate = document.querySelector("#question-template");

if (questionList && questionTemplate) {
  const updateQuestion = (question, index) => {
    question.querySelector("[data-question-number]").textContent = String(index + 1);
    question.querySelectorAll("[data-field]").forEach((field) => {
      const fieldName = field.dataset.field;
      field.name = `question_${index}_${fieldName}`;
      if (fieldName !== "required") {
        field.id = `question-${index}-${fieldName}`;
      }
    });
    question.querySelectorAll("[data-label-for]").forEach((label) => {
      label.htmlFor = `question-${index}-${label.dataset.labelFor}`;
    });

    const typeSelect = question.querySelector('[data-field="type"]');
    const optionFields = question.querySelector("[data-option-fields]");
    const options = question.querySelector('[data-field="options"]');
    const needsOptions = typeSelect.value !== "text";
    optionFields.hidden = !needsOptions;
    options.disabled = !needsOptions;
  };

  const updateQuestions = () => {
    questionList.querySelectorAll("[data-question]").forEach(updateQuestion);
  };

  questionList.addEventListener("click", (event) => {
    const removeButton = event.target.closest("[data-remove-question]");
    if (removeButton) {
      removeButton.closest("[data-question]").remove();
      updateQuestions();
      return;
    }

    const addOptionButton = event.target.closest("[data-add-option]");
    const removeOptionButton = event.target.closest("[data-remove-option]");
    const optionButton = addOptionButton || removeOptionButton;
    if (optionButton) {
      const options = optionButton
        .closest("[data-question]")
        .querySelector('[data-field="options"]');
      const lines = options.value.split("\n");
      if (addOptionButton) {
        if (options.value) {
          options.value += "\n";
        }
      } else if (lines.length > 0) {
        lines.pop();
        options.value = lines.join("\n");
      }
      options.focus();
    }
  });

  questionList.addEventListener("change", (event) => {
    if (event.target.matches('[data-field="type"]')) {
      updateQuestions();
    }
  });

  document.querySelector("[data-add-question]").addEventListener("click", () => {
    questionList.append(questionTemplate.content.cloneNode(true));
    updateQuestions();
    questionList.lastElementChild.querySelector('[data-field="text"]').focus();
  });

  updateQuestions();
}
