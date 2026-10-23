// workspace/calculator.js
document.addEventListener('DOMContentLoaded', () => {
  const display = document.querySelector('.display');
  let currentInput = '0';
  let previousInput = '';
  let operation = null;
  let resetDisplay = false;

  function updateDisplay() {
    display.textContent = currentInput;
  }

  function appendDigit(digit) {
    if (currentInput === '0' || resetDisplay) {
      currentInput = digit;
      resetDisplay = false;
    } else {
      currentInput += digit;
    }
    updateDisplay();
  }

  function appendDecimal() {
    if (resetDisplay) {
      currentInput = '0.';
      resetDisplay = false;
    } else if (!currentInput.includes('.')) {
      currentInput += '.';
    }
    updateDisplay();
  }

  function chooseOperation(op) {
    if (operation !== null && !resetDisplay) {
      compute();
    }
    previousInput = currentInput;
    operation = op;
    resetDisplay = true;
  }

  function compute() {
    if (operation === null || previousInput === '') return;
    const prev = parseFloat(previousInput);
    const curr = parseFloat(currentInput);
    let result = 0;

    switch (operation) {
      case '+':
        result = prev + curr;
        break;
      case '-':
        result = prev - curr;
        break;
      case '*':
        result = prev * curr;
        break;
      case '/':
        result = curr === 0 ? 'Error' : prev / curr;
        break;
      default:
        return;
    }

    currentInput = String(result);
    operation = null;
    previousInput = '';
    resetDisplay = true;
    updateDisplay();
  }

  function clear() {
    currentInput = '0';
    previousInput = '';
    operation = null;
    resetDisplay = false;
    updateDisplay();
  }

  function backspace() {
    if (resetDisplay) return;
    if (currentInput.length > 1) {
      currentInput = currentInput.slice(0, -1);
    } else {
      currentInput = '0';
    }
    updateDisplay();
  }

  document.querySelectorAll('.digit').forEach((btn) => {
    btn.addEventListener('click', () => appendDigit(btn.textContent.trim()));
  });

  document.querySelectorAll('.operator').forEach((btn) => {
    btn.addEventListener('click', () => chooseOperation(btn.textContent.trim()));
  });

  document.querySelector('.decimal')?.addEventListener('click', appendDecimal);
  document.querySelector('.clear')?.addEventListener('click', clear);
  document.querySelector('.backspace')?.addEventListener('click', backspace);
  document.querySelector('.equals')?.addEventListener('click', compute);

  window.addEventListener('keydown', (e) => {
    if (e.key >= '0' && e.key <= '9') appendDigit(e.key);
    else if (e.key === '.') appendDecimal();
    else if (['+', '-', '*', '/'].includes(e.key)) chooseOperation(e.key);
    else if (e.key === 'Enter' || e.key === '=') compute();
    else if (e.key === 'Backspace') backspace();
    else if (e.key === 'Escape' || e.key.toLowerCase() === 'c') clear();
  });
});
