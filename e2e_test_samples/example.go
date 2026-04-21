// Example Go module for parser testing
package main

import "fmt"

// Calculator struct
type Calculator struct{}

// Add two integers
func (c *Calculator) Add(a, b int) int {
  return a + b
}

// Subtract two integers
func (c *Calculator) Subtract(a, b int) int {
  return a - b
}

// Multiply two floats
func Multiply(x, y float64) float64 {
  return x * y
}

// Divide two floats
func Divide(x, y float64) (float64, error) {
  if y == 0 {
    return 0, fmt.Errorf("cannot divide by zero")
  }
  return x / y, nil
}
