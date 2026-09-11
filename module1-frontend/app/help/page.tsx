import { AppShell } from "@/components/ui/layout/AppShell";

export default function HelpPage() {
  return (
    <AppShell>
      <h1 className="text-2xl font-bold mb-4">Help</h1>
      <p className="text-gray-600">
        Having trouble checking in? Contact your instructor or TA.
      </p>
    </AppShell>
  );
}