import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["node_modules", "static"] },
  {
    files: ["**/*.{ts,tsx}"],
    extends: [
      tseslint.configs.recommended,
      reactHooks.configs.flat["recommended-latest"],
      reactRefresh.configs.vite,
    ],
  },
);
