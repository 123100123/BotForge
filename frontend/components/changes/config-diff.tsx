import { SpecDiff } from "@/components/versions/spec-diff";
import type { SpecChange } from "@/lib/types";

interface ConfigDiffProps {
  /** Configuration changes against the previous version (old value struck through, new value after it). */
  changes: SpecChange[];
  /** The first version of the bot has nothing to compare with. */
  isFirst?: boolean;
  emptyText?: string;
}

/** The configuration diff of a change. Pure: props only (wraps the spec-diff renderer). */
export function ConfigDiff({ changes, isFirst = false, emptyText }: ConfigDiffProps) {
  return <SpecDiff diff={changes} isFirst={isFirst} emptyText={emptyText} />;
}
