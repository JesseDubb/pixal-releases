import { useEffect, useLayoutEffect, useRef } from "react";
import { ArrowRight, Check, MagnifyingGlass, SlidersHorizontal, X } from "@phosphor-icons/react";
import { Btn } from "../lib/Btn.jsx";
import { FONT, MOTION } from "../lib/design-tokens.js";
import { SETTINGS, matchSettings } from "../lib/settings-layout.js";
import { flatten, indexPages } from "../lib/settings-search.js";


const groupPage = (content) => {
  const groups = [];
  for (const node of flatten(content)) {
    if (node.type?.settingsKind === "group") groups.push({ heading: node, children: [] });
    else {
      if (!groups.length) groups.push({ heading: null, children: [] });
      groups[groups.length - 1].children.push(node);
    }
  }
  return groups.map((group, i) => (
    <section className="px-settings-group" key={group.heading?.key || i}>
      {group.heading}
      <div className="px-settings-group-body">{group.children}</div>
    </section>
  ));
};

export const SettingsWorkspace = ({ pages, tab, onTab, onClose, query, onQuery,
  searchRef, bodyRef, note, busy, activity, loaded }) => {
  const headerRef = useRef(null);
  const scrollPositions = useRef({});
  const target = useRef(null);
  const active = pages.find((page) => page.id === tab) || pages[0];
  const searching = !!query.trim();
  const results = searching ? matchSettings(indexPages(pages), query) : [];
  const status = busy ? activity || "Working…"
    : note?.text || (loaded ? "Changes save automatically" : "Loading your settings…");
  useLayoutEffect(() => {
    const previous = document.activeElement;
    const settings = headerRef.current?.closest(".px-settings");
    headerRef.current?.querySelector('[role="tab"][tabindex="0"]')?.focus({ preventScroll: true });
    return () => {
      // Do not steal focus if the user opened a different surface from the rail.
      const focused = document.activeElement;
      if (focused === document.body || settings?.contains(focused)
          || focused?.closest('.px-picker[data-settings="true"]')) {
        previous?.isConnected && previous.focus({ preventScroll: true });
      }
    };
  }, []);
  useEffect(() => {
    const onEscape = (event) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      if (document.querySelector('.px-settings [aria-haspopup="listbox"][aria-expanded="true"]')) return;
      event.preventDefault();
      if (query) { onQuery(""); searchRef.current?.focus(); }
      else onClose();
    };
    window.addEventListener("keydown", onEscape);
    return () => window.removeEventListener("keydown", onEscape);
  }, [query, onQuery, onClose, searchRef]);
  const changeTab = (id) => {
    if (!searching) scrollPositions.current[tab] = bodyRef.current?.scrollTop || 0;
    onQuery(""); onTab(id);
  };
  useLayoutEffect(() => {
    const body = bodyRef.current;
    if (!body) return;
    if (target.current && !searching) {
      const node = [...body.querySelectorAll("[data-setting]")]
        .find((el) => el.dataset.setting === target.current);
      if (node) {
        target.current = null;
        node.scrollIntoView({ block: "center", behavior: "instant" });
        node.focus({ preventScroll: true });
        node.classList.add("px-setting-found");
        const timer = setTimeout(() => node.classList.remove("px-setting-found"), 1800);
        return () => { clearTimeout(timer); node.classList.remove("px-setting-found"); };
      }
    } else body.scrollTop = searching ? 0 : scrollPositions.current[tab] || 0;
  }, [tab, searching]);
  const openResult = (entry) => {
    target.current = entry.id; entry.reveal?.(); onQuery(""); onTab(entry.tab);
  };
  return (
    <>
      <style>{SETTINGS_CSS}</style>
      <header ref={headerRef} className="px-settings-header">
        <div className="px-settings-titlebar">
          <div className="px-settings-title"><SlidersHorizontal size={20} weight="duotone" />
            <h2>Settings</h2></div>
          <span className="px-settings-local">Your local studio</span>
          <Btn iconOnly size="sm" title="Close settings" onClick={onClose} icon={<X size={14} />} />
        </div>
        <div className="px-settings-search">
          <MagnifyingGlass size={16} aria-hidden="true" />
          <input ref={searchRef} value={query} aria-label="Search all settings"
            placeholder="Find a setting, model or engine…" autoComplete="off" spellCheck={false}
            onChange={(e) => onQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape" && query) { e.preventDefault(); e.stopPropagation(); onQuery(""); }
              if (e.key === "Enter" && results.length) openResult(results[0]);
              if (e.key === "ArrowDown" && results.length) {
                e.preventDefault(); bodyRef.current?.querySelector("button")?.focus();
              }
            }} />
          {query ? <Btn variant="link" iconOnly size="sm" title="Clear search"
            onClick={() => { onQuery(""); searchRef.current?.focus(); }} icon={<X size={14} />} />
            : <kbd>/</kbd>}
        </div>
        <nav className="px-settings-tabs" role="tablist" aria-label="Settings pages">
          {pages.map((page) => <button key={page.id} type="button" role="tab"
            id={`settings-tab-${page.id}`} aria-controls="settings-page"
            aria-selected={!searching && page.id === tab} tabIndex={page.id === tab ? 0 : -1}
            onClick={() => changeTab(page.id)}
            onKeyDown={(e) => {
              const delta = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
              if (!delta && e.key !== "Home" && e.key !== "End") return;
              e.preventDefault();
              const i = e.key === "Home" ? 0 : e.key === "End" ? pages.length - 1
                : (pages.indexOf(page) + delta + pages.length) % pages.length;
              changeTab(pages[i].id);
              e.currentTarget.parentNode.children[i]?.focus();
            }}>{page.label}</button>)}
        </nav>
      </header>
      <div ref={bodyRef} id="settings-page" role={searching ? "region" : "tabpanel"}
        onScroll={(e) => { if (!searching) scrollPositions.current[tab] = e.currentTarget.scrollTop; }}
        aria-label={searching ? "Search results" : undefined}
        aria-labelledby={searching ? undefined : `settings-tab-${tab}`}
        className={`px-scroll px-settings-body${tab === "about" && !searching ? " px-settings-about" : ""}`}>
        {searching ? <div className="px-settings-results" onKeyDown={(e) => {
          if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) return;
          const buttons = [...e.currentTarget.querySelectorAll("button")];
          const i = buttons.indexOf(e.target);
          if (i < 0) return;
          e.preventDefault();
          if (e.key === "ArrowUp" && i === 0) { searchRef.current?.focus(); return; }
          const next = e.key === "Home" ? 0 : e.key === "End" ? buttons.length - 1
            : (i + (e.key === "ArrowDown" ? 1 : -1) + buttons.length) % buttons.length;
          buttons[next]?.focus();
        }}>
          <div className="px-settings-result-count" role="status">
            {results.length ? `${results.length} result${results.length === 1 ? "" : "s"} across Settings` : "No matching settings"}
          </div>
          {results.map((entry, i) => <button type="button" key={`${entry.tab}-${entry.id}-${i}`}
            className="px-settings-result" onClick={() => openResult(entry)}>
            <span><span className="px-settings-result-path">{entry.path}</span>
              <span className="px-settings-result-name">{entry.label}</span></span>
            <ArrowRight size={16} />
          </button>)}
          {!results.length && <p>Try a model name, “memory”, or “upscale”.</p>}
        </div> : tab === "about" ? active.content : groupPage(active.content)}
      </div>
      <footer className="px-settings-footer" aria-live="polite" data-error={note && !note.ok ? "true" : undefined}>
        <span className="px-settings-save-icon" aria-hidden="true">{note && !note.ok ? "!" : busy || !loaded ? "·" : <Check size={13} weight="bold" />}</span>
        <span title={status}>{status}</span>
        <kbd title="Close settings">Esc</kbd>
      </footer>
    </>
  );
};

export const SETTINGS_CSS = `
.px-settings { container-type:inline-size; --picker-max-width:340px; }
.px-picker [role="option"]:focus-visible { outline:1px solid var(--accent); outline-offset:-1px; }
.px-settings-header { flex:none; padding:${SETTINGS.inset}px ${SETTINGS.inset}px 0; }
.px-settings-titlebar { display:flex; align-items:center; gap:12px; margin-bottom:20px; }
.px-settings-title { display:flex; align-items:center; gap:10px; color:var(--text); }
.px-settings-title > svg { color:var(--accent); }
.px-settings-title h2 { font-size:20px; font-weight:600; letter-spacing:-.035em; margin:0; line-height:1.2; }
.px-settings-local { margin-left:auto; color:var(--textSec); font-size:11px; }
.px-settings-search { display:flex; align-items:center; gap:10px; height:36px; padding:0 12px; border:1px solid var(--border); border-radius:10px; background:var(--surfaceInset); color:var(--textSec); transition:border-color ${MOTION.hover}; }
.px-settings-search:focus-within { border-color:var(--accentStr); box-shadow:0 0 0 3px var(--accentMut); }
.px-settings-search input { min-width:0; flex:1; border:0; outline:0; background:transparent; color:var(--text); font:400 12px ${FONT}; }
.px-settings-search input::placeholder { color:var(--textSec); }
.px-settings kbd { font:10px ui-monospace,monospace; color:var(--textSec); border:1px solid var(--borderHov); padding:2px 4px; border-radius:4px; }
.px-settings-tabs { display:flex; gap:24px; margin-top:12px; border-bottom:1px solid var(--border); }
.px-settings-tabs button { position:relative; flex:none; background:none; border:0; padding:14px 0; color:var(--textSec); cursor:pointer; font:500 12px ${FONT}; transition:color ${MOTION.hover}; }
.px-settings-tabs button::after { content:""; position:absolute; left:0; right:0; bottom:-1px; height:2px; background:var(--accent); border-radius:2px; opacity:0; transition:opacity ${MOTION.state}; }
.px-settings-tabs button[aria-selected="true"] { color:var(--text); }
.px-settings-tabs button[aria-selected="true"]::after { opacity:1; }
.px-settings-tabs button:hover { color:var(--text); }
.px-settings-body { flex:1; min-height:0; overflow-y:auto; overflow-x:hidden; padding:${SETTINGS.inset}px; display:flex; flex-direction:column; gap:${SETTINGS.groupGap}px; scrollbar-gutter:stable; }
.px-settings-body:not(.px-settings-about) { --textTer:color-mix(in srgb,var(--text) 54%,transparent); --textMut:color-mix(in srgb,var(--text) 38%,transparent); }
.px-settings-group { display:flex; flex-direction:column; gap:12px; min-width:0; }
.px-settings-group-body { display:flex; flex-direction:column; gap:${SETTINGS.cardGap}px; }
.px-settings-group-heading { display:flex; align-items:center; justify-content:space-between; gap:8px; font:500 10px ${FONT}; letter-spacing:.09em; text-transform:uppercase; color:var(--textTer); padding:0 2px; }
.px-settings-card, .px-settings-group-body > .px-set-rows { border:1px solid var(--border); border-radius:14px; padding:8px 16px; background:var(--surfaceInset); min-width:0; }
.px-settings-card { display:flex; flex-direction:column; gap:8px; }
.px-settings-card-header { display:flex; align-items:baseline; flex-wrap:wrap; gap:8px 12px; padding:8px 0 10px; border-bottom:1px solid var(--border); margin-bottom:2px; }
.px-settings-card-title { font:600 13px ${FONT}; color:var(--text); }
.px-settings-card-gloss { font:400 11px/1.45 ${FONT}; color:var(--textTer); }
.px-set-rows { display:flex; flex-direction:column; min-width:0; }
.px-setting { display:flex; align-items:center; gap:16px; min-height:${SETTINGS.row}px; padding:8px 0; border-radius:6px; outline:none; transition:background ${MOTION.state},box-shadow ${MOTION.state}; }
.px-setting-label { display:flex; flex:1 1 auto; flex-direction:column; justify-content:center; min-width:110px; gap:4px; }
.px-setting-name { color:var(--text); font:400 13px/1.4 ${FONT}; }
.px-setting-name > span { max-width:100%; }
.px-setting-hint { color:var(--textTer); font:400 11px/1.4 ${FONT}; overflow-wrap:anywhere; }
.px-setting-rail { display:flex; align-items:center; justify-content:flex-end; flex:0 1 auto; min-width:0; max-width:68%; margin-left:auto; }
.px-setting-rail > * { min-width:0; max-width:100%; }
.px-setting-found { background:var(--accentMut); box-shadow:0 0 0 6px var(--accentMut); }
.px-settings-card > div:has(> .px-setting) { width:100%; }
.px-settings-card > div > .px-setting:only-child { width:100%; }
.px-settings-footer { flex:none; height:42px; padding:0 24px; display:flex; align-items:center; gap:8px; border-top:1px solid var(--border); color:var(--textSec); font:400 11px/1.4 ${FONT}; background:transparent; }
.px-settings-save-icon { width:16px; height:16px; display:grid; place-items:center; color:var(--accentDim); flex:none; }
.px-settings-footer > span:nth-child(2) { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.px-settings-footer kbd { margin-left:auto; flex:none; }
.px-settings-footer[data-error="true"] { color:var(--text); background:var(--errorMut); }
.px-settings-footer[data-error="true"] .px-settings-save-icon { color:var(--text); }
.px-settings-results { display:flex; flex-direction:column; gap:8px; }
.px-settings-result-count { color:var(--textSec); font-size:11px; margin-bottom:8px; }
.px-settings-result { display:flex; align-items:center; justify-content:space-between; gap:20px; border:1px solid var(--border); border-radius:12px; padding:14px 16px; background:var(--surfaceInset); text-align:left; color:var(--textSec); cursor:pointer; font-family:${FONT}; transition:background ${MOTION.hover},border-color ${MOTION.hover}; }
.px-settings-result:hover { background:var(--bg3); border-color:var(--borderHov); }
.px-settings-result > span { min-width:0; }
.px-settings-result-path { display:block; font-size:10px; margin-bottom:5px; color:var(--textTer); }
.px-settings-result-name { display:block; font-size:13px; color:var(--text); overflow-wrap:anywhere; }
.px-settings-results p { font-size:12px; color:var(--textSec); }
.px-settings :is(button,input,[tabindex]):focus-visible { outline:2px solid var(--accent); outline-offset:3px; }
.px-settings input:focus-visible { outline-offset:1px; }
.px-settings-about { display:block; }
.px-library-summary { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); border:1px solid var(--border); border-radius:14px; background:var(--surfaceInset); padding:20px 4px; }
.px-library-summary > div { display:flex; flex-direction:column; gap:6px; padding:0 16px; }
.px-library-summary strong { font-size:24px; font-weight:500; letter-spacing:-.05em; line-height:1; color:var(--text); font-variant-numeric:tabular-nums; }
.px-library-summary span { color:var(--textTer); font-size:11px; }
.px-library-families { display:flex; flex-direction:column; gap:10px; }
.px-library-family { border:1px solid var(--border); border-radius:14px; background:var(--surfaceInset); overflow:hidden; }
.px-library-family-name { font:500 13px ${FONT}; }
.px-library-count { color:var(--textTer); font-size:11px; }
.px-library-family-size { margin-left:auto; color:var(--textTer); font:11px ui-monospace,monospace; }
.px-library-family-body { padding:0 16px 8px; }
.px-library-lanes { color:var(--textSec); font-size:11px; line-height:1.5; padding:0 0 12px; border-bottom:1px solid var(--border); margin-bottom:4px; }
.px-library-row { display:flex; align-items:flex-start; gap:16px; padding:12px 0; outline:none; }
.px-library-identity { flex:1; min-width:0; display:flex; flex-direction:column; gap:4px; }
.px-library-name { font-size:13px; font-weight:500; line-height:1.4; overflow-wrap:anywhere; }
.px-library-name a:hover { text-decoration:underline !important; text-underline-offset:3px; }
.px-library-file { color:var(--textTer); font:10px/1.5 ui-monospace,monospace; overflow-wrap:anywhere; }
.px-library-detail { color:var(--textSec); font-size:11px; line-height:1.4; }
.px-library-size { flex:none; color:var(--textSec); font:11px/1.6 ui-monospace,monospace; font-variant-numeric:tabular-nums; }
.px-library-absent { display:flex; justify-content:space-between; gap:16px; padding:14px 16px; border:1px dashed var(--borderHov); border-radius:14px; color:var(--textSec); font-size:12px; }
.px-library-absent > span + span { color:var(--textTer); font-size:11px; }
.px-memory-overview { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:24px; padding:8px 0 12px; }
.px-memory-stat { min-width:0; display:flex; flex-direction:column; gap:8px; }
.px-memory-stat > span:first-child { font-size:11px; color:var(--textTer); }
.px-memory-stat strong { font-size:20px; font-weight:500; letter-spacing:-.035em; color:var(--text); font-variant-numeric:tabular-nums; }
.px-memory-stat small { font-size:11px; font-weight:400; letter-spacing:0; color:var(--textTer); }
.px-memory-track { height:3px; width:100%; background:var(--bg4); border-radius:3px; overflow:hidden; }
.px-memory-track > span { display:block; height:100%; border-radius:inherit; }
@media(max-width:1100px) { .px-settings-tabs { gap:20px; } }
@container (max-width:520px) {
 .px-setting { flex-wrap:wrap; gap:10px 16px; }
 .px-setting-label { min-width:140px; }
 .px-setting-rail { max-width:100%; }
}
@media(max-width:540px) {
 .px-settings-header { padding:20px 16px 0; }
 .px-settings-body { padding:20px 16px; }
 .px-settings-tabs { justify-content:space-between; gap:10px; }
 .px-settings-local { display:none; }
 .px-settings-titlebar > button { margin-left:auto; }
 .px-settings-card,.px-settings-group-body > .px-set-rows { padding:8px 12px; }
 .px-setting { gap:10px; flex-wrap:wrap; }
 .px-setting-label { min-width:120px; }
 .px-setting-rail { max-width:100%; }
}
@media(prefers-reduced-motion:reduce) {
 .px-settings *, .px-settings *::after { transition:none !important; scroll-behavior:auto !important; }
}
`;
