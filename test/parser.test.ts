import test from 'node:test';
import assert from 'node:assert/strict';

import { parseFile, detectLanguage, generateNodeId } from '../src/core/parser';

const source = `import { helper } from './helper';

export function greet(name: string): string {
  return helper(name);
}

export class Greeter {
  say(name: string) {
    return greet(name);
  }
}
`;

test('detectLanguage infers file type from extension', () => {
  assert.equal(detectLanguage('a.ts'), 'typescript');
  assert.equal(detectLanguage('a.py'), 'python');
  assert.equal(detectLanguage('a.unknown'), 'unknown');
});

test('generateNodeId normalizes file path', () => {
  assert.equal(generateNodeId('func', 'greet', 'src/a-b.ts'), 'func_greet_src_a_b_ts');
});

test('parseFile extracts imports, exports, functions and classes', () => {
  const parsed = parseFile(source, 'src/greeter.ts');

  assert.equal(parsed.language, 'typescript');
  assert.equal(parsed.imports.length, 1);
  assert.equal(parsed.imports[0].from, './helper');

  const fn = parsed.nodes.find((node) => node.name === 'greet');
  assert.ok(fn, 'greet function should be parsed');

  const klass = parsed.nodes.find((node) => node.name === 'Greeter');
  assert.ok(klass, 'Greeter class should be parsed');

  assert.ok(parsed.exports.some((entry) => entry.name === 'greet'));
  assert.ok(parsed.exports.some((entry) => entry.name === 'Greeter'));
});
