"use client";

import { memo } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";

interface AppHeaderProps {
  showNewResearch?: boolean;
}

export default memo(function AppHeader({ showNewResearch }: AppHeaderProps): React.ReactNode {
  return (
    <header className="flex items-center justify-between px-8 py-6 border-b border-border bg-background sticky top-0 z-10 transition-all duration-300">
      <Link href="/" className="flex items-center gap-3 group">
        <div className="w-10 h-10 border border-primary flex items-center justify-center text-primary bg-transparent group-hover:bg-primary group-hover:text-primary-foreground transition-colors duration-500">
          <span className="font-serif text-xl italic">D</span>
        </div>
        <div className="flex flex-col">
          <h1 className="text-2xl font-serif tracking-tight leading-none">Deep Research</h1>
          <span className="text-[10px] uppercase tracking-[0.2em] text-muted-foreground font-sans">Intelligence Agent</span>
        </div>
      </Link>
      {showNewResearch && (
        <Button variant="outline" size="sm" className="rounded-none border-primary text-primary hover:bg-primary hover:text-primary-foreground font-sans uppercase tracking-widest text-xs px-6 transition-all duration-300" asChild>
          <Link href="/">New Inquiry</Link>
        </Button>
      )}
    </header>
  );
});