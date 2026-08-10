import js from '@eslint/js'
import svelte from 'eslint-plugin-svelte'
import globals from 'globals'
import ts from 'typescript-eslint'

export default [
  { ignores: ['dist/', 'node_modules/', '.svelte-kit/'] },
  js.configs.recommended,
  ...ts.configs.recommended,
  ...svelte.configs.recommended,
  {
    languageOptions: {
      globals: { ...globals.browser, ...globals.node },
    },
  },
  {
    // `*.svelte.ts` is a rune module rather than a component, and eslint-plugin-svelte claims it
    // too — so it needs the TS parser named here as well, or `interface` is a parse error inside a
    // plain TypeScript file (KAN-552, `tests/reactive.svelte.ts`).
    files: ['**/*.svelte', '**/*.svelte.ts', '**/*.svelte.js'],
    languageOptions: {
      parserOptions: { parser: ts.parser },
    },
  },
]
