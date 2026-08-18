import { X } from "lucide-react";
import type { ReactNode } from "react";

export default function Modal({
  title,
  open,
  onClose,
  children,
  footer,
  testId,
}: {
  title: string;
  open: boolean;
  onClose: () => void;
  children: ReactNode;
  /**
   * `data-testid` na CAIXA do modal — cabeçalho e rodapé inclusive.
   *
   * ⚠️ Existe por causa da régua de 360px. Pôr o recorte no conteúdo (`children`) deixa título e
   * barra de ação FORA da varredura de `textoForaDaTela`, e foi exatamente assim que um título
   * comprido empurrando o "Fechar" 338px para fora da tela passou por uma medição que devolveu
   * lista vazia. Todo modal medido pela régua deve receber `testId` aqui, nunca num `<div>`
   * interno.
   */
  testId?: string;
  /**
   * Ação primária do modal. Vive numa barra `sticky bottom-0` DENTRO da caixa que rola, para que
   * ela nunca saia da tela enquanto o dono preenche o formulário. **Opcional**: modal que não
   * passa `footer` continua exatamente como era.
   *
   * ⚠️ Não é enfeite. Em 360×740 o formulário de conta bancária tem 1010px numa caixa de 629px —
   * sem esta barra o botão que efetiva a escolha "não sei o saldo" nasce 303px abaixo da borda da
   * tela e 467px abaixo da escolha, que é a forma do PR #56 (uma conta real foi marcada como paga
   * sem o dono conseguir ver o controle que a confirmava).
   */
  footer?: ReactNode;
}) {
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4"
      onClick={onClose}
    >
      <div
        data-testid={testId}
        className="max-h-[85vh] w-full max-w-md overflow-y-auto rounded-2xl bg-white p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-start justify-between gap-2">
          {/* `min-w-0 break-words`: o título é digitação livre — nome de contato, título de evento
              — e `name` aceita 255 chars no backend. Sem os dois, um nome colado sem espaço não
              tem onde quebrar, o `<h2>` cresce e empurra o "Fechar" para fora da tela: medido em
              698px numa viewport de 360. O `shrink-0` no botão é a outra metade — sem ele o
              flex o espreme antes de deixar o título quebrar. */}
          <h2 className="min-w-0 break-words text-lg font-bold text-neutral-800">{title}</h2>
          <button
            onClick={onClose}
            aria-label="Fechar"
            className="-mr-2 flex h-11 w-11 shrink-0 items-center justify-center rounded-pill text-neutral-400 hover:text-neutral-700"
          >
            <X size={20} />
          </button>
        </div>
        {children}
        {footer && (
          // `-mx-6 -mb-6` desfaz o `p-6` da caixa para a barra encostar nas bordas; o fundo opaco
          // é o que impede o conteúdo de aparecer por baixo dela enquanto rola.
          <div className="sticky bottom-0 -mx-6 -mb-6 mt-4 border-t border-neutral-100 bg-white px-6 py-4">
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}

export function Field({
  label,
  value,
  onChange,
  type = "text",
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
  placeholder?: string;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-neutral-600">{label}</span>
      <input
        type={type}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400 focus:ring-2 focus:ring-primary-100"
      />
    </label>
  );
}
