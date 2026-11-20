"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronDown, FileText, Film } from "lucide-react";
import { Logo } from "./Logo";
import { cn } from "@/lib/cn";

// Served next to the console by Caddy on the deployed instance (deploy/ec2/Caddyfile, site/).
const LINKS = [
  { href: "/docs/design.html", label: "Design Document", icon: FileText },
  { href: "/presentation/ClaimSense_Capstone_Presentation.mp4", label: "Recorded Demo", icon: Film },
];

/** The logo and wordmark; clicking them opens links to the design document and the demo. */
export function BrandMenu({
  size = "md",
  subtitle,
}: {
  size?: "sm" | "md";
  subtitle?: string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className={cn(
          "flex items-center gap-2.5 rounded-lg p-1 pr-2 text-left transition-colors hover:bg-white/10",
          open && "bg-white/10",
        )}
      >
        <Logo size={size === "sm" ? 34 : 44} />
        <div className="leading-tight">
          <div
            className={cn(
              "font-serif font-semibold tracking-tight text-white",
              size === "sm" ? "text-base" : "text-xl",
            )}
          >
            ClaimSense
          </div>
          {subtitle && (
            <div className="text-[10px] font-medium uppercase tracking-[0.18em] text-teal-300/70">
              {subtitle}
            </div>
          )}
        </div>
        <ChevronDown
          className={cn("h-4 w-4 text-teal-300/70 transition-transform", open && "rotate-180")}
        />
      </button>
      {open && (
        <div
          role="menu"
          className="absolute left-1 top-full z-40 mt-2 grid min-w-[210px] gap-0.5 rounded-xl border border-claimsense-line bg-white p-1.5 shadow-lg"
        >
          {LINKS.map(({ href, label, icon: Icon }) => (
            <a
              key={href}
              role="menuitem"
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              onClick={() => setOpen(false)}
              className="flex items-center gap-2.5 rounded-lg px-3 py-2.5 text-sm font-semibold text-claimsense-ink hover:bg-claimsense-goldSoft"
            >
              <Icon className="h-4 w-4 text-claimsense-primary" />
              {label}
            </a>
          ))}
        </div>
      )}
    </div>
  );
}
