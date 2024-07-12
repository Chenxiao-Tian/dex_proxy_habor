import path from "path";
import { fileURLToPath } from "url";
const __dirname = path.dirname(fileURLToPath(import.meta.url));

export default {
  entry: './dist/dex_proxy.js',
  output: {
    filename: 'main.js',
    path: path.resolve(__dirname, 'packed'),
  },
  experiments: {
    outputModule: false,
  },
  target: 'node20.9',
  mode: 'development'
}

