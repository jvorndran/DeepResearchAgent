"use client";

import ReactMarkdown from "react-markdown";
import { CheckCircle, ChartBar, FileText } from "@phosphor-icons/react";
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
        return chart ? <ReportChart key={index} chartId={chartId} chart={chart} /> : null;
      }
      return (
        <div key={index} className="prose prose-lg dark:prose-invert max-w-none prose-headings:font-serif prose-headings:font-normal prose-h1:text-5xl prose-h2:text-3xl prose-h3:text-2xl prose-p:font-sans prose-p:font-light prose-p:leading-relaxed prose-a:text-primary prose-a:underline-offset-4 hover:prose-a:text-primary/80 prose-blockquote:border-l-primary prose-blockquote:bg-primary/5 prose-blockquote:py-2 prose-blockquote:px-6 prose-blockquote:font-serif prose-blockquote:italic prose-blockquote:text-xl">
          <ReactMarkdown>{part}</ReactMarkdown>
        </div>
      );
    });
  };

  return (
    <div data-testid="report-view" className="flex-1 overflow-y-auto px-6 py-16 md:px-12 lg:px-24 bg-background">
      <div className="max-w-5xl mx-auto flex flex-col gap-24 pb-32 animate-in fade-in slide-in-from-bottom-12 duration-1000">
        
        {/* Report Header */}
        <header className="flex flex-col gap-8 text-center border-b border-border pb-16">
          <div className="flex items-center justify-center gap-3 text-[10px] uppercase tracking-[0.3em] text-primary font-sans">
            <CheckCircle weight="light" size={16} />
            <span>Intelligence Synthesis Complete</span>
          </div>
          <h1 data-testid="report-title" className="text-5xl md:text-7xl lg:text-8xl font-serif tracking-tighter text-foreground leading-[1.1] max-w-4xl mx-auto">
            {report.title}
          </h1>
          <div className="w-24 h-px bg-primary mx-auto mt-4"></div>
        </header>

        {/* Executive Summary */}
        <section data-testid="executive-summary" className="relative group">
          <div className="absolute -inset-8 bg-primary/5 opacity-0 group-hover:opacity-100 transition-opacity duration-1000 blur-2xl"></div>
          <div className="relative border-l-2 border-primary pl-8 md:pl-12 py-4">
            <div className="flex items-center gap-4 mb-6">
              <FileText className="text-primary" weight="light" size={32} />
              <h2 className="text-2xl font-serif uppercase tracking-widest text-foreground">Executive Brief</h2>
            </div>
            <p className="text-xl md:text-2xl font-sans font-light leading-relaxed text-foreground/80 max-w-3xl">
              {report.executive_summary}
            </p>
          </div>
        </section>

        {/* Main Content */}
        <article className="prose-container max-w-4xl mx-auto">
          {renderMarkdownWithCharts(report.markdown)}
        </article>

        {/* Data Sources */}
        {report.data_sources && report.data_sources.length > 0 && (
          <section className="mt-16 pt-16 border-t border-border">
            <div className="flex items-center gap-4 mb-12">
              <ChartBar className="text-primary" weight="light" size={32} />
              <h2 className="text-2xl font-serif uppercase tracking-widest text-foreground">Data Provenance</h2>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
              {report.data_sources.map((source, idx) => (
                <div key={idx} className="flex flex-col gap-3 p-6 border border-border/50 bg-muted/10 hover:border-primary/50 transition-colors duration-500">
                  <span className="font-serif text-2xl text-foreground">{source.provider}</span>
                  <span className="font-sans font-light text-sm text-muted-foreground leading-relaxed">{source.description}</span>
                  <div className="flex flex-wrap gap-2 mt-4">
                    {source.tickers?.map((t) => (
                      <span key={t} className="bg-transparent px-3 py-1 text-[10px] uppercase tracking-widest font-mono border border-border text-foreground/70">
                        {t}
                      </span>
                    ))}
                    {source.series_ids?.map((s) => (
                      <span key={s} className="bg-transparent px-3 py-1 text-[10px] uppercase tracking-widest font-mono border border-border text-foreground/70">
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