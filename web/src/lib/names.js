// Product names for template keys and model files - the UI never shows code ids.
// Raw names stay available as tooltips wherever these are used.

export const prettyTemplate = (t) => ({
  realism: "Realism",
  realism_ii: "Realism II",
  fantasy: "Fantasy",
  anime: "Anime",
  zimage: "Z-Image",
  identity_edit: "Identity Edit",
  zara_edit: "Identity Edit",        // pre-rename ledger entries
  qwen_edit: "Qwen Edit",
  qwen_image: "Qwen Image",
  face_mint: "New Face",
  klein_inpaint: "Klein Inpaint",
  klein_edit: "Klein Edit",
  anima: "Anima",
  upscale_image: "Upscale",
  upscale_video: "Upscale",
  ltx_i2v: "LTX 2.3",
  ltx25_i2v: "LTX 2.5",
  h3_i2v: "MiniMax H3",
  h3_multishot: "MiniMax H3 Multishot",
  h3_still: "MiniMax H3",
  h3_still_2x: "MiniMax H3 2x",
  h3_ref_still: "MiniMax H3 Ref",
  h3_ref_still_2x: "MiniMax H3 Ref 2x",
  vl_review: "review",
}[t] || String(t || "").replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase()));

// "krea2_turbo_mxfp8" -> "Krea 2 Turbo"; unknown files get a cleaned title-case
// with quant/precision noise stripped (the flavor matters, the packing doesn't).
const QUANT_NOISE = /\b(mxfp8|nvfp4|fp8(mixed|_scaled)?|int8(_\w+)?|convrot|scaled|bf16|fp16|fp32|gguf|i?q\d[_a-z0-9]*)\b/gi;

// "krea2_identity_edit_v1_2@1" -> "Identity Edit V1.2"; strength shown only
// when it isn't 1. "dropped unknown: X" honesty notes pass through untouched.
export const prettyLora = (s) => {
  const str = String(s);
  if (str.startsWith("dropped")) return str;
  const m = str.match(/^(.*?)(?:@([\d.]+))?$/);
  let name = (m[1] || str)
    .replace(/\.(safetensors|gguf)$/i, "")
    .replace(/(^|[_\s-])krea\s?2([_\s-]|$)/i, " ")
    .replace(/_v(\d+)_(\d+)/i, " v$1.$2")
    .replace(/[_]+/g, " ").replace(/\s+/g, " ").trim();
  name = name.replace(/\b\w/g, (c) => c.toUpperCase()) || str;
  return m[2] && m[2] !== "1" ? `${name} @${m[2]}` : name;
};

export const prettyModel = (m, family) => {
  if (!m) return m;
  let s = String(m).split(/[\\/]/).pop().replace(/\.(safetensors|gguf|ckpt|pt)$/i, "");
  if (family === "minimax_h3") {
    // The Animate picker's own wording (server _h3_finetune_label): packaging
    // words drop and the identity survives - "10eros_max_fl2va_beta2" reads
    // "10Eros Max Beta2". A stem that is ALL packaging (the stock builds)
    // composes family + variant + quant instead: "H3 FL2VA int8".
    const DROP = new Set(["h3", "fl2va", "ref2va", "pruned", "int8", "convrot",
                          "comfyui", "minimax"]);
    const words = s.split(/[_\-\s]+/).filter(Boolean);
    const identity = words.filter((w) => !DROP.has(w.toLowerCase()));
    if (identity.length)
      return identity.map((w) => w.toLowerCase()
        .replace(/(^|\d)([a-z])/g, (_m, a, b) => a + b.toUpperCase()))
        .join(" ");
    const PACK = new Set(["minimax", "pruned", "convrot", "comfyui"]);
    const TOKEN = { h3: "H3", fl2va: "FL2VA", ref2va: "REF2VA" };
    return words.filter((w) => !PACK.has(w.toLowerCase()))
      .map((w) => TOKEN[w.toLowerCase()] || w).join(" ") || "MiniMax H3";
  }
  // Official LTX weights carry the whole recipe in the filename
  // (ltx-2.5-22b-distilled-transformer-comfy-int8-convrot); the version and
  // whether it's the distilled build are the only parts a human chooses by.
  const ltx = s.match(/^ltx[ _-]?(\d+(?:\.\d+)?)/i);
  if (ltx) return `LTX ${ltx[1]}${/distilled/i.test(s) ? " Distilled" : ""}`;
  // Resolved family outranks filename branding. Normalize Z-Image's common
  // filename shorthand before presentation; a finetune named
  // `solordzZITZIBKrea2_zitV20` is truthfully shown as Z-Image Turbo, never as
  // a standalone Krea 2 badge.
  if (family === "zimage") {
    s = s.replace(/zitzibkrea\s?2/gi, " Z-Image ")
      .replace(/z[_ -]?image/gi, " Z-Image ")
      .replace(/krea\s?2/gi, " ")
      .replace(/zit(?=v?\d|[_ -]|$)/gi, " Turbo ")
      .replace(QUANT_NOISE, "")
      .replace(/[_]+/g, " ").replace(/\s+/g, " ").trim();
    s = s.replace(/\b\w/g, (c) => c.toUpperCase())
      .replace(/\bNsfw\b/g, "NSFW").replace(/\bV(?=\d)/g, "v");
    return s || "Z-Image";
  }
  const low = s.toLowerCase();
  // Before the "turbo" bit below, which on its own would present
  // anima-turbo-v1.0 as a model called "Turbo" with no family left in the name.
  if (family === "anima" || low.startsWith("anima")) {
    const rest = s.replace(/^anima[_ -]*/i, "").replace(QUANT_NOISE, "")
      .replace(/[_-]+/g, " ").replace(/\s+/g, " ").trim();
    return ("Anima " + rest).trim()
      .replace(/\b\w/g, (c) => c.toUpperCase()).replace(/\bV(?=\d)/g, "v");
  }
  const bits = [];
  if (family === "krea2" || low.includes("krea2") || low.includes("krea 2"))
    bits.push("Krea 2");
  if (low.includes("fineporn")) bits.push("Fineporn");
  if (low.includes("turbo")) bits.push("Turbo");
  if (bits.length) return bits.join(" ");
  s = s.replace(QUANT_NOISE, "").replace(/[_-]+/g, " ").replace(/\s+/g, " ").trim();
  return s ? s.replace(/\b\w/g, (c) => c.toUpperCase()) : m;
};

export const resolvedModelFamily = (info, template) => {
  if (info?.model_family) return info.model_family;
  if (String(info?.execution_profile || "").startsWith("zimage_")) return "zimage";
  if (String(info?.execution_profile || "").startsWith("anima_")) return "anima";
  if (template === "anima") return "anima";
  if (["zimage", "anime", "fantasy"].includes(template)) return "zimage";
  if (["realism", "realism_ii", "identity_edit", "zara_edit"].includes(template))
    return "krea2";
  if (template === "h3_i2v" || template === "h3_multishot") return "minimax_h3";
  return null;
};

// Model-family folder names for the picker. A family is a whole architecture,
// so this is the level someone actually chooses at ("I want Z-Image") before
// they care which build of it they are on.
const FAMILY_LABELS = {
  krea2: "Krea 2",
  klein: "FLUX.2 Klein",
  zimage: "Z-Image",
  qwen_image: "Qwen Image",
  qwen_edit: "Qwen Image Edit",
  flux: "Flux",
  minimax_h3: "MiniMax H3",
  video: "Video",
  audio: "Audio",
  auxiliary: "Auxiliary",
  unknown: "Other",
};

export const familyName = (f) => FAMILY_LABELS[f] ||
  String(f || "Other").replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase());

// What a family's variants are called in the folder view. Z-Image is the one
// that genuinely splits (Base vs Turbo are different schedules, not just
// different weights), so it is the case this exists for.
export const variantName = (v) => !v || v === "any" ? "" :
  String(v).replace(/\b\w/g, (c) => c.toUpperCase());

const PROFILE_LABELS = {
  zimage_base: "Base",
  zimage_turbo_v4: "Turbo v4",
  zimage_clear_anime: "Clear Anime",
};

export const prettyResolvedModel = (info, template) => {
  if (!info?.model) return "";
  const family = resolvedModelFamily(info, template);
  const model = prettyModel(info.model, family);
  const profile = PROFILE_LABELS[info.execution_profile] || info.execution_profile;
  return family === "zimage" && profile ? `${model} · ${profile}` : model;
};

// One line for a sampler schedule, everywhere it is stated: the tuning card's
// collapsed summary and the job card's record of what ran.
export const tuningLine = (t) => !t ? "" : [
  t.sampler_name, t.scheduler,
  t.steps !== undefined && t.steps !== null ? `${t.steps} steps` : null,
  t.cfg !== undefined && t.cfg !== null ? `cfg ${t.cfg}` : null,
  t.eta ? `eta ${t.eta}` : null,
].filter(Boolean).join(" · ");
