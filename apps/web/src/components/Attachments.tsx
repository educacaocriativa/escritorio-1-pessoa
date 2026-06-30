import type { Attachment } from "@e1p/shared-types";
import { FileText, Trash2, Upload } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, apiErrorMessage } from "../lib/api";

const ACCEPT = "application/pdf,image/jpeg,image/png";
const kb = (n: number) => (n < 1024 * 1024 ? `${Math.round(n / 1024)} KB` : `${(n / 1024 / 1024).toFixed(1)} MB`);

/** Upload real de arquivos (PDF/JPEG/PNG) ligados a uma entidade (boleto, contrato...). */
export default function Attachments({
  ownerType,
  ownerId,
  slots,
}: {
  ownerType: string;
  ownerId: string;
  slots: { key: string; label: string }[];
}) {
  const [items, setItems] = useState<Attachment[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const { data } = await api.get<Attachment[]>(
      `/attachments?owner_type=${ownerType}&owner_id=${ownerId}`,
    );
    setItems(data);
  }, [ownerType, ownerId]);

  useEffect(() => {
    load();
  }, [load]);

  async function upload(file: File, label: string) {
    setError(null);
    setBusy(label);
    try {
      const fd = new FormData();
      fd.append("owner_type", ownerType);
      fd.append("owner_id", ownerId);
      fd.append("label", label);
      fd.append("file", file);
      await api.post("/attachments", fd, { headers: { "Content-Type": "multipart/form-data" } });
      await load();
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  async function open(att: Attachment) {
    const { data } = await api.get(`/attachments/${att.id}/download`, { responseType: "blob" });
    window.open(URL.createObjectURL(data as Blob), "_blank");
  }

  async function remove(att: Attachment) {
    if (!confirm(`Remover "${att.filename}"?`)) return;
    await api.delete(`/attachments/${att.id}`);
    load();
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        {slots.map((s) => (
          <UploadButton key={s.key} label={s.label} busy={busy === s.key} onFile={(f) => upload(f, s.key)} />
        ))}
      </div>
      {error && <p className="rounded-lg bg-red-50 p-2 text-xs text-danger">{error}</p>}
      {items.length > 0 && (
        <ul className="divide-y divide-neutral-100 rounded-lg border border-neutral-100">
          {items.map((a) => (
            <li key={a.id} className="flex items-center gap-2 px-3 py-2">
              <FileText size={15} className="shrink-0 text-neutral-400" />
              <button onClick={() => open(a)} className="min-w-0 flex-1 truncate text-left text-sm text-neutral-700 hover:text-primary-600">
                {a.filename}
              </button>
              <span className="shrink-0 rounded-pill bg-neutral-100 px-2 text-[10px] uppercase text-neutral-500">{a.label}</span>
              <span className="shrink-0 text-xs text-neutral-400">{kb(a.size)}</span>
              <button onClick={() => remove(a)} className="shrink-0 text-neutral-300 hover:text-danger">
                <Trash2 size={14} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function UploadButton({ label, busy, onFile }: { label: string; busy: boolean; onFile: (f: File) => void }) {
  const ref = useRef<HTMLInputElement>(null);
  return (
    <>
      <button
        onClick={() => ref.current?.click()}
        disabled={busy}
        className="flex items-center gap-1.5 rounded-pill bg-neutral-100 px-3 py-1.5 text-xs font-semibold text-neutral-600 hover:bg-neutral-200 disabled:opacity-60"
      >
        <Upload size={13} /> {busy ? "Enviando..." : label}
      </button>
      <input
        ref={ref}
        type="file"
        accept={ACCEPT}
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onFile(f);
          e.target.value = "";
        }}
      />
    </>
  );
}
