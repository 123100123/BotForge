import { LandingPage } from "@/components/landing/landing-page";

/** Public landing page. The auth guard lives in app/bots/layout.tsx, not here. */
export default function Home() {
  return <LandingPage />;
}
