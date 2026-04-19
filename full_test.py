#!/usr/bin/env python3.11
"""
Comprehensive full test suite for all SMP MCP tool handlers.
Uses the CORRECT dispatcher keys and handles dynamic IDs.
"""
from __future__ import annotations

import asyncio
import json
import os
import traceback
from datetime import datetime
from typing import Any

# Enable safety features
os.environ['SMP_SAFETY_ENABLED'] = 'true'

from smp.protocol.mcp import app_lifespan
from smp.protocol.dispatcher import get_dispatcher


class MCPTestRunner:
    """Run comprehensive tests for all MCP tool handlers."""

    def __init__(self) -> None:
        self.results: dict[str, dict[str, Any]] = {}
        self.passed = 0
        self.failed = 0
        self.total = 0
        self.start_time = datetime.now()
        self.state: dict[str, Any] = {}
        self.last_session_id: str | None = None
        self.last_review_id: str | None = None

    async def test_handler(self, method_name: str, params: dict[str, Any]) -> bool:
        """Test a single handler via dispatcher."""
        self.total += 1
        try:
            dispatcher = get_dispatcher()
            handler = dispatcher.get_handler(method_name)

            if not handler:
                self.results[method_name] = {
                    'status': 'FAILED',
                    'error': f'Handler not found in dispatcher',
                }
                self.failed += 1
                return False

            # Handle dynamic params
            processed_params = params.copy()
            for k, v in processed_params.items():
                if v == 'USE_LAST_SESSION' and self.last_session_id:
                    processed_params[k] = self.last_session_id
                elif v == 'USE_LAST_REVIEW' and self.last_review_id:
                    processed_params[k] = self.last_review_id

            # Call handler with state context
            start = datetime.now()
            result = await handler.handle(processed_params, self.state)
            duration = (datetime.now() - start).total_seconds()

            # Capture IDs for subsequent tests
            if isinstance(result, dict):
                if 'session_id' in result:
                    self.last_session_id = result['session_id']
                if 'review_id' in result:
                    self.last_review_id = result['review_id']

            result_str = str(result)[:150] if result else 'None'
            self.results[method_name] = {
                'status': 'PASSED',
                'result': result_str,
                'duration': duration,
            }
            self.passed += 1
            return True

        except Exception as e:
            duration = (datetime.now() - start).total_seconds() if 'start' in locals() else 0
            error_msg = str(e).split('\n')[0][:100]
            self.results[method_name] = {
                'status': 'FAILED',
                'error': error_msg,
                'traceback': traceback.format_exc()[:500],
                'duration': duration,
            }
            self.failed += 1
            return False

    async def run_all_tests(self) -> None:
        """Run all handler tests within MCP server lifespan."""
        print(f'Starting comprehensive MCP tool handlers test suite...')
        print(f'Safety features: ENABLED')
        print(f'Test codebase: 11 nodes, 14 edges')
        print('=' * 80)

        # Initialize MCP server lifespan
        async with app_lifespan() as state:
            self.state = {
                'engine': state['engine'],
                'enricher': state['enricher'],
                'builder': state['builder'],
                'registry': state['registry'],
                'vector': state['vector'],
                'safety': state['safety'],
                'telemetry_engine': state['telemetry_engine'],
                'handoff_manager': state['handoff_manager'],
                'integrity_verifier': state['integrity_verifier'],
            }

            # Test parameters
            test_node_id = 'src/auth/manager.py::Function::authenticate_user::5'

            tests = [
                # Graph Intelligence (8)
                ('smp/navigate', {'query': 'authenticate_user'}),
                ('smp/locate', {'query': 'authenticate_user', 'top_k': 5}),
                ('smp/search', {'query': 'authentication function', 'top_k': 5}),
                ('smp/trace', {'start': 'authenticate_user', 'relationship': 'CALLS', 'direction': 'outgoing', 'depth': 2}),
                ('smp/flow', {'start': 'authenticate_user', 'end': 'get_user', 'flow_type': 'data'}),
                ('smp/context', {'file_path': 'src/auth/manager.py', 'depth': 2}),
                ('smp/impact', {'entity': 'authenticate_user', 'change_type': 'modify'}),
                ('smp/graph/why', {'entity': 'authenticate_user', 'depth': 2}),

                # Memory & Update (3)
                ('smp/update', {'file_path': 'src/auth/manager.py', 'change_type': 'modified'}),
                ('smp/batch_update', {'changes': [{'file_path': 'src/auth/manager.py', 'change_type': 'modified'}]}),
                ('smp/reindex', {'scope': 'full'}),

                # Enrichment (4)
                ('smp/enrich', {'node_id': test_node_id, 'force': False}),
                ('smp/enrich/batch', {'scope': 'full', 'force': False}),
                ('smp/enrich/status', {'scope': 'full'}),
                ('smp/enrich/stale', {'scope': 'full'}),

                # Annotation (3)
                ('smp/annotate', {'node_id': test_node_id, 'description': 'Test description', 'force': True}),
                ('smp/annotate/bulk', {'annotations': [{'node_id': test_node_id, 'description': 'Test'}]}),
                ('smp/tag', {'scope': 'full', 'tags': ['test'], 'action': 'add'}),

                # Telemetry (1)
                ('smp/telemetry', {'action': 'get_stats'}),

                # Safety (5)
                ('smp/session/open', {'mode': 'read', 'scope': ['src/auth/manager.py']}),
                ('smp/checkpoint', {'session_id': 'USE_LAST_SESSION', 'files': ['src/auth/manager.py']}),
                ('smp/lock', {'session_id': 'USE_LAST_SESSION', 'files': ['src/auth/manager.py']}),
                ('smp/unlock', {'session_id': 'USE_LAST_SESSION', 'files': ['src/auth/manager.py']}),
                ('smp/session/close', {'session_id': 'USE_LAST_SESSION', 'status': 'completed'}),

                # Additional
                ('smp/verify/integrity', {'node_id': test_node_id, 'session_id': 'USE_LAST_SESSION'}),
                ('smp/audit/get', {'audit_log_id': 'nonexistent'}),
                ('smp/dryrun', {'session_id': 'test', 'file_path': 'src/auth/manager.py', 'proposed_content': 'test', 'change_summary': 'test'}),
                ('smp/handoff/review', {'files_changed': ['src/auth/manager.py'], 'reviewers': ['test'], 'session_id': 'USE_LAST_SESSION'}),
                ('smp/handoff/approve', {'review_id': 'USE_LAST_REVIEW', 'reviewer': 'test-reviewer'}),
                ('smp/handoff/reject', {'review_id': 'USE_LAST_REVIEW', 'reviewer': 'test-reviewer', 'reason': 'test'}),
                ('smp/rollback', {'session_id': 'USE_LAST_SESSION', 'checkpoint_id': 'test-cp'}),
                ('smp/handoff/pr', {'review_id': 'USE_LAST_REVIEW', 'title': 'Test PR', 'body': 'Test', 'branch': 'test-branch'}),
                ('smp/guard/check', {'session_id': 'USE_LAST_SESSION', 'target': 'src/auth/manager.py', 'intended_change': 'modify'}),
            ]

            # Run all tests
            for method_name, params in tests:
                status = '✓' if await self.test_handler(method_name, params) else '✗'
                result_info = self.results.get(method_name, {})
                print(f'{status} {method_name:<40} {result_info.get("status", "UNKNOWN"):<10}', end='')
                if result_info.get('duration'):
                    print(f' ({result_info["duration"]:.3f}s)', end='')
                if result_info.get('error'):
                    error_msg = result_info['error'][:40]
                    print(f' {error_msg}', end='')
                print()

            print('=' * 80)
            self._print_summary()

    def _print_summary(self) -> None:
        """Print test summary."""
        total_time = (datetime.now() - self.start_time).total_seconds()

        print(f'\nTest Results Summary:')
        print(f'  Total Tests: {self.total}')
        print(f'  Passed: {self.passed} ({100*self.passed/self.total:.1f}%)')
        print(f'  Failed: {self.failed} ({100*self.failed/self.total:.1f}%)')
        print(f'  Duration: {total_time:.2f}s')

        # Group results by status
        passed_tools = [k for k, v in self.results.items() if v['status'] == 'PASSED']
        failed_tools = [k for k, v in self.results.items() if v['status'] == 'FAILED']

        if passed_tools:
            print(f'\n✓ Passed ({len(passed_tools)}):')
            for tool in sorted(passed_tools):
                print(f'  - {tool}')

        if failed_tools:
            print(f'\n✗ Failed ({len(failed_tools)}):')
            for tool in sorted(failed_tools):
                error = self.results[tool].get('error', 'Unknown error')
                print(f'  - {tool}')
                print(f'    Error: {error[:70]}')

        # Save detailed results
        self._save_results()

    def _save_results(self) -> None:
        """Save detailed results to JSON file."""
        results_file = '/home/bhagyarekhab/SMP/FULL_TEST_RESULTS.json'
        with open(results_file, 'w') as f:
            json.dump(self.results, f, indent=2)
        print(f'\nDetailed results saved to: {results_file}')


async def main() -> None:
    """Run the full test suite."""
    runner = MCPTestRunner()
    await runner.run_all_tests()


if __name__ == '__main__':
    asyncio.run(main())
