import * as React from "react"

import { cn } from "@/lib/utils"

interface KanbanContextValue {
  columns: Record<string, unknown[]>
  getItemId: (item: unknown) => string
  onMove: (itemId: string, toColumn: string, beforeItemId: string | null) => void
  draggingId: string | null
  setDraggingId: (id: string | null) => void
  overColumn: string | null
  setOverColumn: (col: string | null) => void
  overItemId: string | null
  setOverItemId: (id: string | null) => void
}

const KanbanContext = React.createContext<KanbanContextValue | null>(null)

function useKanban(): KanbanContextValue {
  const ctx = React.useContext(KanbanContext)
  if (!ctx) throw new Error("Kanban components must be used inside <Kanban>")
  return ctx
}

interface KanbanProps<T> {
  value: Record<string, T[]>
  onValueChange: (value: Record<string, T[]>) => void
  getItemValue: (item: T) => string
  children: React.ReactNode
}

function Kanban<T>({ value, onValueChange, getItemValue, children }: KanbanProps<T>) {
  const [draggingId, setDraggingId] = React.useState<string | null>(null)
  const [overColumn, setOverColumn] = React.useState<string | null>(null)
  const [overItemId, setOverItemId] = React.useState<string | null>(null)

  const onMove = React.useCallback(
    (itemId: string, toColumn: string, beforeItemId: string | null) => {
      onValueChange(moveItem(value, getItemValue, itemId, toColumn, beforeItemId))
    },
    [value, onValueChange, getItemValue],
  )

  const ctx: KanbanContextValue = {
    columns: value as unknown as Record<string, unknown[]>,
    getItemId: getItemValue as unknown as (item: unknown) => string,
    onMove,
    draggingId,
    setDraggingId,
    overColumn,
    setOverColumn,
    overItemId,
    setOverItemId,
  }

  return <KanbanContext.Provider value={ctx}>{children}</KanbanContext.Provider>
}

function moveItem<T>(
  columns: Record<string, T[]>,
  getId: (item: T) => string,
  itemId: string,
  toColumn: string,
  beforeItemId: string | null,
): Record<string, T[]> {
  const next: Record<string, T[]> = {}
  let moved: T | null = null
  for (const [col, items] of Object.entries(columns)) {
    const idx = items.findIndex((it) => getId(it) === itemId)
    if (idx === -1) {
      next[col] = [...items]
    } else {
      moved = items[idx]
      next[col] = items.filter((it) => getId(it) !== itemId)
    }
  }
  if (!moved) return columns
  const target = next[toColumn] ? [...next[toColumn]] : []
  const beforeIdx = beforeItemId
    ? target.findIndex((it) => getId(it) === beforeItemId)
    : -1
  if (beforeIdx === -1) {
    target.push(moved)
  } else {
    target.splice(beforeIdx, 0, moved)
  }
  next[toColumn] = target
  return next
}

function KanbanBoard({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="kanban-board"
      className={cn("grid auto-rows-fr gap-4", className)}
      {...props}
    />
  )
}

function KanbanColumn({
  value: columnValue,
  className,
  ...props
}: React.ComponentProps<"section"> & { value: string }) {
  const ctx = useKanban()
  const isOver = ctx.overColumn === columnValue && ctx.draggingId !== null
  return (
    <section
      data-slot="kanban-column"
      className={cn(
        "flex min-w-0 flex-col rounded-lg transition-colors",
        isOver && "bg-accent/40",
        className,
      )}
      onDragOver={(e) => {
        if (ctx.draggingId === null) return
        e.preventDefault()
        ctx.setOverColumn(columnValue)
      }}
      onDragLeave={(e) => {
        if (e.currentTarget === e.target) ctx.setOverColumn(null)
      }}
      onDrop={(e) => {
        if (ctx.draggingId === null) return
        e.preventDefault()
        ctx.onMove(ctx.draggingId, columnValue, ctx.overItemId)
        ctx.setDraggingId(null)
        ctx.setOverColumn(null)
        ctx.setOverItemId(null)
      }}
      {...props}
    />
  )
}

function KanbanColumnHeader({
  title,
  count,
  className,
}: {
  title: string
  count: number
  className?: string
}) {
  return (
    <div
      data-slot="kanban-column-header"
      className={cn(
        "mb-2.5 flex items-center gap-2.5 px-1 text-sm font-semibold",
        className,
      )}
    >
      <span className="line-clamp-1">{title}</span>
      <span className="text-muted-foreground inline-flex h-5 min-w-5 items-center justify-center rounded-sm border px-1.5 text-[11px] tabular-nums">
        {count}
      </span>
    </div>
  )
}

function KanbanColumnContent({
  className,
  ...props
}: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="kanban-column-content"
      className={cn("flex flex-col gap-2.5 p-0.5", className)}
      {...props}
    />
  )
}

function KanbanItem({
  value: itemId,
  className,
  children,
  ...props
}: React.ComponentProps<"div"> & { value: string }) {
  const ctx = useKanban()
  const isDragging = ctx.draggingId === itemId
  const isOver = ctx.overItemId === itemId && ctx.draggingId !== null
  return (
    <div
      data-slot="kanban-item"
      draggable
      onDragStart={(e) => {
        ctx.setDraggingId(itemId)
        e.dataTransfer.effectAllowed = "move"
      }}
      onDragEnd={() => {
        ctx.setDraggingId(null)
        ctx.setOverColumn(null)
        ctx.setOverItemId(null)
      }}
      onDragOver={(e) => {
        if (ctx.draggingId === null || ctx.draggingId === itemId) return
        e.preventDefault()
        ctx.setOverItemId(itemId)
      }}
      className={cn(
        "cursor-grab rounded-lg border bg-card text-card-foreground shadow-sm transition-opacity active:cursor-grabbing",
        isDragging && "opacity-40",
        isOver && "ring-2 ring-ring",
        className,
      )}
      {...props}
    >
      {children}
    </div>
  )
}

export {
  Kanban,
  KanbanBoard,
  KanbanColumn,
  KanbanColumnHeader,
  KanbanColumnContent,
  KanbanItem,
}