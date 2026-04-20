// Example Rust module for parser testing
pub struct Calculator;

impl Calculator {
    /// Add two numbers
    pub fn add(a: i32, b: i32) -> i32 {
        a + b
    }

    /// Subtract two numbers
    pub fn subtract(a: i32, b: i32) -> i32 {
        a - b
    }
}

/// Multiply two floats
pub fn multiply(x: f64, y: f64) -> f64 {
    x * y
}

/// Divide two floats
pub fn divide(x: f64, y: f64) -> Result<f64, String> {
    if y == 0.0 {
        Err("Cannot divide by zero".to_string())
    } else {
        Ok(x / y)
    }
}
