import { mkdirSync } from "node:fs";
import path from "node:path";
import commonjs from "@rollup/plugin-commonjs";
import { nodeResolve } from "@rollup/plugin-node-resolve";
import postcss from "rollup-plugin-postcss";

const outputDirectory = path.resolve("dist");
mkdirSync(outputDirectory, { recursive: true });

export default {
  input: "app.js",
  output: {
    file: path.join(outputDirectory, "app.bundle.js"),
    format: "iife",
    name: "KWExcelLink",
    sourcemap: false,
  },
  plugins: [
    nodeResolve(),
    commonjs(),
    postcss({
      extract: path.join(outputDirectory, "tabulator.css"),
      minimize: true,
      sourceMap: false,
    }),
  ],
};
