import tseslint from "typescript-eslint";
export default tseslint.config(
  { ignores: ["**/node_modules/**", "**/dist/**", "**/.expo/**"] },
  ...tseslint.configs.recommended,
  {
    rules: {
      "@typescript-eslint/no-require-imports": "off",
      "@typescript-eslint/no-explicit-any": "error",
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
    },
  },
);
