import { X } from "lucide-react";
import type { ReactNode } from "react";

/**
 * Painel lateral (slide-over da direita) — mesmo modelo de open/onClose/clique-no-backdrop-fecha
 * do Modal.tsx, mas ancorado à direita em vez de centralizado. Reusável (não é single-use).
 */
export default function Drawer({
  title,
  subtitle,
  open,
  onClose,
  children,
}: {
  title: string;
  subtitle?: string;
  open: boolean;
  onClose: () => void;
  children: ReactNode;
}) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/30" onClick={onClose}>
      <div
        className="flex h-full w-full max-w-lg flex-col bg-white p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-start justify-between">
          <div>
            <h2 className="text-lg font-bold text-neutral-800">{title}</h2>
            {subtitle && <p className="text-sm text-neutral-500">{subtitle}</p>}
          </div>
          <button onClick={onClose} className="text-neutral-400 hover:text-neutral-700">
            <X size={20} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto">{children}</div>
      </div>
    </div>
  );
}
