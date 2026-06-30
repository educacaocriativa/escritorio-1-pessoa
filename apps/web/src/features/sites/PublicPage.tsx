import type { PublicPage as PublicPageT } from "@e1p/shared-types";
import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { publicApi } from "../../lib/api";
import PageBlocks from "./PageBlocks";

/** Página pública (visitante abre sem login). */
export default function PublicPage() {
  const { slug = "" } = useParams();
  const [page, setPage] = useState<PublicPageT | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const { data } = await publicApi.get<PublicPageT>(`/public/pages/${slug}`);
      setPage(data);
    } catch {
      setPage(null);
    } finally {
      setLoading(false);
    }
  }, [slug]);

  useEffect(() => {
    load();
  }, [load]);

  async function lead(l: { name: string; email: string; phone: string }) {
    await publicApi.post(`/public/pages/${slug}/submit`, {
      name: l.name,
      email: l.email || null,
      phone: l.phone,
    });
  }

  if (loading) return <Centered>Carregando...</Centered>;
  if (!page) return <Centered>Página não encontrada.</Centered>;

  return (
    <div className="min-h-screen" style={{ background: page.bg_color }}>
      <PageBlocks blocks={page.blocks} style={page} onLead={lead} />
    </div>
  );
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-neutral-50 p-4 text-neutral-500">
      {children}
    </div>
  );
}
