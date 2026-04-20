// Example C module for parser testing
#include <stdlib.h>
#include <stdio.h>

// Add two integers
int add(int a, int b) {
  return a + b;
}

// Subtract two integers
int subtract(int a, int b) {
  return a - b;
}

// Multiply two floats
double multiply(double x, double y) {
  return x * y;
}

// Divide two floats
double divide(double x, double y) {
  if (y == 0.0) {
    printf("Error: Cannot divide by zero\n");
    exit(1);
  }
  return x / y;
}
