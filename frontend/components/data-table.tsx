"use client"

import { Card } from "@/components/ui/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { TrendingUp, TrendingDown, Minus } from "lucide-react"
import { cn } from "@/lib/utils"

export interface TableColumn {
  key: string
  label: string
  align?: "left" | "center" | "right"
  format?: "number" | "currency" | "percent" | "change"
  prefix?: string
  suffix?: string
}

export interface DataTableProps {
  data: Record<string, string | number>[]
  columns: TableColumn[]
  title: string
  subtitle?: string
}

function formatValue(value: string | number, column: TableColumn): React.ReactNode {
  if (typeof value === "string") return value
  
  const prefix = column.prefix || ""
  const suffix = column.suffix || ""
  
  switch (column.format) {
    case "currency":
      return `${prefix}${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}${suffix}`
    case "percent":
      return `${value > 0 ? "+" : ""}${value.toFixed(1)}%`
    case "change":
      const isPositive = value > 0
      const isNeutral = value === 0
      return (
        <span className={cn(
          "inline-flex items-center gap-1 font-medium",
          isPositive && "text-emerald-400",
          !isPositive && !isNeutral && "text-rose-400",
          isNeutral && "text-muted-foreground"
        )}>
          {isPositive ? (
            <TrendingUp className="h-3 w-3" />
          ) : isNeutral ? (
            <Minus className="h-3 w-3" />
          ) : (
            <TrendingDown className="h-3 w-3" />
          )}
          {isPositive ? "+" : ""}{value.toFixed(1)}%
        </span>
      )
    case "number":
    default:
      return `${prefix}${value.toLocaleString()}${suffix}`
  }
}

export function DataTable({ data, columns, title, subtitle }: DataTableProps) {
  return (
    <Card className="border-border/50 bg-card/50 p-5">
      <div className="mb-4">
        <h3 className="text-base font-semibold tracking-tight text-foreground">
          {title}
        </h3>
        {subtitle && (
          <p className="mt-0.5 text-xs text-muted-foreground">
            {subtitle}
          </p>
        )}
      </div>
      
      <div className="overflow-x-auto rounded-md border border-border/50">
        <Table>
          <TableHeader>
            <TableRow className="border-border/50 hover:bg-transparent">
              {columns.map((col) => (
                <TableHead
                  key={col.key}
                  className={cn(
                    "h-9 bg-secondary/30 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground",
                    col.align === "right" && "text-right",
                    col.align === "center" && "text-center"
                  )}
                >
                  {col.label}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.map((row, rowIndex) => (
              <TableRow 
                key={rowIndex} 
                className="border-border/30 hover:bg-secondary/20"
              >
                {columns.map((col) => (
                  <TableCell
                    key={col.key}
                    className={cn(
                      "py-2.5 text-xs",
                      col.align === "right" && "text-right font-mono",
                      col.align === "center" && "text-center"
                    )}
                  >
                    {formatValue(row[col.key], col)}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </Card>
  )
}
