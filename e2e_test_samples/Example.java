// Example Java module for parser testing
public class Calculator {
  // Add two numbers
  public int add(int a, int b) {
    return a + b;
  }

  // Subtract two numbers
  public int subtract(int a, int b) {
    return a - b;
  }
}

// Multiply two numbers
public class MathUtils {
  public static double multiply(double x, double y) {
    return x * y;
  }

  // Divide two numbers
  public static double divide(double x, double y) {
    if (y == 0) {
      throw new IllegalArgumentException("Cannot divide by zero");
    }
    return x / y;
  }
}
