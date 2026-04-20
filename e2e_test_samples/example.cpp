// Example C++ module for parser testing
#include <iostream>
#include <stdexcept>

class Calculator {
public:
  // Add two numbers
  int add(int a, int b) {
    return a + b;
  }

  // Subtract two numbers
  int subtract(int a, int b) {
    return a - b;
  }
};

// Multiply two floats
double multiply(double x, double y) {
  return x * y;
}

// Divide two floats
double divide(double x, double y) {
  if (y == 0.0) {
    throw std::invalid_argument("Cannot divide by zero");
  }
  return x / y;
}
