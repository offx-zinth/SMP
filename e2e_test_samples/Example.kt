// Example Kotlin module for parser testing
class Calculator {
    // Add two numbers
    fun add(a: Int, b: Int): Int {
        return a + b
    }

    // Subtract two numbers
    fun subtract(a: Int, b: Int): Int {
        return a - b
    }
}

// Multiply two floats
fun multiply(x: Double, y: Double): Double {
    return x * y
}

// Divide two floats
fun divide(x: Double, y: Double): Double {
    if (y == 0.0) {
        throw IllegalArgumentException("Cannot divide by zero")
    }
    return x / y
}
