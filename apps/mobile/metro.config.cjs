const { getDefaultConfig } = require("expo/metro-config");
const config = getDefaultConfig(__dirname);
// Keep cloud and local validation bounded; native bundles do not need a large worker pool.
config.maxWorkers = 1;
config.resolver.assetExts.push("wasm");
module.exports = config;
