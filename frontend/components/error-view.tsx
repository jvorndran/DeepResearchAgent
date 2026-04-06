"use client";

import { useRouter } from "next/navigation";
import { Warning, ArrowLeft } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import type { ResearchStatus } from "@/lib/types";

interface ErrorViewProps {
  status: Extract<ResearchStatus, "failed" | "error">;
  errorText?: string;
}

export default function ErrorView({ status, errorText }: ErrorViewProps) {
  const router = useRouter();

  return (
    <div data-testid="error-view" className="flex-1 flex items-center justify-center p-6 md:p-12 lg:p-24 bg-background animate-in fade-in duration-1000">
      <div className="max-w-2xl w-full border border-destructive/30 bg-destructive/5 p-12 md:p-16 relative group">
        <div className="absolute -inset-0.5 bg-gradient-to-br from-destructive/20 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-1000 blur-md"></div>
        <div className="relative flex flex-col items-center text-center gap-8">
          <div className="w-20 h-20 border border-destructive text-destructive flex items-center justify-center mb-4">
            <Warning size={40} weight="light" />
          </div>
          
          <div className="flex flex-col gap-4">
            <h2 className="text-4xl md:text-5xl font-serif tracking-tight text-destructive">
              Synthesis Interrupted
            </h2>
            <div className="w-16 h-px bg-destructive mx-auto"></div>
            <p className="text-lg text-muted-foreground font-sans font-light max-w-lg mx-auto">
              {status === "failed"
                ? "The intelligence pipeline concluded without generating a viable report."
                : "A critical anomaly occurred during execution."}
            </p>
          </div>

          <div className="w-full text-left bg-background border border-destructive/20 p-6">
            <div className="text-[10px] uppercase tracking-[0.2em] text-destructive/70 font-mono mb-4">
              Error.Log
            </div>
            <p className="text-sm text-foreground/80 font-mono whitespace-pre-wrap leading-relaxed">
              {errorText || "The quality analyst may have rejected the report after maximum retries, or a system timeout occurred."}
            </p>
          </div>

          <Button 
            onClick={() => router.push("/")} 
            className="mt-8 rounded-none bg-transparent text-foreground hover:bg-destructive hover:text-destructive-foreground font-sans uppercase tracking-[0.15em] text-xs px-10 py-6 transition-all duration-500 border border-destructive/50 hover:border-destructive"
          >
            <ArrowLeft className="mr-3" weight="light" size={16} />
            Re-Initialize Protocol
          </Button>
        </div>
      </div>
    </div>
  );
}