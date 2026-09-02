import { useEffect, useMemo, useRef, useState } from "react";
import {
  IconCheck,
  IconCircleCheckFilled,
  IconClockFilled,
  IconPencilFilled,
  IconRefresh,
  IconSearch,
  IconTags,
  IconX,
} from "@tabler/icons-react";

import { BoardColumn } from "@/components/board-column";
import { TopicsModal } from "@/components/topics-modal";
import { PostModal } from "@/components/post-modal";
import { ToastProvider } from "@/components/toast";
import { MOCK } from "@/lib/api";
import { Kanban, KanbanBoard } from "@/components/ui/kanban";
import { useBoard } from "@/hooks/use-board";
import { groupPosts } from "@/lib/grouping";
import { Button } from "@/ui/button";
import { Input, InputGroup, InputGroupAddon } from "@/ui/input";
import { cn } from "@/lib/utils";
import type { BoardChannel, GroupedPost } from "@/types";

/** True when a post group matches the board search: post text or channel name. */
function groupMatches(
  group: GroupedPost,
  query: string,
  channels: BoardChannel[],
): boolean {
  if (!query) return true;
  if (group.posts.some((post) => post.text.toLowerCase().includes(query)))
    return true;
  return group.posts.some((post) =>
    channels.some(
      (channel) =>
        channel.id === post.channel_id &&
        channel.display_name.toLowerCase().includes(query),
    ),
  );
}

const COLUMNS: {
  key: "drafts" | "accepted" | "posted";
  title: string;
  icon: React.ComponentType<{ className?: string }>;
  accent: string;
  emptyLabel: string;
}[] = [
  {
    key: "drafts",
    title: "Drafts",
    icon: IconPencilFilled,
    accent: "text-orange-600",
    emptyLabel: "No drafts right now.",
  },
  {
    key: "accepted",
    title: "Scheduled",
    icon: IconClockFilled,
    accent: "text-green-600",
    emptyLabel: "Nothing scheduled yet.",
  },
  {
    key: "posted",
    title: "Posted",
    icon: IconCircleCheckFilled,
    accent: "text-blue-600",
    emptyLabel: "Nothing posted yet.",
  },
];

// The Kanban is disabled, so columns can never be reordered: the grouping is
// fully derived from the board.
const noop = () => {};

export default function App() {
  const { board, error, loading, refreshing, refresh } = useBoard();
  const [openGroup, setOpenGroup] = useState<GroupedPost | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [topicsOpen, setTopicsOpen] = useState(false);
  const [search, setSearch] = useState("");

  // After a user-triggered refresh succeeds, briefly swap the refresh icon
  // for a checkmark. `requestedRef` excludes the initial page load.
  const [justRefreshed, setJustRefreshed] = useState(false);
  const requestedRefresh = useRef(false);
  const awaitingRefreshResult = useRef(false);

  useEffect(() => {
    if (refreshing) {
      setJustRefreshed(false);
      if (requestedRefresh.current) awaitingRefreshResult.current = true;
      return;
    }
    requestedRefresh.current = false;
    if (!awaitingRefreshResult.current) return;
    awaitingRefreshResult.current = false;
    if (error !== null) return;
    setJustRefreshed(true);
    const timer = window.setTimeout(() => setJustRefreshed(false), 1600);
    return () => window.clearTimeout(timer);
  }, [refreshing, error]);

  const grouped = useMemo<{
    drafts: GroupedPost[];
    accepted: GroupedPost[];
    posted: GroupedPost[];
  }>(
    () =>
      board
        ? {
            drafts: groupPosts(board.drafts),
            accepted: groupPosts(board.accepted),
            posted: groupPosts(board.posted),
          }
        : { drafts: [], accepted: [], posted: [] },
    [board],
  );

  // Keep the open post in sync with fresh board data; close it if the post
  // disappeared (e.g. deleted in Buffer while the modal was open).
  useEffect(() => {
    if (!board || !openGroup || !modalOpen) return;
    const all = [...grouped.drafts, ...grouped.accepted, ...grouped.posted];
    const fresh = all.find((g) => g.key === openGroup.key);
    if (fresh) {
      setOpenGroup(fresh);
    } else {
      setOpenGroup(null);
      setModalOpen(false);
    }
  }, [board, grouped, openGroup, modalOpen]);

  const handleOpen = (group: GroupedPost) => {
    setOpenGroup(group);
    setModalOpen(true);
  };

  const handleBoardChanged = () => {
    refresh();
  };

  // Nothing on screen yet: the first fetch is in flight, so every column shows
  // cards taking shape. Background refreshes keep the real cards and dim them.
  const showSkeletons = board === null && error === null;
  const query = search.trim().toLowerCase();
  const channels = board?.channels ?? [];
  const visibleGroups = (key: "drafts" | "accepted" | "posted"): GroupedPost[] =>
    grouped[key].filter((group) => groupMatches(group, query, channels));

  return (
    <ToastProvider>
      <main className="mx-auto flex min-h-screen max-w-6xl flex-col gap-10 p-6 py-16">
        <header className="flex flex-wrap items-start justify-between gap-x-4 gap-y-3">
          <div className="order-1 min-w-0">
            <h1 className="text-2xl font-bold tracking-tight">
              {board?.title ?? "Content Board"}
            </h1>
            {MOCK && (
              <span
                className="mt-1.5 inline-block rounded-full bg-amber-500/15 px-2 py-0.5 text-xs font-semibold text-amber-600"
                title="In-memory mock data — run `npm run dev` for the real backend"
              >
                mock data
              </span>
            )}
          </div>
          {/* Search shares the button cluster: sm inputs and sm buttons are
              both h-7, and sm:mt-0.5 centers the row on the title's 32px line
              instead of the taller title + badge block. */}
          <div className="order-2 flex w-full flex-wrap items-center gap-2 sm:mt-0.5 sm:w-auto">
            <InputGroup
              size="sm"
              className="min-w-0 flex-1 sm:w-64 sm:flex-none md:w-72"
            >
              <InputGroupAddon>
                <IconSearch />
              </InputGroupAddon>
              <Input
                placeholder="Search posts…"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Escape" && search !== "") {
                    event.preventDefault();
                    setSearch("");
                  }
                }}
                aria-label="Search posts"
              />
              {search !== "" && (
                <InputGroupAddon>
                  <Button
                    variant="quiet"
                    size="sm"
                    isIconOnly
                    onPress={() => setSearch("")}
                    aria-label="Clear search"
                  >
                    <IconX />
                  </Button>
                </InputGroupAddon>
              )}
            </InputGroup>
            <Button
              variant="secondary"
              size="sm"
              onPress={() => setTopicsOpen(true)}
            >
              <IconTags />
              Topics
            </Button>
            <Button
              variant="secondary"
              size="sm"
              onPress={() => {
                requestedRefresh.current = true;
                refresh();
              }}
              isDisabled={loading}
            >
              Refresh
              <span className="relative flex size-4 items-center justify-center">
                <IconRefresh
                  className={cn(
                    "absolute transition-all duration-300",
                    !justRefreshed && "opacity-100",
                    refreshing && "animate-spin",
                    justRefreshed && "scale-50 opacity-0",
                  )}
                />
                <IconCheck
                  className={cn(
                    "absolute scale-50 opacity-0 transition-all duration-300",
                    justRefreshed && "scale-100 opacity-100",
                  )}
                />
              </span>
            </Button>
          </div>
        </header>

        {!board && error ? (
          <div className="flex flex-col items-center gap-3 py-16 text-center">
            <p className="text-fg-muted">Unable to load the content board.</p>
            <p className="text-fg-danger text-sm">{error}</p>
            <Button variant="secondary" size="sm" onPress={() => refresh()}>
              <IconRefresh />
              Retry
            </Button>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            {/* A failed background refresh keeps the stale board on screen. */}
            {board && error && (
              <p className="text-fg-danger text-sm">Couldn’t refresh: {error}</p>
            )}
            <Kanban
              value={grouped}
              onValueChange={noop}
              getItemValue={(group) => group.key}
              disabled
            >
              <KanbanBoard
                className={cn(
                  "grid-cols-1 md:grid-cols-3",
                  refreshing &&
                    !showSkeletons &&
                    "opacity-70 transition-opacity duration-200",
                )}
              >
                {COLUMNS.map((col) => (
                  <BoardColumn
                    key={col.key}
                    title={col.title}
                    icon={col.icon}
                    accent={col.accent}
                    columnValue={col.key}
                    groups={visibleGroups(col.key)}
                    channels={board?.channels ?? []}
                    emptyLabel={query ? "No matching posts." : col.emptyLabel}
                    onOpen={handleOpen}
                    loading={showSkeletons}
                  />
                ))}
              </KanbanBoard>
            </Kanban>
          </div>
        )}

        <PostModal
          group={openGroup}
          channels={board?.channels ?? []}
          open={modalOpen}
          onOpenChange={setModalOpen}
          onAccepted={handleBoardChanged}
          onChanged={handleBoardChanged}
        />

        <TopicsModal
          open={topicsOpen}
          onOpenChange={setTopicsOpen}
        />
      </main>
    </ToastProvider>
  );
}
