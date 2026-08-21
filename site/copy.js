/* Adds a copy button to every code block.
 *
 * The button is created here rather than written into the markup so the pages
 * stay readable as plain HTML, and so a browser with JavaScript disabled sees
 * the code exactly as before rather than a dead button it cannot use.
 */
(function () {
  "use strict";

  var blocks = document.querySelectorAll("main pre");
  if (!blocks.length || !document.body) return;

  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text);
    }
    // Pages is served over HTTPS, so this path is for local file:// previews.
    return new Promise(function (resolve, reject) {
      var scratch = document.createElement("textarea");
      scratch.value = text;
      scratch.setAttribute("readonly", "");
      scratch.style.position = "fixed";
      scratch.style.top = "-1000px";
      document.body.appendChild(scratch);
      scratch.select();
      var ok = false;
      try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
      document.body.removeChild(scratch);
      ok ? resolve() : reject(new Error("copy command rejected"));
    });
  }

  Array.prototype.forEach.call(blocks, function (pre) {
    var shell = document.createElement("div");
    shell.className = "code-block";
    pre.parentNode.insertBefore(shell, pre);

    // The button sits in a bar above the code rather than floating over it.
    // Install commands are long enough to scroll horizontally, and a floating
    // button hides the tail of the line the moment the user scrolls to read it.
    var bar = document.createElement("div");
    bar.className = "code-bar";
    shell.appendChild(bar);
    shell.appendChild(pre);

    var button = document.createElement("button");
    button.type = "button";
    button.className = "copy-btn";
    button.textContent = "Copy";
    // The visible label changes to "Copied"; the accessible name should not
    // silently change meaning, so it describes the action either way.
    button.setAttribute("aria-label", "Copy code to clipboard");

    // Both clipboard paths can be refused - a browser permission prompt that
    // was declined, or a hardened context. Selecting the block first makes the
    // fallback instruction true rather than merely encouraging: the user really
    // can press Ctrl+C at that point.
    function selectBlock() {
      var selection = window.getSelection();
      if (!selection) return false;
      var range = document.createRange();
      range.selectNodeContents(pre);
      selection.removeAllRanges();
      selection.addRange(range);
      return true;
    }

    var revert;
    button.addEventListener("click", function () {
      copyText(pre.innerText).then(function () {
        button.textContent = "Copied";
        button.classList.add("is-copied");
      }, function () {
        button.textContent = selectBlock() ? "Selected — press Ctrl+C" : "Copy failed";
        button.classList.add("is-failed");
      }).then(function () {
        clearTimeout(revert);
        revert = setTimeout(function () {
          button.textContent = "Copy";
          button.classList.remove("is-copied", "is-failed");
        }, 2000);
      });
    });

    bar.appendChild(button);
  });
})();
