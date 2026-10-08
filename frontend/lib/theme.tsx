"use client";

import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useMemo, useState } from "react";

export type ThemePreference = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";

export const THEME_STORAGE_KEY = "botforge.theme";

/**
 * Runs in <head> before first paint (app/layout.tsx): resolves the stored preference (light | dark | system)
 * to light or dark and writes it to data-theme on <html>. Keep it in sync with resolve() below.
 */
export const THEME_INIT_SCRIPT = `(function(){var p="system";try{var s=localStorage.getItem("${THEME_STORAGE_KEY}");if(s==="light"||s==="dark")p=s}catch(e){}var d=p==="dark";if(p==="system"){try{d=window.matchMedia("(prefers-color-scheme: dark)").matches}catch(e){}}document.documentElement.setAttribute("data-theme",d?"dark":"light")})()`;

const QUERY = "(prefers-color-scheme: dark)";

function readPreference(): ThemePreference {
  try {
    const v = localStorage.getItem(THEME_STORAGE_KEY);
    if (v === "light" || v === "dark") return v;
  } catch {
    // storage blocked: fall through to system
  }
  return "system";
}

function systemTheme(): ResolvedTheme {
  try {
    return window.matchMedia(QUERY).matches ? "dark" : "light";
  } catch {
    return "light";
  }
}

function resolve(pref: ThemePreference): ResolvedTheme {
  return pref === "system" ? systemTheme() : pref;
}

interface ThemeContextValue {
  preference: ThemePreference;
  resolved: ResolvedTheme;
  setPreference: (pref: ThemePreference) => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

// useLayoutEffect warns on the server; the provider only needs it in the browser.
const useIsoLayoutEffect = typeof window === "undefined" ? useEffect : useLayoutEffect;

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  // The server cannot know the stored value; the inline script already painted the right theme, so state
  // starts neutral and syncs in a layout effect (no visible flash, no hydration mismatch).
  const [preference, setPreferenceState] = useState<ThemePreference>("system");
  const [resolved, setResolved] = useState<ResolvedTheme>("light");

  useIsoLayoutEffect(() => {
    const pref = readPreference();
    setPreferenceState(pref);
    setResolved(resolve(pref));
  }, []);

  // Always write the resolved value (also re-applies it after React's dev remount clears <html> attributes).
  useIsoLayoutEffect(() => {
    document.documentElement.setAttribute("data-theme", resolved);
  }, [resolved]);

  // While the preference is system, follow the operating system.
  useEffect(() => {
    if (preference !== "system") return;
    let mq: MediaQueryList;
    try {
      mq = window.matchMedia(QUERY);
    } catch {
      return;
    }
    const onChange = () => setResolved(mq.matches ? "dark" : "light");
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [preference]);

  // Keep several tabs in step.
  useEffect(() => {
    function onStorage(e: StorageEvent) {
      if (e.key !== THEME_STORAGE_KEY) return;
      const pref = readPreference();
      setPreferenceState(pref);
      setResolved(resolve(pref));
    }
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  const setPreference = useCallback((pref: ThemePreference) => {
    setPreferenceState(pref);
    setResolved(resolve(pref));
    try {
      if (pref === "system") localStorage.removeItem(THEME_STORAGE_KEY);
      else localStorage.setItem(THEME_STORAGE_KEY, pref);
    } catch {
      // storage blocked: the choice still applies for this page view
    }
  }, []);

  const value = useMemo(() => ({ preference, resolved, setPreference }), [preference, resolved, setPreference]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used inside <ThemeProvider>");
  return ctx;
}
