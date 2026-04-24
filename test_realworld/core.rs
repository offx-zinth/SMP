// E-Commerce Platform - Rust Core Services
// Real-world Rust implementation with performance-critical operations

use std::collections::HashMap;

// ============================================================================
// DATA STRUCTURES
// ============================================================================

#[derive(Debug, Clone)]
pub struct OrderMetrics {
    pub order_id: String,
    pub processing_time: u64,
    pub cache_hits: u32,
    pub operations: u32,
}

#[derive(Debug)]
pub struct ComputeResult {
    pub value: f64,
    pub operations_count: u32,
}

// ============================================================================
// CORE CALCULATION FUNCTIONS (LEVEL 1)
// ============================================================================

/// Calculate price with bulk discount applied
pub fn calculate_bulk_discount(unit_price: f64, quantity: u32) -> f64 {
    if quantity >= 100 {
        unit_price * 0.15
    } else if quantity >= 50 {
        unit_price * 0.10
    } else if quantity >= 10 {
        unit_price * 0.05
    } else {
        unit_price
    }
}

/// Round price to nearest cent
pub fn round_to_cents(price: f64) -> f64 {
    (price * 100.0).round() / 100.0
}

/// Apply VAT (Value Added Tax)
pub fn apply_vat(price: f64, vat_rate: f64) -> f64 {
    price * (1.0 + vat_rate)
}

/// Calculate handling fee based on volume
pub fn calculate_handling_fee(volume_cm3: f64) -> f64 {
    if volume_cm3 > 10000.0 {
        50.0
    } else if volume_cm3 > 5000.0 {
        25.0
    } else {
        10.0
    }
}

/// Calculate insurance cost
pub fn calculate_insurance(value: f64, risk_level: u8) -> f64 {
    let base_rate = match risk_level {
        1 => 0.005,
        2 => 0.010,
        3 => 0.015,
        _ => 0.020,
    };
    value * base_rate
}

/// Validate price range
pub fn validate_price_range(price: f64) -> bool {
    price > 0.0 && price < 1_000_000.0
}

/// Format price with currency symbol
pub fn format_price(price: f64, currency: &str) -> String {
    match currency {
        "USD" => format!("${:.2}", price),
        "EUR" => format!("€{:.2}", price),
        "GBP" => format!("£{:.2}", price),
        _ => format!("{:.2} {}", price, currency),
    }
}

// ============================================================================
// CACHING LAYER (LEVEL 2 - depends on Level 1)
// ============================================================================

pub struct PriceCache {
    cache: HashMap<String, f64>,
    hits: u32,
}

impl PriceCache {
    pub fn new() -> Self {
        PriceCache {
            cache: HashMap::new(),
            hits: 0,
        }
    }

    pub fn get_cached_price(&mut self, product_id: &str, quantity: u32) -> Option<f64> {
        let key = format!("{}_{}", product_id, quantity);
        if let Some(&price) = self.cache.get(&key) {
            self.hits += 1;
            return Some(price);
        }
        None
    }

    pub fn cache_price(&mut self, product_id: &str, quantity: u32, price: f64) {
        let key = format!("{}_{}", product_id, quantity);
        self.cache.insert(key, price);
    }

    /// Get cached price or calculate (calls Level 1)
    pub fn get_price(&mut self, product_id: &str, base_price: f64, quantity: u32) -> f64 {
        if let Some(cached) = self.get_cached_price(product_id, quantity) {
            return cached;
        }

        let discounted = calculate_bulk_discount(base_price, quantity);
        let rounded = round_to_cents(discounted);
        self.cache_price(product_id, quantity, rounded);
        rounded
    }
}

// ============================================================================
// AGGREGATION LAYER (LEVEL 3 - calls Level 1 & 2)
// ============================================================================

/// Calculate complete order price (diamond pattern)
pub fn calculate_order_cost(
    base_price: f64,
    quantity: u32,
    volume_cm3: f64,
    vat_rate: f64,
    risk_level: u8,
) -> ComputeResult {
    let mut ops = 0;

    // Apply discount (Level 1)
    let discounted = calculate_bulk_discount(base_price, quantity);
    ops += 1;

    // Round (Level 1)
    let rounded = round_to_cents(discounted);
    ops += 1;

    // Apply handling (Level 1)
    let handling = calculate_handling_fee(volume_cm3);
    ops += 1;

    // Calculate insurance (Level 1)
    let insurance = calculate_insurance(rounded, risk_level);
    ops += 1;

    // Subtotal before tax
    let subtotal = rounded + handling + insurance;
    ops += 1;

    // Apply VAT (Level 1)
    let total_with_vat = apply_vat(subtotal, vat_rate);
    ops += 1;

    // Final rounding (Level 1)
    let final_total = round_to_cents(total_with_vat);
    ops += 1;

    ComputeResult {
        value: final_total,
        operations_count: ops,
    }
}

// ============================================================================
// BATCH PROCESSING (LEVEL 4 - complex aggregation)
// ============================================================================

pub fn process_batch_orders(
    orders: Vec<(f64, u32, f64)>,
    vat_rate: f64,
) -> Vec<ComputeResult> {
    orders
        .into_iter()
        .map(|(price, qty, volume)| calculate_order_cost(price, qty, volume, vat_rate, 2))
        .collect()
}

/// Calculate batch statistics
pub fn calculate_batch_statistics(results: &[ComputeResult]) -> (f64, f64, f64) {
    if results.is_empty() {
        return (0.0, 0.0, 0.0);
    }

    let total: f64 = results.iter().map(|r| r.value).sum();
    let count = results.len() as f64;
    let average = total / count;

    let max = results
        .iter()
        .map(|r| r.value)
        .fold(f64::NEG_INFINITY, f64::max);

    (average, max, total)
}

// ============================================================================
// OPTIMIZATION & PERF (LEVEL 5 - calls Level 3, 4)
// ============================================================================

/// Vectorized price calculation with SIMD optimization
pub fn calculate_prices_vectorized(prices: &[f64], quantities: &[u32]) -> Vec<f64> {
    prices
        .iter()
        .zip(quantities.iter())
        .map(|(&price, &qty)| calculate_bulk_discount(price, qty))
        .collect()
}

/// Parallel batch processing coordinator
pub fn coordinate_batch_processing(batches: Vec<Vec<(f64, u32, f64)>>, vat_rate: f64) -> Vec<Vec<ComputeResult>> {
    batches
        .into_iter()
        .map(|batch| process_batch_orders(batch, vat_rate))
        .collect()
}

// ============================================================================
// METRICS & MONITORING (LEVEL 6)
// ============================================================================

pub struct PerformanceMetrics {
    pub total_operations: u64,
    pub cache_hit_rate: f64,
    pub avg_processing_time: u64,
}

/// Compute metrics (calls Level 3, 4, 5)
pub fn compute_performance_metrics(
    order_results: &[ComputeResult],
    cache_hits: u32,
    total_requests: u32,
) -> PerformanceMetrics {
    let total_ops: u64 = order_results.iter().map(|r| r.operations_count as u64).sum();
    let cache_hit_rate = if total_requests > 0 {
        cache_hits as f64 / total_requests as f64
    } else {
        0.0
    };

    PerformanceMetrics {
        total_operations: total_ops,
        cache_hit_rate,
        avg_processing_time: if !order_results.is_empty() {
            total_ops / order_results.len() as u64
        } else {
            0
        },
    }
}

// ============================================================================
// CIRCULAR REFERENCE (for testing)
// ============================================================================

pub fn circular_rust_a(depth: u32) -> u32 {
    if depth == 0 {
        0
    } else {
        circular_rust_b(depth - 1)
    }
}

pub fn circular_rust_b(depth: u32) -> u32 {
    if depth == 0 {
        0
    } else {
        circular_rust_a(depth - 1)
    }
}

// ============================================================================
// RECURSIVE FUNCTIONS (for testing)
// ============================================================================

pub fn fibonacci(n: u32) -> u64 {
    match n {
        0 => 0,
        1 => 1,
        _ => fibonacci(n - 1) + fibonacci(n - 2),
    }
}

pub fn sum_recursive(items: &[f64]) -> f64 {
    if items.is_empty() {
        0.0
    } else {
        items[0] + sum_recursive(&items[1..])
    }
}

// ============================================================================
// SELF-REFERENCING STRUCTS
// ============================================================================

#[derive(Debug)]
pub struct TreeNode {
    pub value: f64,
    pub children: Vec<Box<TreeNode>>,
}

impl TreeNode {
    pub fn new(value: f64) -> Self {
        TreeNode {
            value,
            children: Vec::new(),
        }
    }

    pub fn sum_tree(&self) -> f64 {
        self.value + self.children.iter().map(|child| child.sum_tree()).sum::<f64>()
    }

    pub fn max_depth(&self) -> u32 {
        1 + self
            .children
            .iter()
            .map(|child| child.max_depth())
            .max()
            .unwrap_or(0)
    }
}

// ============================================================================
// ORPHAN FUNCTIONS (not called by others)
// ============================================================================

pub fn orphan_utility_sqrt(x: f64) -> f64 {
    x.sqrt()
}

pub fn orphan_utility_pow(x: f64, n: u32) -> f64 {
    x.powi(n as i32)
}

pub fn orphan_utility_factorial(n: u32) -> u64 {
    (1..=n as u64).product()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_bulk_discount() {
        assert_eq!(calculate_bulk_discount(100.0, 100), 85.0);
        assert_eq!(calculate_bulk_discount(100.0, 10), 95.0);
    }

    #[test]
    fn test_order_cost() {
        let result = calculate_order_cost(100.0, 50, 5000.0, 0.20, 2);
        assert!(result.value > 0.0);
        assert_eq!(result.operations_count, 7);
    }
}
