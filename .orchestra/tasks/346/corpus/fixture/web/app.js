function openDeleteOrchModal() { // G346_R4_DEF
  return "open";
}

const deleteButton = document.querySelector("#delete-orch");
deleteButton.addEventListener("click", openDeleteOrchModal); // G346_R4_JS_CALLBACK

const helpText = "openDeleteOrchModal"; // G346_R4_NOISE_STRING
// openDeleteOrchModal is intentionally mentioned in a comment. // G346_R4_NOISE_COMMENT

