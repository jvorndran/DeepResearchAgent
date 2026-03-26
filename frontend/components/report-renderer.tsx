"use client"

import { Separator } from "@/components/ui/separator"
import { WorkflowVisualizer } from "./workflow-visualizer"
import { DataChart } from "./data-chart"
import { DataPieChart } from "./pie-chart"
import { DataTable } from "./data-table"
import { MetricCards } from "./metric-cards"
import { TextSection, QuoteBlock, Callout } from "./text-section"
import { ExecutiveSummary } from "./executive-summary"
import { HeatmapChart } from "./heatmap-chart"
import { Timeline } from "./timeline"
import { ProgressList } from "./progress-list"
import { StatComparison } from "./stat-comparison"
import { NumberedList } from "./numbered-list"
import { ScatterPlot } from "./scatter-chart"
import type { 
  ReportBlock, 
  ReportSchema,
  ChartBlock,
  PieChartBlock,
  TableBlock,
  MetricsBlock,
  TextBlock,
  QuoteBlock as QuoteBlockType,
  CalloutBlock,
  SummaryBlock,
  WorkflowBlock,
  SectionHeaderBlock,
  HeatmapBlock,
  TimelineBlock,
  ProgressListBlock,
  StatComparisonBlock,
  NumberedListBlock,
  ScatterBlock,
} from "@/lib/report-schema"
import { cn } from "@/lib/utils"

interface ReportRendererProps {
  report: ReportSchema
}

// Render individual block based on type
function RenderBlock({ block }: { block: ReportBlock }) {
  switch (block.type) {
    case "workflow":
      return <WorkflowVisualizer collapsed={(block as WorkflowBlock).config.collapsed} />
    
    case "separator":
      return <Separator className="bg-border/30" />
    
    case "section-header": {
      const config = (block as SectionHeaderBlock).config
      return (
        <div className="pt-4">
          <h2 className="text-lg font-semibold tracking-tight text-foreground">
            {config.title}
          </h2>
          {config.subtitle && (
            <p className="mt-0.5 text-sm text-muted-foreground">{config.subtitle}</p>
          )}
        </div>
      )
    }
    
    case "summary": {
      const config = (block as SummaryBlock).config
      return (
        <ExecutiveSummary 
          title={config.title}
          keyFindings={config.keyFindings}
          conclusion={config.conclusion}
          dataSources={config.dataSources}
        />
      )
    }
    
    case "metrics": {
      const config = (block as MetricsBlock).config
      return <MetricCards metrics={config.metrics} title={config.title} />
    }
    
    case "chart": {
      const config = (block as ChartBlock).config
      return (
        <DataChart 
          data={config.data}
          series={config.series}
          xAxisKey={config.xAxisKey}
          title={config.title}
          subtitle={config.subtitle}
          height={config.height}
        />
      )
    }
    
    case "pie-chart": {
      const config = (block as PieChartBlock).config
      return (
        <DataPieChart
          data={config.data}
          title={config.title}
          subtitle={config.subtitle}
          innerRadius={config.innerRadius}
          valuePrefix={config.valuePrefix}
          valueSuffix={config.valueSuffix}
        />
      )
    }
    
    case "table": {
      const config = (block as TableBlock).config
      return (
        <DataTable
          data={config.data}
          columns={config.columns}
          title={config.title}
          subtitle={config.subtitle}
        />
      )
    }
    
    case "text": {
      const config = (block as TextBlock).config
      return (
        <TextSection title={config.title} variant={config.variant}>
          {config.content && (
            <p className="text-sm leading-relaxed text-muted-foreground">
              {config.content}
            </p>
          )}
          {config.subsections && config.subsections.length > 0 && (
            <div className="mt-4 space-y-3">
              {config.subsections.map((section, idx) => (
                <div key={idx}>
                  <h4 className="mb-1 text-xs font-semibold uppercase tracking-wider text-foreground/80">
                    {section.heading}
                  </h4>
                  <p className="text-sm text-muted-foreground">{section.content}</p>
                </div>
              ))}
            </div>
          )}
        </TextSection>
      )
    }
    
    case "quote": {
      const config = (block as QuoteBlockType).config
      return (
        <QuoteBlock 
          quote={config.quote} 
          source={config.source} 
          role={config.role} 
        />
      )
    }
    
    case "callout": {
      const config = (block as CalloutBlock).config
      return (
        <Callout type={config.variant} title={config.title}>
          {config.content}
        </Callout>
      )
    }
    
    case "heatmap": {
      const config = (block as HeatmapBlock).config
      return (
        <HeatmapChart
          title={config.title}
          subtitle={config.subtitle}
          data={config.data}
          rows={config.rows}
          cols={config.cols}
          valuePrefix={config.valuePrefix}
          valueSuffix={config.valueSuffix}
          minLabel={config.minLabel}
          maxLabel={config.maxLabel}
        />
      )
    }

    case "timeline": {
      const config = (block as TimelineBlock).config
      return <Timeline title={config.title} subtitle={config.subtitle} events={config.events} />
    }

    case "progress-list": {
      const config = (block as ProgressListBlock).config
      return (
        <ProgressList
          title={config.title}
          subtitle={config.subtitle}
          items={config.items}
          unit={config.unit}
          showRank={config.showRank}
        />
      )
    }

    case "stat-comparison": {
      const config = (block as StatComparisonBlock).config
      return (
        <StatComparison
          title={config.title}
          subtitle={config.subtitle}
          entities={config.entities}
        />
      )
    }

    case "numbered-list": {
      const config = (block as NumberedListBlock).config
      return (
        <NumberedList
          title={config.title}
          subtitle={config.subtitle}
          items={config.items}
          variant={config.variant}
        />
      )
    }

    case "scatter": {
      const config = (block as ScatterBlock).config
      return (
        <ScatterPlot
          title={config.title}
          subtitle={config.subtitle}
          series={config.series}
          xLabel={config.xLabel}
          yLabel={config.yLabel}
          height={config.height}
        />
      )
    }

    default:
      return null
  }
}

// Calculate grid column class based on width
function getWidthClass(width?: "full" | "half" | "third"): string {
  switch (width) {
    case "half":
      return "md:col-span-1"
    case "third":
      return "md:col-span-1"
    default:
      return "md:col-span-2"
  }
}

// Group blocks for grid layout
function groupBlocksForGrid(blocks: ReportBlock[]): ReportBlock[][] {
  const groups: ReportBlock[][] = []
  let currentGroup: ReportBlock[] = []
  let currentWidth = 0

  for (const block of blocks) {
    const blockWidth = block.width === "half" ? 1 : block.width === "third" ? 0.66 : 2
    
    if (currentWidth + blockWidth <= 2) {
      currentGroup.push(block)
      currentWidth += blockWidth
    } else {
      if (currentGroup.length > 0) {
        groups.push(currentGroup)
      }
      currentGroup = [block]
      currentWidth = blockWidth
    }
    
    // If we've filled the row, push it
    if (currentWidth >= 2) {
      groups.push(currentGroup)
      currentGroup = []
      currentWidth = 0
    }
  }
  
  // Push any remaining blocks
  if (currentGroup.length > 0) {
    groups.push(currentGroup)
  }
  
  return groups
}

export function ReportRenderer({ report }: ReportRendererProps) {
  const blockGroups = groupBlocksForGrid(report.blocks)
  
  return (
    <div className="space-y-6">
      {blockGroups.map((group, groupIndex) => {
        // If single full-width block, render directly
        if (group.length === 1 && (!group[0].width || group[0].width === "full")) {
          return (
            <RenderBlock key={group[0].id} block={group[0]} />
          )
        }
        
        // Otherwise render as grid row
        return (
          <div key={groupIndex} className="grid gap-6 md:grid-cols-2">
            {group.map(block => (
              <div key={block.id} className={cn(getWidthClass(block.width))}>
                <RenderBlock block={block} />
              </div>
            ))}
          </div>
        )
      })}
    </div>
  )
}
