"use client";

import * as React from "react"
import { usePretextHeight, useElementWidth } from "@/hooks/use-pretext"
import { cn } from "@/lib/utils"

export interface TextareaProps extends React.ComponentProps<"textarea"> {
  autoResize?: boolean;
  font?: string;
  lineHeight?: number;
  paddingVertical?: number;
  maxHeight?: number;
}

function Textarea({ 
  className, 
  autoResize = false,
  font = "12px sans-serif",
  lineHeight = 16,
  paddingVertical = 16,
  maxHeight = 300,
  style,
  value,
  ...props 
}: TextareaProps) {
  const { ref: containerRef, width } = useElementWidth<HTMLTextAreaElement>();
  
  // paddingHorizontal: textareas usually have some horizontal padding. 
  // We'll estimate based on px-2.5 (10px each side) unless overridden.
  const paddingHorizontal = 20;
  
  const { height: textHeight } = usePretextHeight(
    autoResize ? (typeof value === "string" ? value : "") : "",
    font,
    Math.max(0, width - paddingHorizontal),
    lineHeight
  );

  const calculatedHeight = autoResize 
    ? Math.min(maxHeight, Math.max(64, textHeight + paddingVertical))
    : undefined;

  const combinedStyle = autoResize 
    ? { ...style, height: `${calculatedHeight}px` }
    : style;

  return (
    <textarea
      ref={containerRef}
      data-slot="textarea"
      value={value}
      className={cn(
        "flex min-h-16 w-full rounded-none border border-input bg-transparent px-2.5 py-2 text-xs transition-colors outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-1 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:bg-input/50 disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-1 aria-invalid:ring-destructive/20 md:text-xs dark:bg-input/30 dark:disabled:bg-input/80 dark:aria-invalid:border-destructive/50 dark:aria-invalid:ring-destructive/40",
        autoResize ? "resize-none overflow-hidden" : "field-sizing-content",
        className
      )}
      style={combinedStyle}
      {...props}
    />
  )
}

export { Textarea }
