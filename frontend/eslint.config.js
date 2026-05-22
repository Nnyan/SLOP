// ESLint flat config for Mediastack Vue 3 frontend
// Core Rule 3.1: semantic checks on frontend, not just syntax
// Findings written to data/eslint_findings.json for LLM ingestion

import js from "@eslint/js";
import pluginVue from "eslint-plugin-vue";

export default [
  js.configs.recommended,
  ...pluginVue.configs["flat/recommended"],
  {
    files: ["src/**/*.vue", "src/**/*.js", "src/**/*.ts"],
    rules: {
      // Real bug prevention
      "no-unused-vars": "error",
      "no-undef": "error",
      "no-unreachable": "error",
      "no-constant-condition": "error",

      // Vue-specific real bugs
      "vue/no-unused-vars": "error",
      "vue/no-unused-components": "error",
      "vue/no-mutating-props": "error",       // Core Rule 2.3: test behavior
      "vue/require-v-for-key": "error",
      "vue/valid-v-if": "error",
      "vue/no-async-in-computed-properties": "error",
      "vue/no-side-effects-in-computed-properties": "error",

      // Security
      "no-eval": "error",                     // Core Rule 3.8
      "no-implied-eval": "error",

      // Style (warnings only — don't block CI)
      "vue/component-name-in-template-casing": ["warn", "PascalCase"],
      "vue/html-self-closing": "warn",
    },
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
    },
  },
  {
    ignores: ["dist/**", "node_modules/**", "*.min.js"],
  },
];
