import { redirect } from "next/navigation";

/** /bots/[id]/settings has no page of its own: it opens the first sub-page. */
export default async function SettingsIndex({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  redirect(`/bots/${encodeURIComponent(id)}/settings/telegram`);
}
