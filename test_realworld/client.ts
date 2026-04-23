/**
 * E-Commerce Platform - TypeScript Frontend Client
 * Real-world TypeScript implementation with async/await patterns
 */

// ============================================================================
// DATA TYPES & INTERFACES
// ============================================================================

interface User {
  userId: string;
  email: string;
  name: string;
  createdAt: Date;
}

interface Product {
  productId: string;
  name: string;
  price: number;
  stock: number;
}

interface CartItem {
  productId: string;
  quantity: number;
  price: number;
}

interface Order {
  orderId: string;
  userId: string;
  items: CartItem[];
  total: number;
  status: "pending" | "processing" | "shipped" | "delivered";
  createdAt: Date;
}

interface ApiResponse<T> {
  success: boolean;
  data?: T;
  error?: string;
}

// ============================================================================
// VALIDATION FUNCTIONS (LEVEL 1)
// ============================================================================

/**
 * Validate email format
 */
export function validateEmail(email: string): boolean {
  const regex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  return regex.test(email);
}

/**
 * Validate phone number format
 */
export function validatePhoneNumber(phone: string): boolean {
  const regex = /^\d{10,15}$/;
  return regex.test(phone.replace(/\D/g, ""));
}

/**
 * Validate password strength
 */
export function validatePasswordStrength(password: string): boolean {
  // At least 8 chars, 1 uppercase, 1 number
  return (
    password.length >= 8 &&
    /[A-Z]/.test(password) &&
    /\d/.test(password)
  );
}

/**
 * Sanitize user input
 */
export function sanitizeInput(input: string): string {
  return input
    .replace(/[<>;"']/g, "")
    .trim();
}

/**
 * Format currency
 */
export function formatCurrency(amount: number, currency: string = "USD"): string {
  const formatter = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
  });
  return formatter.format(amount);
}

/**
 * Calculate tax
 */
export function calculateTax(amount: number, taxRate: number): number {
  return amount * taxRate;
}

/**
 * Apply coupon discount
 */
export function applyCouponDiscount(amount: number, couponCode: string): number {
  const discounts: Record<string, number> = {
    SAVE10: 0.1,
    SAVE20: 0.2,
    VIPONLY: 0.3,
  };
  const discount = discounts[couponCode] || 0;
  return amount * (1 - discount);
}

// ============================================================================
// CART SERVICE (LEVEL 2 - uses Level 1)
// ============================================================================

export class ShoppingCart {
  private items: CartItem[] = [];

  /**
   * Add item to cart
   */
  public addItem(productId: string, quantity: number, price: number): void {
    const existing = this.items.find((i) => i.productId === productId);
    if (existing) {
      existing.quantity += quantity;
    } else {
      this.items.push({ productId, quantity, price });
    }
  }

  /**
   * Remove item from cart
   */
  public removeItem(productId: string): boolean {
    const index = this.items.findIndex((i) => i.productId === productId);
    if (index >= 0) {
      this.items.splice(index, 1);
      return true;
    }
    return false;
  }

  /**
   * Calculate cart subtotal (calls Level 1)
   */
  public calculateSubtotal(): number {
    return this.items.reduce((sum, item) => sum + item.price * item.quantity, 0);
  }

  /**
   * Apply coupon to cart (calls Level 1)
   */
  public applyCoupon(couponCode: string): number {
    const subtotal = this.calculateSubtotal();
    return applyCouponDiscount(subtotal, couponCode);
  }

  /**
   * Calculate total with tax and shipping (DIAMOND PATTERN)
   */
  public calculateTotal(taxRate: number, shippingCost: number): number {
    const subtotal = this.calculateSubtotal();
    const tax = calculateTax(subtotal, taxRate);
    return subtotal + tax + shippingCost;
  }

  /**
   * Get cart summary
   */
  public getCartSummary(): {
    itemCount: number;
    subtotal: number;
    items: CartItem[];
  } {
    return {
      itemCount: this.items.reduce((sum, item) => sum + item.quantity, 0),
      subtotal: this.calculateSubtotal(),
      items: [...this.items],
    };
  }

  /**
   * Clear cart
   */
  public clear(): void {
    this.items = [];
  }
}

// ============================================================================
// API CLIENT (LEVEL 3 - calls Level 1 & 2)
// ============================================================================

export class ApiClient {
  private baseUrl: string;
  private token?: string;

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl;
  }

  /**
   * Set authentication token
   */
  public setToken(token: string): void {
    this.token = token;
  }

  /**
   * Make GET request
   */
  private async get<T>(endpoint: string): Promise<ApiResponse<T>> {
    try {
      const response = await fetch(`${this.baseUrl}${endpoint}`, {
        method: "GET",
        headers: this.getHeaders(),
      });
      const data = await response.json();
      return { success: response.ok, data, error: !response.ok ? "Request failed" : undefined };
    } catch (error) {
      return { success: false, error: String(error) };
    }
  }

  /**
   * Make POST request
   */
  private async post<T>(endpoint: string, body: any): Promise<ApiResponse<T>> {
    try {
      const response = await fetch(`${this.baseUrl}${endpoint}`, {
        method: "POST",
        headers: this.getHeaders(),
        body: JSON.stringify(body),
      });
      const data = await response.json();
      return { success: response.ok, data, error: !response.ok ? "Request failed" : undefined };
    } catch (error) {
      return { success: false, error: String(error) };
    }
  }

  /**
   * Get request headers
   */
  private getHeaders(): HeadersInit {
    const headers: HeadersInit = { "Content-Type": "application/json" };
    if (this.token) {
      headers["Authorization"] = `Bearer ${this.token}`;
    }
    return headers;
  }

  /**
   * Login user
   */
  public async login(email: string, password: string): Promise<ApiResponse<{ token: string }>> {
    // Validate inputs (calls Level 1)
    if (!validateEmail(email)) {
      return { success: false, error: "Invalid email" };
    }

    return this.post<{ token: string }>("/auth/login", { email, password });
  }

  /**
   * Register user
   */
  public async register(
    email: string,
    password: string,
    name: string
  ): Promise<ApiResponse<User>> {
    // Validate inputs (calls Level 1)
    if (!validateEmail(email)) {
      return { success: false, error: "Invalid email" };
    }
    if (!validatePasswordStrength(password)) {
      return { success: false, error: "Password too weak" };
    }

    // Sanitize inputs
    const sanitizedName = sanitizeInput(name);

    return this.post<User>("/auth/register", {
      email,
      password,
      name: sanitizedName,
    });
  }

  /**
   * Get user profile
   */
  public async getUserProfile(): Promise<ApiResponse<User>> {
    return this.get<User>("/user/profile");
  }

  /**
   * Create order with cart
   */
  public async createOrder(cart: ShoppingCart): Promise<ApiResponse<Order>> {
    const summary = cart.getCartSummary();
    return this.post<Order>("/orders", { items: summary.items });
  }
}

// ============================================================================
// CHECKOUT SERVICE (LEVEL 4 - orchestrates Level 2 & 3)
// ============================================================================

export class CheckoutService {
  private cart: ShoppingCart;
  private apiClient: ApiClient;
  private taxRate: number = 0.08;
  private shippingCost: number = 10.0;

  constructor(apiClient: ApiClient) {
    this.cart = new ShoppingCart();
    this.apiClient = apiClient;
  }

  /**
   * Add product to checkout (calls Level 2)
   */
  public addProduct(productId: string, quantity: number, price: number): void {
    this.cart.addItem(productId, quantity, price);
  }

  /**
   * Apply coupon code (calls Level 2)
   */
  public applyDiscount(couponCode: string): number {
    return this.cart.applyCoupon(couponCode);
  }

  /**
   * Get checkout summary (calls Level 2)
   */
  public getCheckoutSummary(): {
    subtotal: number;
    tax: number;
    shipping: number;
    total: number;
  } {
    const subtotal = this.cart.calculateSubtotal();
    const tax = calculateTax(subtotal, this.taxRate);
    return {
      subtotal,
      tax,
      shipping: this.shippingCost,
      total: subtotal + tax + this.shippingCost,
    };
  }

  /**
   * Process checkout (DEEP NESTING - calls multiple levels)
   */
  public async processCheckout(
    couponCode?: string
  ): Promise<ApiResponse<{ order: Order; total: number }>> {
    // Level 1: Apply coupon (if provided)
    let subtotal = this.cart.calculateSubtotal();
    if (couponCode) {
      subtotal = this.cart.applyCoupon(couponCode);
    }

    // Level 2: Calculate tax and shipping (calls Level 1)
    const tax = calculateTax(subtotal, this.taxRate);
    const total = subtotal + tax + this.shippingCost;

    // Level 3: Validate total
    if (total < 0) {
      return { success: false, error: "Invalid total" };
    }

    // Level 4: Create order via API (calls Level 3)
    const orderResponse = await this.apiClient.createOrder(this.cart);

    if (!orderResponse.success) {
      return { success: false, error: orderResponse.error };
    }

    // Level 5: Clear cart (calls Level 2)
    this.cart.clear();

    return { success: true, data: { order: orderResponse.data!, total } };
  }
}

// ============================================================================
// STATE MANAGEMENT (LEVEL 5 - complex state orchestration)
// ============================================================================

export class AppState {
  private currentUser?: User;
  private checkout: CheckoutService;
  private apiClient: ApiClient;
  private listeners: Set<() => void> = new Set();

  constructor(apiClient: ApiClient) {
    this.apiClient = apiClient;
    this.checkout = new CheckoutService(apiClient);
  }

  /**
   * Login user (calls Level 3)
   */
  public async login(email: string, password: string): Promise<boolean> {
    const response = await this.apiClient.login(email, password);
    if (response.success && response.data) {
      this.apiClient.setToken(response.data.token);
      this.currentUser = await this.loadUserProfile();
      this.notifyListeners();
      return true;
    }
    return false;
  }

  /**
   * Register user (calls Level 3)
   */
  public async register(email: string, password: string, name: string): Promise<boolean> {
    const response = await this.apiClient.register(email, password, name);
    if (response.success && response.data) {
      this.currentUser = response.data;
      this.notifyListeners();
      return true;
    }
    return false;
  }

  /**
   * Load user profile (calls Level 3)
   */
  private async loadUserProfile(): Promise<User | undefined> {
    const response = await this.apiClient.getUserProfile();
    return response.data;
  }

  /**
   * Add to cart (calls Level 4)
   */
  public addToCart(productId: string, quantity: number, price: number): void {
    this.checkout.addProduct(productId, quantity, price);
    this.notifyListeners();
  }

  /**
   * Complete purchase (calls Level 4)
   */
  public async completePurchase(
    couponCode?: string
  ): Promise<ApiResponse<{ order: Order; total: number }>> {
    const result = await this.checkout.processCheckout(couponCode);
    if (result.success) {
      this.notifyListeners();
    }
    return result;
  }

  /**
   * Get current user
   */
  public getCurrentUser(): User | undefined {
    return this.currentUser;
  }

  /**
   * Subscribe to state changes
   */
  public subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  /**
   * Notify all listeners of state change
   */
  private notifyListeners(): void {
    this.listeners.forEach((listener) => listener());
  }
}

// ============================================================================
// CIRCULAR DEPENDENCY (intentional for testing)
// ============================================================================

export class ComponentA {
  static render(): string {
    return "A: " + ComponentB.render();
  }
}

export class ComponentB {
  static render(): string {
    return "B";
  }
}

// ============================================================================
// RECURSIVE FUNCTIONS
// ============================================================================

/**
 * Calculate fibonacci recursively
 */
export function fibonacci(n: number): number {
  if (n <= 1) return n;
  return fibonacci(n - 1) + fibonacci(n - 2);
}

/**
 * Deeply nested DOM tree traversal
 */
export function traverseDOM(element: Element): number {
  if (!element.children.length) return 1;
  return 1 + Array.from(element.children).map(traverseDOM).reduce((a, b) => Math.max(a, b), 0);
}

// ============================================================================
// ORPHAN UTILITIES (not called by others)
// ============================================================================

/**
 * Calculate compound interest
 */
export function calculateCompoundInterest(principal: number, rate: number, years: number): number {
  return principal * Math.pow(1 + rate / 100, years);
}

/**
 * Generate random UUID
 */
export function generateUUID(): string {
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

/**
 * Parse JWT token
 */
export function parseJWT(token: string): Record<string, any> | null {
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  try {
    return JSON.parse(atob(parts[1]));
  } catch {
    return null;
  }
}

// ============================================================================
// EXPORT FOR TESTING
// ============================================================================

export default {
  ShoppingCart,
  ApiClient,
  CheckoutService,
  AppState,
};
