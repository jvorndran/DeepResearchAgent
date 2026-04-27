"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { FileText } from "@phosphor-icons/react";
import AppHeader from "@/components/app-header";
import { apiFetch } from "@/lib/api";
import type { SavedReportSummary } from "@/lib/types";

export default function ReportLibraryClient() {
  const [reports, setReports] = useState<SavedReportSummary[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    apiFetch("/api/reports")
      .then(async (response) => {
        if (!response.ok) throw new Error(`Failed to load reports: ${response.status}`);
        return response.json();
      })
      .then((data) => {
        if (!cancelled) setReports(data.reports ?? []);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="min-h-screen bg-background text-foreground">
      <AppHeader showNewResearch />
      <main className="mx-auto flex w-full max-w-5xl flex-col gap-8 px-6 py-12 md:px-10">
        <header className="border-l-4 border-primary pl-6">
          <h1 className="text-4xl md:text-5xl font-serif tracking-tight">Saved Reports</h1>
          <p className="mt-3 max-w-2xl text-sm text-muted-foreground font-sans leading-relaxed">
            Completed research reports are saved automatically when the pipeline finishes.
          </p>
        </header>

        {error && <div className="border border-destructive/40 p-4 text-sm text-destructive">{error}</div>}

        <div className="grid gap-4">
          {reports.map((report) => (
            <Link
              key={report.job_id}
              href={`/chat/${report.job_id}`}
              className="group border border-border bg-card p-5 transition-colors hover:border-primary"
            >
              <div className="flex items-start gap-4">
                <div className="mt-1 flex h-9 w-9 shrink-0 items-center justify-center border border-primary/40 text-primary">
                  <FileText size={18} />
                </div>
                <div className="min-w-0 flex-1">
                  <h2 className="font-sans text-lg font-bold text-foreground group-hover:text-primary">
                    {report.title}
                  </h2>
                  <p className="mt-2 line-clamp-2 text-sm text-muted-foreground">{report.query}</p>
                  <div className="mt-4 text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
                    {new Date(report.created_at).toLocaleString()}
                  </div>
                </div>
              </div>
            </Link>
          ))}
          {!error && reports.length === 0 && (
            <div className="border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
              No saved reports yet.
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
