// Example TypeScript module for parser testing
interface Addable {
  value: number;
}

class Calculator {
  // Add two numbers
  add(a: number, b: number): number {
    return a + b;
  }

  // Subtract two numbers
  subtract(a: number, b: number): number {
    return a - b;
  }
}

// Multiply two numbers
function multiply(x: number, y: number): number {
  return x * y;
}

// Divide two numbers
function divide(x: number, y: number): number {
  if (y === 0) {
    throw new Error("Cannot divide by zero");
  }
  return x / y;
}

export { Calculator, multiply, divide };
