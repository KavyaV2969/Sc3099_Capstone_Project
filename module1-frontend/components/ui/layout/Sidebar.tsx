"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { clearAuthStorage } from "@/lib/storage";

const navItems = [
  { label: "Home", href: "/" },
  { label: "Courses", href: "/courses" },
  { label: "Privacy & Security", href: "/privacy" },
  { label: "Help", href: "/help" },
];

interface SidebarProps {
  isOpen: boolean;
  onClose: () => void;
}

export function Sidebar({ isOpen, onClose }: SidebarProps) {
  const pathname = usePathname();
  const router = useRouter();

  function handleLogout() {
    clearAuthStorage();
    router.push("/login");
  }

  return (
    <>
      {isOpen && (
        <div
          className="fixed inset-0 bg-black/30 z-10"
          onClick={onClose}
        />
      )}

      <aside
        className={`fixed top-0 left-0 h-full w-56 bg-white border-r p-4 flex flex-col z-20
          transform transition-transform duration-200
          ${isOpen ? "translate-x-0" : "-translate-x-full"}`}
      >
        <div className="flex justify-between items-center mb-6 px-2">
          <h2 className="text-lg font-bold">SAIV</h2>
          <button onClick={onClose} className="text-gray-500 text-xl leading-none">
            ×
          </button>
        </div>

        <nav className="flex-1 space-y-1">
          {navItems.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              onClick={onClose}
              className={`block px-3 py-2 rounded text-sm font-medium ${
                pathname === item.href
                  ? "bg-blue-100 text-blue-700"
                  : "text-gray-700 hover:bg-gray-100"
              }`}
            >
              {item.label}
            </Link>
          ))}
        </nav>

        <button
          onClick={handleLogout}
          className="px-3 py-2 rounded text-sm font-medium text-red-600 hover:bg-red-50 text-left"
        >
          Logout
        </button>
      </aside>
    </>
  );
}