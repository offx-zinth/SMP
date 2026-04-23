// E-Commerce Platform - Java Integration Services
// Real-world Java implementation with enterprise patterns

import java.util.*;
import java.time.*;
import java.util.concurrent.*;
import java.util.stream.*;

/**
 * Notification Service - handles multi-channel notifications
 */
public class NotificationService {
    private Queue<String> notificationQueue;
    private Map<String, Integer> retryCount;

    public NotificationService() {
        this.notificationQueue = new ConcurrentLinkedQueue<>();
        this.retryCount = new ConcurrentHashMap<>();
    }

    /**
     * Format notification message
     */
    public String formatNotificationMessage(String userId, String eventType, String details) {
        return String.format("[%s] %s: %s", userId, eventType, details);
    }

    /**
     * Send email notification
     */
    public boolean sendEmailNotification(String email, String subject, String body) {
        if (!email.contains("@")) {
            return false;
        }
        // In real system: call email service
        return true;
    }

    /**
     * Send SMS notification
     */
    public boolean sendSmsNotification(String phoneNumber, String message) {
        if (phoneNumber.length() < 10) {
            return false;
        }
        // In real system: call SMS provider
        return true;
    }

    /**
     * Send push notification
     */
    public boolean sendPushNotification(String userId, String title, String message) {
        String formatted = formatNotificationMessage(userId, "PUSH", title);
        notificationQueue.offer(formatted);
        return true;
    }

    /**
     * Queue notification for delivery
     */
    public void queueNotification(String notification) {
        notificationQueue.offer(notification);
    }

    /**
     * Process notification queue
     */
    public int processNotificationQueue() {
        int processed = 0;
        while (!notificationQueue.isEmpty()) {
            notificationQueue.poll();
            processed++;
        }
        return processed;
    }
}

/**
 * Reward Service - manages customer rewards and loyalty
 */
public class RewardService {
    private Map<String, Integer> rewardPoints;
    private Map<String, LocalDateTime> lastResetDate;

    public RewardService() {
        this.rewardPoints = new ConcurrentHashMap<>();
        this.lastResetDate = new ConcurrentHashMap<>();
    }

    /**
     * Calculate points earned from purchase
     */
    public int calculateRewardPoints(double purchaseAmount) {
        return (int) (purchaseAmount * 10); // 1 point per 10 cents
    }

    /**
     * Add points to user account
     */
    public void addRewardPoints(String userId, int points) {
        rewardPoints.merge(userId, points, Integer::sum);
    }

    /**
     * Get user's current points
     */
    public int getUserRewardPoints(String userId) {
        return rewardPoints.getOrDefault(userId, 0);
    }

    /**
     * Redeem reward points (calls calculateRewardPoints conceptually)
     */
    public boolean redeemRewardPoints(String userId, int pointsToRedeem) {
        int currentPoints = getUserRewardPoints(userId);
        if (currentPoints < pointsToRedeem) {
            return false;
        }
        rewardPoints.put(userId, currentPoints - pointsToRedeem);
        return true;
    }

    /**
     * Check if eligible for tier upgrade
     */
    public boolean isEligibleForTierUpgrade(String userId) {
        int points = getUserRewardPoints(userId);
        return points >= 1000; // 1000 points required
    }

    /**
     * Upgrade user tier (calls isEligibleForTierUpgrade)
     */
    public boolean upgradeUserTier(String userId) {
        if (!isEligibleForTierUpgrade(userId)) {
            return false;
        }
        // In real system: update user tier in database
        return true;
    }
}

/**
 * Recommendation Engine - provides product recommendations
 */
public class RecommendationEngine {
    private Map<String, List<String>> userPurchaseHistory;
    private Map<String, List<String>> productSimilarities;

    public RecommendationEngine() {
        this.userPurchaseHistory = new ConcurrentHashMap<>();
        this.productSimilarities = new ConcurrentHashMap<>();
    }

    /**
     * Get user purchase history
     */
    public List<String> getUserPurchaseHistory(String userId) {
        return userPurchaseHistory.getOrDefault(userId, new ArrayList<>());
    }

    /**
     * Get similar products
     */
    public List<String> getSimilarProducts(String productId) {
        return productSimilarities.getOrDefault(productId, new ArrayList<>());
    }

    /**
     * Calculate recommendation score for product
     */
    public double calculateRecommendationScore(String userId, String productId) {
        List<String> history = getUserPurchaseHistory(userId);
        if (history.isEmpty()) {
            return 0.5; // Neutral score
        }
        return history.size() / 10.0; // Simplified scoring
    }

    /**
     * Get recommended products for user (DIAMOND PATTERN)
     */
    public List<String> getRecommendedProducts(String userId) {
        List<String> recommendations = new ArrayList<>();
        List<String> history = getUserPurchaseHistory(userId);

        for (String productId : history) {
            List<String> similar = getSimilarProducts(productId);
            for (String simProduct : similar) {
                double score = calculateRecommendationScore(userId, simProduct);
                if (score > 0.6 && !recommendations.contains(simProduct)) {
                    recommendations.add(simProduct);
                }
            }
        }

        return recommendations;
    }
}

/**
 * Analytics Aggregator - combines data from multiple sources
 */
public class AnalyticsAggregator {
    private NotificationService notificationService;
    private RewardService rewardService;
    private RecommendationEngine recommendationEngine;

    public AnalyticsAggregator() {
        this.notificationService = new NotificationService();
        this.rewardService = new RewardService();
        this.recommendationEngine = new RecommendationEngine();
    }

    /**
     * Generate user profile (CALLS MULTIPLE SERVICES - Level 5 aggregation)
     */
    public Map<String, Object> generateUserProfile(String userId) {
        Map<String, Object> profile = new HashMap<>();

        // Call reward service
        int points = rewardService.getUserRewardPoints(userId);
        profile.put("reward_points", points);

        boolean eligibleForUpgrade = rewardService.isEligibleForTierUpgrade(userId);
        profile.put("eligible_for_upgrade", eligibleForUpgrade);

        // Call recommendation engine
        List<String> recommendations = recommendationEngine.getRecommendedProducts(userId);
        profile.put("recommendations", recommendations);

        // Send notification (calls format)
        String message = notificationService.formatNotificationMessage(userId, "PROFILE_GENERATED", "Profile updated");
        profile.put("notification", message);

        return profile;
    }

    /**
     * Execute end-to-end user action (DEEP NESTING - 5+ levels)
     */
    public boolean executeUserAction(String userId, String action, double amount) {
        // Level 1: Format notification
        String notification = notificationService.formatNotificationMessage(userId, action, String.valueOf(amount));

        // Level 2: Calculate rewards
        int earnedPoints = rewardService.calculateRewardPoints(amount);

        // Level 3: Add points
        rewardService.addRewardPoints(userId, earnedPoints);

        // Level 4: Check upgrade eligibility
        boolean eligible = rewardService.isEligibleForTierUpgrade(userId);

        // Level 5: If eligible, upgrade
        if (eligible) {
            rewardService.upgradeUserTier(userId);
        }

        // Level 6: Generate recommendations
        List<String> recommendations = recommendationEngine.getRecommendedProducts(userId);

        // Level 7: Queue notification about action
        notificationService.queueNotification(notification);

        return true;
    }
}

/**
 * Circular dependency test
 */
public class CircularDependencyA {
    public static int processA(int value) {
        if (value < 0) {
            return value;
        }
        return CircularDependencyB.processB(value - 1);
    }
}

public class CircularDependencyB {
    public static int processB(int value) {
        if (value < 0) {
            return 0;
        }
        return CircularDependencyA.processA(value - 1);
    }
}

/**
 * Recursive structures
 */
public class TreeNode {
    public int value;
    public List<TreeNode> children;

    public TreeNode(int value) {
        this.value = value;
        this.children = new ArrayList<>();
    }

    /**
     * Calculate tree sum recursively
     */
    public int sumTree() {
        return value + children.stream().mapToInt(TreeNode::sumTree).sum();
    }

    /**
     * Find maximum depth
     */
    public int maxDepth() {
        if (children.isEmpty()) {
            return 1;
        }
        return 1 + children.stream().mapToInt(TreeNode::maxDepth).max().orElse(0);
    }
}

/**
 * Orphan utilities - not called by other functions
 */
public class OrphanUtilities {
    public static double calculateQuadraticFormula(double a, double b, double c) {
        return (-b + Math.sqrt(b * b - 4 * a * c)) / (2 * a);
    }

    public static List<Integer> getPrimeNumbers(int limit) {
        return IntStream.range(2, limit).filter(n -> IntStream.range(2, n).noneMatch(i -> n % i == 0))
                .boxed().collect(Collectors.toList());
    }

    public static int countDigits(long number) {
        return String.valueOf(Math.abs(number)).length();
    }
}

/**
 * Main entry point for testing
 */
public class ECommerceIntegrationDemo {
    public static void main(String[] args) {
        System.out.println("E-Commerce Integration Services");
        System.out.println("================================\n");

        // Initialize services
        AnalyticsAggregator aggregator = new AnalyticsAggregator();

        // Test user profile generation
        System.out.println("1. Generating user profile...");
        Map<String, Object> profile = aggregator.generateUserProfile("user_123");
        System.out.println("   Profile: " + profile);

        // Test user action execution
        System.out.println("\n2. Executing user action...");
        boolean success = aggregator.executeUserAction("user_123", "PURCHASE", 150.0);
        System.out.println("   Success: " + success);

        // Test circular dependency
        System.out.println("\n3. Testing circular dependency...");
        int result = CircularDependencyA.processA(5);
        System.out.println("   Result: " + result);

        // Test tree structure
        System.out.println("\n4. Testing tree structure...");
        TreeNode root = new TreeNode(10);
        TreeNode child1 = new TreeNode(5);
        TreeNode child2 = new TreeNode(7);
        root.children.add(child1);
        root.children.add(child2);
        System.out.println("   Tree sum: " + root.sumTree());
        System.out.println("   Tree depth: " + root.maxDepth());

        System.out.println("\n================================");
        System.out.println("Integration test complete!");
    }
}
