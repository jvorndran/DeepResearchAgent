import { useMemo, useState, useEffect, useRef } from "react";
import { prepare, layout } from "@chenglou/pretext";

export interface PretextOptions {
  whiteSpace?: "normal" | "pre-wrap";
  wordBreak?: "normal" | "keep-all";
}

const DEFAULT_PRETEXT_OPTIONS: PretextOptions = { whiteSpace: "pre-wrap" };

/**
 * Hook to measure text height using Pretext (without touching the DOM).
 * Useful for virtualization, auto-resizing textareas, etc.
 */
export function usePretextHeight(
  text: string,
  font: string,
  width: number,
  lineHeight: number,
  options: PretextOptions = DEFAULT_PRETEXT_OPTIONS
) {
  const { whiteSpace, wordBreak } = options;

  const prepared = useMemo(() => {
    if (!text) return null;
    return prepare(text, font, { whiteSpace, wordBreak });
  }, [text, font, whiteSpace, wordBreak]);

  return useMemo(() => {
    if (!prepared || width <= 0) return { height: 0, lineCount: 0 };
    return layout(prepared, width, lineHeight);
  }, [prepared, width, lineHeight]);
}

/**
 * Hook to automatically track an element's width.
 */
export function useElementWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);

  useEffect(() => {
    const element = ref.current;
    if (!element) return;

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setWidth(entry.contentRect.width);
      }
    });

    observer.observe(element);
    setWidth(element.getBoundingClientRect().width);

    return () => observer.disconnect();
  }, []);

  return { ref, width };
}
