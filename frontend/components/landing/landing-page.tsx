import { CapabilityIndex } from "./capability-index";
import { ClosingBand, LandingFooter } from "./closing-footer";
import { Hero } from "./hero";
import { HowItWorks } from "./how-it-works";
import { LandingNav } from "./nav";
import { ReportsSection } from "./reports-section";
import { RolesSection } from "./roles-section";

/** Public landing page. A server component; client islands are the theme menu, the mobile menu, the role demo and the real components that need state. */
export function LandingPage() {
  return (
    <div className="flex min-h-dvh flex-col">
      <LandingNav />
      <main className="flex-1">
        <Hero />
        <RolesSection />
        <HowItWorks />
        <CapabilityIndex />
        <ReportsSection />
        <ClosingBand />
      </main>
      <LandingFooter />
    </div>
  );
}
