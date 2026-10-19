The extracted folders currently in this directory are source repositories, not
browser-ready distributions. The web app now uses npm package imports and a
Rollup build; it does not load these source folders directly.

- tabulator-master (Tabulator 6.6.1): its package metadata expects generated
  browser bundles under dist/js and dist/css. Those build outputs are absent.
- formulajs-formulajs-42dbeb1 (Formula.js 4.6.1): its package metadata expects
  a generated browser bundle at lib/browser/formula.min.js. That output is
  absent.

The source files under src/ use module imports and cannot be loaded directly by
the classic script tags in web/index.html. The extracted zip archives are also
source archives; keeping them here does not make the libraries available.

Package versions matching the checked-out sources are declared in
`web/package.json`: `tabulator-tables@6.6.1` and
`@formulajs/formulajs@4.6.1`. To build the browser assets, run these commands
from the `web` directory:

    npm install
    npm run build

Rollup resolves `import { TabulatorFull as Tabulator } from "tabulator-tables"` (the
full build with edit, sort, format and clipboard modules) and the Formula.js
module, then writes `web/dist/app.bundle.js` and `web/dist/tabulator.css`.
Include the generated `web/dist` files with the extension. They are required
runtime assets; Revit does not run npm or build them when the button starts.
