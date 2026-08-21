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

  // ⌘C on Apple platforms, Ctrl+C everywhere else. navigator.platform is
  // deprecated but still the most widely supported signal; the modern
  // userAgentData.platform is preferred when the browser exposes it.
  function copyShortcut() {
    var platform = "";
    if (navigator.userAgentData && navigator.userAgentData.platform) {
      platform = navigator.userAgentData.platform;
    } else if (navigator.platform) {
      platform = navigator.platform;
    }
    return /mac|iphone|ipad|ipod/i.test(platform) ? "\u2318C" : "Ctrl+C";
  }

  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text);
    }
    // Pages is served over HTTPS, so this path is for local file:// previews.
    return new Promise(function (resolve, reject) {
      // Off-screen on both axes, not just vertically: a positive inline offset
      // on one axis can still widen the scroll area for the frame this exists.
      // tabindex -1 keeps it out of tab order.
      //
      // Deliberately not aria-hidden. select() below moves focus here, and
      // focusing an aria-hidden element is exactly the state that rule forbids.
      // The element is created, read and removed inside one synchronous block,
      // so it is never present at a point where assistive tech could reach it.
      var scratch = document.createElement("textarea");
      scratch.value = text;
      scratch.setAttribute("readonly", "");
      scratch.setAttribute("tabindex", "-1");
      scratch.style.position = "fixed";
      scratch.style.top = "-1000px";
      scratch.style.left = "-1000px";
      scratch.style.opacity = "0";
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
      // One attribute with one value, rather than two independent classes.
      // Two classes can both be set - a failed click followed by a successful
      // one inside the revert window did exactly that - and then the later
      // rule wins at equal specificity, colouring a successful copy as a
      // failure. A single value cannot contradict itself.
      clearTimeout(revert);
      delete button.dataset.state;

      // textContent, not innerText: innerText is the *rendered* text, so it
      // forces a reflow and can renormalise whitespace. Code must survive a
      // round trip byte for byte, and the <code> child is the code itself
      // without any wrapper the block might grow later.
      var source = pre.querySelector("code") || pre;
      copyText(source.textContent).then(function () {
        button.textContent = "Copied";
        button.dataset.state = "copied";
      }, function () {
        button.textContent = selectBlock() ? "Selected — press " + copyShortcut() : "Copy failed";
        button.dataset.state = "failed";
      }).then(function () {
        clearTimeout(revert);
        revert = setTimeout(function () {
          button.textContent = "Copy";
          delete button.dataset.state;
        }, 2000);
      });
    });

    bar.appendChild(button);
  });
})();
