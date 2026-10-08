import { Suspense } from "react";
import { ChangesView } from "@/components/changes/changes-view";

/** The selected proposal or version lives in `?v=`, which needs a Suspense boundary for the static shell. */
export default function ChangesPage() {
  return (
    <Suspense fallback={null}>
      <ChangesView />
    </Suspense>
  );
}
