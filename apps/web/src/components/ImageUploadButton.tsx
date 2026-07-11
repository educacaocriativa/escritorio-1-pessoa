import { Upload } from "lucide-react";
import { useRef, useState } from "react";
import { apiErrorMessage } from "../lib/api";
import { PUBLIC_IMAGE_ACCEPT, uploadPublicImage } from "../lib/uploadPublicImage";

/**
 * Botão de upload de imagem pública reutilizável (Brand Kit, propostas, carrossel, sites).
 * Sobe o arquivo via `uploadPublicImage` e devolve a URL renderável ao pai por `onUploaded`.
 * O campo de URL manual continua existindo em cada tela (retrocompatibilidade — AC2).
 */
export default function ImageUploadButton({
  onUploaded,
  label = "Enviar imagem",
  className,
}: {
  onUploaded: (url: string) => void;
  label?: string;
  className?: string;
}) {
  const ref = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handle(file: File) {
    setError(null);
    setBusy(true);
    try {
      const url = await uploadPublicImage(file);
      onUploaded(url);
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="inline-flex flex-col gap-1">
      <button
        type="button"
        onClick={() => ref.current?.click()}
        disabled={busy}
        className={
          className ??
          "flex items-center gap-1.5 rounded-pill bg-neutral-100 px-3 py-1.5 text-xs font-semibold text-neutral-600 hover:bg-neutral-200 disabled:opacity-60"
        }
      >
        <Upload size={13} /> {busy ? "Enviando..." : label}
      </button>
      {error && <span className="text-xs text-danger">{error}</span>}
      <input
        ref={ref}
        type="file"
        accept={PUBLIC_IMAGE_ACCEPT}
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) handle(f);
          e.target.value = "";
        }}
      />
    </div>
  );
}
