/* Progressive enhancement: native disclosures and links work without JavaScript. */
(function () {
  "use strict";
  var root = document.querySelector("[data-formulation-practice]");
  if (!root || !window.HeureuxFlashcards) return;
  var answer = root.querySelector("[data-formulation-answer]");
  var controls = root.querySelector("[data-formulation-controls]");
  var previous = controls.querySelector("[data-flashcard-previous]");
  var next = controls.querySelector("[data-flashcard-next]");
  var previousUrl = root.dataset.previousUrl;
  var nextUrl = root.dataset.nextUrl;
  function navigate(url) {
    if (url && url.charAt(0) !== "#") window.location.assign(url);
  }
  answer.open = true;
  answer.querySelector("summary").hidden = true;
  controls.hidden = false;
  root.querySelector("[data-formulation-native-navigation]").hidden = true;
  previous.disabled = !previousUrl || previousUrl.charAt(0) === "#";
  next.disabled = !nextUrl || nextUrl.charAt(0) === "#";
  var deck = window.HeureuxFlashcards.create({
    root: root,
    onLeft: function () { navigate(previousUrl); },
    onRight: function () { navigate(nextUrl); }
  });
  previous.addEventListener("click", function () { navigate(previousUrl); });
  next.addEventListener("click", function () { navigate(nextUrl); });
  deck.reset();
})();
