# Example Ruby module for parser testing

class Calculator
  # Add two numbers
  def add(a, b)
    a + b
  end

  # Subtract two numbers
  def subtract(a, b)
    a - b
  end
end

# Multiply two floats
def multiply(x, y)
  x * y
end

# Divide two floats
def divide(x, y)
  if y == 0
    raise "Cannot divide by zero"
  end
  x / y
end
