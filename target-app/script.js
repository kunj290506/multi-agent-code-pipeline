// Generate script.js — all interactivity and logic for: make calclutor web app
// Generated in offline mode — implements calculator logic.

(function () {
  'use strict';

  let expression = '';
  let justCalculated = false;

  function updateDisplay(value) {
    const display = document.getElementById('display');
    if (display) display.textContent = value || '0';
  }

  window.appendToDisplay = function (value) {
    // After a result, start a fresh expression unless appending an operator.
    if (justCalculated) {
      if (['+', '-', '*', '/'].includes(value)) {
        justCalculated = false;
      } else {
        expression = '';
        justCalculated = false;
      }
    }
    // Prevent double operators.
    const lastChar = expression.slice(-1);
    if (['+', '-', '*', '/'].includes(lastChar) && ['+', '-', '*', '/'].includes(value)) {
      expression = expression.slice(0, -1);
    }
    expression += value;
    updateDisplay(expression);
  };

  window.clearDisplay = function () {
    expression = '';
    justCalculated = false;
    updateDisplay('0');
  };

  window.calculate = function () {
    if (!expression) return;
    try {
      // Use Function constructor to safely evaluate arithmetic only.
      const sanitised = expression.replace(/[^0-9+\-*/().]/g, '');
      // eslint-disable-next-line no-new-func
      const result = Function('"use strict"; return (' + sanitised + ')')();
      if (!isFinite(result)) {
        updateDisplay('Error');
        expression = '';
      } else {
        const formatted = parseFloat(result.toFixed(10)).toString();
        updateDisplay(formatted);
        expression = formatted;
        justCalculated = true;
      }
    } catch (err) {
      updateDisplay('Error');
      expression = '';
    }
  };

  // Keyboard support.
  document.addEventListener('keydown', function (e) {
    if (e.key >= '0' && e.key <= '9') window.appendToDisplay(e.key);
    else if (e.key === '+') window.appendToDisplay('+');
    else if (e.key === '-') window.appendToDisplay('-');
    else if (e.key === '*') window.appendToDisplay('*');
    else if (e.key === '/') { e.preventDefault(); window.appendToDisplay('/'); }
    else if (e.key === '.') window.appendToDisplay('.');
    else if (e.key === 'Enter' || e.key === '=') window.calculate();
    else if (e.key === 'Escape' || e.key === 'c' || e.key === 'C') window.clearDisplay();
    else if (e.key === 'Backspace') {
      expression = expression.slice(0, -1);
      updateDisplay(expression || '0');
    }
  });
})();
