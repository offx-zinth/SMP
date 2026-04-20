"""End-to-end test script to verify all 14 language parsers work."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Add SMP to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from smp.core.models import Language
from smp.parser.registry import ParserRegistry


async def test_all_parsers() -> None:
    """Test parsing all 14 language samples."""
    registry = ParserRegistry()
    samples_dir = Path(__file__).parent / "e2e_test_samples"

    # Expected files for each language
    test_files = [
        ("example.py", Language.PYTHON),
        ("example.js", Language.JAVASCRIPT),
        ("example.ts", Language.TYPESCRIPT),
        ("Example.java", Language.JAVA),
        ("example.c", Language.C),
        ("example.cpp", Language.CPP),
        ("Example.cs", Language.CSHARP),
        ("example.go", Language.GO),
        ("example.rs", Language.RUST),
        ("example.php", Language.PHP),
        ("example.swift", Language.SWIFT),
        ("Example.kt", Language.KOTLIN),
        ("example.rb", Language.RUBY),
        ("example.m", Language.MATLAB),
    ]

    results = {}
    for filename, lang in test_files:
        filepath = samples_dir / filename
        if not filepath.exists():
            print(f"❌ {lang.value:12} - File not found: {filename}")
            results[lang.value] = "MISSING"
            continue

        try:
            doc = registry.parse_file(str(filepath))

            if doc.errors:
                print(
                    f"⚠️  {lang.value:12} - Parsed with {len(doc.errors)} errors: {doc.errors[:1]}"
                )
                results[lang.value] = f"ERRORS({len(doc.errors)})"
            elif not doc.nodes:
                print(f"❌ {lang.value:12} - No nodes extracted")
                results[lang.value] = "NO_NODES"
            else:
                funcs = [n for n in doc.nodes if n.type.value == "function"]
                classes = [n for n in doc.nodes if n.type.value == "class"]
                print(
                    f"✅ {lang.value:12} - {len(doc.nodes)} nodes ({len(classes)} classes, {len(funcs)} functions)"
                )
                results[lang.value] = "OK"
        except Exception as e:
            print(f"❌ {lang.value:12} - Exception: {e}")
            results[lang.value] = f"ERROR: {str(e)[:40]}"

    # Summary
    print("\n" + "=" * 70)
    ok_count = sum(1 for v in results.values() if v == "OK")
    print(f"Summary: {ok_count}/{len(test_files)} languages parsed successfully")
    if ok_count == len(test_files):
        print("🎉 All 14 language parsers working!")
    else:
        print(f"⚠️  {len(test_files) - ok_count} languages have issues")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(test_all_parsers())
