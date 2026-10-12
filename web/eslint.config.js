// One job: catch a React hook called after an early return or inside a condition. Such a page compiles, passes type-checking,
// and renders blank the moment its data arrives.
import hooks from "eslint-plugin-react-hooks";
import ts from "typescript-eslint";

export default [
  { files: ["src/**/*.{ts,tsx}"], languageOptions: { parser: ts.parser, parserOptions: { ecmaFeatures: { jsx: true } } }, plugins: { "react-hooks": hooks },
    rules: { "react-hooks/rules-of-hooks": "error" } },
];
