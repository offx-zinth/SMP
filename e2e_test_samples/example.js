// Example JavaScript module for parser testing
class Calculator {
  // Add two numbers
  add(a, b) {
    return a + b;
  }

  // Subtract two numbers
  subtract(a, b) {
    return a - b;
  }
}

// Multiply two numbers
function multiply(x, y) {
  return x * y;
}

// Divide two numbers
function divide(x, y) {
  if (y === 0) {
    throw new Error("Cannot divide by zero");
  }
  return x / y;
}

module.exports = { Calculator, multiply, divide };
