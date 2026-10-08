"use client";

import { useMemo, useState } from "react";
import type { Requirement, Scenario, TestReport } from "@/lib/types";
import { ScenarioDetail } from "./scenario-detail";
import { ScenarioList } from "./scenario-list";

interface ScenarioBrowserProps {
  scenarios: Scenario[];
  report: TestReport | null;
  requirements: Requirement[];
}

/** The scenarios of a version with the selected one's steps. Opens on the first failing scenario. Props only. */
export function ScenarioBrowser({ scenarios, report, requirements }: ScenarioBrowserProps) {
  const results = useMemo(() => {
    const map: Record<string, NonNullable<TestReport["results"]>[number]> = {};
    for (const r of report?.results ?? []) map[r.scenario_id] = r;
    return map;
  }, [report]);
  const firstId = report?.results?.find((r) => !r.passed)?.scenario_id ?? scenarios[0]?.id ?? null;
  const [picked, setPicked] = useState<string | null>(null);
  const selectedId = picked && scenarios.some((s) => s.id === picked) ? picked : firstId;
  const selected = scenarios.find((s) => s.id === selectedId) ?? null;

  if (scenarios.length === 0) return null;
  return (
    <div className="grid gap-4 md:grid-cols-[minmax(0,18rem)_minmax(0,1fr)] md:items-start">
      <ScenarioList scenarios={scenarios} results={results} selectedId={selectedId} onSelect={setPicked} />
      {selected && (
        <ScenarioDetail key={selected.id} scenario={selected} result={results[selected.id]} requirements={requirements} />
      )}
    </div>
  );
}
