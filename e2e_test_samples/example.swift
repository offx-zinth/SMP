// Example Swift module for parser testing
class Calculator {
    // Add two numbers
    func add(_ a: Int, _ b: Int) -> Int {
        return a + b
    }

    // Subtract two numbers
    func subtract(_ a: Int, _ b: Int) -> Int {
        return a - b
    }
}

// Multiply two floats
func multiply(_ x: Double, _ y: Double) -> Double {
    return x * y
}

// Divide two floats
func divide(_ x: Double, _ y: Double) throws -> Double {
    if y == 0 {
        throw NSError(domain: "MathError", code: 1, userInfo: ["message": "Cannot divide by zero"])
    }
    return x / y
}
