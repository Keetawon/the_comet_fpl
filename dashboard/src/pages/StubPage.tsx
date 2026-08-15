// Placeholder for the pages that come after P1.7b, so the sidebar lists the full roadmap.

interface StubPageProps {
  label: string;
  phase: string;
  description: string;
}

export function StubPage({ label, phase, description }: StubPageProps) {
  return (
    <div className="p-6">
      <h1 className="mb-2 text-lg font-semibold">{label}</h1>
      <p className="mb-1 text-sm text-muted-foreground">Coming soon — {phase}.</p>
      <p className="max-w-xl text-sm text-muted-foreground">{description}</p>
    </div>
  );
}
