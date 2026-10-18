import { AppShell } from "@/components/ui/layout/AppShell";

const faqs = [
  {
    q: "How do I check in?",
    a: "On Home, tap a session that says \"Tap to check in\". Take a photo and complete the location and liveliness checks, then press Check In Now to complete the check in process.",
  },
  {
    q: "Why can't I tap a session?",
    a: "The check-in window isn't open yet, or it has already closed. Only sessions your instructor has activated can be checked into.",
  },
  {
    q: "Why do I have to register my face?",
    a: "Your face is used to confirm it's really you checking in. Check Ins can only be completed after you have registered your face. Your photo is turned into a one-way template and the image isn't stored.",
  },
  {
    q: "How do I change my camera or location permission?",
    a: "Open Privacy & Security and use the switches. If your browser has blocked access, click the camera or lock icon in the address bar and allow it there too.",
  },
  {
    q: "Why was my check-in flagged or rejected?",
    a: "Common reasons are being far from the classroom, using a device the system doesn't recognise, or a photo that doesn't match your registered face.",
  },
  {
    q: "Can I appeal a flagged or rejected check-in?",
    a: "Yes. Open the course, tap the check-in, and choose Appeal this result. You can appeal once, within 7 days of the check-in.",
  },
  {
    q: "Can I check in without an internet connection?",
    a: "No. Check-ins are always sent live. The app can open offline, but you need a connection to check in.",
  },
  {
    q: "Who do I contact if something is wrong?",
    a: "Contact your instructor or TA, and tell them which session and what error you saw.",
  },
];

export default function HelpPage() {
  return (
    <AppShell>
      <div className="flex justify-center pt-12">
        <div className="max-w-md w-full">
          <h1 className="text-2xl font-bold mb-6">Help</h1>

          <h2 className="text-lg font-semibold mb-3">Frequently asked questions</h2>
          {faqs.map((f) => (
            <details key={f.q} className="card-panel !max-w-none mb-3">
              <summary className="font-semibold cursor-pointer">{f.q}</summary>
              <p className="text-sm text-gray-600 mt-2">{f.a}</p>
            </details>
          ))}
        </div>
      </div>
    </AppShell>
  );
}