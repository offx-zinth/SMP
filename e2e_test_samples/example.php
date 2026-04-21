<?php
// Example PHP module for parser testing

class Calculator {
    // Add two numbers
    public function add($a, $b) {
        return $a + $b;
    }

    // Subtract two numbers
    public function subtract($a, $b) {
        return $a - $b;
    }
}

// Multiply two floats
function multiply($x, $y) {
    return $x * $y;
}

// Divide two floats
function divide($x, $y) {
    if ($y == 0) {
        throw new Exception("Cannot divide by zero");
    }
    return $x / $y;
}
?>
