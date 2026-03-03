/**
 * SMP Initialize API Route
 * Loads sample code into the memory store
 */

import { NextRequest, NextResponse } from 'next/server';
import { getProtocolHandler } from '@/lib/smp/protocol/handler';

// Sample TypeScript code for demonstration
const SAMPLE_FILES = [
  {
    path: 'src/auth/login.ts',
    content: `
/**
 * Authentication module for user login functionality
 * Handles credential validation and JWT token generation
 */

import { hashPassword, compareHash } from './utils/crypto';
import { UserModel } from '../db/user';
import { TokenService } from './token-service';

export interface LoginCredentials {
  email: string;
  password: string;
}

export interface AuthResult {
  success: boolean;
  token?: string;
  user?: UserProfile;
  error?: string;
}

export interface UserProfile {
  id: string;
  email: string;
  name: string;
  role: 'user' | 'admin' | 'moderator';
}

/**
 * Validates user credentials and returns JWT token
 * @param credentials - User login credentials
 * @returns Authentication result with token on success
 */
export async function authenticateUser(
  credentials: LoginCredentials
): Promise<AuthResult> {
  const { email, password } = credentials;
  
  // Find user by email
  const user = await UserModel.findByEmail(email);
  if (!user) {
    return { success: false, error: 'User not found' };
  }
  
  // Verify password
  const isValid = await compareHash(password, user.passwordHash);
  if (!isValid) {
    return { success: false, error: 'Invalid password' };
  }
  
  // Generate token
  const token = await TokenService.generateToken({
    userId: user.id,
    role: user.role,
  });
  
  return {
    success: true,
    token,
    user: {
      id: user.id,
      email: user.email,
      name: user.name,
      role: user.role,
    },
  };
}

/**
 * Validates an existing JWT token
 * @param token - JWT token to validate
 * @returns Decoded token payload or null if invalid
 */
export async function validateToken(token: string): Promise<UserProfile | null> {
  try {
    const payload = await TokenService.verifyToken(token);
    if (!payload || !payload.userId) {
      return null;
    }
    
    const user = await UserModel.findById(payload.userId);
    return user ? {
      id: user.id,
      email: user.email,
      name: user.name,
      role: user.role,
    } : null;
  } catch (error) {
    console.error('Token validation failed:', error);
    return null;
  }
}

/**
 * Logs out a user by invalidating their token
 * @param token - JWT token to invalidate
 */
export async function logoutUser(token: string): Promise<void> {
  await TokenService.invalidateToken(token);
}

/**
 * Refreshes an existing token
 * @param token - Current JWT token
 * @returns New token or null if refresh failed
 */
export async function refreshToken(token: string): Promise<string | null> {
  const user = await validateToken(token);
  if (!user) {
    return null;
  }
  
  return TokenService.generateToken({
    userId: user.id,
    role: user.role,
  });
}

export class AuthService {
  private tokenExpiry: number = 3600; // 1 hour
  private secretKey: string;
  
  constructor(secretKey: string) {
    this.secretKey = secretKey;
  }
  
  async login(credentials: LoginCredentials): Promise<AuthResult> {
    return authenticateUser(credentials);
  }
  
  async logout(token: string): Promise<void> {
    return logoutUser(token);
  }
  
  async refresh(token: string): Promise<string | null> {
    return refreshToken(token);
  }
  
  validate(token: string): Promise<UserProfile | null> {
    return validateToken(token);
  }
}
`,
  },
  {
    path: 'src/auth/token-service.ts',
    content: `
/**
 * Token Service for JWT management
 */

import jwt from 'jsonwebtoken';

export interface TokenPayload {
  userId: string;
  role: string;
  iat?: number;
  exp?: number;
}

const JWT_SECRET = process.env.JWT_SECRET || 'default-secret-key';
const TOKEN_EXPIRY = '1h';

export class TokenService {
  /**
   * Generates a new JWT token
   */
  static async generateToken(payload: Omit<TokenPayload, 'iat' | 'exp'>): Promise<string> {
    return new Promise((resolve, reject) => {
      jwt.sign(
        payload,
        JWT_SECRET,
        { expiresIn: TOKEN_EXPIRY },
        (err, token) => {
          if (err) reject(err);
          else resolve(token!);
        }
      );
    });
  }
  
  /**
   * Verifies and decodes a JWT token
   */
  static async verifyToken(token: string): Promise<TokenPayload | null> {
    return new Promise((resolve) => {
      jwt.verify(token, JWT_SECRET, (err, decoded) => {
        if (err) resolve(null);
        else resolve(decoded as TokenPayload);
      });
    });
  }
  
  /**
   * Invalidates a token (add to blacklist)
   */
  static async invalidateToken(token: string): Promise<void> {
    // In production, add to Redis blacklist
    console.log('Token invalidated:', token.substring(0, 20) + '...');
  }
  
  /**
   * Decodes token without verification
   */
  static decodeToken(token: string): TokenPayload | null {
    try {
      return jwt.decode(token) as TokenPayload;
    } catch {
      return null;
    }
  }
}
`,
  },
  {
    path: 'src/db/user.ts',
    content: `
/**
 * User database model
 */

export interface UserDocument {
  id: string;
  email: string;
  name: string;
  passwordHash: string;
  role: 'user' | 'admin' | 'moderator';
  createdAt: Date;
  updatedAt: Date;
}

export class UserModel {
  /**
   * Find user by email address
   */
  static async findByEmail(email: string): Promise<UserDocument | null> {
    // Database query implementation
    const users = await this.findAll();
    return users.find(u => u.email === email) || null;
  }
  
  /**
   * Find user by ID
   */
  static async findById(id: string): Promise<UserDocument | null> {
    // Database query implementation
    const users = await this.findAll();
    return users.find(u => u.id === id) || null;
  }
  
  /**
   * Get all users
   */
  static async findAll(): Promise<UserDocument[]> {
    // Mock implementation
    return [];
  }
  
  /**
   * Create a new user
   */
  static async create(data: Omit<UserDocument, 'id' | 'createdAt' | 'updatedAt'>): Promise<UserDocument> {
    const now = new Date();
    const user: UserDocument = {
      id: generateId(),
      ...data,
      createdAt: now,
      updatedAt: now,
    };
    return user;
  }
  
  /**
   * Update user by ID
   */
  static async update(id: string, data: Partial<UserDocument>): Promise<UserDocument | null> {
    const user = await this.findById(id);
    if (!user) return null;
    
    return {
      ...user,
      ...data,
      updatedAt: new Date(),
    };
  }
  
  /**
   * Delete user by ID
   */
  static async delete(id: string): Promise<boolean> {
    const user = await this.findById(id);
    return !!user;
  }
}

function generateId(): string {
  return Math.random().toString(36).substring(2, 15);
}
`,
  },
  {
    path: 'src/auth/utils/crypto.ts',
    content: `
/**
 * Cryptographic utilities for password hashing
 */

import bcrypt from 'bcrypt';

const SALT_ROUNDS = 10;

/**
 * Hash a password using bcrypt
 */
export async function hashPassword(password: string): Promise<string> {
  return bcrypt.hash(password, SALT_ROUNDS);
}

/**
 * Compare a password against a hash
 */
export async function compareHash(password: string, hash: string): Promise<boolean> {
  return bcrypt.compare(password, hash);
}

/**
 * Generate a random token
 */
export function generateRandomToken(length: number = 32): string {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  let result = '';
  for (let i = 0; i < length; i++) {
    result += chars.charAt(Math.floor(Math.random() * chars.length));
  }
  return result;
}

/**
 * Hash a string using SHA-256
 */
export async function sha256(input: string): Promise<string> {
  const encoder = new TextEncoder();
  const data = encoder.encode(input);
  const hashBuffer = await crypto.subtle.digest('SHA-256', data);
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
}
`,
  },
  {
    path: 'src/api/routes.ts',
    content: `
/**
 * API Routes configuration
 */

import { Router } from 'express';
import { authenticateUser, validateToken, logoutUser } from '../auth/login';
import { UserModel } from '../db/user';

const router = Router();

/**
 * POST /api/auth/login
 * User login endpoint
 */
router.post('/auth/login', async (req, res) => {
  try {
    const { email, password } = req.body;
    const result = await authenticateUser({ email, password });
    
    if (!result.success) {
      return res.status(401).json({ error: result.error });
    }
    
    res.json({
      token: result.token,
      user: result.user,
    });
  } catch (error) {
    console.error('Login error:', error);
    res.status(500).json({ error: 'Internal server error' });
  }
});

/**
 * POST /api/auth/logout
 * User logout endpoint
 */
router.post('/auth/logout', async (req, res) => {
  const token = req.headers.authorization?.replace('Bearer ', '');
  
  if (token) {
    await logoutUser(token);
  }
  
  res.json({ success: true });
});

/**
 * GET /api/auth/me
 * Get current user profile
 */
router.get('/auth/me', async (req, res) => {
  const token = req.headers.authorization?.replace('Bearer ', '');
  
  if (!token) {
    return res.status(401).json({ error: 'No token provided' });
  }
  
  const user = await validateToken(token);
  
  if (!user) {
    return res.status(401).json({ error: 'Invalid token' });
  }
  
  res.json({ user });
});

/**
 * GET /api/users
 * List all users (admin only)
 */
router.get('/users', async (req, res) => {
  const token = req.headers.authorization?.replace('Bearer ', '');
  const user = await validateToken(token || '');
  
  if (!user || user.role !== 'admin') {
    return res.status(403).json({ error: 'Forbidden' });
  }
  
  const users = await UserModel.findAll();
  res.json({ users });
});

export default router;
`,
  },
  {
    path: 'tests/auth.test.ts',
    content: `
/**
 * Authentication tests
 */

import { authenticateUser, validateToken, logoutUser } from '../src/auth/login';
import { TokenService } from '../src/auth/token-service';

describe('Authentication', () => {
  describe('authenticateUser', () => {
    it('should return success with valid credentials', async () => {
      const result = await authenticateUser({
        email: 'test@example.com',
        password: 'password123',
      });
      
      expect(result.success).toBe(true);
      expect(result.token).toBeDefined();
      expect(result.user).toBeDefined();
    });
    
    it('should return error with invalid credentials', async () => {
      const result = await authenticateUser({
        email: 'nonexistent@example.com',
        password: 'wrongpassword',
      });
      
      expect(result.success).toBe(false);
      expect(result.error).toBeDefined();
    });
  });
  
  describe('TokenService', () => {
    it('should generate and verify token', async () => {
      const token = await TokenService.generateToken({
        userId: 'user123',
        role: 'user',
      });
      
      expect(token).toBeDefined();
      
      const payload = await TokenService.verifyToken(token);
      expect(payload).toBeDefined();
      expect(payload?.userId).toBe('user123');
    });
    
    it('should return null for invalid token', async () => {
      const payload = await TokenService.verifyToken('invalid-token');
      expect(payload).toBeNull();
    });
  });
  
  describe('validateToken', () => {
    it('should return user profile for valid token', async () => {
      // First authenticate to get token
      const authResult = await authenticateUser({
        email: 'test@example.com',
        password: 'password123',
      });
      
      if (authResult.token) {
        const user = await validateToken(authResult.token);
        expect(user).toBeDefined();
        expect(user?.email).toBe('test@example.com');
      }
    });
  });
});
`,
  },
];

export async function GET(request: NextRequest): Promise<NextResponse> {
  const handler = getProtocolHandler();
  
  // Batch update all sample files
  const changes = SAMPLE_FILES.map(file => ({
    file_path: file.path,
    content: file.content,
    change_type: 'created' as const,
  }));
  
  const response = await handler.handleRequest({
    jsonrpc: '2.0',
    method: 'smp/batch_update',
    params: { changes },
    id: 'init',
  });
  
  return NextResponse.json({
    jsonrpc: '2.0',
    result: {
      initialized: true,
      files_loaded: SAMPLE_FILES.length,
      ...response.result,
    },
    id: 'init',
  });
}
