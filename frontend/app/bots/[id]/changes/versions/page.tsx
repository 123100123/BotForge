import { redirect } from "next/navigation";

/** Versions and tests now live on the Changes page; this keeps old links working. */
export default async function VersionsRedirect({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  redirect(`/bots/${encodeURIComponent(id)}/changes`);
}
