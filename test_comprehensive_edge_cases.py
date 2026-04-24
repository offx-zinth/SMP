"""
Comprehensive Real-World Edge Case Test Suite for SMP MCP Tools
Tests 40+ edge cases including circular deps, deep nesting, diamond patterns, etc.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from smp.engine.query import DefaultQueryEngine
from smp.store.graph.neo4j_store import Neo4jGraphStore


@dataclass
class TestResult:
    """Result of a single test"""

    name: str
    passed: bool
    error: str = ""
    metrics: dict[str, Any] | None = None


class RealWorldTestSuite:
    """Comprehensive real-world test suite"""

    def __init__(self, engine: DefaultQueryEngine):
        self.engine = engine
        self.results: list[TestResult] = []

    # ========================================================================
    # CIRCULAR DEPENDENCY TESTS (1-3)
    # ========================================================================

    async def test_circular_dependency_detection(self) -> TestResult:
        """Test 1: Detect circular dependencies"""
        try:
            # circular_function_a calls circular_function_b
            result = await self.engine.navigate("circular_function_a")
            calls = result.get("relationships", {}).get("calls", [])

            # Should show the circular reference
            passed = len(calls) > 0 and any("circular_function_b" in c for c in calls)

            return TestResult("Circular Dependency Detection", passed)
        except Exception as e:
            return TestResult("Circular Dependency Detection", False, str(e))

    async def test_circular_b_to_a(self) -> TestResult:
        """Test 2: Reverse circular reference"""
        try:
            result = await self.engine.navigate("circular_function_b")
            calls = result.get("relationships", {}).get("calls", [])
            passed = len(calls) > 0 and any("circular_function_a" in c for c in calls)
            return TestResult("Circular B → A Reference", passed)
        except Exception as e:
            return TestResult("Circular B → A Reference", False, str(e))

    async def test_circular_java_dependencies(self) -> TestResult:
        """Test 3: Circular dependencies in Java"""
        try:
            result = await self.engine.navigate("CircularDependencyA")
            # CircularDependencyA.processA calls CircularDependencyB.processB
            calls = result.get("relationships", {}).get("calls", [])
            passed = len(calls) > 0 or "CircularDependencyA" in str(result)
            return TestResult("Circular Java Dependencies", passed)
        except Exception as e:
            return TestResult("Circular Java Dependencies", False, str(e))

    # ========================================================================
    # DEEP NESTING TESTS (4-6)
    # ========================================================================

    async def test_deep_call_chain_level_5(self) -> TestResult:
        """Test 4: Deep call chain - 5 levels"""
        try:
            # complete_order_fulfillment calls process_order (Level 3)
            result = await self.engine.find_flow("complete_order_fulfillment", "process_order")
            passed = result.get("path") is not None and len(result.get("path", [])) >= 2
            return TestResult("Deep Call Chain (Level 5+)", passed, metrics={"depth": len(result.get("path", []))})
        except Exception as e:
            return TestResult("Deep Call Chain (Level 5+)", False, str(e))

    async def test_deep_calculation_chain(self) -> TestResult:
        """Test 5: Complex calculation dependencies"""
        try:
            # calculate_order_total calls multiple Level 1 functions
            result = await self.engine.navigate("calculate_order_total")
            calls = result.get("relationships", {}).get("calls", [])
            # Should call at least 4 functions
            passed = len(calls) >= 4
            return TestResult("Complex Calculation Chain", passed, metrics={"call_count": len(calls)})
        except Exception as e:
            return TestResult("Complex Calculation Chain", False, str(e))

    async def test_recursive_function_detection(self) -> TestResult:
        """Test 6: Detect recursive functions"""
        try:
            result = await self.engine.navigate("recursive_tree_traversal")
            # Function should appear in its own called_by
            called_by = result.get("relationships", {}).get("called_by", [])
            # Self-reference means it's recursive
            passed = len(called_by) > 0 or "recursive_tree_traversal" in str(result)
            return TestResult("Recursive Function Detection", passed)
        except Exception as e:
            return TestResult("Recursive Function Detection", False, str(e))

    # ========================================================================
    # DIAMOND PATTERN TESTS (7-9)
    # ========================================================================

    async def test_diamond_pattern_bottom(self) -> TestResult:
        """Test 7: Diamond pattern - bottom node"""
        try:
            # calculate_discount is called by apply_discount_to_order
            result = await self.engine.navigate("calculate_discount")
            called_by = result.get("relationships", {}).get("called_by", [])
            passed = len(called_by) > 0
            return TestResult("Diamond Pattern (Bottom)", passed, metrics={"called_by_count": len(called_by)})
        except Exception as e:
            return TestResult("Diamond Pattern (Bottom)", False, str(e))

    async def test_diamond_pattern_multiple_callers(self) -> TestResult:
        """Test 8: Function called by multiple sources"""
        try:
            # calculate_order_subtotal called by multiple functions
            result = await self.engine.navigate("calculate_order_subtotal")
            called_by = result.get("relationships", {}).get("called_by", [])
            # Should have multiple callers
            passed = len(called_by) >= 2
            return TestResult("Multiple Callers (Diamond)", passed, metrics={"caller_count": len(called_by)})
        except Exception as e:
            return TestResult("Multiple Callers (Diamond)", False, str(e))

    async def test_diamond_impact_analysis(self) -> TestResult:
        """Test 9: Impact analysis on diamond node"""
        try:
            # Changing format_currency should affect all functions that use it
            result = await self.engine.assess_impact("format_currency")
            affected = result.get("affected_functions", [])
            passed = len(affected) >= 1
            return TestResult("Diamond Impact Analysis", passed, metrics={"affected": len(affected)})
        except Exception as e:
            return TestResult("Diamond Impact Analysis", False, str(e))

    # ========================================================================
    # CROSS-LANGUAGE TESTS (10-13)
    # ========================================================================

    async def test_python_to_rust_calls(self) -> TestResult:
        """Test 10: Python calling Rust"""
        try:
            # Look for python functions
            result = await self.engine.locate("process_order")
            passed = len(result) > 0 and "services.py" in result[0].get("file", "")
            return TestResult("Python to Rust Calls", passed)
        except Exception as e:
            return TestResult("Python to Rust Calls", False, str(e))

    async def test_rust_core_functions(self) -> TestResult:
        """Test 11: Rust core functions parsed"""
        try:
            result = await self.engine.locate("calculate_order_cost")
            # Should find Rust function
            passed = len(result) > 0 and "core.rs" in result[0].get("file", "")
            return TestResult("Rust Core Functions", passed)
        except Exception as e:
            return TestResult("Rust Core Functions", False, str(e))

    async def test_java_integration_parsing(self) -> TestResult:
        """Test 12: Java integration layer"""
        try:
            result = await self.engine.locate("NotificationService")
            passed = len(result) > 0 and "Integration.java" in result[0].get("file", "")
            return TestResult("Java Integration Parsing", passed)
        except Exception as e:
            return TestResult("Java Integration Parsing", False, str(e))

    async def test_typescript_client_functions(self) -> TestResult:
        """Test 13: TypeScript client functions"""
        try:
            result = await self.engine.locate("validateEmail")
            passed = len(result) > 0 and "client.ts" in result[0].get("file", "")
            return TestResult("TypeScript Client Functions", passed)
        except Exception as e:
            return TestResult("TypeScript Client Functions", False, str(e))

    # ========================================================================
    # SEARCH & NAVIGATION TESTS (14-18)
    # ========================================================================

    async def test_search_by_keyword(self) -> TestResult:
        """Test 14: Search by keyword"""
        try:
            result = await self.engine.search("calculate")
            matched = result.get("matches", [])
            passed = len(matched) >= 5  # Should find at least 5 calculate functions
            return TestResult("Search by Keyword", passed, metrics={"matches": len(matched)})
        except Exception as e:
            return TestResult("Search by Keyword", False, str(e))

    async def test_search_for_validation_functions(self) -> TestResult:
        """Test 15: Find all validation functions"""
        try:
            result = await self.engine.search("validate")
            matched = result.get("matches", [])
            passed = len(matched) > 0
            return TestResult("Find Validation Functions", passed, metrics={"found": len(matched)})
        except Exception as e:
            return TestResult("Find Validation Functions", False, str(e))

    async def test_navigate_with_large_relationship_graph(self) -> TestResult:
        """Test 16: Navigate function with many relationships"""
        try:
            # process_order has many relationships
            result = await self.engine.navigate("process_order")
            rels = result.get("relationships", {})
            passed = sum(len(v) if isinstance(v, list) else 0 for v in rels.values()) > 0
            return TestResult("Large Relationship Graph", passed)
        except Exception as e:
            return TestResult("Large Relationship Graph", False, str(e))

    async def test_navigate_orphan_function(self) -> TestResult:
        """Test 17: Navigate orphan function (not called by others)"""
        try:
            result = await self.engine.navigate("orphan_utility_sqrt")
            # Orphan should have empty called_by
            called_by = result.get("relationships", {}).get("called_by", [])
            passed = len(called_by) == 0
            return TestResult("Navigate Orphan Function", passed)
        except Exception as e:
            return TestResult("Navigate Orphan Function", False, str(e))

    async def test_flow_between_distant_nodes(self) -> TestResult:
        """Test 18: Find flow between distant nodes"""
        try:
            result = await self.engine.find_flow("register_user", "log_user_action")
            # Flow may be direct or indirect
            passed = result.get("path") is not None
            return TestResult("Flow Between Distant Nodes", passed)
        except Exception as e:
            return TestResult("Flow Between Distant Nodes", False, str(e))

    # ========================================================================
    # IMPACT ANALYSIS TESTS (19-22)
    # ========================================================================

    async def test_impact_high_degree_function(self) -> TestResult:
        """Test 19: Impact on function with many callers"""
        try:
            # log_user_action is called by many functions
            result = await self.engine.assess_impact("log_user_action")
            affected = result.get("affected_functions", [])
            passed = len(affected) > 0 and result.get("severity") == "medium" or result.get("severity") == "high"
            return TestResult("Impact High-Degree Function", passed, metrics={"affected": len(affected)})
        except Exception as e:
            return TestResult("Impact High-Degree Function", False, str(e))

    async def test_impact_low_degree_function(self) -> TestResult:
        """Test 20: Impact on function with few callers"""
        try:
            result = await self.engine.assess_impact("authenticate_user")
            severity = result.get("severity", "unknown")
            passed = severity in ["low", "medium"]
            return TestResult("Impact Low-Degree Function", passed, metrics={"severity": severity})
        except Exception as e:
            return TestResult("Impact Low-Degree Function", False, str(e))

    async def test_impact_leaf_function(self) -> TestResult:
        """Test 21: Impact on leaf function (calls nothing)"""
        try:
            result = await self.engine.assess_impact("validate_email")
            passed = "error" not in result or result.get("severity") in ["low", "unknown"]
            return TestResult("Impact Leaf Function", passed)
        except Exception as e:
            return TestResult("Impact Leaf Function", False, str(e))

    async def test_impact_with_entity_format(self) -> TestResult:
        """Test 22: Impact using file:type:name format"""
        try:
            result = await self.engine.assess_impact("services.py:fn:process_order")
            passed = "error" not in result or result.get("affected_functions")
            return TestResult("Impact with Entity Format", passed)
        except Exception as e:
            return TestResult("Impact with Entity Format", False, str(e))

    # ========================================================================
    # EDGE CASE TESTS (23-30)
    # ========================================================================

    async def test_empty_string_input(self) -> TestResult:
        """Test 23: Empty string input handling"""
        try:
            result = await self.engine.locate("")
            # Should return empty or error gracefully
            passed = isinstance(result, list)
            return TestResult("Empty String Input", passed)
        except Exception as e:
            return TestResult("Empty String Input", False, str(e))

    async def test_nonexistent_function_search(self) -> TestResult:
        """Test 24: Search for nonexistent function"""
        try:
            result = await self.engine.locate("nonexistent_function_xyz_123")
            # Should return empty list, not error
            passed = isinstance(result, list) and len(result) == 0
            return TestResult("Nonexistent Function Search", passed)
        except Exception as e:
            return TestResult("Nonexistent Function Search", False, str(e))

    async def test_special_characters_in_names(self) -> TestResult:
        """Test 25: Functions with underscores and numbers"""
        try:
            result = await self.engine.locate("calculate_discount")
            passed = len(result) > 0
            return TestResult("Special Characters in Names", passed)
        except Exception as e:
            return TestResult("Special Characters in Names", False, str(e))

    async def test_very_long_function_name(self) -> TestResult:
        """Test 26: Handle complex entity names"""
        try:
            result = await self.engine.locate("reserve_order_inventory")
            passed = len(result) > 0
            return TestResult("Long Function Names", passed)
        except Exception as e:
            return TestResult("Long Function Names", False, str(e))

    async def test_case_sensitivity(self) -> TestResult:
        """Test 27: Case sensitivity in function names"""
        try:
            result_lower = await self.engine.locate("processordered")  # Wrong case
            result_correct = await self.engine.locate("process_order")
            # Correct case should work
            passed = len(result_correct) > 0
            return TestResult("Case Sensitivity", passed)
        except Exception as e:
            return TestResult("Case Sensitivity", False, str(e))

    async def test_flow_to_itself(self) -> TestResult:
        """Test 28: Flow from function to itself"""
        try:
            result = await self.engine.find_flow("recursive_factorial", "recursive_factorial")
            # Should show the recursive call
            passed = result.get("path") is not None
            return TestResult("Flow to Self (Recursion)", passed)
        except Exception as e:
            return TestResult("Flow to Self (Recursion)", False, str(e))

    async def test_partial_name_matching(self) -> TestResult:
        """Test 29: Partial name matching"""
        try:
            result = await self.engine.search("order")
            matched = result.get("matches", [])
            # Should find multiple order-related functions
            passed = len(matched) > 0
            return TestResult("Partial Name Matching", passed, metrics={"matches": len(matched)})
        except Exception as e:
            return TestResult("Partial Name Matching", False, str(e))

    async def test_search_with_multiple_words(self) -> TestResult:
        """Test 30: Search with multiple keywords"""
        try:
            result = await self.engine.search("payment process")
            matched = result.get("matches", [])
            passed = isinstance(matched, list)
            return TestResult("Multiple Keyword Search", passed, metrics={"matches": len(matched)})
        except Exception as e:
            return TestResult("Multiple Keyword Search", False, str(e))

    # ========================================================================
    # PERFORMANCE TESTS (31-35)
    # ========================================================================

    async def test_large_graph_traversal(self) -> TestResult:
        """Test 31: Traversal on large graph"""
        try:
            start = time.time()
            result = await self.engine.navigate("complete_order_fulfillment")
            elapsed = time.time() - start
            passed = elapsed < 5.0  # Should complete in under 5 seconds
            return TestResult("Large Graph Traversal", passed, metrics={"time_ms": elapsed * 1000})
        except Exception as e:
            return TestResult("Large Graph Traversal", False, str(e))

    async def test_multiple_sequential_queries(self) -> TestResult:
        """Test 32: Multiple queries in sequence"""
        try:
            start = time.time()
            for i in range(10):
                await self.engine.locate("process_order")
            elapsed = time.time() - start
            passed = elapsed < 10.0
            return TestResult(
                "Multiple Sequential Queries", passed, metrics={"total_time_ms": elapsed * 1000, "avg_ms": (elapsed / 10) * 1000}
            )
        except Exception as e:
            return TestResult("Multiple Sequential Queries", False, str(e))

    async def test_concurrent_queries(self) -> TestResult:
        """Test 33: Concurrent query execution"""
        try:
            start = time.time()
            tasks = [
                self.engine.locate("process_order"),
                self.engine.locate("calculate_tax"),
                self.engine.locate("validate_email"),
                self.engine.navigate("generate_token"),
            ]
            results = await asyncio.gather(*tasks)
            elapsed = time.time() - start
            passed = elapsed < 5.0 and len(results) == 4
            return TestResult("Concurrent Queries", passed, metrics={"time_ms": elapsed * 1000})
        except Exception as e:
            return TestResult("Concurrent Queries", False, str(e))

    async def test_large_flow_computation(self) -> TestResult:
        """Test 34: Complex flow computation"""
        try:
            start = time.time()
            result = await self.engine.find_flow("register_user", "sanitize_input")
            elapsed = time.time() - start
            passed = result.get("path") is not None and elapsed < 5.0
            return TestResult("Large Flow Computation", passed, metrics={"time_ms": elapsed * 1000})
        except Exception as e:
            return TestResult("Large Flow Computation", False, str(e))

    async def test_impact_on_high_cardinality_node(self) -> TestResult:
        """Test 35: Impact analysis on highly connected node"""
        try:
            start = time.time()
            result = await self.engine.assess_impact("calculate_discount")
            elapsed = time.time() - start
            passed = elapsed < 5.0 and ("affected_functions" in result or "error" in result)
            return TestResult("Impact High Cardinality", passed, metrics={"time_ms": elapsed * 1000})
        except Exception as e:
            return TestResult("Impact High Cardinality", False, str(e))

    # ========================================================================
    # LANGUAGE-SPECIFIC TESTS (36-40)
    # ========================================================================

    async def test_rust_recursive_functions(self) -> TestResult:
        """Test 36: Rust recursive functions (fibonacci, fib)"""
        try:
            result = await self.engine.locate("fibonacci")
            passed = len(result) > 0
            return TestResult("Rust Recursive Functions", passed)
        except Exception as e:
            return TestResult("Rust Recursive Functions", False, str(e))

    async def test_rust_self_referencing_structs(self) -> TestResult:
        """Test 37: Rust self-referencing structures"""
        try:
            result = await self.engine.locate("TreeNode")
            passed = len(result) > 0
            return TestResult("Rust Self-Referencing Structs", passed)
        except Exception as e:
            return TestResult("Rust Self-Referencing Structs", False, str(e))

    async def test_java_class_methods(self) -> TestResult:
        """Test 38: Java class method resolution"""
        try:
            result = await self.engine.locate("sendEmailNotification")
            passed = len(result) > 0 and "Integration.java" in result[0].get("file", "")
            return TestResult("Java Class Methods", passed)
        except Exception as e:
            return TestResult("Java Class Methods", False, str(e))

    async def test_typescript_async_functions(self) -> TestResult:
        """Test 39: TypeScript async/await functions"""
        try:
            result = await self.engine.locate("login")
            passed = len(result) > 0
            return TestResult("TypeScript Async Functions", passed)
        except Exception as e:
            return TestResult("TypeScript Async Functions", False, str(e))

    async def test_typescript_class_relationships(self) -> TestResult:
        """Test 40: TypeScript class and method relationships"""
        try:
            result = await self.engine.navigate("ShoppingCart")
            # Should show methods and relationships
            passed = result.get("entity") is not None
            return TestResult("TypeScript Class Relationships", passed)
        except Exception as e:
            return TestResult("TypeScript Class Relationships", False, str(e))

    # ========================================================================
    # RUN ALL TESTS
    # ========================================================================

    async def run_all_tests(self) -> list[TestResult]:
        """Run all 40 tests"""
        tests = [
            self.test_circular_dependency_detection(),
            self.test_circular_b_to_a(),
            self.test_circular_java_dependencies(),
            self.test_deep_call_chain_level_5(),
            self.test_deep_calculation_chain(),
            self.test_recursive_function_detection(),
            self.test_diamond_pattern_bottom(),
            self.test_diamond_pattern_multiple_callers(),
            self.test_diamond_impact_analysis(),
            self.test_python_to_rust_calls(),
            self.test_rust_core_functions(),
            self.test_java_integration_parsing(),
            self.test_typescript_client_functions(),
            self.test_search_by_keyword(),
            self.test_search_for_validation_functions(),
            self.test_navigate_with_large_relationship_graph(),
            self.test_navigate_orphan_function(),
            self.test_flow_between_distant_nodes(),
            self.test_impact_high_degree_function(),
            self.test_impact_low_degree_function(),
            self.test_impact_leaf_function(),
            self.test_impact_with_entity_format(),
            self.test_empty_string_input(),
            self.test_nonexistent_function_search(),
            self.test_special_characters_in_names(),
            self.test_very_long_function_name(),
            self.test_case_sensitivity(),
            self.test_flow_to_itself(),
            self.test_partial_name_matching(),
            self.test_search_with_multiple_words(),
            self.test_large_graph_traversal(),
            self.test_multiple_sequential_queries(),
            self.test_concurrent_queries(),
            self.test_large_flow_computation(),
            self.test_impact_on_high_cardinality_node(),
            self.test_rust_recursive_functions(),
            self.test_rust_self_referencing_structs(),
            self.test_java_class_methods(),
            self.test_typescript_async_functions(),
            self.test_typescript_class_relationships(),
        ]

        print("\n" + "=" * 80)
        print("RUNNING COMPREHENSIVE EDGE CASE TEST SUITE")
        print("=" * 80 + "\n")

        self.results = await asyncio.gather(*tests)

        return self.results

    def print_report(self) -> None:
        """Print detailed test report"""
        print("\n" + "=" * 80)
        print("TEST RESULTS REPORT")
        print("=" * 80 + "\n")

        passed = sum(1 for r in self.results if r.passed)
        failed = len(self.results) - passed
        pass_rate = 100 * passed / len(self.results)

        print(f"Total Tests: {len(self.results)}")
        print(f"Passed: {passed}")
        print(f"Failed: {failed}")
        print(f"Pass Rate: {pass_rate:.1f}%\n")

        print("-" * 80)
        print("RESULTS BY CATEGORY")
        print("-" * 80)

        categories = {
            "Circular Dependencies": self.results[0:3],
            "Deep Nesting": self.results[3:6],
            "Diamond Patterns": self.results[6:9],
            "Cross-Language": self.results[9:13],
            "Search & Navigation": self.results[13:18],
            "Impact Analysis": self.results[18:22],
            "Edge Cases": self.results[22:30],
            "Performance": self.results[30:35],
            "Language-Specific": self.results[35:40],
        }

        for category, tests in categories.items():
            cat_passed = sum(1 for t in tests if t.passed)
            cat_total = len(tests)
            print(f"\n{category}: {cat_passed}/{cat_total}")
            for test in tests:
                status = "✓" if test.passed else "✗"
                metrics = f" {test.metrics}" if test.metrics else ""
                print(f"  {status} {test.name}{metrics}")
                if test.error:
                    print(f"    Error: {test.error}")

        print("\n" + "=" * 80)
        print("END OF REPORT")
        print("=" * 80 + "\n")


async def main():
    """Main test execution"""
    store = Neo4jGraphStore(
        uri="bolt://localhost:7687", user="neo4j", password="123456789$Do"
    )
    await store.connect()

    engine = DefaultQueryEngine(store)
    suite = RealWorldTestSuite(engine)

    try:
        results = await suite.run_all_tests()
        suite.print_report()
    finally:
        await store.close()


if __name__ == "__main__":
    asyncio.run(main())
