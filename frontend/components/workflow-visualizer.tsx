"use client"

import { useState } from "react"
import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { ScrollArea } from "@/components/ui/scroll-area"
import { 
  Brain, 
  Cpu, 
  Database, 
  FileCode, 
  Terminal, 
  FileText, 
  Check,
  ChevronRight,
  Circle,
  Zap,
  GitBranch,
  Search,
  Globe,
  Calculator,
  Sparkles,
  ArrowRight,
  Clock,
  CheckCircle2,
  Loader2,
  AlertCircle
} from "lucide-react"
import { cn } from "@/lib/utils"

// Types for workflow state
interface ToolCall {
  id: string
  name: string
  status: "pending" | "running" | "completed" | "error"
  duration?: number
  result?: string
}

interface SubAgentAction {
  id: string
  agentName: string
  agentType: "research" | "analysis" | "synthesis" | "validation"
  task: string
  status: "pending" | "running" | "completed" | "error"
  tools: ToolCall[]
  startTime?: number
  endTime?: number
}

interface OrchestratorTodo {
  id: string
  task: string
  status: "pending" | "running" | "completed" | "error"
  subAgents: SubAgentAction[]
  progress?: number
}

export interface WorkflowState {
  status: "idle" | "running" | "completed" | "error"
  currentPhase: string
  todos: OrchestratorTodo[]
  totalDuration?: number
}

// Mock data representing a completed research workflow
const mockWorkflowState: WorkflowState = {
  status: "completed",
  currentPhase: "Report Generation",
  totalDuration: 47.3,
  todos: [
    {
      id: "todo-1",
      task: "Gather semiconductor industry data from financial APIs",
      status: "completed",
      progress: 100,
      subAgents: [
        {
          id: "agent-1a",
          agentName: "Data Collector",
          agentType: "research",
          task: "Query Financial Modeling Prep API for CapEx data",
          status: "completed",
          startTime: 0,
          endTime: 3200,
          tools: [
            { id: "t1", name: "fmp_api_query", status: "completed", duration: 1.8, result: "Retrieved 20 quarters of data" },
            { id: "t2", name: "data_validation", status: "completed", duration: 0.4, result: "Schema validated" },
          ]
        },
        {
          id: "agent-1b",
          agentName: "Index Researcher",
          agentType: "research",
          task: "Fetch shipping volume indices from FRED",
          status: "completed",
          startTime: 1000,
          endTime: 4500,
          tools: [
            { id: "t3", name: "fred_api_query", status: "completed", duration: 2.1, result: "Baltic Dry Index retrieved" },
            { id: "t4", name: "fred_api_query", status: "completed", duration: 1.9, result: "Container Freight Index retrieved" },
            { id: "t5", name: "data_merge", status: "completed", duration: 0.5, result: "Indices combined" },
          ]
        },
      ]
    },
    {
      id: "todo-2",
      task: "Extract and normalize data schemas",
      status: "completed",
      progress: 100,
      subAgents: [
        {
          id: "agent-2a",
          agentName: "Schema Analyzer",
          agentType: "analysis",
          task: "Analyze data structure and create unified schema",
          status: "completed",
          startTime: 4500,
          endTime: 8200,
          tools: [
            { id: "t6", name: "schema_detection", status: "completed", duration: 1.2, result: "Detected 3 data sources" },
            { id: "t7", name: "column_mapping", status: "completed", duration: 0.8, result: "Mapped 24 columns" },
            { id: "t8", name: "type_inference", status: "completed", duration: 0.6, result: "Types inferred" },
          ]
        },
      ]
    },
    {
      id: "todo-3",
      task: "Perform statistical analysis and correlation testing",
      status: "completed",
      progress: 100,
      subAgents: [
        {
          id: "agent-3a",
          agentName: "Statistical Engine",
          agentType: "analysis",
          task: "Calculate correlation coefficients",
          status: "completed",
          startTime: 8200,
          endTime: 15600,
          tools: [
            { id: "t9", name: "python_sandbox", status: "completed", duration: 2.4, result: "Pearson r = 0.87" },
            { id: "t10", name: "python_sandbox", status: "completed", duration: 1.8, result: "Lag analysis complete" },
          ]
        },
        {
          id: "agent-3b",
          agentName: "Visualization Agent",
          agentType: "synthesis",
          task: "Generate charts and data visualizations",
          status: "completed",
          startTime: 12000,
          endTime: 18500,
          tools: [
            { id: "t11", name: "chart_generator", status: "completed", duration: 3.2, result: "4 charts generated" },
            { id: "t12", name: "export_png", status: "completed", duration: 0.8, result: "Assets exported" },
          ]
        },
      ]
    },
    {
      id: "todo-4",
      task: "Synthesize findings and generate comprehensive report",
      status: "completed",
      progress: 100,
      subAgents: [
        {
          id: "agent-4a",
          agentName: "Report Writer",
          agentType: "synthesis",
          task: "Draft executive summary and analysis sections",
          status: "completed",
          startTime: 18500,
          endTime: 38200,
          tools: [
            { id: "t13", name: "llm_generate", status: "completed", duration: 8.5, result: "Executive summary written" },
            { id: "t14", name: "llm_generate", status: "completed", duration: 6.2, result: "Analysis sections drafted" },
            { id: "t15", name: "citation_linker", status: "completed", duration: 1.4, result: "12 sources cited" },
          ]
        },
        {
          id: "agent-4b",
          agentName: "Quality Validator",
          agentType: "validation",
          task: "Verify data accuracy and report coherence",
          status: "completed",
          startTime: 35000,
          endTime: 47300,
          tools: [
            { id: "t16", name: "fact_checker", status: "completed", duration: 4.8, result: "All facts verified" },
            { id: "t17", name: "coherence_check", status: "completed", duration: 2.1, result: "Score: 94/100" },
            { id: "t18", name: "format_validator", status: "completed", duration: 0.9, result: "Format approved" },
          ]
        },
      ]
    },
  ]
}

/** Snapshot used while the pipeline is running (UI demo). */
export function createGeneratingWorkflowState(): WorkflowState {
  const w = structuredClone(mockWorkflowState)
  w.status = "running"
  w.currentPhase = "Data collection"
  w.totalDuration = undefined
  if (w.todos[0]) {
    w.todos[0].status = "running"
    w.todos[0].progress = 42
    const firstAgent = w.todos[0].subAgents[0]
    if (firstAgent) {
      firstAgent.status = "running"
      const firstTool = firstAgent.tools[0]
      if (firstTool) firstTool.status = "running"
      for (let i = 1; i < firstAgent.tools.length; i++) {
        firstAgent.tools[i].status = "pending"
      }
    }
    for (let i = 1; i < w.todos[0].subAgents.length; i++) {
      w.todos[0].subAgents[i].status = "pending"
      w.todos[0].subAgents[i].tools.forEach((t) => {
        t.status = "pending"
      })
    }
  }
  for (let i = 1; i < w.todos.length; i++) {
    w.todos[i].status = "pending"
    w.todos[i].progress = 0
    w.todos[i].subAgents.forEach((a) => {
      a.status = "pending"
      a.tools.forEach((t) => {
        t.status = "pending"
      })
    })
  }
  return w
}

// Icon mapping for agent types
const agentTypeIcons = {
  research: Search,
  analysis: Calculator,
  synthesis: Sparkles,
  validation: CheckCircle2,
}

const agentTypeColors = {
  research: "text-chart-3",
  analysis: "text-chart-1",
  synthesis: "text-chart-4",
  validation: "text-chart-2",
}

// Tool icon mapping
const toolIcons: Record<string, typeof Database> = {
  fmp_api_query: Globe,
  fred_api_query: Globe,
  data_validation: CheckCircle2,
  data_merge: GitBranch,
  schema_detection: FileCode,
  column_mapping: Database,
  type_inference: Cpu,
  python_sandbox: Terminal,
  chart_generator: Sparkles,
  export_png: FileText,
  llm_generate: Brain,
  citation_linker: Search,
  fact_checker: AlertCircle,
  coherence_check: Brain,
  format_validator: Check,
}

// Status indicator component
function StatusIndicator({ status }: { status: "pending" | "running" | "completed" | "error" }) {
  if (status === "completed") {
    return (
      <div className="flex h-5 w-5 items-center justify-center rounded-full bg-chart-2/20 ring-1 ring-chart-2/40">
        <Check className="h-3 w-3 text-chart-2" />
      </div>
    )
  }
  if (status === "running") {
    return (
      <div className="flex h-5 w-5 items-center justify-center rounded-full bg-primary/20 ring-1 ring-primary/40">
        <Loader2 className="h-3 w-3 animate-spin text-primary" />
      </div>
    )
  }
  if (status === "error") {
    return (
      <div className="flex h-5 w-5 items-center justify-center rounded-full bg-destructive/20 ring-1 ring-destructive/40">
        <AlertCircle className="h-3 w-3 text-destructive" />
      </div>
    )
  }
  return (
    <div className="flex h-5 w-5 items-center justify-center rounded-full bg-muted ring-1 ring-border">
      <Circle className="h-2 w-2 text-muted-foreground" />
    </div>
  )
}

// Tool call component
function ToolCallItem({ tool }: { tool: ToolCall }) {
  const IconComponent = toolIcons[tool.name] || Zap
  
  return (
    <div className="group flex items-center gap-2 rounded-md bg-background/50 px-2.5 py-1.5 ring-1 ring-border/50 transition-all hover:bg-background hover:ring-border">
      <div className="flex h-5 w-5 items-center justify-center rounded bg-secondary">
        <IconComponent className="h-3 w-3 text-muted-foreground" />
      </div>
      <div className="flex-1 min-w-0">
        <p className="truncate font-mono text-[10px] text-foreground/80">{tool.name}</p>
      </div>
      {tool.duration && (
        <span className="font-mono text-[9px] text-muted-foreground">{tool.duration.toFixed(1)}s</span>
      )}
      <StatusIndicator status={tool.status} />
    </div>
  )
}

// SubAgent component with expanded details
function SubAgentCard({ agent, isLast }: { agent: SubAgentAction; isLast: boolean }) {
  const [isExpanded, setIsExpanded] = useState(true)
  const IconComponent = agentTypeIcons[agent.agentType]
  const colorClass = agentTypeColors[agent.agentType]
  
  const duration = agent.endTime && agent.startTime 
    ? ((agent.endTime - agent.startTime) / 1000).toFixed(1) 
    : null
  
  return (
    <div className="relative">
      {/* Connection line */}
      {!isLast && (
        <div className="absolute left-[22px] top-12 h-[calc(100%-40px)] w-px bg-gradient-to-b from-border via-border/50 to-transparent" />
      )}
      
      <div className="rounded-lg border border-border/50 bg-card/30 backdrop-blur-sm transition-all hover:bg-card/50 hover:border-border">
        {/* Agent Header */}
        <button
          onClick={() => setIsExpanded(!isExpanded)}
          className="flex w-full items-center gap-3 p-3 text-left"
        >
          <div className={cn(
            "flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ring-1 ring-inset",
            agent.status === "completed" 
              ? "bg-card ring-border" 
              : "bg-primary/10 ring-primary/30"
          )}>
            <IconComponent className={cn("h-4 w-4", colorClass)} />
          </div>
          
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold text-foreground">{agent.agentName}</span>
              <Badge 
                variant="outline" 
                className={cn(
                  "h-4 border-0 px-1.5 text-[9px] font-medium uppercase tracking-wider",
                  agent.agentType === "research" && "bg-chart-3/15 text-chart-3",
                  agent.agentType === "analysis" && "bg-chart-1/15 text-chart-1",
                  agent.agentType === "synthesis" && "bg-chart-4/15 text-chart-4",
                  agent.agentType === "validation" && "bg-chart-2/15 text-chart-2",
                )}
              >
                {agent.agentType}
              </Badge>
            </div>
            <p className="mt-0.5 truncate text-[11px] text-muted-foreground">{agent.task}</p>
          </div>
          
          <div className="flex items-center gap-2">
            {duration && (
              <div className="flex items-center gap-1 text-[10px] text-muted-foreground">
                <Clock className="h-3 w-3" />
                <span className="font-mono">{duration}s</span>
              </div>
            )}
            <ChevronRight className={cn(
              "h-4 w-4 text-muted-foreground transition-transform",
              isExpanded && "rotate-90"
            )} />
          </div>
        </button>
        
        {/* Tools List */}
        {isExpanded && agent.tools.length > 0 && (
          <div className="border-t border-border/30 px-3 pb-3 pt-2">
            <div className="mb-2 flex items-center gap-1.5">
              <Zap className="h-3 w-3 text-muted-foreground" />
              <span className="text-[9px] font-medium uppercase tracking-wider text-muted-foreground">
                Tool Calls ({agent.tools.length})
              </span>
            </div>
            <div className="space-y-1.5">
              {agent.tools.map((tool) => (
                <ToolCallItem key={tool.id} tool={tool} />
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// Orchestrator Todo component
function OrchestratorTodoCard({ todo, index, isLast }: { todo: OrchestratorTodo; index: number; isLast: boolean }) {
  const [isExpanded, setIsExpanded] = useState(true)
  
  return (
    <div className="relative">
      {/* Main vertical line */}
      {!isLast && (
        <div className="absolute left-5 top-14 h-[calc(100%-48px)] w-px bg-gradient-to-b from-primary/40 via-primary/20 to-transparent" />
      )}
      
      <Card className="overflow-hidden border-border/50 bg-card/50 backdrop-blur-sm">
        {/* Todo Header */}
        <button
          onClick={() => setIsExpanded(!isExpanded)}
          className="flex w-full items-center gap-4 p-4 text-left transition-colors hover:bg-secondary/30"
        >
          {/* Step Number */}
          <div className={cn(
            "relative flex h-10 w-10 shrink-0 items-center justify-center rounded-xl font-mono text-sm font-bold",
            todo.status === "completed" 
              ? "bg-primary/15 text-primary ring-1 ring-primary/30" 
              : todo.status === "running"
              ? "bg-primary/20 text-primary ring-1 ring-primary/50"
              : "bg-secondary text-muted-foreground ring-1 ring-border"
          )}>
            {todo.status === "completed" ? (
              <Check className="h-5 w-5" />
            ) : todo.status === "running" ? (
              <Loader2 className="h-5 w-5 animate-spin" />
            ) : (
              index + 1
            )}
            {/* Pulse effect for running */}
            {todo.status === "running" && (
              <span className="absolute inset-0 animate-ping rounded-xl bg-primary/20" />
            )}
          </div>
          
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-foreground">{todo.task}</p>
            <div className="mt-1 flex items-center gap-3">
              <span className="text-[10px] text-muted-foreground">
                {todo.subAgents.length} subagent{todo.subAgents.length !== 1 ? "s" : ""}
              </span>
              <span className="text-muted-foreground/50">•</span>
              <span className="text-[10px] text-muted-foreground">
                {todo.subAgents.reduce((acc, a) => acc + a.tools.length, 0)} tool calls
              </span>
            </div>
          </div>
          
          <ChevronRight className={cn(
            "h-5 w-5 text-muted-foreground transition-transform",
            isExpanded && "rotate-90"
          )} />
        </button>
        
        {/* Progress Bar */}
        {todo.progress !== undefined && (
          <div className="h-0.5 bg-secondary">
            <div 
              className="h-full bg-gradient-to-r from-primary via-primary to-chart-2 transition-all duration-500"
              style={{ width: `${todo.progress}%` }}
            />
          </div>
        )}
        
        {/* SubAgents */}
        {isExpanded && todo.subAgents.length > 0 && (
          <div className="space-y-3 border-t border-border/30 bg-background/30 p-4">
            {todo.subAgents.map((agent, agentIndex) => (
              <SubAgentCard 
                key={agent.id} 
                agent={agent} 
                isLast={agentIndex === todo.subAgents.length - 1}
              />
            ))}
          </div>
        )}
      </Card>
    </div>
  )
}

interface WorkflowVisualizerProps {
  /** When omitted, shows the completed demo workflow. */
  workflow?: WorkflowState
}

// Main Workflow Visualizer Component
export function WorkflowVisualizer({ workflow: workflowProp }: WorkflowVisualizerProps) {
  const workflow = workflowProp ?? mockWorkflowState
  
  // Calculate total tools and agents
  const totalTools = workflow.todos.reduce(
    (acc, todo) => acc + todo.subAgents.reduce((a, agent) => a + agent.tools.length, 0),
    0
  )
  const totalAgents = workflow.todos.reduce((acc, todo) => acc + todo.subAgents.length, 0)
  
  return (
    <Card className="overflow-hidden border-border/50 bg-card/50">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border/40 bg-gradient-to-r from-card to-card/80 px-4 py-3">
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/15 ring-1 ring-primary/30">
            <Brain className="h-4 w-4 text-primary" />
          </div>
          <div>
            <h3 className="text-xs font-semibold text-foreground">Agent Workflow</h3>
            <p className="text-[10px] text-muted-foreground">LangGraph Orchestration</p>
          </div>
        </div>
        
        <div className="flex items-center gap-4">
          {/* Stats */}
          <div className="flex items-center gap-3 text-[10px]">
            <div className="flex items-center gap-1.5">
              <GitBranch className="h-3 w-3 text-muted-foreground" />
              <span className="text-muted-foreground">{totalAgents} agents</span>
            </div>
            <div className="flex items-center gap-1.5">
              <Zap className="h-3 w-3 text-muted-foreground" />
              <span className="text-muted-foreground">{totalTools} tools</span>
            </div>
            {workflow.totalDuration && (
              <div className="flex items-center gap-1.5">
                <Clock className="h-3 w-3 text-muted-foreground" />
                <span className="font-mono text-muted-foreground">{workflow.totalDuration}s</span>
              </div>
            )}
          </div>
          
          {/* Status Badge */}
          <Badge 
            variant="outline"
            className={cn(
              "h-5 border-0 px-2 text-[9px] font-semibold uppercase tracking-wider",
              workflow.status === "completed" && "bg-chart-2/15 text-chart-2",
              workflow.status === "running" && "bg-primary/15 text-primary",
              workflow.status === "error" && "bg-destructive/15 text-destructive",
              workflow.status === "idle" && "bg-muted text-muted-foreground",
            )}
          >
            {workflow.status === "running" && <Loader2 className="mr-1 h-2.5 w-2.5 animate-spin" />}
            {workflow.status}
          </Badge>
        </div>
      </div>
      
      {/* Workflow Steps */}
      <ScrollArea className="h-[400px]">
        <div className="space-y-4 p-4">
          {workflow.todos.map((todo, index) => (
            <OrchestratorTodoCard 
              key={todo.id} 
              todo={todo} 
              index={index}
              isLast={index === workflow.todos.length - 1}
            />
          ))}
        </div>
      </ScrollArea>
    </Card>
  )
}
