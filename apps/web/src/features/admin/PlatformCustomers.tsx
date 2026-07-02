import type { PlatformCustomerCard } from "@e1p/shared-types";
import { Building2, Mail, Search, ShoppingBag, Users } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../../lib/api";

// Avatar colorido determinístico a partir do nome (visual mais atrativo que cinza).
const AVATAR = [
  "from-violet-500 to-indigo-500", "from-rose-500 to-pink-500", "from-emerald-500 to-teal-500",
  "from-amber-500 to-orange-500", "from-sky-500 to-blue-500", "from-fuchsia-500 to-purple-500",
];
function avatarClass(name: string): string {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0;
  return AVATAR[h % AVATAR.length];
}
function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  return ((parts[0]?.[0] ?? "") + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase();
}

export default function PlatformCustomers() {
  const [customers, setCustomers] = useState<PlatformCustomerCard[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .get<PlatformCustomerCard[]>("/admin/customers")
      .then(({ data }) => setCustomers(data))
      .finally(() => setLoading(false));
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return customers;
    return customers.filter(
      (c) =>
        c.name.toLowerCase().includes(q) ||
        (c.email ?? "").toLowerCase().includes(q) ||
        c.tenant_name.toLowerCase().includes(q),
    );
  }, [customers, query]);

  const totalPurchases = customers.reduce((s, c) => s + c.purchases, 0);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Chip icon={<Users size={13} />} value={customers.length} label="clientes" />
        <Chip icon={<ShoppingBag size={13} />} value={totalPurchases} label="compras" />
      </div>

      <div className="relative">
        <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-neutral-400" />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Buscar cliente, e-mail ou escritório…"
          className="w-full rounded-xl border border-neutral-200 bg-white py-2.5 pl-9 pr-3 text-sm outline-none focus:border-primary-400"
        />
      </div>

      {loading ? (
        <p className="rounded-2xl bg-white p-8 text-center text-sm text-neutral-400 shadow-sm">Carregando…</p>
      ) : filtered.length === 0 ? (
        <div className="rounded-2xl bg-white p-10 text-center shadow-sm">
          <GraduationEmpty />
          <p className="mt-3 text-sm text-neutral-400">
            {customers.length === 0
              ? "Ainda não há clientes. Eles aparecem aqui quando um escritório vende um produto ou curso."
              : "Nenhum cliente encontrado para a busca."}
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map((c, i) => (
            <div
              key={`${c.tenant_id}-${c.email ?? c.name}-${i}`}
              className="group rounded-2xl bg-white p-4 shadow-sm transition hover:shadow-md"
            >
              <div className="flex items-center gap-3">
                <div
                  className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-gradient-to-br ${avatarClass(c.name)} text-sm font-bold text-white`}
                >
                  {initials(c.name) || "?"}
                </div>
                <div className="min-w-0 flex-1">
                  <p className="truncate font-semibold text-neutral-800">{c.name}</p>
                  {c.email && (
                    <p className="flex items-center gap-1 truncate text-xs text-neutral-400">
                      <Mail size={11} className="shrink-0" /> {c.email}
                    </p>
                  )}
                </div>
              </div>
              <div className="mt-3 flex items-center justify-between border-t border-neutral-50 pt-3">
                <span className="flex min-w-0 items-center gap-1 text-xs text-neutral-500">
                  <Building2 size={12} className="shrink-0 text-primary-500" />
                  <span className="truncate">{c.tenant_name}</span>
                </span>
                <span className="flex shrink-0 items-center gap-1 rounded-pill bg-accent-50 px-2 py-0.5 text-xs font-semibold text-accent-700">
                  <ShoppingBag size={11} /> {c.purchases}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function Chip({ icon, value, label }: { icon: React.ReactNode; value: number; label: string }) {
  return (
    <span className="flex items-center gap-1 rounded-pill bg-neutral-100 px-3 py-1 text-sm text-neutral-500">
      {icon} <span className="font-semibold text-neutral-700">{value}</span>
      <span className="text-neutral-400">{label}</span>
    </span>
  );
}

function GraduationEmpty() {
  return (
    <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-neutral-100">
      <Users size={22} className="text-neutral-300" />
    </div>
  );
}
