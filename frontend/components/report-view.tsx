"use client";

import ReactMarkdown from "react-markdown";
import { CaretRight, ChartBar, FileText } from "@phosphor-icons/react";
import ReportChart from "@/components/report-chart";
import type { ResearchReport } from "@/lib/types";

interface ReportViewProps {
  report: ResearchReport;
}

export default function ReportView({ report }: ReportViewProps) {
  const renderMarkdownWithCharts = (markdown: string) => {
    const parts = markdown.split(/(<!--\s*CHART:\S+?\s*-->)/g);
    return parts.map((part, index) => {
      const match = part.match(/<!--\s*CHART:(\S+?)\s*-->/);
      if (match) {
        const chartId = match[1];
        const chart = report.charts?.[chartId];
        return chart ? (
          <div key={index} className="my-12 p-6 bg-muted/30 rounded-xl border border-border">
            <ReportChart chartId={chartId} chart={chart} />
          </div>
        ) : null;
      }
      return <ReactMarkdown key={index}>{part}</ReactMarkdown>;
    });
  };

  return (
    <div data-testid="report-view" className="flex-1 overflow-y-auto p-4 md:p-8 lg:p-12 bg-background">
      <div className="max-w-5xl mx-auto flex flex-col gap-12 pb-24 pt-16 px-8 md:px-16 lg:px-24 bg-card shadow-2xl border border-border rounded-sm">
        
        {/* Report Header */}
        <header className="flex flex-col gap-4">
          <div className="flex items-center gap-2 text-sm font-bold text-foreground/90">
            <CaretRight weight="fill" className="text-primary" size={20} />
            <span>Investment Research</span>
          </div>
          <div className="w-full h-px bg-border mb-2"></div>
          <h1 data-testid="report-title" className="text-3xl md:text-4xl lg:text-5xl font-sans font-bold text-foreground leading-tight">
            {report.title}
          </h1>
        </header>

        {/* Executive Summary */}
        <section data-testid="executive-summary" className="border-l-4 border-primary pl-6 py-2">
          <h2 className="text-lg font-bold font-sans text-foreground mb-3">
            Executive Summary
          </h2>
          <p className="text-base font-sans leading-relaxed text-muted-foreground max-w-4xl">
            {report.executive_summary}
          </p>
        </section>

        {/* Main Content */}
        <article className="prose prose-slate max-w-none prose-headings:font-sans prose-headings:font-bold prose-headings:text-foreground prose-h1:text-3xl prose-h2:text-xl prose-h3:text-lg prose-p:font-sans prose-p:text-foreground/80 prose-p:leading-relaxed prose-a:text-primary prose-a:no-underline hover:prose-a:underline">
          {renderMarkdownWithCharts(report.markdown)}
        </article>

        {/* Data Sources */}
        {report.data_sources && report.data_sources.length > 0 && (
          <section className="mt-12 pt-8 border-t border-border">
            <div className="flex items-center gap-3 mb-6">
              <ChartBar className="text-muted-foreground" weight="regular" size={24} />
              <h2 className="text-lg font-bold font-sans text-foreground">Data Sources</h2>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {report.data_sources.map((source, idx) => (
                <div key={idx} className="flex flex-col gap-2 p-5 bg-muted/30 rounded-sm border border-border/50">
                  <span className="font-sans font-bold text-foreground">{source.provider}</span>
                  <span className="font-sans text-sm text-muted-foreground leading-relaxed">{source.description}</span>
                  <div className="flex flex-wrap gap-2 mt-3">
                    {source.tickers?.map((t) => (
                      <span key={t} className="bg-background px-2 py-1 text-xs font-mono text-muted-foreground border border-border rounded-sm">
                        {t}
                      </span>
                    ))}
                    {source.series_ids?.map((s) => (
                      <span key={s} className="bg-background px-2 py-1 text-xs font-mono text-muted-foreground border border-border rounded-sm">
                        {s}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}