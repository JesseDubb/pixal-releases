// three-loader.js — Three.js leaves the bundle and is fetched at runtime.
// three.module.js is 665KB minified, over half of what app.js used to be,
// and only the decorative logo (BlockLogo) needs it. So it
// ships as a static file under /vendor/, precached by sw.js, and arrives one
// dynamic import after boot instead of taxing every parse of the bundle.
//
// The specifier is ABSOLUTE on purpose: esbuild rewrites or inlines a
// relative dynamic import, and build.bat marks "/vendor/*" external, so this
// exact string survives into app.js untouched.
let pending = null;

export const loadThree = () => {
  if (!pending) {
    // One shared promise for every logo. A rejected import clears the memo so
    // the next call retries; a resolved one is kept for the life of the page.
    pending = import("/vendor/three.module.js").catch((err) => {
      pending = null;
      throw err;
    });
  }
  return pending;
};
