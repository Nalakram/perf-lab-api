// src/perflab/screens/ObjectivesScreen.tsx
//
// Objectives (P4a/P4b): a multi-domain goal — a race, a strength meet, a
// Hyrox, a benchmark PR — replaces the running-only, frontend-only "Goal
// Race" screen and its hard-coded Valencia Marathon mock. Backed by
// GET/POST /v1/objectives and PATCH/DELETE /v1/objectives/{id}.
import { useState } from "react";
import * as api from "@/api/perfLabClient";
import { useAuth } from "@/auth/useAuth";
import type { ApiError, MacrocycleRead, ObjectiveRead } from "@/types";
import { usePerfLab } from "../store";
import { useAuthedResource } from "../useAuthedResource";
import { ResourceState } from "../ResourceState";
import { sortObjectives } from "../objectives";
import { domainLabel } from "../domains";
import { Card, Pill, ScreenHeader, Track } from "../ui";

function statusLabel(status: ObjectiveRead["status"]): string {
  return status.charAt(0).toUpperCase() + status.slice(1);
}

function statusColor(status: ObjectiveRead["status"]): string {
  if (status === "achieved") return "text-good";
  if (status === "abandoned") return "text-faint";
  return "text-ac";
}

export function ObjectivesScreen() {
  const { state, actions } = usePerfLab();
  const auth = useAuth();
  const [mutatingId, setMutatingId] = useState<number | null>(null);
  const [mutateError, setMutateError] = useState<string | null>(null);

  const objectivesRes = useAuthedResource<ObjectiveRead[]>(
    (t) => api.listObjectives(t),
    [state.objectivesRefreshKey],
  );

  async function markAchieved(id: number) {
    if (!auth.token) return;
    setMutatingId(id);
    setMutateError(null);
    try {
      await api.updateObjective(id, { status: "achieved" }, auth.token);
      actions.refreshObjectives();
    } catch (e) {
      setMutateError((e as ApiError)?.message ?? "Couldn't update that objective.");
    } finally {
      setMutatingId(null);
    }
  }

  async function remove(id: number) {
    if (!auth.token) return;
    setMutatingId(id);
    setMutateError(null);
    try {
      await api.deleteObjective(id, auth.token);
      actions.refreshObjectives();
    } catch (e) {
      setMutateError((e as ApiError)?.message ?? "Couldn't delete that objective.");
    } finally {
      setMutatingId(null);
    }
  }

  // Every non-success branch — guest gate, first load, load failure, empty —
  // belongs to ResourceState, in that fixed order. The screen no longer decides
  // which one applies, so a failed fetch can't read as "no objectives yet" and
  // the guest gate can't be forgotten. The old `loading || objectives === null`
  // guard is gone with it: the hook now reports `loading` on the first render,
  // so the one-frame empty-CTA flash it worked around cannot occur.
  return (
    <ResourceState
      resource={objectivesRes}
      isEmpty={(rows) => rows.length === 0}
      variant="screen"
      icon={<TargetIcon />}
      guest={{
        title: "Sign in to set your objectives",
        body: "Objectives — a race, a meet, a Hyrox, a benchmark PR — live on your account so your plan can point at them.",
        action: { label: "Sign in →", onClick: actions.openAuth },
      }}
      loadingContent={{ title: "Loading your objectives…", body: "Fetching what your plan is pointed at." }}
      error={{
        title: "Couldn't load your objectives",
        action: { label: "Retry", onClick: actions.refreshObjectives },
      }}
      empty={{
        title: "Set your first objective",
        body: "A race, a meet, a Hyrox, a lift PR — give your plan something to point at, benchmark-linked or free-text.",
        action: { label: "New objective →", onClick: actions.openObjectiveCreate, primary: true },
      }}
      staleLabel="Couldn't refresh your objectives — showing your last loaded list."
    >
      {(objectives) => (
        <section className="flex flex-col gap-[18px] px-[30px] pb-9 pt-[26px]">
          <ScreenHeader title="Objectives" subtitle="A race, a meet, a Hyrox, a PR — the targets your training is pointed at.">
            <button onClick={actions.openObjectiveCreate} className="rounded-[9px] bg-gradient-to-r from-ac to-[#a7e36e] px-4 py-[11px] text-[12.5px] font-semibold leading-none text-[#0a0c10]">New objective →</button>
          </ScreenHeader>

          <div className="flex items-start gap-[10px] rounded-[12px] border border-ac/[0.18] bg-ac/[0.05] px-4 py-3">
            <span className="mt-[1px] text-[13px] text-ac">◆</span>
            <p className="m-0 text-[12px] font-medium leading-[1.5] text-mute">
              Objectives aren’t just a wishlist — they <span className="text-soft">drive what your plan emphasizes</span>
              {" "}(more work toward your highest-priority goal), <span className="text-soft">taper you before a target date</span>,
              and <span className="text-soft">decide which benchmarks the Assess tab suggests</span>. Set a priority and, for measurable goals, link a benchmark so progress tracks automatically.
            </p>
          </div>

          {mutateError && (
            <div className="rounded-[11px] border border-hot/25 bg-hot/[0.08] px-[14px] py-[11px] text-[12px] font-medium leading-[1.5] text-hot">{mutateError}</div>
          )}

          <ProgramSection />

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {sortObjectives(objectives).map((o) => (
              <ObjectiveCard key={o.id} o={o} busy={mutatingId === o.id} onAchieve={() => markAchieved(o.id)} onDelete={() => remove(o.id)} />
            ))}
          </div>
        </section>
      )}
    </ResourceState>
  );
}

// Program (Phase 5): the athlete's macrocycles — a thin container above blocks,
// anchored to an objective, that yields a real cross-block "week X of Y". Folded
// into the Objectives screen (rather than its own nav item) since a program only
// exists to serve an objective. Fetches its own list keyed by the macrocycles
// refresh key. Renders nothing while it has no data to show so it never adds
// visual noise before there's a program.
function ProgramSection() {
  const { state, actions } = usePerfLab();
  const macrosRes = useAuthedResource<MacrocycleRead[]>(
    (t) => api.listMacrocycles(t),
    [state.macrocyclesRefreshKey],
  );

  return (
    <Card className="flex flex-col gap-[14px] p-5">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-[8px]">
          <span className="font-mono text-[10px] font-semibold uppercase leading-none tracking-[0.14em] text-ac">Program</span>
          <span className="text-[11px] font-medium leading-none text-faint">week X of Y across your blocks</span>
        </div>
        <button
          onClick={actions.openMacrocycleCreate}
          className="rounded-[9px] border border-white/10 bg-white/[0.04] px-[13px] py-[9px] text-[12px] font-semibold leading-none text-soft"
        >
          New program →
        </button>
      </div>

      {/*
        The card shell always renders; only its body is state-dependent, so this
        is the `note` weight. Stale-while-refresh is preserved by the contract
        rather than by a hand-rolled `loading && data === null` conjunct: a
        refresh keeps the previous rows on screen, and a FAILED refresh keeps
        them too while saying so — where the old code silently dropped the list.
      */}
      <ResourceState
        resource={macrosRes}
        isEmpty={(rows) => rows.length === 0}
        variant="note"
        guest={{ body: "Sign in to track a program across your blocks." }}
        loadingContent={{ body: "Loading your program…" }}
        empty={{ body: "No program yet. Anchor one to an objective to track a real week X of Y across every block." }}
        error={{ title: "Couldn't load your program" }}
        staleLabel="Couldn't refresh your program — showing your last loaded weeks."
      >
        {(macros) => (
          <div className="flex flex-col gap-[10px]">
            {macros.map((m) => (
              <MacrocycleRow key={m.id} m={m} />
            ))}
          </div>
        )}
      </ResourceState>
    </Card>
  );
}

function MacrocycleRow({ m }: { m: MacrocycleRead }) {
  const wp = m.week_progress;
  return (
    <div className="flex items-center justify-between gap-3 rounded-[11px] border border-white/[0.06] bg-white/[0.02] px-[14px] py-[12px]">
      <div className="min-w-0">
        <div className="flex items-center gap-[8px]">
          <span className="truncate text-[14px] font-bold leading-none text-ink">{m.objective_label}</span>
          <Pill>{statusLabel(m.status)}</Pill>
        </div>
        <div className="mt-2 flex items-center gap-[10px] text-[11px] font-medium leading-none text-faint">
          <span>Since {m.start_date}</span>
          <span className="text-[#3a4049]">·</span>
          <span>{m.block_count} block{m.block_count === 1 ? "" : "s"}</span>
          {m.target_date && (
            <>
              <span className="text-[#3a4049]">·</span>
              <span>By {m.target_date}</span>
            </>
          )}
        </div>
      </div>
      <div className="flex flex-none items-center gap-4">
        {wp.pct != null && (
          <div className="hidden w-[110px] sm:block">
            <Track pct={Math.max(0, Math.min(100, wp.pct))} />
          </div>
        )}
        <div className="text-right">
          <div className="font-mono text-[15px] font-semibold leading-none text-ink">week {wp.current_week}</div>
          <div className="mt-1 font-mono text-[9px] font-semibold uppercase leading-none tracking-[0.14em] text-faint">
            {wp.total_weeks != null ? `of ${wp.total_weeks}` : "open horizon"}
          </div>
        </div>
      </div>
    </div>
  );
}

function ObjectiveCard({
  o,
  busy,
  onAchieve,
  onDelete,
}: {
  o: ObjectiveRead;
  busy: boolean;
  onAchieve: () => void;
  onDelete: () => void;
}) {
  const hasTarget = o.target_value != null;
  const hasProgress = o.progress.pct != null;

  return (
    <Card className="flex flex-col gap-[14px] p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-[8px]">
            <span className="text-[16px] font-bold leading-none text-ink">{o.label}</span>
            <Pill>{domainLabel(o.domain)}</Pill>
          </div>
          <div className="mt-2 flex items-center gap-[10px] text-[11px] font-medium leading-none text-faint">
            <span>Priority {o.priority}</span>
            <span className="text-[#3a4049]">·</span>
            <span className={statusColor(o.status)}>{statusLabel(o.status)}</span>
          </div>
        </div>
        {o.days_to_go != null && (
          <div className="flex-none text-right">
            <div className="font-mono text-[26px] font-semibold leading-none text-ink">{o.days_to_go}</div>
            <div className="mt-1 font-mono text-[9px] font-semibold uppercase leading-none tracking-[0.14em] text-faint">days to go</div>
          </div>
        )}
      </div>

      {(hasTarget || o.target_date) && (
        <div className="flex flex-wrap items-center gap-[18px] border-t border-white/[0.05] pt-[12px] text-[12.5px] font-medium leading-none text-mute">
          {hasTarget && (
            <span>
              Target <span className="text-soft">{o.target_value}{o.target_unit ? ` ${o.target_unit}` : ""}</span>
            </span>
          )}
          {o.target_date && (
            <span>
              By <span className="text-soft">{o.target_date}</span>
            </span>
          )}
        </div>
      )}

      {hasProgress && (
        <div>
          <div className="mb-[6px] flex items-center justify-between text-[11px] font-medium leading-none text-faint">
            <span>Progress{o.progress.direction ? ` · ${o.progress.direction}` : ""}</span>
            <span className="text-soft">{o.progress.current ?? "—"} / {o.progress.target ?? "—"}</span>
          </div>
          <Track pct={Math.max(0, Math.min(100, o.progress.pct as number))} />
        </div>
      )}

      <div className="mt-auto flex gap-[9px] pt-1">
        {o.status === "active" && (
          <button
            onClick={onAchieve}
            disabled={busy}
            className="rounded-[9px] border border-good/30 bg-good/[0.1] px-[13px] py-[9px] text-[12px] font-semibold leading-none text-good disabled:opacity-50"
          >
            Mark achieved
          </button>
        )}
        <button
          onClick={onDelete}
          disabled={busy}
          className="rounded-[9px] border border-white/10 bg-white/[0.03] px-[13px] py-[9px] text-[12px] font-semibold leading-none text-mute disabled:opacity-50"
        >
          Delete
        </button>
      </div>
    </Card>
  );
}

// The local Notice component is gone: ResourceState now owns every notice
// branch, so the four states can no longer drift apart per screen.
function TargetIcon() {
  return (
    <div className="grid h-[60px] w-[60px] place-items-center rounded-[16px] border border-ac/25 bg-ac/[0.1]">
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="var(--ac)" strokeWidth="1.6">
        <circle cx="12" cy="12" r="9" />
        <circle cx="12" cy="12" r="5" />
        <circle cx="12" cy="12" r="1.2" fill="var(--ac)" stroke="none" />
      </svg>
    </div>
  );
}
