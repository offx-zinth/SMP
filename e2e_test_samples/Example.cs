// Example C# module for parser testing
using System;

public class Calculator {
  // Add two numbers
  public int Add(int a, int b) {
    return a + b;
  }

  // Subtract two numbers
  public int Subtract(int a, int b) {
    return a - b;
  }
}

// Math utilities
public class MathUtils {
  // Multiply two floats
  public static double Multiply(double x, double y) {
    return x * y;
  }

  // Divide two floats
  public static double Divide(double x, double y) {
    if (y == 0) {
      throw new ArgumentException("Cannot divide by zero");
    }
    return x / y;
  }
}
