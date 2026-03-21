"use client";

import type { DebateRound } from "@/lib/types";

interface Props {
  rounds: DebateRound[];
}

interface ArgumentCardProps {
  side: "bull" | "bear";
  round: number;
  argument: string;
  confidence: number;
  rebuttals: string[];
}

function ArgumentCard({ side, round, argument, confidence, rebuttals }: ArgumentCardProps) {
  const isBull = side === "bull";
  const accent = isBull ? "#10B981" : "#EF4444";
  const label = isBull ? "Bull" : "Bear";

  return (
    <div
      className="rounded-lg border p-4 space-y-3"
      style={{
        background: "var(--color-surface)",
        borderColor: "var(--color-border)",
        borderLeft: `3px solid ${accent}`,
      }}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span
            className="text-xs font-mono font-semibold uppercase tracking-widest"
            style={{ color: accent }}
          >
            {label} — Round {round + 1}
          </span>
        </div>
        <span
          className="text-xs font-mono"
          style={{ color: "var(--color-muted)" }}
        >
          {Math.round(confidence * 100)}% confidence
        </span>
      </div>

      <p className="text-sm leading-relaxed" style={{ color: "var(--color-text)" }}>
        {argument}
      </p>

      {rebuttals.length > 0 && (
        <div>
          <p
            className="text-xs font-mono uppercase tracking-widest mb-2"
            style={{ color: "var(--color-muted)" }}
          >
            Rebuttals
          </p>
          <ul className="space-y-1">
            {rebuttals.map((r, i) => (
              <li
                key={i}
                className="text-sm pl-3 border-l-2"
                style={{ color: "var(--color-muted)", borderColor: "var(--color-border)" }}
              >
                {r}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export default function AgentDebate({ rounds }: Props) {
  if (!rounds || rounds.length === 0) {
    return (
      <p className="text-sm" style={{ color: "var(--color-muted)" }}>
        No debate transcript available.
      </p>
    );
  }

  return (
    <div
      className="rounded-lg border p-5 space-y-5"
      style={{ background: "var(--color-surface)", borderColor: "var(--color-border)" }}
    >
      <h3
        className="text-xs font-mono uppercase tracking-widest"
        style={{ color: "var(--color-muted)" }}
      >
        Debate Transcript — {rounds.length} Round{rounds.length !== 1 ? "s" : ""}
      </h3>

      {rounds.map((round, i) => (
        <div key={i} className="space-y-3">
          <div
            className="text-xs font-mono px-2 py-0.5 rounded w-fit"
            style={{ background: "var(--color-border)", color: "var(--color-muted)" }}
          >
            Round {i + 1}
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            <ArgumentCard
              side="bull"
              round={i}
              argument={round.bull.argument}
              confidence={round.bull.confidence}
              rebuttals={round.bull.rebuttals}
            />
            <ArgumentCard
              side="bear"
              round={i}
              argument={round.bear.argument}
              confidence={round.bear.confidence}
              rebuttals={round.bear.rebuttals}
            />
          </div>
        </div>
      ))}
    </div>
  );
}
